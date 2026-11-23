# 2. Modelos de predicción y criterio de alertas

FHIPredict no usa un único modelo gigante, sino **dos modelos especializados de LightGBM** que se complementan: uno estima dónde puede **iniciar o reactivarse** un foco mañana, y el otro estima hacia dónde puede **propagarse** si ya hay fuego o riesgo alto.

---

## Qué es LightGBM en lenguaje simple

Ambos modelos utilizan **LightGBM**, un algoritmo basado en cientos de **árboles de decisión** encadenados.

- Cada árbol funciona como una serie de preguntas simples de "sí o no" sobre el clima, la sequía acumulada, el terreno y el historial reciente de fuego.
- Cada árbol nuevo corrige los errores que dejaron los árboles anteriores.
- Al combinar cientos de árboles, el modelo entrega una probabilidad entre `0 %` y `100 %` de que ocurra un incendio relevante.

---

## Cómo se entrenaron sin hacer trampa

Para saber si el modelo realmente sirve hacia adelante y no está memorizando el pasado, se usó una **separación estricta por tiempo**:

| Bloque | Años | Para qué se usó |
|---|---|---|
| **Entrenamiento** | `2018–2023` | Aprender los patrones entre clima, sequía, vegetación, fuego reciente e incendios. |
| **Validación** | `2024–2025` | Decidir cuándo frenar el entrenamiento para no sobreajustar y calibrar umbrales de referencia. |
| **Prueba ciega (Test)** | `2026` | Medir el desempeño real en datos nunca vistos durante el aprendizaje. |

Además, en los datos de memoria de fuego y climatología mensual se respetó siempre el orden cronológico: para predecir un día `D`, el modelo solo puede mirar focos hasta el día anterior (`D - 1`) y promedios mensuales de años anteriores.

> [!IMPORTANT]
> **Por qué se submuestrean los días sin fuego:** en Argentina la gran mayoría de celdas y días no tiene incendios. Entrenar con millones de días tranquilos idénticos sería lento e ineficiente. Por eso, durante el entrenamiento solo se conserva una fracción pequeña de días sin fuego (`8 de cada 1.000` en ignición; `200 de cada 1.000` en propagación) y luego se aplica un ajuste fijo al resultado final para que la probabilidad vuelva a reflejar la frecuencia real del país.

---

## Modelo 1: Riesgo de ignición (`lgbm-risk-24h-v2`)

Responde a la pregunta: *"¿Qué tan probable es que esta celda de 5 × 5 km tenga un foco relevante en las próximas 24 horas?"*

Utiliza **20 señales de entrada** agrupadas en cuatro familias:

| Grupo | Qué información mira |
|---|---|
| **Ubicación y calendario** | Latitud, longitud, mes y día del año. |
| **Memoria reciente de fuego** | Focos en los últimos 7 y 30 días, energía radiativa (FRP) de 7 días, promedio histórico del mes y años desde el último incendio. |
| **Terreno** | Elevación en metros. |
| **Clima y sequía** | Temperatura máxima, humedad relativa, viento máximo, lluvia del día, radiación solar, lluvia acumulada a 7/15/30 días, días consecutivos sin lluvia y déficit de presión de vapor (sequedad del aire). |

En la prueba ciega de 2026 demostró una gran capacidad para ordenar el territorio de menor a mayor peligro: las celdas clasificadas en **`Extremo`** concentran incendios **~276 veces más seguido** que una celda elegida al azar.

---

## Modelo 2: Propagación espacial (`lgbm-spread-v2`)

Responde a la pregunta: *"Si una celda tiene fuego activo (o riesgo alto hoy), ¿qué tan probable es que se propague a cada una de sus 8 celdas vecinas en 24, 48 o 72 horas?"*

Utiliza **47 señales de entrada**. Suma a las variables de clima y fuego todo lo necesario para entender el salto de una celda origen a una celda vecina destino:

- **Geometría y relieve:** distancia, dirección del enlace y diferencia de altura / pendiente entre origen y destino.
- **Viento direccional:** qué tan alineado sopla el viento desde la celda que arde hacia la vecina, y con qué intensidad.
- **Control industrial:** si la celda origen es una zona de antorchas industriales conocidas (`is_industrial_s`) y qué proporción histórica de focos industriales tiene.
- **Presión de vecinos:** cuántos vecinos alrededor ya están activos y con qué intensidad.
- **Combustible vegetal (4 fracciones):** porcentaje estimado de **pastizal**, **bosque**, **zona agrícola** y **superficie no combustible** (agua, roca, urbano o suelo desnudo).

Además, incorpora **tres reglas físicas obligatorias**: a mayor horizonte (24h → 48h → 72h) el riesgo nunca puede bajar; más terreno no combustible solo puede frenar la propagación; y si el origen es industrial, la probabilidad de propagación solo puede bajar.

> [!WARNING]
> **Lección clave aprendida (trampa de fuga de datos):** en una versión experimental se intentó representar el "tipo de combustible" usando la tasa histórica de incendios de cada zona entre 2018 y 2023. El resultado empeoró: el modelo memorizó el mapa histórico en 28 árboles y dejó de prestar atención al viento. Al reemplazarlo por fracciones biofísicas puras sin historial de fuego, el modelo aprendió física real de propagación y mejoró de forma clara.

---

## Cómo se asignan los niveles de alerta (`Bajo`, `Moderado`, `Alto`, `Extremo`)

En producción, FHIPredict separa dos lógicas según el tipo de capa:

1. **Capa de ignición (`/api/v1/forecast`), `/monitor` y selección de fuentes en `/api/v1/spread`:**
   - Usan **percentiles diarios acotados** (`RISK_CUTOFF_MODE=daily_percentile`).
   - En días templados o fuera de temporada, el sistema baja los umbrales para seguir destacando el **top 0,05 % (`Extremo`)**, **top 0,3 % (`Alto`)** y **top 1 % (`Moderado`)** de mayor riesgo relativo del día.
   - Tiene **pisos de seguridad selectivos** (`1,5 %` en `Extremo`, `0,5 %` en `Alto` y `0,2 %` en `Moderado`) para evitar ruido masivo en días tranquilos o lluviosos, y **techos** fijados en los umbrales de validación para no perder sensibilidad en olas de calor extremas.
   - Con esta alineación, toda celda no industrial que el mapa marca en `Alto` o `Extremo` también se evalúa como fuente potencial en la capa de propagación.

2. **Categorías de la capa de propagación (`/api/v1/spread`):**
   - Mantienen sus umbrales estáticos de validación (`Extremo >= 45,6 %`, `Alto >= 19,8 %`, `Moderado >= 8,2 %`).
   - **Por qué:** cuando una celda no tiene fuego observado por satélite, su aporte a la propagación se pondera por su probabilidad de ignición. Si se usaran percentiles diarios sobre la salida de propagación, fuentes no confirmadas con riesgo bajo podrían pintar círculos rojos engañosos.

---

## Cómo interpretar correctamente las alertas

El riesgo diario de incendios en una celda de 5 × 5 km es un evento muy poco frecuente (~0,06 % diario en 2026). Eso genera un efecto importante:

- Incluso con un modelo muy preciso en ordenamiento, alrededor de **5 de cada 6 alertas en categoría `Extremo` no terminan en un foco confirmado ese día** (~16,5 % de precisión).
- Por eso, FHIPredict debe leerse como una **herramienta de priorización territorial** (para decidir dónde mirar primero y asignar recursos con 276× más eficiencia que el azar), y **no como una alarma binaria infalible**.

---

## Checklist de comprensión

- [ ] Entiendo la diferencia entre qué responde el modelo de ignición (20 variables) y el de propagación (47 variables).
- [ ] Entiendo por qué los datos de entrenamiento, validación y prueba se separaron por años estrictos.
- [ ] Entiendo por qué `Extremo` sirve para priorizar vigilancia y no garantiza que habrá incendio en todas las celdas marcadas.

## Siguiente lectura

Continúa con [03-arquitectura-backend-y-monitor.md](03-arquitectura-backend-y-monitor.md) para ver cómo el servidor empaqueta ambos modelos, cachea los pronósticos y audita sus aciertos en DuckDB.
