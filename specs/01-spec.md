# FHIPredict — Product & Functional Specification (SDD)

> Note: Living domain-level specifications with RFC 2119 requirements and `GIVEN`/`WHEN`/`THEN` scenarios live under [openspec/specs/](../openspec/specs/). This document serves as the consolidated product overview.

## 1. Purpose
Standalone, lightweight web application for **live fire-risk prediction, neighbor propagation (`24h–72h`), and empirical VIIRS validation across Argentina** using pre-trained LightGBM models (`lgbm-risk-24h-v2` and `lgbm-spread-v2`) combined with real-time weather forecasts from **Open-Meteo** and active hotspot detections from **NASA FIRMS VIIRS**.

The interface exposes two focused views with the **FuegoContinuo** visual identity:
- **`/` (Forecast Map)**: Full-viewport MapLibre GL map visualizing base ignition risk (`1–15` days), spatial propagation (`24h–72h`), province/hotspot navigation (`NavigationPanel`), dynamic or static risk legend (`RiskLegend`), and optional 3D terrain/roads.
- **`/monitor` (Empirical Monitor Dashboard)**: Lazy-loaded validation dashboard comparing daily 24h forecast snapshots against real NASA FIRMS VIIRS detections, with a 3-step reading guide, plain-language summary, charts, and CSV export.

---

## 2. Scope & Non-Goals

### In Scope
- Self-contained repository with zero runtime dependency on `FireHistoryInterface`, `FireHistoryInterfaceAPI`, or `ModeloPredictivo`.
- Dual-model inference:
  - `fire_risk_bundle.joblib` (`lgbm-risk-24h-v2`, 20 features) + `spread_bundle.joblib` (`lgbm-spread-v2`, 47 features) over `cell_baseline.parquet` (`64,653` 5×5 km cells mapped to `971` weather grid coordinates).
  - Live fire-memory blending: rolls recent NASA FIRMS VIIRS detections (`1d`, `2d`, `7d`, `30d` in `monitor.duckdb`) into cell fire-memory features with linear horizon decay (`service.py`), falling back to `cell_baseline.parquet` when DuckDB history is absent.
- Real-time weather ingestion from Open-Meteo Forecast API (`past_days=30` + `forecast_days=15`, `timezone=America/Argentina/Buenos_Aires`) computing rolling 7d/15d/30d rainfall, dry streaks (`< 1.0 mm`), VPD, wind direction, and wind gusts.
- Risk threshold resolution (`_resolve_risk_cutoffs` in `service.py` + `compute_daily_percentile_cutoffs` in `predictor.py`):
  - `RISK_CUTOFF_MODE="daily_percentile"` (default): derives daily cutoffs at top `5%` (`RISK_TOP_FRAC_MODERADO=0.05`), `1%` (`RISK_TOP_FRAC_ALTO=0.01`), and `0.1%` (`RISK_TOP_FRAC_EXTREMO=0.001`), bounded above by static validation cutoffs (`Extremo=0.057851`, `Alto=0.012920`, `Moderado=0.003550`) during severe outbreaks and clamped above safety floors (`0.0001` / `0.0003` / `0.001`) on near-zero days, falling back to static cutoffs on small (`< 100`) or degenerate distributions.
  - `RISK_CUTOFF_MODE="static"`: applies fixed validation cutoffs from `fire_risk_bundle.joblib`.
  - Both `/api/v1/forecast` (`meta.cutoffs`) and `/api/v1/spread` (`meta.source_cutoff`) expose active cutoff metadata so unconfirmed high-risk source cells (`p_risk >= source_cutoffs["Alto"]`) stay aligned across endpoints, while target spread categorization preserves static `SpreadPredictor.categorize` thresholds (`Extremo=0.456281`, `Alto=0.197783`, `Moderado=0.082370`).
- Heuristic confidence estimation (`_compute_confidence`): combines LightGBM tree-depth agreement (`stability in [0.2, 1.0]`), daily horizon decay (`CONFIDENCE_HORIZON_DECAY_PER_DAY=0.025`, floored at `0.35`), and stale-cache penalty (`CONFIDENCE_STALE_PENALTY=0.15`), clamped to `[5, 99]%` and classified into `Alta` (`>= 75`), `Media` (`>= 50`), and `Baja` (`< 50`) (with an additional `0.9` factor for spread predictions).
- Temporal controls on `/`:
  - **Window presets**: `24h (1 día)`, `3 días`, `7 días`, `15 días` (peak daily risk within the window).
  - **Day-by-day selector**: slider from `Día 1` (+24h) through `Día 15` to inspect any individual 24h slice.
  - **Propagation horizon**: `24h`, `48h`, `72h` toggleable overlay (`lgbm-spread-v2`).
- Cell inspection popup on click: `cell_id`, coordinates, `riesgo_pct`, `categoria`, `confianza_pct` / `confianza_nivel`, `tmax_c`, `rh_pct`, `wind_kmh`, `rain_mm`, `rain_30d_mm`, `dry_days`, `vpd_kpa`, `elev_m`, `years_since_fire`, and spread overlay metrics (`propagacion_pct`, `riesgo_base_pct`, `riesgo_fusionado_pct`, `horizon_hours`).
- Empirical validation (`/monitor`): idempotent daily 24h snapshot persistence, async NASA FIRMS VIIRS ingestion (`VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`), pure-NumPy metrics (`ROC-AUC`, `PR-AUC`, `calibration_ratio`, `Brier`, category breakdown, `Hit/Miss/False Alarm`), charts, and CSV export.

### Out of Scope (Non-Goals)
- Historical multi-year fire calendar, user authentication/RBAC, or physical perimeter simulation (Rothermel / Cell2Fire / ELMFIRE).

---

## 3. Time Granularity Contract
- **Native model resolution**: **24 hours (1 day)** (`horizon_hours: 24`, trained on daily weather aggregates).
- **Minimum selectable range**: **1 day (24h)**.
- **Maximum selectable range**: **15 days** (within Open-Meteo's 16-day `forecast_days` limit).
- **Multi-day aggregation rule** (for `3d`, `7d`, `15d` windows):
  - Peak daily probability (comonotonic Fréchet bound under high inter-day weather/drought autocorrelation): $P_{\text{range}} = \max_{d \in [0..k-1]} p_d$. Cutoffs are resolved against `cached.probs[:, :span]` and compared against `prob`, preserving exact consistency with the 24h scale without artificially inflating multi-day categories.

---

## 4. Visual Identity (FuegoContinuo)
- **Surfaces**: `--space-base: #07100F`, `--space-surface: #0D1816`, `--space-elevated: #111E1B`, `--space-border: #21312D`.
- **Accent**: `--primary: #B8EE68`, `--primary-hover: #CBF58C`.
- **Text**: `--text-primary: #EFF5ED`, `--text-secondary: #93A39C`, `--text-muted: #687771`.
- **Typography**: `Manrope` (headings), `DM Sans` (body), `DM Mono` (coordinates, percentages, dates).
- **Risk Color Scale**:
  - `Bajo`: `#3D786E` (filtered out by default via `min_risk=Moderado`)
  - `Moderado`: `#68D9D0`
  - `Alto`: `#FF9C55`
  - `Extremo`: `#FF6759`
