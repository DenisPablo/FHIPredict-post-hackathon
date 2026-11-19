# Veredicto científico: ModeloPredictivo-2026 (`lgbm-risk-24h-v2`)

> [!NOTE]
> **Contexto histórico vs. estado actual en `FHIPredict` (actualizado 2026-11-19):**
> Este documento es la auditoría histórica del repositorio previo **`ModeloPredictivo-2026`** (`commit a18d981`, 2026-11-15) sobre el artefacto `lgbm-risk-24h-v2`. Varias de sus reservas iniciales **ya fueron resueltas en `FHIPredict`**:
> - **M2 / M3 (pronóstico meteorológico real)**: `FHIPredict` reemplaza las tablas estáticas retrospectivas por pronósticos en vivo de Open-Meteo (`past_days=30`, `forecast_days=15`).
> - **Memoria de fuego dinámica**: `ForecastService` mezcla las detecciones diarias de NASA FIRMS VIIRS (`monitor.duckdb`) con `cell_baseline.parquet` y decae las ventanas móviles a lo largo del horizonte (`service.py`).
> - **Escala de ventanas y monitoreo empírico**: `mode="window"` usa la probabilidad diaria pico (cota de Fréchet en la misma escala de 24 h), y el dashboard `/monitor` mide diariamente `ROC-AUC`, `PR-AUC`, `calibration_ratio` y `Hits / Misses` contra VIIRS.
> - **Siguen vigentes como propiedades del artefacto entrenado (`fire_risk_bundle.joblib`)**: las observaciones **M1** y **M4–M11** (ej. sesgo de selección en las 64.653 celdas históricas, incertidumbre del PR-AUC y necesidad de recalibrar umbrales tras acumular muestra en producción).

**Veredicto histórico (sobre `ModeloPredictivo-2026`):** sólido con reservas como índice de riesgo del día; todavía no era un pronóstico antes de integrarle Open-Meteo.

Las métricas declaradas se reproducen exactas, la memoria de fuego no tiene fuga temporal y la corrección de probabilidad está bien hecha. Las reservas son tres:
- usa el clima observado del mismo día que predice;
- la tabla de "7 días" cubre días ya pasados;
- la mejora sobre una referencia simple está inflada porque se eligió una referencia débil.

**¿Aplica como agregado a FireHistory?** Sí, como capa de "riesgo de hoy" precalculada fuera del servidor. No como "pronóstico", hasta que se alimente con un pronóstico meteorológico.

Repo evaluado: [DenisPablo/ModeloPredictivo-2026](https://github.com/DenisPablo/ModeloPredictivo-2026), commit `a18d981`. Fecha: 2026-11-15. Método: las skills `scientific-critical-thinking` y `statistical-analysis`. Todo se midió con los datos del propio repo y su código, reentrenando el modelo (ver §6).

---

## 1. Qué afirma el modelo

Predice la probabilidad de que una celda de 5 × 5 km tenga un foco "crítico" en las próximas 24 h: al menos un foco armonizado con FRP ≥ 10 MW.
- Cubre 64.653 celdas de Argentina.
- Usa 20 variables: posición, estación del año, memoria de fuego de días anteriores, clima de NASA POWER/MERRA-2 y sequía.
- Entrena con 2018–2023, valida con 2024–2025 y prueba con 2026.
- Métricas declaradas en 2026: ROC-AUC 0,9196, PR-AUC 0,0785, calibración 1,04 y lift de 275,9× en la categoría "Extremo".

## 2. Tabla de hallazgos

| # | Hallazgo | Evidencia medida | Severidad | Recomendación |
|---|---|---|---|---|
| M1 | **Las métricas se reproducen exactas** | Con el modelo publicado: ROC 0,9196, PR 0,0785, calibración 1,0417, lift 275,9×, idénticas al metadata. Al reentrenar: ROC 0,9197. Las matrices tienen exactamente las filas declaradas (1.321.940 / 421.793 / 173.598). Los 7 tests pasan. | Fortaleza | — |
| M2 | **Usa el clima del día que intenta predecir** | El código une el clima por `fm.fecha = wf.fecha`: temperatura máxima, lluvia y viento del día t, observados después del hecho. Con el clima del día anterior (t−1), ROC baja de 0,9197 a **0,9098** (Δ = 0,0102, IC95 % pareado por días [0,0077; 0,0131]) y la calibración empeora de 1,04 a **1,15**. La documentación declara Δ = −0,0066, pero lo midió sobre el modelo v1, que tenía fuga, no sobre el v2. | **Alta** (por cómo se presenta) | Llamarlo "riesgo de hoy" o *nowcast*. Para que sea un pronóstico a 24 h, entrenar con t−1 o alimentarlo con un pronóstico meteorológico real (NASA POWER no pronostica). |
| M3 | **La tabla "riesgo_celda_7d" cubre días pasados** | `models/riesgo_celda_7d.parquet` va del 2026-11-04 al 2026-11-10. `export_backend.py` toma los **últimos 7 días con clima observado** (`max(fecha) − 6 … max(fecha)`) y congela la memoria de fuego al primero. Es un riesgo retrospectivo. | **Alta** (por cómo se presenta) | No publicarlo como "pronóstico de 7 días". Para hacerlo de verdad: pronóstico meteorológico para t+1 a t+7 y un modelo por horizonte. |
| M4 | **La mejora "3,12×" usa una referencia débil** | Se compara contra un solo indicador (años desde el último fuego): PR 0,0252. Una referencia que combina persistencia de 7 y 30 días con recencia da **PR 0,0362**. Contra ella, la mejora es **2,2×**, no 3,1×. | Media | Reportar contra la referencia de persistencia. |
| M5 | **La incertidumbre de PR-AUC es grande** | Bootstrap por bloques de día, 314 días: PR-AUC del v2 con IC95 % [0,057; 0,103]. Las variantes con t−1 [0,057; 0,102] y sin clima [0,051; 0,097] se superponen. La diferencia de PR entre clima t y t−1 no es significativa (+0,0025 [−0,008; +0,016]). | Media | Publicar intervalos de confianza. No sostener diferencias de PR sin ellos. |
| M6 | **El clima ordena las celdas, pero no aporta precisión distinguible en las alertas** | Sin clima: ROC 0,886 [0,877; 0,894], PR 0,0696 y calibración 1,66. El clima sube ROC +0,034 y corrige la calibración, pero el aumento de PR (+0,007) cae dentro del ruido. La señal más fuerte para precisión es la memoria de fuego. | Media | Contarlo así en la defensa. |
| M7 | **La calibración es buena en total pero no en las puntas** | Por tramos de población (modelo publicado): la mitad de menor riesgo sobreestima ×1,54, y el 0,1 % de mayor riesgo **subestima** (predicho 7,5 % contra 10,4 % observado, razón 0,73). La calibración global de 1,04 lo esconde. | Media | Recalibrar (isotónica sobre validación) o mostrar la categoría en lugar de la probabilidad exacta. |
| M8 | **"Extremo" = 5 de cada 6 alertas son falsas** | La precisión de "Extremo" es 16,5 % y su recall 11,5 % (con el lift de 275,9× sobre una prevalencia de 0,06 %). Es útil para priorizar dónde mirar, no como alerta binaria. | Media | Mostrar la precisión junto al lift en la interfaz y la documentación. |
| M9 | **Las celdas incluidas se definen mirando el futuro** | `active_cells` son las celdas con alguna detección entre 2000 y 2026, test incluido. De los 12.102 positivos de 2026, **741 (6,1 %)** ocurren en celdas sin fuego previo, que solo están en el universo porque se quemaron en 2026. Las 48.058 celdas sin fuego quedan fuera, así que las métricas valen solo para "celdas que alguna vez ardieron". | Baja–media | Definir el universo con datos hasta el fin del entrenamiento, o usar las 112.711 celdas de la grilla. |
| M10 | **La etiqueta usa otra armonización** | `firms_argentina_harmonized.parquet` (`stat-calibrated-n20-v4`) usa NOAA-20 como referencia y estima antes de 2018. En 2018, el 18,9 % de los positivos son estimados. Aun así, los totales anuales coinciden con la API de FireHistory dentro de ~2 % (2024: 138.921 contra 138.133; 2020: 390.896 contra 396.896). | Baja | Para integrarlo, regenerar la etiqueta desde `conteos_celda_dia` de FireHistory. Así hay una sola armonización. |
| M11 | **El test 2026 no es del todo ciego** | Los tests automáticos exigen umbrales sobre 2026 (ROC ≥ 0,85, lift ≥ 20×), y el v2 se ajustó después de ver el v1. Eso abre la puerta a decisiones guiadas por el test (*garden of forking paths*). Además, 2026 es NRT y va hasta el 10 de noviembre. | Baja | Fijar un holdout que nadie mire, por ejemplo diciembre de 2026 a marzo de 2027, y reportarlo una sola vez. |
| M12 | **Lo que está bien hecho** | Memoria de fuego estrictamente anterior a t. Climatología con años previos (corrigieron la fuga del v1). Corrección de prior `ln(0,008)` correcta para submuestreo de negativos (King y Zeng). Pesos Horvitz-Thompson correctos (×125). Cortes de categoría derivados en validación. Muestreo determinista. | Fortaleza | — |

## 3. Si aplica como agregado a FireHistory

| Criterio | Estado |
|---|---|
| Encaja en el desafío | ✅ El desafío pide anticipar períodos críticos y fortalecer la alerta temprana. Un índice diario de riesgo complementa el calendario histórico. |
| Grilla compatible | ✅ Mismo `cell_id` (fila × 460 + columna). 64.600 de 64.653 celdas están en `dim_celdas` de la API (53 quedan afuera). |
| Regla "sin ML en el servidor" | ✅ si se precalcula: un proceso diario fuera de la API genera una tabla Parquet y la API solo la lee, igual que los factores. |
| Coherente con la armonización | ⚠️ Usa otra armonización (NOAA-20). Coincide ±2 % en totales, pero conviene regenerar la etiqueta desde FireHistory. |
| Listo para mostrar como "pronóstico" | ❌ Hoy es el riesgo de días pasados con clima observado (M2, M3). |
| Prioridad para la demo | Baja frente al bloqueo actual: el sitio publicado no llega a la API y muestra datos de ejemplo. |

**Recomendación:** sumarlo como capa **"Riesgo de hoy (experimental)"**: el mapa coloreado por categoría, con la precisión de cada una y la leyenda "basado en condiciones observadas". Contarlo en el pitch como extensión, con estas cifras honestas: ROC 0,91–0,92 y alertas "Extremo" con 16 % de acierto, 276 veces el azar.

## 4. Responsabilidades

- **Repo del modelo:** M2, M3, M4, M7, M9, M11 (código y presentación de métricas), y regenerar la etiqueta desde FireHistory (M10).
- **FireHistory (API y frontend):** un endpoint que lea la tabla precalculada, una capa del mapa con su leyenda y los textos de precisión (M8). Nada de ML dentro de la API.

## 5. Limitaciones de esta evaluación

- El clima de t−1 es una cota inferior de lo que daría un pronóstico real a 24 h. Un buen pronóstico debería quedar entre t−1 y t.
- El bootstrap remuestrea días, pero no corrige la dependencia espacial dentro de cada día ni entre días consecutivos. Los intervalos son, si acaso, algo estrechos.
- No probé la generalización espacial (dejar regiones afuera) ni otras semillas.
- No revisé `ingest_nasapower.py` contra la API de NASA POWER: usé los Parquet incluidos en el repo.
- LightGBM se ejecutó con la `libomp` que trae scikit-learn (no hay Homebrew). Los resultados del modelo publicado coinciden al decimal, así que no afecta.

## 6. Cómo replicar

Desde esta carpeta, con un entorno con `requirements.txt` instalado:

```bash
bash scripts/run_all.sh ../ModeloPredictivo-2026 ../FireHistoryInterfaceAPI/data/current python
```

- `p1_build.py`: arma las matrices con el código del repo, con clima del día t y con clima de t−1.
- `p2_eval.py`: reproduce las métricas, reentrena las variantes (t, t−1, sin clima, sin posición), calcula las referencias y el bootstrap por días, y mide la calibración por tramos. Salida en `resultados/p2_eval.txt`.
- `p3_compat.py`: compatibilidad de grilla con FireHistory, positivos en celdas nuevas y totales anuales. Salida en `resultados/p3_compat.txt`.
