# FHIPredict — Technical Architecture (SDD)

## 1. Repository Structure
```text
FHIPredict-post-hackathon/
├── .github/workflows/
│   └── deploy.yml                  # Build Docker image to GHCR + optional SSH deploy
├── odd/tasks/
│   └── hotspot-propagation-model.md
├── specs/
│   ├── 01-spec.md                  # Product & functional specification
│   ├── 02-architecture.md          # Technical architecture & API contract
│   ├── 03-tasks.md                 # Implementation history
│   ├── 04-propagation-proposal.md  # Propagation model proposal (reconciled)
│   └── 05-comparison-results.md    # Comparative benchmarks (v2 vs spread-v1 vs spread-v2)
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, lifespan loops, SPA static serving, API routes
│   │   ├── config.py               # Pydantic settings (models, cache TTL, Open-Meteo, FIRMS, DuckDB)
│   │   ├── predictor.py            # FireRiskPredictor loader + tree-depth stability
│   │   ├── spread.py               # SpreadPredictor, 8-neighbor graph, wind alignment, fusion
│   │   ├── openmeteo.py            # Async Open-Meteo batch client + 30d/15d weather features
│   │   ├── service.py              # ForecastService: scoring, disk/TTL cache, live VIIRS memory
│   │   └── monitor/
│   │       ├── snapshots.py        # SnapshotStore (idempotent daily 24h snapshots in DuckDB)
│   │       ├── firms.py            # NASA FIRMS CSV client, spatial bucket index, ViirsStore
│   │       ├── evaluator.py        # Pure-NumPy ROC-AUC, PR-AUC, Brier, calibration, outcomes
│   │       └── service.py          # MonitorService (asyncio.Lock, background run, GeoJSON)
│   ├── models/
│   │   ├── fire_risk_bundle.joblib
│   │   ├── fire_risk_metadata.json
│   │   ├── spread_bundle.joblib
│   │   ├── spread_metadata.json
│   │   ├── comparison_report.json
│   │   ├── cell_baseline.parquet   # 64,653 cells: coords, elevation, fuel fractions, industrial flags
│   │   └── .forecast_cache.joblib  # Pre-warmed fallback forecast cache
│   ├── scripts/                    # Offline training & benchmark scripts (export, train, compare, wd10m)
│   ├── tests/                      # 29 pytest tests across 7 test modules
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── forecast.ts         # Typed client for /api/v1/forecast & /api/v1/spread
│   │   │   └── monitor.ts          # Typed client for /api/v1/monitor/* + CSV builder
│   │   ├── components/
│   │   │   ├── RiskMap.tsx         # MapLibre GL map, popups, spread layer, 3D terrain
│   │   │   ├── NavigationPanel.tsx # Province jumps & top-30 high-risk cells
│   │   │   ├── TimeRangeBar.tsx    # Window/day/risk controls & refresh trigger
│   │   │   ├── RiskLegend.tsx      # Risk color scale legend
│   │   │   └── MonitorDashboard.tsx# Separate /monitor dashboard (guide, charts, CSV export)
│   │   ├── data/provinces.ts
│   │   ├── styles/index.css        # FuegoContinuo tokens
│   │   ├── i18n.ts                 # ES / EN translations
│   │   └── App.tsx                 # Route switch (/ vs /monitor) & TanStack Query state
│   ├── tests/                      # 7 Vitest tests across 4 files
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts              # Dev proxy /api -> http://localhost:8000
└── Dockerfile                      # Multi-stage Vite build + Python 3.12 FastAPI runtime
```

---

## 2. Inference & Data Flow

### Model Features Required
- **`lgbm-risk-24h-v2` (20 features)**:
  1. **Static / Cell Baseline** (`cell_baseline.parquet`): `lat_centro`, `lon_centro`, `elevacion_m`, `mediana_historica_mes` (12-month lookup).
  2. **Dynamic Fire Memory** (`ViirsStore` live detections blended with `cell_baseline.parquet`, decayed over forecast horizon `d_idx`): `focos_ultimos_7d`, `focos_ultimos_30d`, `frp_ultimos_7d`, `anios_desde_ultimo_fuego`.
  3. **Calendar**: `mes`, `dia_anio`.
  4. **Dynamic Weather** (Open-Meteo `/v1/forecast`):
     - `daily=temperature_2m_max,relative_humidity_2m_mean,wind_speed_10m_max,wind_direction_10m_dominant,wind_gusts_10m_max,precipitation_sum,shortwave_radiation_sum` (`past_days=30`, `forecast_days=15`, `timezone=America/Argentina/Buenos_Aires`).
     - Computed features: `lluvia_acum_7d`, `lluvia_acum_15d`, `lluvia_acum_30d`, `dias_consecutivos_sin_lluvia` (`< 1.0 mm`), `vpd_approx` (Tetens formula).
- **`lgbm-spread-v2` (47 features)**: adds directed 8-neighbor graph geometry (`dist_km`, `sin_bearing`, `cos_bearing`, `delta_elev_m`, `slope_deg`), source activity/industrial flags (`is_industrial_s`, `industrial_focos_share_s`), 4 biophysical fuel fractions (`fuel_bosque`, `fuel_pastizal`, `fuel_agro`, `fuel_no_combustible`), and directional wind coupling (`wind_alignment`, `upwind_wind_speed`).
  - Unconfirmed high-risk source cells (`p_risk >= Alto` without observed fire) are weighted by `p_risk[s]` under the law of total probability (`service.py`).

### Weather Grid & Memory Budget Strategy
- Each 5×5 km cell maps to **971** unique `(lat_clima, lon_clima)` weather grid nodes.
- Open-Meteo is queried in chunks (`chunk_size=100`, `max_concurrency=1` by default to prevent rate-limit 429s) with retry/backoff, TTL cache (`cache_ttl_s=10800` / 3h), disk cache (`.forecast_cache.joblib`), stale-while-revalidate serving, and a periodic background refresh loop (`refresh_interval_s=10800`).
- DuckDB monitoring stores (`monitor.duckdb`) run with `memory_limit="256MB"` and `threads=1` to fit comfortably within a 1 GB RAM VPS.

---

## 3. Backend API Contract
- `GET /api/v1/health` → `{ status, model_version, spread_model_version, cells_total, grid_points, forecast_cached }`
- `GET /api/v1/forecast?mode=window&days=1..16` or `?mode=day&day_offset=0..15&min_risk=Moderado&bbox=...&refresh=false`
  - Returns GeoJSON `FeatureCollection` (`meta` + up to `20,000` `Point` features) with `cell_id`, `riesgo_pct`, `categoria`, `confianza_pct`, `confianza_nivel`, weather, and elevation properties.
- `GET /api/v1/spread?horizon_hours=24|48|72&day_offset=0..15&min_risk=Moderado&bbox=...&refresh=false`
  - Returns GeoJSON `FeatureCollection` of neighbor propagation probabilities (`propagacion_pct`, `riesgo_base_pct`, `riesgo_fusionado_pct`, `categoria`, `confianza_pct`, `confianza_nivel`, `horizon_hours`).
- `GET /api/v1/monitor/metrics?limit=30` → `{ items: [...] }` (daily empirical metrics from `daily_eval_metrics`).
- `GET /api/v1/monitor/comparison?target_date=YYYY-MM-DD&issued_date=...&min_frp_mw=10.0&min_alert_risk=Moderado` → GeoJSON `FeatureCollection` of `hit`, `miss`, and `false_alarm` cells.
- `GET /api/v1/monitor/status` → `{ running, last_run_at, last_result, last_error }`.
- `POST /api/v1/monitor/run?date=...&day_range=1..10&min_frp_mw=10.0` → `202 Accepted` triggering background VIIRS ingestion + evaluation (`FIRMS_MAP_KEY` required; NASA FIRMS Area API accepts `day_range` 1..5).
