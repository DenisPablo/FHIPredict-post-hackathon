# Spec: Empirical VIIRS Monitor (`viirs-monitor`)

## Scope
Defines idempotent daily 24h forecast snapshot persistence, NASA FIRMS VIIRS hotspot ingestion and 5 km cell mapping, pure-NumPy daily empirical evaluation, DuckDB storage under a 256 MB memory budget, and the `/api/v1/monitor/*` API contract.

Primary implementation files:
- `backend/app/monitor/snapshots.py`
- `backend/app/monitor/firms.py`
- `backend/app/monitor/evaluator.py`
- `backend/app/monitor/service.py`
- `backend/app/main.py`

---

## Requirements

### Requirement MON-1: Idempotent Daily 24h Snapshot Persistence
When `ENABLE_MONITOR_SNAPSHOTS=true`, `ForecastService._maybe_save_snapshot_24h` SHALL resolve the Argentina (`UTC-3`) calendar date from `generated_at` (`argentina_today_iso`), select the matching forecast day index (`target_date = issued_date = today_ar` when present, fallback `0`), and persist those probabilities and risk categories computed via `_resolve_risk_cutoffs(probs_24h)` into `SnapshotStore` (`forecast_snapshots_24h` table in `MONITOR_DIR/monitor.duckdb`).
`SnapshotStore.save_snapshot_24h` MUST reject empty or mismatched-length arrays with `ValueError`, MUST be idempotent per `(issued_date, cell_id)` (returning `False` without overwriting when `issued_date` already exists and `overwrite=False`), and SHALL use DuckDB settings `memory_limit=MONITOR_DUCKDB_MEMORY_LIMIT` (`"256MB"` default) and `threads=1`.

#### Scenario: Snapshot persistence matches forecast cutoffs and ignores duplicate writes
- **GIVEN** a `CachedForecast` scored on `2026-11-18` under `RISK_CUTOFF_MODE="daily_percentile"`
- **WHEN** `_maybe_save_snapshot_24h` runs twice for the same `issued_date`
- **THEN** the first call MUST return `True` with per-category cell counts matching `query_geojson(..., mode="day", day_offset=0)["meta"]["counts"]`
- **AND** the second call MUST return `False` without modifying stored rows.

---

### Requirement MON-2: NASA FIRMS VIIRS Ingestion & Spatial Mapping
`MonitorService.ingest_and_evaluate` SHALL acquire `asyncio.Lock`, iterate over `FIRMS_SOURCES` (`VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`), fetch area CSVs from `FIRMS_BASE_URL` for `FIRMS_BBOX` (`-73.6,-55.2,-53.5,-21.7`), exclude low-confidence detections (`confidence == "l"`) by default in `parse_firms_csv`, assign detections to nearest cell within `max_dist_km=6.0` via `CellSpatialIndex` (returning `-1` beyond `6.0 km` and dropping `-1` during `aggregate_viirs_by_cell`), and upsert `(acq_date, source, cell_id)` partitions in `ViirsStore` (`viirs_cell_daily`).
For each ingested `acq_date` that already has a stored 24h snapshot, `ingest_and_evaluate` SHALL trigger `evaluate_date`.

#### Scenario: FIRMS CSV parsing filters low-confidence rows and maps nearby cells
- **GIVEN** a FIRMS CSV containing high (`h`), nominal (`n`), and low (`l`) confidence rows plus one point beyond `6.0 km`
- **WHEN** `parse_firms_csv(..., exclude_low_confidence=True)`, `CellSpatialIndex.assign`, and `aggregate_viirs_by_cell` run
- **THEN** the low-confidence row MUST be excluded, the distant hotspot MUST map to `-1` and be dropped, and in-range rows MUST aggregate counts, `frp_sum`, and `frp_max` by `(acq_date, cell_id)`.

#### Scenario: Re-ingesting the same date and source replaces cleanly
- **GIVEN** existing `viirs_cell_daily` rows for `("2026-11-18", "VIIRS_SNPP_NRT")`
- **WHEN** `ViirsStore.save_daily_detections` saves updated detections for the same `(acq_date, source)`
- **THEN** prior rows for that `(acq_date, source)` partition MUST be replaced atomically without primary-key errors.

---

### Requirement MON-3: Pure-NumPy Empirical Evaluation & Outcome Classification
`build_ground_truth_vector` MUST align sparse VIIRS rows onto snapshot `cell_id` order and mark a cell positive (`1`) iff `detections_count >= 1` AND `frp_sum >= min_frp_mw` (`10.0` MW default).
`compute_binary_metrics` MUST calculate pure-NumPy `observed_rate`, `mean_predicted_prob`, `calibration_ratio` (`None` when `observed_rate == 0.0`), `brier_score`, `roc_auc` (`None` when `n_pos == 0` or `n_neg == 0`), `pr_auc` (`None` when `n_pos == 0`), and per-category (`Extremo`, `Alto`, `Moderado`, `Bajo`) `cells_count`, `positives_count`, `precision`, `recall`, and `lift`.
`classify_cell_outcomes` SHALL label cells with `risk >= min_alert_risk` (default `"Alto"`; `Moderado` acts as a non-alarm preventive watch layer) and `y_true == 1` as `"hit"`, `risk >= min_alert_risk` and `y_true == 0` as `"false_alarm"`, `risk < min_alert_risk` and `y_true == 1` as `"miss"`, and MUST omit true negatives.
`EvaluationStore` MUST persist records in `daily_eval_metrics` keyed by `(target_date, issued_date, min_frp_mw)`.

#### Scenario: Zero positive detections avoid division by zero
- **GIVEN** probabilities and categories paired with an all-zero ground truth vector (`n_positives == 0`)
- **WHEN** `compute_binary_metrics` runs
- **THEN** `roc_auc`, `pr_auc`, and `calibration_ratio` MUST be `None` without raising exceptions.

#### Scenario: Outcome classification omits true negatives
- **GIVEN** 4 cells covering one hit, one false alarm, one miss, and one true negative under `min_alert_risk="Moderado"`
- **WHEN** `classify_cell_outcomes` runs
- **THEN** only the 3 actionable cells (`hit`, `false_alarm`, `miss`) MUST be returned.

---

### Requirement MON-4: Non-Blocking Monitor API & Periodic Loop
- `GET /api/v1/monitor/status` MUST return `{ running, last_run_at, last_result, last_error }` immediately without touching DuckDB or NASA FIRMS.
- `GET /api/v1/monitor/metrics?limit=30` (`1 <= limit <= 365`) MUST return `{ items }` ordered newest first (`target_date DESC, issued_date DESC`).
- `GET /api/v1/monitor/comparison` MUST accept `target_date` (`YYYY-MM-DD`), optional `issued_date`, `min_frp_mw >= 0`, and `min_alert_risk` (`Moderado` | `Alto` | `Extremo`), returning a GeoJSON `FeatureCollection` of `hit`, `miss`, and `false_alarm` cells or HTTP `404` when no snapshot exists for `issued_date`.
- `GET /api/v1/monitor/threshold-comparison?limit=14` (`1 <= limit <= 90`) MUST re-evaluate stored 24h snapshots against VIIRS ground truth under both the previous profile (`0.1% / 1% / 5%`, floors `0.001 / 0.0003 / 0.0001`) and current selective settings (`RISK_TOP_FRAC_*` / `RISK_FLOOR_*`) without altering DuckDB schemas, returning `{ profiles, summary, items }`.
- `POST /api/v1/monitor/run` SHALL accept optional `date` (`YYYY-MM-DD`), `day_range` (`1..10`; note NASA FIRMS Area API accepts `1..5`), and `min_frp_mw >= 0`. When `FIRMS_MAP_KEY` is blank, it MUST return HTTP `400`. When configured, it MUST return HTTP `202` (`status="started"` or `"already_running"`) while executing in a background `asyncio.Task`.
- `MonitorService.run_periodic_monitor` (`MONITOR_REFRESH_INTERVAL_S=21600` default) SHALL sleep between cycles and skip ingestion silently when `FIRMS_MAP_KEY` is blank.

#### Scenario: Missing FIRMS_MAP_KEY rejects manual run while configured key enqueues async job
- **GIVEN** an application instance without `FIRMS_MAP_KEY` vs one with `FIRMS_MAP_KEY` configured
- **WHEN** a client calls `POST /api/v1/monitor/run`
- **THEN** the unconfigured instance MUST return HTTP `400`, and the configured instance MUST return HTTP `202` with `status="started"` and complete ingestion asynchronously visible on `GET /api/v1/monitor/status`.
