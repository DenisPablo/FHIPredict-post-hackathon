# FHIPredict — Technical Architecture (SDD)

## 1. Repository Structure
```text
FHIPredict-post-hackathon/
├── .github/workflows/
│   └── deploy.yml                  # Build Docker image to GHCR + optional SSH deploy
├── documentacion del proyecto/     # Spanish walkthrough & operations documentation (00..05)
├── odd/tasks/
│   └── hotspot-propagation-model.md
├── openspec/                       # Living Spec-Driven Development workspace
│   ├── config.yaml                 # Project metadata, hardware constraints & SDD workflow rules
│   ├── README.md                   # Multi-machine SDD guide
│   ├── changes/.gitkeep            # Active feature change proposals/deltas
│   └── specs/
│       ├── deployment/spec.md
│       ├── fire-risk-forecast/spec.md
│       ├── frontend-ui/spec.md
│       ├── spatial-spread/spec.md
│       └── viirs-monitor/spec.md
├── specs/
│   ├── 01-spec.md                  # Product & functional specification overview
│   ├── 02-architecture.md          # Technical architecture & API contract
│   ├── 03-tasks.md                 # Implementation history & milestone reconciliation
│   ├── 04-propagation-proposal.md  # Propagation model proposal (reconciled)
│   └── 05-comparison-results.md    # Comparative benchmarks (v2 vs spread-v1 vs spread-v2)
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, lifespan loops, SPA static serving, API routes
│   │   ├── config.py               # Pydantic settings (models, cache TTL, cutoffs, confidence, FIRMS, DuckDB)
│   │   ├── predictor.py            # FireRiskPredictor loader, tree-depth stability & daily percentile cutoffs
│   │   ├── spread.py               # SpreadPredictor, 8-neighbor graph, wind alignment, fusion
│   │   ├── openmeteo.py            # Async Open-Meteo batch client + 30d/15d weather features
│   │   ├── service.py              # ForecastService: scoring, disk/TTL cache, live VIIRS memory, cutoffs
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
│   ├── tests/                      # 33 pytest tests across 7 test modules
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── forecast.ts         # Typed client for /api/v1/forecast & /api/v1/spread
│   │   │   └── monitor.ts          # Typed client for /api/v1/monitor/* + CSV builder
│   │   ├── components/
│   │   │   ├── RiskMap.tsx         # MapLibre GL map, popups, spread layer, 3D terrain, roads
│   │   │   ├── NavigationPanel.tsx # Province jumps (25 targets) & top-30 high-risk cells
│   │   │   ├── TimeRangeBar.tsx    # Window/day/risk controls & refresh trigger
│   │   │   ├── RiskLegend.tsx      # Dynamic daily-percentile or static risk scale legend
│   │   │   └── MonitorDashboard.tsx# Separate /monitor dashboard (guide, charts, CSV export)
│   │   ├── data/provinces.ts
│   │   ├── styles/index.css        # FuegoContinuo tokens
│   │   ├── i18n.ts                 # ES / EN translations
│   │   └── App.tsx                 # Route switch (/ vs /monitor) & TanStack Query state
│   ├── tests/                      # 9 Vitest tests across 5 files
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts              # Dev proxy /api -> http://127.0.0.1:8000
├── Dockerfile                      # Multi-stage Vite build + Python 3.12 FastAPI runtime
├── DOCUMENTACION_PROPAGACION_ESPACIAL.md
├── README.md
└── veredicto-modelo-predictivo.md
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
  - Active source cells combine non-industrial cells (`is_industrial < 0.5`) with recent observed fire memory (`focos_7d >= 1.0`) or unconfirmed high predicted risk (`p_risk >= source_cutoffs["Alto"]`), where `source_cutoffs` is resolved via `ForecastService._resolve_risk_cutoffs(p_risk)`.
  - Unconfirmed high-risk source cells are weighted by `p_risk[s]` under the Law of Total Probability (`service.py`).
  - Target propagation probabilities `p_spread` are categorized using static bundle thresholds (`SpreadPredictor.categorize`: `Extremo >= 0.456281`, `Alto >= 0.197783`, `Moderado >= 0.082370`).

### Risk Cutoffs, Confidence & Memory Budget Controls
- **Cutoffs (`RISK_CUTOFF_MODE`)**:
  - `daily_percentile` (default): `FireRiskPredictor.compute_daily_percentile_cutoffs` derives top `1%` (`RISK_TOP_FRAC_MODERADO=0.01`), `0.3%` (`RISK_TOP_FRAC_ALTO=0.003`), and `0.05%` (`RISK_TOP_FRAC_EXTREMO=0.0005`) quantiles, clamped between selective safety floors (`RISK_FLOOR_MODERADO=0.002`, `RISK_FLOOR_ALTO=0.005`, `RISK_FLOOR_EXTREMO=0.015`) and static bundle validation cutoffs (`0.003550` / `0.012920` / `0.057851`), with static fallback on `< 100` finite samples or degenerate/tied distributions.
  - `static`: uses fixed validation cutoffs from `fire_risk_bundle.joblib`.
- **Heuristic Confidence**: `stability * clip(1 - day_idx * CONFIDENCE_HORIZON_DECAY_PER_DAY, 0.35, 1.0) * freshness_factor * extra_factor * 100`, clamped to `[5.0, 99.0]`, where `CONFIDENCE_STALE_PENALTY=0.15`, `CONFIDENCE_HIGH_CUTOFF=75.0` (`Alta`), and `CONFIDENCE_MEDIUM_CUTOFF=50.0` (`Media`, else `Baja`). Spread applies `extra_factor=0.9`.
- **Weather Grid & Memory Budget**:
  - Each 5×5 km cell maps to **971** unique `(lat_clima, lon_clima)` weather grid nodes.
  - Open-Meteo is queried in chunks (`chunk_size=100`, `max_concurrency=1` by default to prevent rate-limit `429`s) with retry/backoff, TTL cache (`cache_ttl_s=10800` / 3h), disk cache (`.forecast_cache.joblib`), stale-while-revalidate serving, and a periodic background refresh loop (`refresh_interval_s=10800`).
  - DuckDB monitoring stores (`monitor.duckdb`) run with `memory_limit="256MB"` and `threads=1` to fit comfortably within a 1 GB RAM VPS.

---

## 3. Backend API Contract
- `GET /api/v1/health` → `{ status, model_version, spread_model_version, cells_total, grid_points, forecast_cached }`
- `GET /api/v1/forecast?mode=window&days=1..16` or `?mode=day&day_offset=0..15&min_risk=Moderado&bbox=...&refresh=false`
  - Returns GeoJSON `FeatureCollection` (`meta` + up to `20,000` `Point` features) with `cell_id`, `riesgo_pct`, `categoria`, `confianza_pct`, `confianza_nivel`, weather, and elevation properties.
  - `meta` includes `model_version`, `generated_at`, `mode`, `fecha_desde`, `fecha_hasta`, `dates_available`, `counts` (across all `64,653` cells), `cutoffs: { mode, Extremo, Alto, Moderado }`, and `returned`.
- `GET /api/v1/spread?horizon_hours=24|48|72&day_offset=0..15&min_risk=Moderado&bbox=...&refresh=false`
  - Returns GeoJSON `FeatureCollection` (up to `20,000` features) of neighbor propagation probabilities (`propagacion_pct`, `riesgo_base_pct`, `riesgo_fusionado_pct`, `categoria`, `confianza_pct`, `confianza_nivel`, `horizon_hours`).
  - `meta` includes `model_version`, `baseline_model_version`, `generated_at`, `horizon_hours`, `fecha_desde`, `fecha_hasta`, `active_source_cells`, `source_cutoff: { mode, Alto }`, `counts` (from static `SpreadPredictor.categorize`), and `returned`.
- `GET /api/v1/monitor/metrics?limit=30` → `{ items: [...] }` (daily empirical metrics from `daily_eval_metrics`, newest first).
- `GET /api/v1/monitor/comparison?target_date=YYYY-MM-DD&issued_date=...&min_frp_mw=10.0&min_alert_risk=Moderado` → GeoJSON `FeatureCollection` of `hit`, `miss`, and `false_alarm` cells (`404` when snapshot is missing).
- `GET /api/v1/monitor/status` → `{ running, last_run_at, last_result, last_error }`.
- `POST /api/v1/monitor/run?date=...&day_range=1..10&min_frp_mw=10.0` → `202 Accepted` triggering background VIIRS ingestion + evaluation (`FIRMS_MAP_KEY` required, else `400`; note NASA FIRMS Area API accepts `day_range` `1..5`).

---

## 4. Production Deployment Topologies
- **Containerized (Docker / GHCR)**: Multi-stage `Dockerfile` + `.github/workflows/deploy.yml` pushing `ghcr.io/<owner>/fhipredict:latest` and optionally deploying via SSH (`ENABLE_VPS_DEPLOY == 'true'`) with `--memory="850m"` and mounted `monitor_data`.
- **Native `systemd` (`DonWeb1` VPS)**: 1 GB RAM + swap Ubuntu VPS running `fhipredict.service` (`uvicorn`) from `/opt/fhipredict/venv`, serving prebuilt `/opt/fhipredict/static`, configured via `/opt/fhipredict/.env` (env vars only; no secrets in Git), and persisting `monitor.duckdb` in `/opt/fhipredict/monitor_data/`. Live server pulls preserve and restore `backend/models/.forecast_cache.joblib` across `git pull --ff-only origin main`.
