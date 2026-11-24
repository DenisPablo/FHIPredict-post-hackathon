# Evolución del modelo predictivo: de `v2` a `v4` y su límite teórico

Esta guía explica, en lenguaje de ingeniería y sin matemáticas complejas, cómo evolucionó el modelo de riesgo de incendios de **FHIPredict**, qué problemas reales aparecieron al enfrentarlo con satélites de la NASA, cómo se corrigió cada uno y por qué con **`lgbm-risk-24h-v4`** el sistema está muy cerca del techo teórico alcanzable con los datos actuales.

> [!NOTE]
> **Resumen ejecutivo:** pasar de `v2` (20 variables + umbrales amplios) a **`v4 + Fase 1`** (30 variables + alertas en 2 niveles + piso calibrado `1.3%`) subió el `PR-AUC` del test 2026 un **`+16.2%`** (`0.0785 → 0.0912`), redujo las falsas alarmas más de un **`90%`** respecto al esquema original y casi duplicó la precisión operativa (`≤ 12 km`) en días tranquilos.

---

## 1. Cómo entender este problema en Machine Learning

Antes de mirar versiones, conviene entender la dificultad real del problema que resuelve el modelo:

- **El tablero:** Argentina se divide en **`64,653` celdas de 5×5 km**. Cada día el modelo le asigna una probabilidad de incendio (en las próximas 24 horas) a cada una de esas celdas.
- **Desbalanceo extremo ("buscar agujas en un pajar"):** en un día normal arden entre `4` y `35` celdas de las `64,653` (alrededor del **`0.06%`** del país). El `99.94%` restante no tiene fuego.
- **Dos pasos distintos que no hay que mezclar:**
  1. **El modelo (el *ranking*):** ordena las `64,653` celdas de más peligrosa a menos peligrosa.
  2. **Los umbrales (la regla de negocio):** deciden *dónde cortar* esa lista ordenada para disparar una alerta roja o dejar una zona solo en vigilancia visual.

### Glosario práctico de métricas (sin fórmulas)

| Métrica | Qué pregunta responde | Analogía simple |
|---|---|---|
| **Captura (`Recall`)** | De todos los incendios reales del día, ¿qué porcentaje quedó dentro de nuestras alertas? | Si hubo 10 incendios y avisamos de 6, la captura es `60%`. |
| **Precisión (`Precision`)** | De todas las alertas que disparamos, ¿qué porcentaje tuvo fuego real? | Si avisamos en 100 celdas y ardieron 15, la precisión es `15%`. |
| **Falsas alarmas (`FA`)** | Cuántas celdas alertamos donde finalmente no hubo incendio. | El costo operativo y la fatiga de las brigadas. |
| **`ROC-AUC`** | ¿El modelo ordena las zonas peligrosas por encima de las seguras? (`0.5` = azar, `1.0` = perfecto). | Sirve para saber si el ranking general es bueno, pero puede verse alto incluso con muchas falsas alarmas. |
| **`PR-AUC`** | ¿Qué tan limpio es el ranking **en la punta más peligrosa** donde realmente disparamos alertas? | Es la métrica más honesta en eventos raros como incendios. |
| **`Lift`** | ¿Cuántas veces mejor que elegir celdas al azar es nuestra alerta? | Un `Lift` de `100×` significa que nuestras celdas alertadas concentran 100 veces más fuego que el promedio del país. |
| **Precisión operativa (`≤ 12 km`)** | ¿Qué porcentaje de alertas tuvo fuego en esa celda **o en la celda pegada de al lado**? | Evita castigar como "error total" un fuego que cayó a 6 km del centro marcado. |

---

## 2. Evolución versión por versión

### Resumen comparativo

| Etapa | Variables | Regla de alerta | `PR-AUC` Val (`2024–25`) | `PR-AUC` Test (`2026`) | Problema principal detectado |
|---|---|---|---|---|---|
| **`v2` inicial** | 20 (clima + historial) | Cortes estáticos del entrenamiento | `0.0691` | `0.0785` | En días moderados daba **0 alertas** (subestimación en vivo). |
| **`v2` + memoria VIIRS + percentiles `5%`** | 20 (+ VIIRS en vivo) | Top `0.1% / 1% / 5%` (`Moderado+` = alarma) | `0.0691` | `0.0785` | **Exceso de ruido**: `~3,230` falsas alarmas por día. |
| **`v2` + separación en 2 niveles** | 20 | `Alto+` (`0.05% / 0.4%`) = alarma; `Moderado` (`2.5%`) = vigilancia | `0.0691` | `0.0785` | Redujo el ruido **`-93%`**, pero faltaba señal de secado del combustible. |
| **`v3` (secado físico)** | 26 (+ `ET0`, balance hídrico `15d/30d`, `VPD 7d`, `focos 1d/2d`) | 2 niveles con piso `Alto = 0.5%` | `0.0751` (`+8.7%`) | `0.0820` (`+4.5%`) | En días tranquilos seguía llenando cuota con celdas de baja probabilidad y "ecos" de focos ya apagados. |
| **`v4` + Fase 1 (actual)** | **30** (+ `focos_vecinos_1d`, `frp_30d`, `dias_desde_foco_reciente`, `ratio_1d_7d`) | 2 niveles con **piso calibrado `Alto = 1.3%`** + métrica `≤ 12 km` | **`0.0799`** (`+15.6%`) | **`0.0912`** (`+16.2%`) | Cerca del techo físico con los datos disponibles (ver sección 4). |

---

### Detalle de cada iteración

#### 1. `lgbm-risk-24h-v2`: el modelo base (20 variables)
- **Qué tenía:** ubicación (`lat`, `lon`, `elevacion_m`), calendario (`mes`, `dia_anio`), clima diario (`temperatura`, `humedad`, `viento`, `lluvia`, `radiación`, `lluvia acumulada 7/15/30d`, `días secos`, `VPD`) e historial de fuego (`focos 7d/30d`, `FRP 7d`, `años desde último foco`).
- **Problemas encontrados en producción:**
  1. **Memoria congelada:** en vivo no actualizaba los incendios recientes con VIIRS, así que el modelo no sabía qué celdas habían ardido ayer.
  2. **Desacople de escala:** se entrenó con clima histórico de **NASA POWER**, pero en vivo corre sobre pronósticos de **Open-Meteo**. En días moderados las probabilidades salían más bajas que los cortes estáticos y el mapa quedaba vacío.
- **Cómo se corrigió:** se conectó la memoria de fuego en vivo desde `viirs_cell_daily` (commit `c41a58b`) y se pasaron los umbrales a **percentiles diarios acotados** (`4b8decb`).

#### 2. Separación operativa en 2 niveles (`Alto+` vs. `Moderado`)
- **Problema encontrado:** usar el top `5%` (`Moderado+`) como alarma generaba **`~3,230` falsas alarmas por día**. Si se bajaba `Moderado` al `1%`, bajaba el ruido pero se destruía la cobertura visual.
- **Cómo se corrigió:** se separaron los roles operativos como trabajan las brigadas reales:
  - **Alerta accionable (`Extremo` + `Alto`)**: estricta (`top 0.05%` y `0.4%`), pocas celdas críticas para movilización.
  - **Capa de vigilancia (`Moderado`)**: más amplia (`top 2.5%`), visible en el mapa como contexto preventivo pero **sin disparar alarma** ni ensuciar las métricas de falsas alarmas en `/monitor`.

#### 3. `lgbm-risk-24h-v3`: secado físico del combustible (26 variables)
- **Problema encontrado:** el modelo veía la lluvia caída y el calor del día, pero no sabía cuánta agua había *evaporado* el suelo/pasto durante las últimas semanas ni si una celda había ardido exactamente ayer.
- **Cómo se corrigió:** se agregaron 6 variables físicas calculadas exactamente igual en entrenamiento (NASA POWER) y en producción (Open-Meteo):
  - `et0_approx`: cuánta agua evapora la atmósfera ese día (evapotranspiración de referencia FAO-56).
  - `balance_hidrico_15d` y `balance_hidrico_30d`: lluvia acumulada menos agua evaporada (mide el estrés hídrico real del combustible).
  - `vpd_mean_7d`: sequedad atmosférica sostenida durante toda la semana.
  - `focos_ultimos_1d` y `focos_ultimos_2d`: persistencia de corto plazo.
- **Resultado:** en el hindcast limpio de 13 días (`740` focos), las capturas en `Alto+` saltaron de `367` (`49.6%`) a **`450` (`60.8%`, `+83` incendios capturados)**.

#### 4. `lgbm-risk-24h-v4` + Fase 1: ataque directo a las falsas alarmas (30 variables)
Al diseccionar las `3,726` falsas alarmas de `v3`, aparecieron **dos fugas claras de precisión**:
1. **El "eco de ceniza" (`49%` de las falsas alarmas):** celdas que habían ardido hace 2 a 7 días y ayer ya estaban apagadas seguían recibiendo alerta alta toda la semana por culpa de `focos_ultimos_7d`.
2. **La cuota fija en días tranquilos (`29%` de las falsas alarmas):** en días con pocos focos, el piso bajo (`0.5%`) forzaba a llenar `~250` celdas de baja probabilidad donde solo acertaba el `0.46%` (`5` de `1,094`).
3. **Desvíos de 1 celda (`≤ 12 km`):** `+484` supuestas "falsas alarmas" tenían un incendio real pegado en la celda vecina ese mismo día.

- **Cómo se corrigió:**
  - **En el modelo (`v4`):** se sumaron 4 variables específicas:
    - `focos_vecinos_1d`: focos activos ayer en celdas vecinas (`≤ 12 km`) → resultó ser la nueva señal más fuerte (**`753` splits** en LightGBM), moviendo la probabilidad hacia la celda vecina en riesgo de contagio.
    - `frp_ultimos_30d`: energía total quemada en los últimos 30 días (indica cuánto combustible ya se consumió).
    - `dias_desde_foco_reciente` y `ratio_actividad_1d_7d`: permiten al árbol distinguir un foco activo ayer de uno que lleva varios días apagado.
  - **En los umbrales (Fase 1):** se subió el piso mínimo de `Alto` de `0.5%` a **`1.3%`** (su corte calibrado natural) para que en días tranquilos el sistema no rellene alertas con ruido, y se incorporó en `/monitor` la métrica de **precisión operativa `≤ 12 km`**.
- **Resultado:** en el test completo de 2026 (`173,598` muestras), `PR-AUC` subió de `0.0820` a **`0.0912`** (`ROC-AUC` `0.9248`). En la simulación limpia de 9 días tranquilos con clima pronosticado (`15–23 Nov`), las alertas bajaron un **`-50.9%`** (`222 → 109/día`), la precisión exacta subió **`+85%`** (`1.65% → 3.06%`) y la precisión operativa `≤ 12 km` subió **`+89%`** (`4.65% → 8.78%`).

---

## 3. Dos lecciones clave de análisis de datos que surgieron en el camino

Para quien está aprendiendo ML y análisis de datos, estos dos hallazgos valen tanto como el propio modelo:

### Lección A: El bug silencioso de zonas horarias (`UTC` vs. `UTC-3`)
El servidor corre en horario `UTC`, mientras Open-Meteo devuelve fechas en hora Argentina (`UTC-3`). Cuando el sistema refrescaba automáticamente a las `22:40 ART` (`01:40 UTC` del día siguiente), guardaba el pronóstico de **hoy** bajo la fecha de **mañana**, bloqueando el snapshot real del día siguiente.
- **Corrección:** se unificó el cálculo de fecha a `UTC-3` (`argentina_today_iso`) en `openmeteo.py` y `service.py` para garantizar que `issued_date == target_date`.

### Lección B: La trampa del *target leakage* (fuga de información del futuro)
Cuando evaluamos esos snapshots generados a las `22:40 ART` contra los incendios de ese mismo día, el modelo pareció acertar `4/4` y `7/7` (`100%`). En realidad estaba haciendo trampa sin querer: a las `22:40` los incendios de la tarde ya habían ocurrido y ya estaban cargados en VIIRS.
- **Regla de oro en ML temporal:** cuando simules el pasado (*hindcast*), asegúrate siempre de que el modelo para el día `D` **solo vea datos estrictamente anteriores (`≤ D - 1`)**. Si un número parece demasiado bueno para ser verdad, casi siempre hay *leakage*.

---

## 4. Por qué con `v4` estamos cerca del límite teórico actual

Es tentador pensar que con "un poco más de ajuste de LightGBM" la línea verde debería pegarse al `100%` de los focos reales de VIIRS sin falsas alarmas. Con los datos que hoy alimentan al modelo, existen **tres barreras físicas** que ponen un techo real:

1. **Predisposición física vs. la chispa humana:**
   El clima y el secado te dicen dónde el combustible está **listo para arder** (condición necesaria), pero en Argentina la gran mayoría de los incendios se inician por **acción humana** (quemas rurales, colillas, fogatas, fallas eléctricas). Ningún modelo meteorológico puede saber en qué hectárea exacta alguien va a encender un fósforo mañana.
2. **Resolución espacial (`50 km` vs. `5 km`):**
   El clima llega en una grilla aproximada de `50 × 50 km`, pero el mapa predice en celdas de `5 × 5 km`. Si toda una región de `50 km` está igual de caliente, seca y ventosa, el modelo no tiene información dentro de esa grilla para distinguir cuál de las ~100 celdas internas se prenderá primero (salvo por el historial de fuego). Por eso casi 1 de cada 3 alertas tiene fuego en la celda vecina (`≤ 12 km`).
3. **La realidad del desbalanceo al alertar solo el `0.17%` del país:**
   En días tranquilos, `v4 + Fase 1` alerta unas `~109` celdas de `64,653` (`0.17%` del territorio). Capturar el `25–60%` de todos los focos del país dentro de menos del `0.5%` del mapa ya representa una concentración de señal superior a **`100×` sobre el azar**. Subir la captura más allá de eso sin cambiar los datos de entrada exige abrir el umbral y aceptar cientos de falsas alarmas.

---

## 5. Cómo romper ese techo en el futuro (Fase 3)

Para mejorar el rendimiento de forma estructural más allá de `v4`, el próximo paso ya no es ajustar hiperparámetros ni umbrales, sino **incorporar información nueva a escala fina (`5×5 km` o menor)**:

- **Estado real de la vegetación (`NDVI` / `NDMI` satelital de MODIS o Sentinel):** permite distinguir dentro de una misma zona calurosa dónde hay pastizal/monte seco real y dónde hay un cultivo verde, suelo desnudo o agua.
- **Factor antrópico estático:** distancia a rutas, caminos rurales y bordes urbano-rurales (donde se concentra la probabilidad de chispa humana).
- **Calibración en vivo sobre `DonWeb1`:** una vez acumuladas 2 a 4 semanas de snapshots limpios de `v4` en horario `UTC-3`, ajustar finamente la curva de probabilidad directamente contra pronósticos reales de Open-Meteo.

---

## Siguiente lectura

- Para ver cómo se despliega y monitorea este modelo en producción, consulta [05-operacion-despliegue-y-limites.md](05-operacion-despliegue-y-limites.md).
