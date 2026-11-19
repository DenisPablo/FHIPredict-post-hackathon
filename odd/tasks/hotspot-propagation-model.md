# Objective: Implement `lgbm-spread-v1` → `lgbm-spread-v2` hotspot propagation model (24h–72h) and head-to-head comparative benchmark against `lgbm-risk-24h-v2`
Branch: `feat/propagation-model-v3` (merged to `main` in `5159078`) | Delivery strategy: `single-pr`
Test runner: `backend/.venv/Scripts/python.exe -m pytest`

## Specs

- **S1**: "Quiero que analices que tan dificil es extender el modelo para que calcule la propagacion estimada de un hotspost" / "Hazme una propuesta formal de modificacion del proyecto otra rama, vamos a sacar otro modelo medir el rendimiento de ambos" / "Como se propagra en las proximas 24 hs - 72 hs."
  - Scope: Extend `openmeteo.py` with `wind_direction_10m_dominant` and `wind_gusts_10m_max` (backward-compatible defaults so existing `v2` callers and tests never break), implement `backend/app/spread.py` (`SpreadPredictor`, 8-neighbor spatial graph builder, bearing/slope/wind-alignment features, and multi-horizon 24h/48h/72h neighbor propagation scoring), and expose optional propagation inference in `config.py`, `service.py`, and `main.py` (`/api/v1/spread` and optional fusion, keeping `/api/v1/forecast` and `/api/v1/health` backward-compatible).
  - Assumption: Unified model taking `horizon_days` in `{1, 2, 3}` (24h, 48h, 72h) as an explicit feature so a single self-contained `spread_bundle.joblib` serves all 3 horizons.
  - Checks: `pytest backend/tests/test_forecast.py backend/tests/test_spread.py`

- **S2**: "Avanza con la implementacion y prepara un set de pruebas para medir el renidmiento de ambos modelos y compararlos" (Training & Model Artifact Generation)
  - Scope: Implement `backend/scripts/train_spread.py` to build the leak-free spatial neighbor propagation dataset `(source_cell s -> neighbor_cell t, date d, horizon_days in {1, 2, 3})` from `ModeloPredictivo/firms_argentina_harmonized.parquet` and `ModeloPredictivo/data/weather/nasapower/nasapower_*.parquet` using the identical temporal split (`train`: 2018–2023, `val`: 2024–2025, `test`: 2026), train `lgbm-spread-v1` with prior-correction calibration, and export `backend/models/spread_bundle.joblib` + `backend/models/spread_metadata.json`.
  - Checks: Run `train_spread.py` and verify `spread_bundle.joblib` and `spread_metadata.json` are generated and load cleanly via `SpreadPredictor.from_bundle`.

- **S3**: "prepara un set de pruebas para medir el renidmiento de ambos modelos y compararlos" (Head-to-Head Benchmark & Automated Comparison Test Suite)
  - Scope: Implement `backend/scripts/compare_models.py` and `backend/tests/test_model_comparison.py` to evaluate `lgbm-risk-24h-v2` vs `lgbm-spread-v1` (plus naive spatial recency baseline and `v2 + spread` fusion) on the unseen 2026 holdout (and 2024–2025 validation) across Track A (global 24h cell risk) and Track B (conditional neighbor propagation at 24h, 48h, and 72h: ROC-AUC, PR-AUC, Brier score, log-loss, calibration ratio, Top-k precision/recall/lift, and inference throughput), writing `backend/models/comparison_report.json` and `specs/05-comparison-results.md`.
  - Checks: Run `compare_models.py` and `pytest backend/tests/test_model_comparison.py`.

- **S4**: "Estamos usando Mapbiomas verdad explicame para que" / "Y no seria mejor integrar mapBiomas para un mayor rendimiento_" / "Cual seria tu plan de implemetnacion" / "Implemetalo" (Upgrade Propagation Model to `lgbm-spread-v2` with Fuel/Land-Cover Fractions, Industrial Heat Filtering, Exact Grid Indices, and Historical Directional Wind)
  - Scope:
    1. Enrich `backend/models/cell_baseline.parquet` via `backend/scripts/export_baseline.py` with exact 5x5 km grid indices (`grid_row`, `grid_col`) and continental fraction (`frac_dentro`) from `ML_NasaSpaceApp/serving_api/dim_celdas.parquet`, persistent industrial flare flags (`is_industrial`, `industrial_focos_share`) from `ML_NasaSpaceApp/serving_api/puntos_industriales.parquet`, and 4 fuel/land-cover fractions (`fuel_bosque`, `fuel_pastizal`, `fuel_agro`, `fuel_no_combustible`) per cell (`64,653` cells), keeping all existing columns 100% backward-compatible for `lgbm-risk-24h-v2`.
    2. Build/enrich historical daily wind direction (`WD10M` from NASA POWER) so training computes real historical downwind alignment `cos(radians(WD10M + 180 - bearing_deg))` and `upwind_wind_speed`.
    3. Update `backend/app/spread.py`, `backend/app/service.py`, `backend/scripts/train_spread.py`, and `backend/scripts/compare_models.py` to train `lgbm-spread-v2` with monotone constraints (`+1` on `horizon_days`, `-1` on `fuel_no_combustible_t` and `is_industrial_s`) and re-run the full head-to-head benchmark (`lgbm-risk-24h-v2` vs `lgbm-spread-v1` vs `lgbm-spread-v2` vs fused `v2 + spread-v2`), updating `backend/models/comparison_report.json` and `specs/05-comparison-results.md`.
  - Checks: `pytest backend/tests/test_forecast.py backend/tests/test_spread.py backend/tests/test_model_comparison.py`

## Tasks

- [x] **T1** (S1) — Implement weather directional features (`openmeteo.py`), spatial propagation module (`spread.py`), API/service integration (`config.py`, `service.py`, `main.py`), and unit tests (`tests/test_spread.py`) | Route: `inline` (sequential foundation required by T2/T3; no Writer trigger) | Status: `done` (`b3324e1`, RED `ModuleNotFoundError: No module named 'app.spread'` -> GREEN `6 passed in 1.87s`)
- [x] **T2** (S2) — Implement `scripts/train_spread.py`, train `lgbm-spread-v1` on 2018–2023 (val 2024–2025, test 2026), and export `models/spread_bundle.joblib` + `models/spread_metadata.json` | Route: `inline` (depends on T1 `SpreadPredictor` schema) | Status: `done` (`baa367a`, trained 1,171,634 pairs, val PR-AUC=0.2922, test PR-AUC=0.3945, test ROC-AUC=0.8749)
- [x] **T3** (S3) — Implement `scripts/compare_models.py`, run full benchmark generating `models/comparison_report.json` and `specs/05-comparison-results.md`, and add `tests/test_model_comparison.py` | Route: `inline` (depends on T2 trained bundle) | Status: `done` (`46c605a`, RED `AssertionError: comparison_report.json must be generated` -> GREEN `12 passed in 3.00s`)
- [x] **T4** (S4) — Enrich `cell_baseline.parquet` (`scripts/export_baseline.py`) with `dim_celdas.parquet`, `puntos_industriales.parquet`, and 4 fuel/land-cover fractions (`fuel_bosque`, `fuel_pastizal`, `fuel_agro`, `fuel_no_combustible`), and ingest historical `WD10M` directional wind (external `ModeloPredictivo/.../wd10m_2018_2026.parquet` via `scripts/fetch_wd10m.py`) | Route: `inline` (sequential data dependency for T5) | Status: `done` (`4339284`, 7,594,002 WD10M rows; 64,653 enriched cells, 420 industrial cells)
- [x] **T5** (S4) — Upgrade `spread.py`, `service.py`, `train_spread.py`, and `compare_models.py` for `lgbm-spread-v2`, retrain `spread_bundle.joblib`, re-run comparative benchmark (`v2` vs `spread-v1` vs `spread-v2`), update `specs/05-comparison-results.md` and `tests/test_model_comparison.py` | Route: `inline` (depends on T4 baseline + wind data) | Status: `done` (`5159078`, val PR-AUC=0.3040, test PR-AUC=0.4125 [+11.01% vs v2, +4.47% vs spread-v1, +34.68% vs naive], 24h fused PR-AUC=0.4443)

## Log

- **L1 (2026-11-15)**: User request verbatim:
  - "Quiero que analices que tan dificil es extender el modelo para que calcule la propagacion estimada de un hotspost"
  - "Hazme una propuesta formal de modificacion del proyecto otra rama, vamos a sacar otro modelo medir el rendimiento de ambos"
  - "Como se propagra en las proximas 24 hs - 72 hs. Que seria ese margen_}"
  - "Avanza con la implementacion y prepara un set de pruebas para medir el renidmiento de ambos modelos y compararlos"
- **L2 (2026-11-15)**: Created formal proposal `specs/04-propagation-proposal.md` on branch `feat/propagation-model-v3` (`caeca03`). Proceeding with T1 → T2 → T3.
- **L3 (2026-11-15)**: Completed T1 (`b3324e1`), T2 (`baa367a`), and T3 (`46c605a`: `compare_models.py`, `comparison_report.json`, `05-comparison-results.md`, `test_model_comparison.py`). Full suite: `12 passed in 3.00s`. Independent verifier (`3050699e-c6c1-4124-b533-e2eefea916e7`) passed S1–S3 with 0 blockers.
- **L4 (2026-11-15)**: User request verbatim:
  - "Explicame el rendimiento"
  - "Estamos usando Mapbiomas verdad explicame para que"
  - "Y no seria mejor integrar mapBiomas para un mayor rendimiento_"
  - "Cual seria tu plan de implemetnacion"
  - "Implemetalo"
  Added S4, T4, and T5 to implement `lgbm-spread-v2` with fuel fractions, industrial heat filtering, exact 5x5 km grid indices, and historical directional wind (`WD10M`).
