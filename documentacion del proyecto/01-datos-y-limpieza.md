# 1. Datos y limpieza (Paso 1)

Antes de entrenar cualquier modelo, la calidad de las predicciones depende de limpiar bien las detecciones satelitales y el clima: eliminar falsos focos industriales, corregir la zona horaria y definir con precisión qué cuenta como un incendio real.

---

## Fuentes de datos del proyecto

| Fuente                         | Qué aporta                                                                                      | Cuándo se usa                                                                                      |
| ------------------------------ | ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **NASA FIRMS (MODIS y VIIRS)** | Detecciones satelitales diarias de focos de calor, ubicación y potencia radiativa (FRP).        | En entrenamiento histórico (`2011–2026`) y en vivo para el monitor y la memoria reciente de fuego. |
| **NASA POWER / MERRA-2**       | Clima diario histórico en superficie (temperatura máxima, humedad, viento, lluvia y radiación). | En entrenamiento y validación histórica (`2018–2026`).                                             |
| **Open-Meteo**                 | Últimos 30 días de clima reciente más pronóstico diario a 15 días sobre 971 nodos en Argentina. | En producción en vivo para generar los pronósticos diarios.                                        |

---

## Cómo se divide Argentina: la grilla de 5 × 5 km

Argentina se divide en una cuadrícula regular de celdas cuadradas de 5 × 5 kilómetros (proyección cartográfica Albers para conservar áreas equivalentes).

- **Celdas activas del modelo (`64.653`):** son todas las celdas que tuvieron al menos una detección satelital registrada entre 2000 y 2026.
- **Celdas excluidas (`48.058`):** de las `112.711` celdas totales de la grilla nacional, casi la mitad nunca registró focos históricos y quedó fuera del universo del modelo (un punto clave que se detalla en las limitaciones).

Cada celda se vincula de forma directa con el nodo climático más cercano de la grilla meteorológica, asegurando cobertura completa del 100 % sin valores faltantes en los cruces.

---

## Limpieza de focos satelitales (`clean_firms.py`)

El script `clean_firms.py` procesa los archivos crudos de NASA FIRMS aplicando seis filtros y normalizaciones en orden:

1. **Validez física y numérica:** descarta registros con coordenadas nulas o inválidas, o con potencia radiativa del fuego menor o igual a cero (`FRP <= 0`).
2. **Filtro de confianza del sensor:**
   - En satélites **VIIRS**, conserva solo detecciones de confianza nominal o alta (`'n'` y `'h'`) y descarta las de confianza baja (`'l'`).
   - En satélites **MODIS**, exige una confianza mínima de `30 %`.
3. **Separación de vegetación vs. antorchas industriales:**
   - Los archivos históricos definitivos (*Standard Processing*, **SP**) incluyen una columna `type`. Se conserva únicamente `type == 0` (fuego de vegetación) y se descartan volcanes, plataformas y fuentes térmicas fijas (`type == 2`, como antorchas petroleras o plantas industriales).
   - Los archivos en tiempo casi real (*Near Real-Time*, **NRT**) no traen esa columna `type`. Para no confundir antorchas con incendios, el pipeline construye primero una lista negra con todas las coordenadas donde `type == 2` apareció al menos 2 veces en los archivos SP y filtra esos puntos también en NRT.
4. **Ajuste a hora local argentina (`UTC` a `UTC-3`):** los satélites reportan en hora universal (`UTC`). El limpiador resta 3 horas antes de asignar la fecha calendario, evitando que incendios nocturnos entre las 21:00 y las 00:00 de Argentina queden contabilizados en el día siguiente.
5. **Asignación a la grilla de 5 × 5 km:** proyecta cada foco a coordenadas métricas Albers y lo asigna directamente a su identificador de celda (`cell_id`).
6. **Unificación y deduplicación:** homogeneiza los nombres de columnas de brillo térmico entre MODIS y VIIRS y elimina duplicados por ubicación, fecha, hora y satélite, dando prioridad siempre al dato definitivo **SP** sobre el **NRT**.

---

## Limpieza climática y criterio de "incendio relevante"

Una vez limpios los focos individuales y descargado el clima diario (`ingest_nasapower.py`), los scripts de entrenamiento aplican tres reglas adicionales:

- **Valores faltantes de NASA (`-999`):** todo código de relleno `-999.0` se convierte a nulo para no contaminar promedios ni máximos.
- **Umbral de día con lluvia (`>= 1.0 mm`):** el viento se pasa a km/h, la lluvia faltante se trata como `0.0 mm`, y solo se reinicia el contador de "días consecutivos sin lluvia" cuando llueve al menos `1.0 mm`. Así se evita que lloviznas mínimas borren una sequía real.
- **Definición de incendio relevante (`>= 10.0 MW`):** un día en una celda solo se marca como evento positivo si tiene al menos 1 foco armonizado con una potencia radiativa de `10.0 MW` o más. Esto filtra ruido térmico débil y pequeñas quemas agrícolas sin impacto.

---

## En producción: cómo se mantienen frescos los datos

En el servidor en vivo no se reentrena nada, pero los datos de entrada sí se actualizan todo el tiempo:

- **Base estática (`cell_baseline.parquet`):** guarda la ubicación, elevación, flag industrial (`420` celdas industriales marcadas), historia climática mensual y fracciones biofísicas de combustible (pastizal, bosque, agrícola y suelo no combustible) de las `64.653` celdas.
- **Memoria de fuego viva:** `ForecastService` combina esa base con las detecciones reales de NASA FIRMS VIIRS guardadas en DuckDB (ventanas de 1, 2, 7 y 30 días), y va atenuando esa memoria día a día conforme avanza el pronóstico de 1 a 15 días.

---

## Checklist de comprensión

- [ ] Entiendo que antes del modelo se eliminan detecciones de baja confianza y antorchas industriales repetitivas.
- [ ] Entiendo por qué la hora se pasa a `UTC-3` antes de agrupar focos por día.
- [ ] Entiendo que `>= 10.0 MW` separa incendios significativos de ruido térmico menor, y `>= 1.0 mm` evita reiniciar rachas de sequía con lloviznas.

## Siguiente lectura

Continúa con [02-modelos-y-prediccion.md](02-modelos-y-prediccion.md) para ver cómo aprenden los dos modelos a partir de estos datos limpios y cómo se traducen sus salidas en alertas.
