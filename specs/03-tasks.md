# FHIPredict — Implementation Tasks (SDD)

- [x] **T1 — Project Scaffold & Model Artifacts Migration**
  - Initialize `FHIPredict/`, `.gitignore`, `README.md`, `fire_risk_bundle.joblib`, `fire_risk_metadata.json`, and `cell_baseline.parquet` (`64,653` cells).

- [x] **T2 — FastAPI Inference Backend + Open-Meteo Client**
  - Implement `FireRiskPredictor`, async Open-Meteo batch client (`past_days=30`, `forecast_days=15`, `971` grid points), rolling weather feature builder, 3h TTL + disk cache (`.forecast_cache.joblib`), and periodic background refresh.
  - Expose `GET /api/v1/health` and `GET /api/v1/forecast` (`mode=window|day`, `bbox`, `min_risk`, `refresh`).

- [x] **T3 — Interactive MapLibre Frontend (FuegoContinuo Identity)**
  - Build Vite + React + TypeScript + Tailwind CSS + MapLibre GL UI (`RiskMap`, `TimeRangeBar`, `RiskLegend`, `NavigationPanel`, cell inspection popups, ES/EN i18n).

- [x] **T4 — Hotspot Propagation Model (`lgbm-spread-v2`)**
  - Add directional wind variables (`wind_direction_10m_dominant`, `wind_gusts_10m_max`), 8-neighbor graph (`spread.py`), biophysical fuel fractions + industrial filter (`export_baseline.py`), `train_spread.py`, `compare_models.py`, and `GET /api/v1/spread`.

- [x] **T5 — Empirical VIIRS Monitoring System & `/monitor` Dashboard**
  - Implement daily 24h snapshot persistence (`snapshots.py`), NASA FIRMS VIIRS ingestion + spatial bucket mapping (`firms.py`), pure-NumPy evaluator (`evaluator.py`), and async `/api/v1/monitor/*` endpoints (`monitor/service.py`) bounded to 256 MB DuckDB memory.
  - Build separate lazy-loaded `/monitor` dashboard (`MonitorDashboard.tsx`) with 3-step reading guide, plain-language summary, charts, and CSV export.

- [x] **T6 — Scientific & Mathematical Integrity Hardening + CI/CD**
  - Blend live VIIRS fire memory with horizon decay in `ForecastService`, align `mode="window"` to peak daily scale, weight unconfirmed spread sources by `p_risk`, add `[tool.setuptools.packages.find]` in `pyproject.toml`, and add `.github/workflows/deploy.yml`.
