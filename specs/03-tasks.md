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

---

## Post-Spec Milestone Reconciliation

- [x] **M1 (`4b8decb`) — Bounded Daily-Percentile Alert Cutoffs**
  - Added `RISK_CUTOFF_MODE` (`daily_percentile` | `static`), `RISK_TOP_FRAC_*`, and `RISK_FLOOR_*` settings in `backend/app/config.py`.
  - Implemented `FireRiskPredictor.compute_daily_percentile_cutoffs` (`backend/app/predictor.py`) bounded between safety floors and static validation cutoffs with fallback on `< 100` finite samples or degenerate/tied arrays.
  - Updated `ForecastService.query_geojson` and `_maybe_save_snapshot_24h` (`backend/app/service.py`) to expose active `meta.cutoffs` (`{ mode, Extremo, Alto, Moderado }`) and persist consistent snapshot categories.
  - Updated `frontend/src/api/forecast.ts`, `frontend/src/App.tsx`, `frontend/src/components/RiskLegend.tsx`, `frontend/src/i18n.ts`, and added unit tests in `backend/tests/test_forecast.py` and `frontend/tests/RiskLegend.test.tsx`.

- [x] **M2 (`7be2e6d`) — Spread Source Selection Alignment with Daily-Percentile Cutoffs**
  - Updated `ForecastService.query_spread_geojson` (`backend/app/service.py`) to resolve unconfirmed high-risk source thresholds via `_resolve_risk_cutoffs(p_risk)` so `/api/v1/spread` (`meta.source_cutoff`) matches `/api/v1/forecast` (`meta.cutoffs.Alto`) in both `daily_percentile` and `static` modes.
  - Preserved static `SpreadPredictor.categorize` thresholds for target propagation risk classification and Law of Total Probability weighting (`p_risk[s]`).
  - Added `meta.source_cutoff` typing in `frontend/src/api/forecast.ts` and verification in `backend/tests/test_spread.py` (`test_spread_source_selection_aligns_with_daily_percentile_cutoffs`).

- [x] **M3 — Documentation Sync & `openspec/` SDD Bootstrap**
  - Synchronized `README.md`, `specs/01-spec.md`, `specs/02-architecture.md`, and `specs/03-tasks.md` with verified codebase state (`33` backend tests across 7 files, `9` frontend tests across 5 files, `documentacion del proyecto/`, Docker/GHCR + `DonWeb1` native `systemd` deployment).
  - Created living `openspec/` structure (`config.yaml`, `README.md`, 5 RFC 2119 domain specs under `openspec/specs/*/spec.md`, and `openspec/changes/.gitkeep`) for multi-machine Spec-Driven Development.

- [x] **M4 — Selective Daily-Percentile Threshold Tuning (`2B`)**
  - Tightened `RISK_TOP_FRAC_*` defaults (`0.0005` / `0.003` / `0.01`) and raised safety floors `RISK_FLOOR_*` (`0.015` / `0.005` / `0.002`) in `backend/app/config.py` and `backend/app/predictor.py` based on live `DonWeb1` empirical monitor validation (`Nov 20–23`, cutting quiet-day false alarms by ~83% while preserving `4/4` capture on active-signal days).
  - Updated `backend/tests/test_forecast.py`, `frontend/src/i18n.ts`, `frontend/tests/RiskLegend.test.tsx`, and synchronized `openspec/specs/{fire-risk-forecast,frontend-ui}/spec.md`, `README.md`, `specs/01-spec.md..03-tasks.md`, and `documentacion del proyecto/`.
