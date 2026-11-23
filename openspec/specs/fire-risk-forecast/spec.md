# Spec: Fire Risk Forecast (`fire-risk-forecast`)

## Scope
Defines baseline loading, Open-Meteo weather ingestion, live VIIRS fire-memory blending, disk/TTL caching, bounded daily-percentile risk categorization, heuristic confidence scoring, and the `/api/v1/health` and `/api/v1/forecast` API contracts.

Primary implementation files:
- `backend/app/config.py`
- `backend/app/predictor.py`
- `backend/app/openmeteo.py`
- `backend/app/service.py`
- `backend/app/main.py`

---

## Requirements

### Requirement FRF-1: Model Bundle & Baseline Loading
`ForecastService` SHALL load `fire_risk_bundle.joblib` (`lgbm-risk-24h-v2`, 20 features, `logit_offset=-4.8283137373023015`, static validation cutoffs `Extremo=0.05785066`, `Alto=0.01292018`, `Moderado=0.00354965`) and `cell_baseline.parquet` (`64,653` 5×5 km cells ordered by `cell_id`, mapped to `971` unique rounded `(lat_clima, lon_clima)` grid coordinates).

#### Scenario: Health check reports loaded baseline and model metadata
- **GIVEN** the FastAPI application has completed lifespan startup with valid model files
- **WHEN** a client sends `GET /api/v1/health`
- **THEN** the server MUST return HTTP `200` with `status="ok"`, `model_version="lgbm-risk-24h-v2"`, `cells_total=64653`, `grid_points=971`, and boolean `forecast_cached`.

---

### Requirement FRF-2: Open-Meteo Ingestion & Rolling Weather Features
`fetch_openmeteo_grid` MUST request 7 daily variables (`temperature_2m_max`, `relative_humidity_2m_mean`, `wind_speed_10m_max`, `wind_direction_10m_dominant`, `wind_gusts_10m_max`, `precipitation_sum`, `shortwave_radiation_sum`) for `past_days=30` and `forecast_days=15` (`timezone=America/Argentina/Buenos_Aires`) in bounded batches (`chunk_size=100`, `max_concurrency=1` by default) with exponential retry/backoff on HTTP `429`/`5xx` and timeouts.
`build_weather_features` SHALL replace upstream nulls with safe local defaults, compute `lluvia_acum_7d`, `lluvia_acum_15d`, `lluvia_acum_30d`, `dias_consecutivos_sin_lluvia` (`precip < 1.0 mm`), and Tetens `vpd_approx`, and slice `D` forecast days starting at the first date `>= today` (or trailing `forecast_days`).

#### Scenario: Rolling weather features produce valid 15-day forecast arrays
- **GIVEN** 30 past days and 15 forecast days of raw weather arrays for 2 grid points
- **WHEN** `build_weather_features(..., forecast_days=15)` runs
- **THEN** the returned `WeatherGridForecast` MUST contain `len(dates) == 15` and `(2, 15)` arrays with computed `vpd_approx` and rolling precipitation sums.

---

### Requirement FRF-3: Live VIIRS Fire Memory Blending & Horizon Decay
`ForecastService._resolve_fire_memory` MUST blend static baseline fire-memory columns (`focos_ultimos_1d`, `focos_ultimos_2d`, `frp_ultimos_1d`, `focos_ultimos_7d`, `focos_ultimos_30d`, `frp_ultimos_7d`, `anios_desde_ultimo_fuego`) with live `ViirsStore` rolling windows (`1d`, `2d`, `7d`, `30d`) weighted by `covered_days / window_days` whenever `covered_days_30d > 0`, taking `min(baseline_anios, days_since_pos / 365.25)` for positive detections. On DuckDB errors or empty history, it SHALL fall back to `cell_baseline.parquet` without failing inference.
`ForecastService._decay_fire_memory_for_horizon` MUST advance fire memory across horizon index `d = day_idx`: setting `focos_1d` and `frp_1d` to `0.0` for `d >= 1`, scaling `focos_2d` by `max(0, (2 - d) / 2)`, `focos_7d` and `frp_7d` by `max(0, (7 - d) / 7)`, `focos_30d` by `max(0, (30 - d) / 30)`, and adding `d / 365.25` to `anios_desde_ultimo_fuego`.

#### Scenario: Live VIIRS detections override baseline and decay across forecast days
- **GIVEN** a VIIRS record stored in `monitor.duckdb` for cell `0` on `2026-11-18` with `4` detections and `45.0` MW FRP
- **WHEN** `_resolve_fire_memory("2026-11-18")` runs and decays to `day_idx=7`
- **THEN** day-0 memory MUST reflect `focos_7d >= 4.0`, `frp_7d >= 45.0`, and `anios_desde_ultimo_fuego < 0.01`
- **AND** at `day_idx=7`, `focos_7d` and `frp_7d` MUST decay to `0.0` while `focos_30d` scales by `23 / 30`.

---

### Requirement FRF-4: TTL Disk Cache & Stale-While-Revalidate Resilience
`ForecastService` SHALL persist `CachedForecast` (`generated_at`, `dates`, `probs`, `stability`, `weather`) to `MODELS_DIR/.forecast_cache.joblib` with `CACHE_TTL_S` (`10800`s default) and periodically refresh every `REFRESH_INTERVAL_S` (`10800`s default).
When an expired cache exists and `refresh=false`, `get_forecast` MUST immediately return the cached payload with `is_stale=True` and trigger a single background refresh task. If upstream Open-Meteo fails while any cache exists, the stale cache SHALL remain served (`expires_at` extended by `60`s); if no cache exists, `GET /api/v1/forecast` MUST return HTTP `503`.

#### Scenario: Periodic refresh survives transient upstream failure
- **GIVEN** `run_periodic_refresh` encounters an upstream error on the first iteration
- **WHEN** the interval elapses for subsequent iterations
- **THEN** the loop MUST log a warning and continue executing future refresh attempts until cancelled.

---

### Requirement FRF-5: Multi-Day Aggregation & Bounded Risk Cutoffs
For `mode="day"`, `query_geojson` SHALL slice `cached.probs[:, idx]` (`0 <= idx < n_avail`) and resolve cutoffs against that day's probabilities.
For `mode="window"`, `query_geojson` MUST take the peak daily probability `max(cached.probs[:, :span], axis=1)` (`span = clamp(days, 1, n_avail)`) as the comonotonic Fréchet bound preserving the 24h probability scale, and resolve cutoffs against `cached.probs[:, :span]`.
`ForecastService._resolve_risk_cutoffs` MUST inspect `RISK_CUTOFF_MODE`:
- When `"static"`, it SHALL return `predictor.risk_cutoffs`.
- When `"daily_percentile"` (default), `FireRiskPredictor.compute_daily_percentile_cutoffs` MUST compute empirical quantiles at `1 - RISK_TOP_FRAC_MODERADO` (`0.01`, top `1%`), `1 - RISK_TOP_FRAC_ALTO` (`0.003`, top `0.3%`), and `1 - RISK_TOP_FRAC_EXTREMO` (`0.0005`, top `0.05%`), clamp each below by selective `RISK_FLOOR_*` bounds (`0.002`, `0.005`, `0.015` — calibrated on Nov 20–23 `DonWeb1` empirical data to cut quiet-day false alarms by ~83% while preserving active-day capture), cap each above by the static validation cutoffs, enforce `Extremo >= Alto >= Moderado`, and fall back to static validation cutoffs when finite values `< 100`, `vmax - vmin <= 1e-12`, or `q_mod <= vmin + 1e-12`.

#### Scenario: Multi-day window preserves 24h probability scale
- **GIVEN** all `64,653` cells have a constant daily probability `0.0045` (`Moderado` in static mode, below `Alto` `0.01292`) across 15 days
- **WHEN** `query_geojson(..., mode="window", days=15, min_risk="Moderado")` runs
- **THEN** `meta.counts["Extremo"]` and `meta.counts["Alto"]` MUST both be `0`, and `meta.counts["Moderado"]` MUST equal `64653`.

#### Scenario: Daily percentile mode adapts, caps outbreaks, clamps rainy days, and guards degenerate inputs
- **GIVEN** `RISK_CUTOFF_MODE="daily_percentile"`
- **WHEN** daily probabilities sit below static cutoffs with non-degenerate spread
- **THEN** `Extremo` / `Alto` / `Moderado` cutoffs MUST drop below static cutoffs to target ~`0.05%`, `0.3%`, and `1%` of cells (clamped at or above `0.015`, `0.005`, `0.002`)
- **AND** on severe outbreaks exceeding static cutoffs, cutoffs MUST cap at static bundle values
- **AND** on near-zero rainy or quiet low-risk days (`<= 0.0018`), cutoffs MUST clamp at safety floors (`0.015`, `0.005`, `0.002`) yielding zero alerts
- **AND** on constant, `< 100` sample, or tied (`q_mod <= vmin`) distributions, cutoffs MUST fall back to static bundle values.

---

### Requirement FRF-6: Heuristic Confidence & GeoJSON Response Contract
`FireRiskPredictor.predict_with_stability` SHALL evaluate tree-depth agreement across `(N // 2, 3N // 4, N)` trees (`stability = clip(1.0 - spread / 0.25, 0.2, 1.0)`).
`ForecastService._compute_confidence` MUST compute `conf_pct = clip(stability * clip(1 - day_idx * CONFIDENCE_HORIZON_DECAY_PER_DAY, 0.35, 1.0) * freshness_factor * extra_factor * 100, 5.0, 99.0)` where `freshness_factor = max(0.5, 1.0 - CONFIDENCE_STALE_PENALTY)` when stale, mapping to `"Alta"` (`>= 75.0`), `"Media"` (`>= 50.0`), or `"Baja"`.
`GET /api/v1/forecast` SHALL return a GeoJSON `FeatureCollection` containing:
- `meta`: `model_version`, `generated_at`, `mode`, `fecha_desde`, `fecha_hasta`, `dates_available`, `counts` (across all `64,653` cells), `cutoffs: { mode, Extremo, Alto, Moderado }`, and `returned`.
- `features`: filtered by `min_risk` (`Bajo` | `Moderado` | `Alto` | `Extremo`) and optional `bbox=west,south,east,north` (returning HTTP `400` if malformed), capped to at most `20,000` highest-probability `Point` features.

#### Scenario: Confidence decreases with forecast horizon and stale cache
- **GIVEN** identical tree-depth stability `0.95`
- **WHEN** `_compute_confidence` evaluates `day_idx=0` fresh, `day_idx=14` fresh, and `day_idx=0` stale
- **THEN** fresh day-0 confidence MUST exceed both day-14 confidence and stale day-0 confidence.
