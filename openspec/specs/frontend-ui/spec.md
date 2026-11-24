# Spec: Frontend Map & Monitor UI (`frontend-ui`)

## Scope
Defines the FuegoContinuo visual design system, client-side routing (`/` and `/monitor`), MapLibre GL forecast and propagation visualization, temporal/filter controls, dynamic risk legend, province/hotspot navigation, `/monitor` empirical dashboard, CSV export, and ES/EN internationalization.

Primary implementation files:
- `frontend/src/App.tsx`
- `frontend/src/api/forecast.ts`
- `frontend/src/api/monitor.ts`
- `frontend/src/components/RiskMap.tsx`
- `frontend/src/components/TimeRangeBar.tsx`
- `frontend/src/components/NavigationPanel.tsx`
- `frontend/src/components/RiskLegend.tsx`
- `frontend/src/components/MonitorDashboard.tsx`
- `frontend/src/data/provinces.ts`
- `frontend/src/i18n.ts`
- `frontend/src/styles/index.css`
- `frontend/tailwind.config.ts`

---

## Requirements

### Requirement FUI-1: FuegoContinuo Design Tokens, Routing & Internationalization
The UI SHALL use the FuegoContinuo dark-first palette (`--space-base: #07100F`, `--space-surface: #0D1816`, `--space-elevated: #111E1B`, `--space-border: #21312D`, `--primary: #B8EE68`, `--text-primary: #EFF5ED`, `--text-secondary: #93A39C`, `--text-muted: #687771`), `Manrope` / `DM Sans` / `DM Mono` typography, and categorical risk colors (`Extremo: #FF6759`, `Alto: #FF9C55`, `Moderado: #68D9D0`, `Bajo: #3D786E`).
`App.tsx` MUST lazy-load `RiskMap` on `/` and `MonitorDashboard` on `/monitor` using `history.pushState` and `popstate` listeners without reloading the page.
All UI strings MUST support `'es'` (default) and `'en'` via `COPY[lang]` and dashboard helpers, with runtime language switching.

#### Scenario: Confidence copy and types exist in ES and EN
- **GIVEN** `COPY.es.popup` and `COPY.en.popup`
- **WHEN** tests or components read confidence labels and `CellProperties`
- **THEN** localized titles, hints, and `Alta` / `Media` / `Baja` labels MUST be defined in both languages.

---

### Requirement FUI-2: Operational Risk & Spread Map (`/`)
`RiskMap` SHALL initialize MapLibre GL centered on `[-64.0, -37.5]` (`zoom: 4.1`) over `argenmap_oscuro` TMS tiles, render `fire-risk-circles` from `/api/v1/forecast`, and render `fire-spread-circles` (`showSpread` default `true`, `#B8EE68` ring) from `/api/v1/spread` using `spreadDayOffset = mode === 'day' ? dayOffset : 0` and selectable `spreadHorizon` (`24`, `48`, `72`).
Users MUST be able to toggle optional IGN `mapabase_hibrido` roads and AWS `terrarium` 3D terrain + hillshade (`pitch: 52`, `exaggeration: 1.6`).
Clicking a base-risk point SHALL open a popup displaying `cell_id`, `riesgo_pct`, `categoria`, period, optional `confianza_nivel` / `confianza_pct`, `tmax_c`, `rh_pct`, `wind_kmh`, `rain_mm`, `rain_30d_mm`, `vpd_kpa`, `elev_m`, `years_since_fire`, `dry_days`, and a Google Maps deep link. Clicking a spread point SHALL display `propagacion_pct`, `riesgo_base_pct`, `riesgo_fusionado_pct`, `horizon_hours`, optional confidence, and a Google Maps link.

---

### Requirement FUI-3: Temporal Controls, Navigation & Dynamic Risk Legend
`TimeRangeBar` SHALL provide window presets (`1`, `3`, `7`, `15` days), a single-day slider (`0..datesAvailable.length - 1`), a `minRisk` selector (`Moderado`, `Alto`, `Extremo`, `Bajo`), and an Open-Meteo force-refresh button.
`NavigationPanel` SHALL provide a collapsible sidebar switching between `PROVINCE_TARGETS` (`25` targets: Argentina + 24 jurisdictions) and Top-30 hotspots sorted descending by `riesgo_pct`, invoking `onFlyTo(center, zoom, id)` on click.
`RiskLegend` SHALL render category percentage thresholds from `meta.cutoffs` when present (displaying `legendDailyPercentileNote` when `cutoffs.mode === 'daily_percentile'`) and fall back to static validation thresholds (`Extremo >= 5.79%`, `Alto 1.29 – 5.79%`, `Moderado 0.35 – 1.29%`, `Bajo < 0.35%`) when `cutoffs` is omitted.

#### Scenario: TimeRangeBar selects 15-day window, single day, and English labels
- **GIVEN** `TimeRangeBar` rendered with `datesAvailable`
- **WHEN** a user clicks `15 días` or moves the single-day slider to index `2`
- **THEN** `onSelectWindow(15)` and `onSelectDay(2)` MUST fire with exact arguments, and `lang="en"` MUST render `"15 days"` and `"Single day"`.

#### Scenario: NavigationPanel flies to selected province and top hotspot
- **GIVEN** `NavigationPanel` rendered with forecast features
- **WHEN** a user clicks `"Córdoba"` and then switches to `"Top riesgo"` and clicks `#101`
- **THEN** `onFlyTo` MUST be invoked with Córdoba coordinates (`[-63.8, -32.1], 6.4, '14'`) and cell `#101` coordinates (`[-65.5, -33.2], 9.2, 'cell-101'`).

#### Scenario: RiskLegend adapts between static fallback and daily_percentile metadata
- **GIVEN** `RiskLegend` rendered without `cutoffs` vs with `cutoffs={{ mode: 'daily_percentile', Extremo: 0.015, Alto: 0.005, Moderado: 0.002 }}`
- **WHEN** rendered in Spanish
- **THEN** omitted `cutoffs` MUST show static percentages without the percentile note, while `daily_percentile` MUST display `≥ 1.50%`, `0.50 – 1.50%`, `0.20 – 0.50%`, `< 0.20%`, and `"Umbral diario: Alerta Alto+ (top 0.4% / 0.05%) · Vigilancia Moderado (top 2.5%)"`.

---

### Requirement FUI-4: Empirical Monitor Dashboard (`/monitor`) & CSV Export
`MonitorDashboard` MUST fetch `/api/v1/monitor/metrics?limit=30`, `/api/v1/monitor/status` (polling every `2000 ms` while `running === true`), and `/api/v1/monitor/threshold-comparison?limit=14`, displaying a toggleable 3-step `QuickInterpretationGuide`, `PlainLanguageSummary`, 6 KPI cards (`ROC-AUC`, `PR-AUC`, `Calibration`, `Brier`, `Hits / Misses`, `False Alarms`), `CategoryCaptureChart`, interactive `DailyHistoryChart` (up to 14 chronological days), interactive `ThresholdComparisonChart` (paired previous vs. current `2B` bars with false-alarm reduction summary and `False alarms` / `Hits` toggle), stock-style `StockComparisonLineChart` (3-line SVG comparing violet real VIIRS, red previous profile, and green current `2B` with `Hits vs. VIIRS` linear and `Alerts vs. VIIRS (log)` modes), category breakdown table, and daily history table.
`buildMonitorCsv` SHALL serialize metric items into RFC-4180 CSV rows including `expected_positives` and `capture_rate_pct`, and `Download CSV` MUST export `fhipredict-monitoreo-viirs.csv` with a UTF-8 BOM.

#### Scenario: MonitorDashboard renders metrics, charts, and enables CSV export
- **GIVEN** mocked `/api/v1/monitor/metrics` returning one evaluation item and idle `/api/v1/monitor/status`
- **WHEN** `MonitorDashboard` mounts
- **THEN** KPI values (`0.145`, `8 / 4`, `120`), plain-language summary, both charts (`aria-label` accessible), category breakdown table, and an enabled `Descargar CSV` button MUST render
- **AND** `buildMonitorCsv` MUST format the header row and metric row cleanly.
