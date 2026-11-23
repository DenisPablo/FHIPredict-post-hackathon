# Spec: Spatial Hotspot Propagation (`spatial-spread`)

## Scope
Defines the conditional 8-neighbor wildfire propagation model (`lgbm-spread-v2`), directed spatial graph construction, directional wind coupling, source-cell selection alignment with daily-percentile risk cutoffs, target probability aggregation and fusion, static target categorization, and the `/api/v1/spread` API contract.

Primary implementation files:
- `backend/app/spread.py`
- `backend/app/service.py`
- `backend/app/main.py`

---

## Requirements

### Requirement SSP-1: Spread Bundle & Directed 8-Neighbor Spatial Graph
When `ENABLE_SPREAD=true` (default) and `MODELS_DIR/spread_bundle.joblib` exists, `ForecastService` SHALL load `SpreadPredictor` (`lgbm-spread-v2`, 47 `SPREAD_FEATURE_COLUMNS`, `logit_offset=-1.6094379124341003`, `wind_directional_gain=0.20`, and static `risk_cutoffs` `Extremo=0.45628072`, `Alto=0.19778348`, `Moderado=0.08237030`).
`build_neighbor_graph` MUST construct directed edges `(s -> t)` across the `64,653` 5×5 km cells satisfying `0.1 < dist_km <= 8.5` with `bearing_deg`, `sin_bearing`, `cos_bearing`, `delta_elev_m = elev_t - elev_s`, and `slope_deg`.
When `ENABLE_SPREAD=false` or `spread_bundle.joblib` is missing, `GET /api/v1/spread` MUST return HTTP `503`.

#### Scenario: Regular 3x3 grid yields 8 outgoing edges from center cell
- **GIVEN** a regular 3×3 grid of 5 km cells around `(-31.50, -64.50)`
- **WHEN** `build_neighbor_graph(..., max_dist_km=8.5)` runs
- **THEN** the center cell MUST have exactly `8` outgoing edges with valid bearings, distances, and elevation slopes.

---

### Requirement SSP-2: Monotonicity & Directional Wind Coupling
The `lgbm-spread-v2` model MUST preserve monotone constraints (`+1` on `horizon_days`, `-1` on `fuel_no_combustible_t` and `is_industrial_s`) so longer horizons never decrease propagation probability and higher non-combustible fractions or industrial sources never increase propagation probability.
`compute_wind_alignment` MUST compute `cos(radians(((wind_from_deg + 180) % 360) - bearing_s_to_t_deg))` in `[-1, 1]`.
When directional wind arrays are available, `SpreadPredictor.predict_pair_probabilities` MUST inject `wind_alignment` and `upwind_wind_speed` into `X` and add `wind_directional_gain * wind_alignment * clip(wind_speed_kmh / 30.0, 0.0, 2.5)` to the logit before sigmoid calibration.

#### Scenario: Downwind neighbors receive higher spread probability than upwind neighbors
- **GIVEN** a source-target pair directed due North (`bearing=0°`) and wind speed `35 km/h`
- **WHEN** wind blows from South (`180°`, downwind `alignment=+1`) vs from North (`0°`, upwind `alignment=-1`)
- **THEN** `predict_pair_probabilities` MUST produce strictly higher probability for downwind propagation than upwind propagation.

#### Scenario: Spread predictions respect horizon and barrier monotonicity
- **GIVEN** random valid 47-feature candidate vectors
- **WHEN** `predict_pair_probabilities` evaluates `horizon_days` in `{1, 2, 3}` (24h, 48h, 72h), increasing `fuel_no_combustible_t`, and `is_industrial_s=1` vs `0`
- **THEN** `P(24h) <= P(48h) <= P(72h)`, high non-combustible barrier `<=` low barrier, and industrial source `<=` non-industrial source within floating-point tolerance (`1e-6`).

---

### Requirement SSP-3: Source Selection Alignment & Law of Total Probability Weighting
In `ForecastService.query_spread_geojson`, active propagation sources SHALL include only non-industrial cells (`is_industrial < 0.5`) that either have recent observed fire memory (`mem_d.focos_7d >= 1.0`) OR have predicted base ignition risk `p_risk >= source_cutoffs["Alto"]`, where `source_cutoffs, source_cutoff_mode = self._resolve_risk_cutoffs(p_risk)`.
Under the Law of Total Probability, `source_active_prob` MUST equal `1.0` for observed-fire sources and `p_risk[s]` for unconfirmed high-risk sources. Each candidate pair probability `cond_pair_probs` MUST be multiplied by `source_active_prob[s_idx]` prior to target aggregation.

#### Scenario: Unconfirmed source selection aligns with daily-percentile cutoffs (`7be2e6d`)
- **GIVEN** a day with zero observed VIIRS fire memory and maximum cell ignition probability `0.01001` (below static `Alto=0.01292`)
- **WHEN** `/api/v1/forecast` and `/api/v1/spread` are queried under `RISK_CUTOFF_MODE="daily_percentile"`
- **THEN** `/api/v1/spread` `meta.source_cutoff.mode` MUST be `"daily_percentile"`
- **AND** `meta.source_cutoff.Alto` MUST equal `/api/v1/forecast` `meta.cutoffs.Alto`
- **AND** `meta.active_source_cells` MUST equal the count of non-industrial cells with `p_risk >= cutoffs["Alto"]` (`> 0`)
- **AND** when `RISK_CUTOFF_MODE="static"`, `meta.source_cutoff.mode` MUST be `"static"` with `active_source_cells == 0`.

#### Scenario: Unconfirmed high-risk sources yield proportionally lower spread than confirmed fires
- **GIVEN** an interior non-industrial cell with `p_risk=0.02` (`Alto`)
- **WHEN** `query_spread_geojson` runs with zero observed fire memory vs with `focos_7d=3.0` and `frp_1d=35.0`
- **THEN** unconfirmed-source spread probability at a neighbor MUST remain strictly attenuated relative to the confirmed-fire scenario.

---

### Requirement SSP-4: Target Aggregation, Risk Fusion & Static Categorization
`aggregate_target_probabilities` MUST combine incoming edge probabilities at target `t` via log-complement product `P_spread(t) = 1 - prod_s (1 - pair_probs(s -> t))`.
`fuse_risk_and_spread` SHALL compute combined risk `1 - (1 - p_risk) * (1 - p_spread)`.
Target cell risk categories (`Extremo`, `Alto`, `Moderado`, `Bajo`) in `query_spread_geojson` MUST continue using static `SpreadPredictor.categorize(p_spread)` (`Extremo >= 0.456281`, `Alto >= 0.197783`, `Moderado >= 0.082370`) rather than daily percentiles.

#### Scenario: Static spread categorization prevents false Alto/Extremo spread alerts from unconfirmed sources
- **GIVEN** unconfirmed `Alto` source cells weighted by `p_risk < 0.015` under `daily_percentile` mode
- **WHEN** `query_spread_geojson` categorizes `p_spread`
- **THEN** `meta.counts["Extremo"]` and `meta.counts["Alto"]` MUST remain `0` because `SpreadPredictor.categorize` enforces static propagation thresholds.

---

### Requirement SSP-5: Spread Endpoint Validation & Response Contract
`GET /api/v1/spread` SHALL validate `horizon_hours` in `{24, 48, 72}` (HTTP `400` otherwise), `day_offset` in `0..15`, optional `min_risk`, optional `bbox=west,south,east,north` (HTTP `400` if invalid), and `refresh`.
`query_spread_geojson` MUST retain only cells with `ranks >= min_rank` AND `p_spread > 0.0`, apply confidence with `extra_factor=0.9`, cap output at `20,000` highest-`p_spread` features, and return `meta` including `model_version`, `baseline_model_version`, `generated_at`, `horizon_hours`, `fecha_desde`, `fecha_hasta`, `active_source_cells`, `source_cutoff: { mode, Alto }`, `counts`, and `returned`.

#### Scenario: Spread endpoint serves 24h, 48h, and 72h GeoJSON FeatureCollections
- **GIVEN** a warmed forecast cache and loaded `lgbm-spread-v2` bundle
- **WHEN** a client requests `GET /api/v1/spread?horizon_hours=24|48|72&min_risk=Moderado`
- **THEN** each response MUST return HTTP `200`, `type="FeatureCollection"`, `meta.model_version="lgbm-spread-v2"`, matching `meta.horizon_hours`, and `meta.source_cutoff`.
