# FHIPredict

Live fire-risk and spatial neighbor propagation forecast platform for Argentina (`1–15` days), combining pre-trained LightGBM models (`lgbm-risk-24h-v2` and `lgbm-spread-v2`), Open-Meteo weather forecasts, and an empirical NASA FIRMS VIIRS validation monitor.

## Architecture & Repository Layout

| Component | Path | Purpose |
|---|---|---|
| FastAPI Inference & Cache | [backend/app/](backend/app/) | `ForecastService` (`service.py`), `FireRiskPredictor` (`predictor.py`), `SpreadPredictor` (`spread.py`), `openmeteo.py` (`971` weather nodes, `past_days=30`, `forecast_days=15`), and `config.py`. |
| Empirical VIIRS Monitor | [backend/app/monitor/](backend/app/monitor/) | Daily 24h forecast snapshots (`snapshots.py`), NASA FIRMS VIIRS ingestion (`firms.py`), pure-NumPy evaluator (`evaluator.py`), and DuckDB storage (`memory_limit="256MB"`, `threads=1`). |
| Models & Baseline | [backend/models/](backend/models/) | `fire_risk_bundle.joblib`, `spread_bundle.joblib`, `cell_baseline.parquet` (`64,653` 5×5 km cells), `.forecast_cache.joblib`, and metadata/benchmark JSON reports. |
| Offline Scripts | [backend/scripts/](backend/scripts/) | Baseline exporter, directional wind fetch, spread training, and comparative benchmark scripts. |
| Frontend Map & Monitor | [frontend/](frontend/) | React 18 + TypeScript + Vite + Tailwind CSS + MapLibre GL (`/` risk & propagation map, `/monitor` lazy-loaded empirical validation dashboard with charts and CSV export). |
| Spec-Driven Development | [openspec/](openspec/) | Living SDD workspace (`config.yaml`, `README.md`, 5 domain specs under `openspec/specs/*/spec.md`, and `openspec/changes/`) for multi-machine development. |
| Baseline Specs & ODD Logs | [specs/](specs/), [odd/](odd/) | Product/architecture baseline specs, spread proposal & benchmark results, and tracked task log. |
| Spanish Walkthrough Docs | [documentacion del proyecto/](documentacion%20del%20proyecto/) | End-to-end Spanish onboarding, modeling, and operations documentation. |
| Deploy | [Dockerfile](Dockerfile), [.github/workflows/deploy.yml](.github/workflows/deploy.yml) | Multi-stage Docker build + GitHub Actions GHCR build/optional SSH deploy; production also supports native `systemd` deployment on `DonWeb1` VPS. |

## API Endpoints

| Method & Path | Description |
|---|---|
| `GET /api/v1/health` | Service status, loaded model versions, total cells (`64,653`), weather grid points (`971`), and forecast cache state. |
| `GET /api/v1/forecast` | 24h (`mode=day`) or multi-day peak (`mode=window`, `1–15d`) fire-risk GeoJSON (`min_risk`, `bbox`, `refresh`; capped at `20,000` points) with `meta.counts` and `meta.cutoffs`. |
| `GET /api/v1/spread` | Conditional neighbor propagation (`24h`/`48h`/`72h`) GeoJSON weighted by source activation probability, returning `meta.source_cutoff` (aligned with `_resolve_risk_cutoffs`) and static `SpreadPredictor.categorize` counts. |
| `GET /api/v1/monitor/metrics` | Historical empirical metrics (`ROC-AUC`, `PR-AUC`, `calibration_ratio`, `Brier`, `Hits / Misses`, category breakdown). |
| `GET /api/v1/monitor/comparison` | GeoJSON of `hit`, `miss`, and `false_alarm` cells for a target date (omits true negatives; returns `404` if snapshot is absent). |
| `GET /api/v1/monitor/status` | Non-blocking background monitor job state (`running`, `last_run_at`, `last_result`, `last_error`). |
| `POST /api/v1/monitor/run` | Enqueues async NASA FIRMS VIIRS ingestion & snapshot evaluation (`202 Accepted`; accepts `day_range` `1..10`, while NASA FIRMS Area API accepts `1..5`; requires `FIRMS_MAP_KEY`). |

## Key Environment Configuration (`backend/app/config.py`)

Settings load from environment variables or `.env` via Pydantic `BaseSettings`.

| Variable | Default | Purpose |
|---|---|---|
| `RISK_CUTOFF_MODE` | `daily_percentile` | Categorization mode for `/api/v1/forecast`, 24h snapshots, and unconfirmed `/api/v1/spread` sources (`daily_percentile` or `static`). |
| `RISK_TOP_FRAC_EXTREMO` / `_ALTO` / `_MODERADO` | `0.0005` / `0.004` / `0.025` | Target daily top fractions (`0.05%` / `0.4%` actionable `Alto+` alerts, `2.5%` preventive `Moderado` watch) in `daily_percentile` mode, capped at static bundle validation cutoffs. |
| `RISK_FLOOR_EXTREMO` / `_ALTO` / `_MODERADO` | `0.008` / `0.002` / `0.0005` | Lower probability floors (`0.8%`, `0.2%`, `0.05%`) balancing quiet-day false-alarm reduction with fire recall. |
| `CONFIDENCE_HORIZON_DECAY_PER_DAY` | `0.025` | Daily decay subtracted from heuristic confidence across the `1–15d` horizon (clamped at `0.35` minimum factor). |
| `CONFIDENCE_STALE_PENALTY` | `0.15` | Multiplicative confidence penalty when serving stale cached weather/forecasts. |
| `CONFIDENCE_HIGH_CUTOFF` / `_MEDIUM_CUTOFF` | `75.0` / `50.0` | Percentage thresholds mapping heuristic confidence (`5–99%`) to `Alta`, `Media`, and `Baja`. |
| `ENABLE_SPREAD` | `true` | Enables `lgbm-spread-v2` loading and `GET /api/v1/spread`. |
| `ENABLE_MONITOR_SNAPSHOTS` | `true` | Enables automatic daily 24h snapshot persistence into DuckDB. |
| `MONITOR_DUCKDB_MEMORY_LIMIT` | `256MB` | DuckDB memory limit (`threads=1`) sized for 1 GB RAM VPS operation. |
| `CACHE_TTL_S` / `REFRESH_INTERVAL_S` | `10800` / `10800` | Forecast cache TTL and periodic Open-Meteo background refresh interval (seconds). |
| `MONITOR_REFRESH_INTERVAL_S` | `21600` | Periodic background VIIRS ingest & evaluation interval (seconds). |
| `FIRMS_MAP_KEY` | *(empty)* | Required NASA FIRMS API key for `POST /api/v1/monitor/run` and periodic VIIRS monitoring. |
| `MODELS_DIR` / `STATIC_DIR` / `MONITOR_DIR` | `backend/models` / `None` / `backend/monitor_data` | Paths for model bundles, built frontend static assets, and `monitor.duckdb`. |

## Quick Start

### Backend
```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Set `FIRMS_MAP_KEY` (for example in `.env`) to enable NASA FIRMS VIIRS ingestion on `/api/v1/monitor/run` and the periodic background monitor loop.

### Frontend
```powershell
cd frontend
npm ci
npm run dev
```
Open `http://localhost:5173` for the forecast map and `http://localhost:5173/monitor` for the empirical VIIRS dashboard (Vite proxies `/api` to `http://127.0.0.1:8000`).

### Docker & Production Deployment
```bash
docker build -t fhipredict:latest .
docker run -d --name fhipredict --memory="850m" -p 8000:8000 -e FIRMS_MAP_KEY=your_key -v fhipredict_monitor:/app/monitor_data fhipredict:latest
```
Production deployment supports two paths:
1. **Docker / GHCR (`.github/workflows/deploy.yml`)**: builds multi-stage images to GHCR on pushes to `main` and optionally deploys over SSH (`--memory="850m"`) when repository variable `ENABLE_VPS_DEPLOY` is `'true'` and deployment secrets are configured.
2. **Native `systemd` on `DonWeb1` VPS**: runs `uvicorn app.main:app` directly inside an isolated Python virtualenv (`/opt/fhipredict/venv`) with prebuilt static assets (`/opt/fhipredict/static`), environment configuration in `/opt/fhipredict/.env`, and persistent DuckDB state in `/opt/fhipredict/monitor_data/monitor.duckdb` within a 1 GB RAM budget. When pulling `main` on `DonWeb1`, preserve and restore `backend/models/.forecast_cache.joblib` before restarting `fhipredict.service`.

## Spec-Driven Development (`openspec/`)

All feature and bugfix changes follow the multi-machine SDD workflow defined in [openspec/README.md](openspec/README.md) and [openspec/config.yaml](openspec/config.yaml): pull `main`, read the relevant domain spec under `openspec/specs/`, track proposals/deltas in `openspec/changes/`, implement with tests, merge approved requirements into `openspec/specs/`, and commit/push cleanly.

## Verification

```powershell
# Backend tests (33 tests across 7 files)
cd backend
.\.venv\Scripts\python.exe -m pytest -q

# Frontend typecheck + tests (9 tests across 5 files) + build
cd frontend
npm run typecheck
npm test
npm run build
```
