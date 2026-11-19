# FHIPredict

Live fire-risk and spatial propagation forecast platform for Argentina (`1–15` days), combining pre-trained LightGBM models (`lgbm-risk-24h-v2` and `lgbm-spread-v2`), Open-Meteo weather forecasts, and an empirical NASA FIRMS VIIRS validation monitor.

## Architecture

| Component | Path | Purpose |
|---|---|---|
| FastAPI Inference & Cache | [backend/app/](backend/app/) | `ForecastService` (`service.py`), `FireRiskPredictor` (`predictor.py`), `SpreadPredictor` (`spread.py`), `openmeteo.py` (`971` weather nodes, `past_days=30`, `forecast_days=15`). |
| Empirical VIIRS Monitor | [backend/app/monitor/](backend/app/monitor/) | Daily 24h forecast snapshots (`snapshots.py`), NASA FIRMS VIIRS ingestion (`firms.py`), NumPy evaluator (`evaluator.py`), and DuckDB storage (`memory_limit="256MB"`). |
| Models & Baseline | [backend/models/](backend/models/) | `fire_risk_bundle.joblib`, `spread_bundle.joblib`, `cell_baseline.parquet` (`64,653` 5×5 km cells), and metadata/benchmark reports. |
| Frontend Map & Monitor | [frontend/](frontend/) | React 18 + TypeScript + Vite + Tailwind CSS + MapLibre GL (`/` risk & propagation map, `/monitor` lazy-loaded empirical validation dashboard with charts and CSV export). |
| Specs & ODD Logs | [specs/](specs/), [odd/](odd/) | Functional/architecture specs, spread benchmark results, and tracked task log. |
| Deploy | [Dockerfile](Dockerfile), [.github/workflows/deploy.yml](.github/workflows/deploy.yml) | Multi-stage Docker build + GitHub Actions workflow (`GHCR` + optional SSH deploy). |

## API Endpoints

| Method & Path | Description |
|---|---|
| `GET /api/v1/health` | Status, loaded model versions, total cells (`64,653`), weather grid points (`971`), and cache state. |
| `GET /api/v1/forecast` | 24h (`mode=day`) or multi-day peak (`mode=window`, `1–15d`) fire-risk GeoJSON (`min_risk`, `bbox`, `refresh`). |
| `GET /api/v1/spread` | Conditional neighbor propagation (`24h`/`48h`/`72h`) GeoJSON weighted by source activation probability. |
| `GET /api/v1/monitor/metrics` | Historical empirical metrics (`ROC-AUC`, `PR-AUC`, `calibration_ratio`, `Brier`, `Hits / Misses`, category breakdown). |
| `GET /api/v1/monitor/comparison` | GeoJSON of `hit`, `miss`, and `false_alarm` cells for a target date (omits true negatives). |
| `GET /api/v1/monitor/status` | Non-blocking background monitor job state. |
| `POST /api/v1/monitor/run` | Enqueues async NASA FIRMS VIIRS ingestion & snapshot evaluation (`202 Accepted`; requires `FIRMS_MAP_KEY`). |

## Quick Start

### Backend
```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Set `FIRMS_MAP_KEY` (e.g. in `.env`) to enable NASA FIRMS VIIRS ingestion on `/api/v1/monitor/run` and the periodic background monitor loop.

### Frontend
```powershell
cd frontend
npm ci
npm run dev
```
Open `http://localhost:5173` for the map and `http://localhost:5173/monitor` for the empirical VIIRS dashboard.

### Docker
```bash
docker build -t fhipredict:latest .
docker run -d --name fhipredict -p 8000:8000 -e FIRMS_MAP_KEY=your_key -v fhipredict_monitor:/app/monitor_data fhipredict:latest
```

## Verification

```powershell
# Backend tests (29 tests)
cd backend
.\.venv\Scripts\python.exe -m pytest -q

# Frontend typecheck + tests (7 tests) + build
cd frontend
npm run typecheck
npm test
npm run build
```
