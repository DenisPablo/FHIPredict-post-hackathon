# Proposal 04 — Hotspot Propagation Model (`lgbm-spread-v1` → `lgbm-spread-v2`) and Comparative Evaluation

| Field | Value |
|---|---|
| Status | **Implemented & merged on `main`** (upgraded to `lgbm-spread-v2`) |
| Branch | `main` (originally developed on `feat/propagation-model-v3`) |
| Baseline model | `lgbm-risk-24h-v2` (on `main`) |
| Deployed spread model | `lgbm-spread-v2` (47 features, enabled by default via `ENABLE_SPREAD=true`) |
| Author / Date | FHIPredict team / 2026-11-15 (reconciled 2026-11-19) |

> **Implementation reconciliation note:** The merged implementation upgraded the original `lgbm-spread-v1` draft to **`lgbm-spread-v2`** (47 features in [backend/app/spread.py](../backend/app/spread.py)):
> - Training dataset construction lives directly inside [backend/scripts/train_spread.py](../backend/scripts/train_spread.py) (no separate `build_spread_dataset.py`).
> - Slope (`slope_deg`) and `delta_elev_m` are computed dynamically on neighbor edges in `spread.py:build_neighbor_graph`, while [backend/scripts/export_baseline.py](../backend/scripts/export_baseline.py) enriches `cell_baseline.parquet` with 4 biophysical `fuel_*` fractions and industrial flags (`is_industrial`, `industrial_focos_share`).
> - Wind alignment uses `cos(radians(wind_from + 180 - bearing))` plus `sin_bearing`/`cos_bearing` (no `aspect` or `slope_alignment`).
> - Feature flag is `ENABLE_SPREAD` ([backend/app/config.py](../backend/app/config.py)), defaulting to `True`, and `showSpread` defaults to `true` in [frontend/src/App.tsx](../frontend/src/App.tsx); unconfirmed `Alto+` source cells are weighted by `p_risk[s]` in `service.py`.

## 1. Context and Problem

The current model (`lgbm-risk-24h-v2`) predicts, **independently per cell**, the probability of a harmonized fire detection in the next 24 h. It has no spatial coupling and no directional information:

- Wind: only `wind_speed_10m_max` (no direction).
- Terrain: only `elevacion_m` (no slope or aspect).
- No neighborhood features (activity in adjacent cells).

Consequently it cannot answer: *"Given an active hotspot in cell A today, which neighboring cells are likely to show fire in the next 24–72 h?"*

## 2. Goals

1. Add a **propagation (spread) model** estimating, for each active cell, the probability that each of its neighbors becomes positive within 24/48/72 h.
2. Keep the existing risk model untouched and **measure both models on identical splits and metrics**.
3. Expose results behind a feature flag without breaking the current API/UI contract.

### Non-Goals

- Physical fire-front simulation (Rothermel / Cell2Fire / ELMFIRE), burned-area perimeters, or rate of spread in m/min. These require fuel-type layers and hourly weather and are out of scope (see §10).
- Replacing `lgbm-risk-24h-v2`.

## 3. Problem Formulation

Unit of prediction: an **ordered pair** `(source cell s, target cell t)` where `t` is in the 8-neighborhood (Moore, 5 km grid) of `s` and `s` had a positive label on day `d`.

- **Label**: `y = 1` if `t` is positive (`n_harmonized >= 1 AND phi_harmonized >= 10.0`, same rule as v2) on any day in `(d, d+H]`, with `H ∈ {1, 2, 3}` days. One model per horizon, or `H` as a feature.
- **Output**: `p_spread(s → t, H)`.
- **Aggregation to map**: `P_spread(t) = 1 − Π_s (1 − p_spread(s → t))` over active neighbors `s`; optionally fused with `p_risk(t)` from v2.

## 4. Feature Design

Reuses all v2 features of the **target** cell plus:

| Group | Features | Source |
|---|---|---|
| Geometry | `bearing_s_to_t`, `dist_km`, `dlat`, `dlon` | grid |
| Wind | `wind_direction_10m_dominant`, `wind_alignment = cos(wind_dir − bearing)`, `wind_speed_10m_max`, `wind_gust_10m_max` | Open-Meteo daily (new vars) |
| Terrain | `slope`, `aspect`, `delta_elev = elev_t − elev_s`, `slope_alignment` | DEM already used for `elevacion_m` |
| Source activity | `n_harmonized_s`, `frp_sum_s`, `focos_ultimos_7d_s` | FIRMS harmonized |
| Neighborhood | `n_active_neighbors_t`, `focos_vecinos_7d_t` | FIRMS harmonized |
| Dryness | existing `vpd_approx`, `lluvia_acum_*`, `dias_consecutivos_sin_lluvia` | existing |

Leakage rule: every feature must be computable using only data with timestamp `<= d`.

## 5. Implementation Plan (work units)

| # | Unit | Files | Notes |
|---|---|---|---|
| U1 | Weather: add wind direction and gusts | `backend/app/openmeteo.py` | Add `wind_direction_10m_dominant`, `wind_gusts_10m_max` to `daily_vars` and `WeatherGridForecast`. Backward compatible. |
| U2 | Terrain: slope/aspect export | `backend/scripts/export_baseline.py` | Extend `cell_baseline.parquet` with `slope`, `aspect`. Existing columns unchanged. |
| U3 | Dataset builder | `backend/scripts/build_spread_dataset.py` (new) | Builds `(s, t, d)` rows with labels; time-based split identical to v2 (train 2018–2023, val 2024–2025, test 2026). |
| U4 | Training | `backend/scripts/train_spread.py` (new) | LightGBM; same prior-correction calibration approach as v2. Outputs `models/spread_bundle.joblib` + `spread_metadata.json`. |
| U5 | Inference | `backend/app/spread.py` (new), `service.py` | `SpreadPredictor` mirroring `FireRiskPredictor`; neighbor aggregation. Gated by `FHI_ENABLE_SPREAD`. |
| U6 | API/UI | `main.py`, `frontend/src` | Optional layer "Propagation" (opt-in); v2 endpoints unchanged. |
| U7 | Benchmark harness | `backend/scripts/compare_models.py` (new) | See §6. |

## 6. Evaluation Protocol (both models measured)

**Principle**: identical data, identical split, identical metrics, reported side by side in `models/comparison_report.json` and `specs/05-comparison-results.md`.

### 6.1 Splits
Same as v2 — train `2018-01-01..2023-12-31`, val `2024-01-01..2025-12-31`, test `2026-01-01..2026-12-31`. Test set is used once for the final report.

### 6.2 Comparable task
v2 and v3 answer different questions, so two evaluation tracks are used:

- **Track A — Per-cell next-24h risk (shared task).** Score every cell-day with (a) v2 alone, (b) v2 + spread fusion `P = 1 − (1 − p_risk)(1 − P_spread)`. Metrics against the v2 label. Tests whether spread adds signal to the existing product.
- **Track B — Conditional spread (new task).** Restrict to cell-days that are neighbors of an active cell. Compare (a) v2 `p_risk(t)`, (b) a **naive baseline** (neighbor is positive if any active neighbor exists / recency heuristic), (c) `lgbm-spread-v1`.

### 6.3 Metrics
| Metric | Reason |
|---|---|
| ROC-AUC, **PR-AUC** | Extreme imbalance (~0.06% positives) — PR-AUC is primary |
| Brier score, log-loss, calibration ratio | Probabilities are shown to users |
| Top-k precision / recall / lift (0.1%, 1%, 5%) | Same operational view already used in v2 |
| Per-category lift (`Bajo`..`Extremo`) | Comparable with v2 metadata |
| Recall@Top-N cells per day | Operational budget framing |
| Metrics by month and by region (NOA, NEA, Cuyo, Pampeana, Patagonia) | Detect seasonal/regional regressions |
| Inference latency and memory | Must not break single-container deployment |

### 6.4 Acceptance Criteria
The candidate is adopted only if **all** hold on the test split:

1. Track B: PR-AUC and top-1% lift of `lgbm-spread-v1` exceed both v2 and the naive baseline by a pre-agreed margin (proposed: ≥ +20% relative PR-AUC).
2. Track A: fusion does **not** degrade calibration ratio outside `[0.9, 1.1]` and does not reduce v2 top-1% recall.
3. No region/month slice regresses more than 10% relative versus v2.
4. Full-country inference stays within current latency budget (+25% max) and Docker image size limits.

If criteria are not met, the branch is kept as a research artifact and `main` is unchanged.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Hotspots are satellite detections, not fire perimeters; label noise from cloud gaps and overpass times | Report limitation; evaluate with and without low-confidence cells |
| Class imbalance and leakage via spatial/temporal autocorrelation | Strict time split; features limited to `<= d`; optional spatial block CV on val |
| 5 km cells can hold entire spread events within one cell (spread invisible at this scale) | Restrict to inter-cell spread; document resolution limit |
| Open-Meteo daily wind direction is a coarse proxy | Use dominant direction + alignment feature; evaluate ablation without it |
| Contract drift in `WeatherGridForecast` | New fields optional; v2 path untouched; tests cover both |

## 8. Testing Strategy

- Unit tests for: bearing/alignment math, neighbor aggregation, label construction (no leakage), `SpreadPredictor` load/predict.
- Regression test: v2 outputs bit-identical with `FHI_ENABLE_SPREAD` off.
- Extend `backend/tests/test_forecast.py` for the new weather fields.

## 9. Deliverables

1. Code per §5 on `feat/propagation-model-v3` (conventional commits, one work unit per commit).
2. `models/spread_bundle.joblib`, `models/spread_metadata.json`.
3. `models/comparison_report.json` and `specs/05-comparison-results.md` with the §6 tables and a go/no-go recommendation.

## 10. Future Work (out of scope)

Fuel/vegetation layers (e.g. MapBiomas), hourly weather, and a physical spread engine (Cell2Fire / ELMFIRE) for perimeter-level simulation.

## 11. Open Decisions

1. One model per horizon (24/48/72 h) vs. horizon as a feature.
2. Acceptance margin for Track B (proposed +20% relative PR-AUC).
3. Ship the Propagation layer in the UI only if the benchmark passes, or behind the flag regardless.
