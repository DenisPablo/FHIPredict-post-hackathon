"""Inference orchestration and TTL cache for all 64,653 Argentina cells."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import time
import duckdb
import joblib
import numpy as np
from .config import Settings
from .monitor.snapshots import SnapshotStore
from .openmeteo import WeatherGridForecast, fetch_openmeteo_grid
from .predictor import FireRiskPredictor
from .spread import (
    NeighborGraph,
    SpreadPredictor,
    aggregate_target_probabilities,
    build_neighbor_graph,
    compute_wind_alignment,
    fuse_risk_and_spread,
)

logger = logging.getLogger(__name__)


RISK_ORDER = {"Bajo": 0, "Moderado": 1, "Alto": 2, "Extremo": 3}


@dataclass
class CellBaseline:
    cell_id: np.ndarray  # (N,) int32
    lat_centro: np.ndarray  # (N,) float32
    lon_centro: np.ndarray  # (N,) float32
    elevacion_m: np.ndarray  # (N,) float32
    focos_ultimos_7d: np.ndarray  # (N,) float32
    focos_ultimos_30d: np.ndarray  # (N,) float32
    frp_ultimos_7d: np.ndarray  # (N,) float32
    anios_desde_ultimo_fuego: np.ndarray  # (N,) float32
    clim_months: np.ndarray  # (N, 12) float32
    grid_coords: list[tuple[float, float]]  # length G
    cell_to_grid: np.ndarray  # (N,) int32
    frac_dentro: np.ndarray | None = None  # (N,) float32
    is_industrial: np.ndarray | None = None  # (N,) float32
    industrial_focos_share: np.ndarray | None = None  # (N,) float32
    fuel_bosque: np.ndarray | None = None  # (N,) float32
    fuel_pastizal: np.ndarray | None = None  # (N,) float32
    fuel_agro: np.ndarray | None = None  # (N,) float32
    fuel_no_combustible: np.ndarray | None = None  # (N,) float32
    focos_ultimos_1d: np.ndarray | None = None  # (N,) float32
    focos_ultimos_2d: np.ndarray | None = None  # (N,) float32
    frp_ultimos_1d: np.ndarray | None = None  # (N,) float32


@dataclass
class CachedForecast:
    generated_at: str
    expires_at: float
    dates: list[str]  # length D
    probs: np.ndarray  # (N, D) float32
    stability: np.ndarray  # (N, D) float16
    weather: WeatherGridForecast
    is_stale: bool = False


def load_baseline(parquet_path: str) -> CellBaseline:
    con = duckdb.connect(":memory:")
    tbl = con.sql(f"SELECT * FROM read_parquet('{parquet_path}') ORDER BY cell_id").fetchnumpy()
    lat_c = tbl["lat_clima"].astype(np.float32)
    lon_c = tbl["lon_clima"].astype(np.float32)

    grid_map: dict[tuple[float, float], int] = {}
    grid_coords: list[tuple[float, float]] = []
    cell_to_grid = np.empty(len(lat_c), dtype=np.int32)
    for i, (la, lo) in enumerate(zip(lat_c.tolist(), lon_c.tolist())):
        key = (round(la, 4), round(lo, 4))
        idx = grid_map.get(key)
        if idx is None:
            idx = len(grid_coords)
            grid_map[key] = idx
            grid_coords.append(key)
        cell_to_grid[i] = idx

    n = len(lat_c)
    clim = np.column_stack([tbl[f"m{m:02d}"].astype(np.float32) for m in range(1, 13)])
    f7 = tbl["focos_ultimos_7d"].astype(np.float32)
    frp7 = tbl["frp_ultimos_7d"].astype(np.float32)
    return CellBaseline(
        cell_id=tbl["cell_id"].astype(np.int32),
        lat_centro=tbl["lat_centro"].astype(np.float32),
        lon_centro=tbl["lon_centro"].astype(np.float32),
        elevacion_m=tbl["elevacion_m"].astype(np.float32),
        focos_ultimos_7d=f7,
        focos_ultimos_30d=tbl["focos_ultimos_30d"].astype(np.float32),
        frp_ultimos_7d=frp7,
        anios_desde_ultimo_fuego=tbl["anios_desde_ultimo_fuego"].astype(np.float32),
        clim_months=clim,
        grid_coords=grid_coords,
        cell_to_grid=cell_to_grid,
        frac_dentro=tbl["frac_dentro"].astype(np.float32) if "frac_dentro" in tbl else np.ones(n, dtype=np.float32),
        is_industrial=tbl["is_industrial"].astype(np.float32) if "is_industrial" in tbl else np.zeros(n, dtype=np.float32),
        industrial_focos_share=tbl["industrial_focos_share"].astype(np.float32) if "industrial_focos_share" in tbl else np.zeros(n, dtype=np.float32),
        fuel_bosque=tbl["fuel_bosque"].astype(np.float32) if "fuel_bosque" in tbl else np.full(n, 0.27, dtype=np.float32),
        fuel_pastizal=tbl["fuel_pastizal"].astype(np.float32) if "fuel_pastizal" in tbl else np.full(n, 0.34, dtype=np.float32),
        fuel_agro=tbl["fuel_agro"].astype(np.float32) if "fuel_agro" in tbl else np.full(n, 0.28, dtype=np.float32),
        fuel_no_combustible=tbl["fuel_no_combustible"].astype(np.float32) if "fuel_no_combustible" in tbl else np.full(n, 0.11, dtype=np.float32),
        focos_ultimos_1d=tbl["focos_ultimos_1d"].astype(np.float32) if "focos_ultimos_1d" in tbl else (f7 / 7.0).astype(np.float32),
        focos_ultimos_2d=tbl["focos_ultimos_2d"].astype(np.float32) if "focos_ultimos_2d" in tbl else (f7 * (2.0 / 7.0)).astype(np.float32),
        frp_ultimos_1d=tbl["frp_ultimos_1d"].astype(np.float32) if "frp_ultimos_1d" in tbl else (frp7 / 7.0).astype(np.float32),
    )


class ForecastService:
    """Computes and caches 15-day fire-risk predictions for all cells."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.predictor = FireRiskPredictor.from_bundle(settings.models_dir / "fire_risk_bundle.joblib")
        self.baseline = load_baseline((settings.models_dir / "cell_baseline.parquet").as_posix())
        spread_bundle = settings.models_dir / "spread_bundle.joblib"
        self.spread_predictor: SpreadPredictor | None = (
            SpreadPredictor.from_bundle(spread_bundle)
            if settings.enable_spread and spread_bundle.exists()
            else None
        )
        self._neighbor_graph: NeighborGraph | None = None
        self._cache_path: Path = settings.models_dir / ".forecast_cache.joblib"
        self._cache: CachedForecast | None = self._load_disk_cache()
        self._snapshot_store: SnapshotStore | None = (
            SnapshotStore(
                db_path=settings.monitor_dir / "monitor.duckdb",
                memory_limit=settings.monitor_duckdb_memory_limit,
            )
            if settings.enable_monitor_snapshots
            else None
        )
        self._lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None

    def _load_disk_cache(self) -> CachedForecast | None:
        if not self._cache_path.exists():
            return None
        try:
            payload = joblib.load(self._cache_path)
            saved_epoch = float(payload["saved_epoch"])
            age_s = max(0.0, time.time() - saved_epoch)
            remaining = max(0.0, self.settings.cache_ttl_s - age_s)
            weather = payload["weather"]
            if "stability" in payload:
                probs = payload["probs"]
                stability = payload["stability"]
                upgraded = False
            else:
                probs, stability = self._score_all_days(weather)
                upgraded = True
            cached = CachedForecast(
                generated_at=payload["generated_at"],
                expires_at=time.monotonic() + remaining,
                dates=payload["dates"],
                probs=probs,
                stability=stability,
                weather=weather,
                is_stale=False,
            )
            if upgraded:
                self._save_disk_cache(cached)
            return cached
        except Exception as exc:
            logger.warning("Ignoring corrupt forecast disk cache: %s", exc)
            return None

    def _save_disk_cache(self, cached: CachedForecast) -> None:
        try:
            tmp_path = self._cache_path.with_suffix(".tmp")
            joblib.dump(
                {
                    "saved_epoch": time.time(),
                    "generated_at": cached.generated_at,
                    "dates": cached.dates,
                    "probs": cached.probs,
                    "stability": cached.stability,
                    "weather": cached.weather,
                },
                tmp_path,
                compress=3,
            )
            tmp_path.replace(self._cache_path)
        except Exception as exc:
            logger.warning("Failed to persist forecast disk cache: %s", exc)

    def _schedule_background_refresh(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return

        async def _run() -> None:
            try:
                await self._refresh_forecast(force_refresh=True)
            except Exception as exc:
                logger.warning("Background forecast refresh failed: %s", exc)

        self._refresh_task = asyncio.create_task(_run())

    async def warm_up(self) -> None:
        """Pre-warm forecast cache in the background on server startup."""
        if self._cache is not None and time.monotonic() < self._cache.expires_at:
            if self._snapshot_store is not None:
                await asyncio.to_thread(self._maybe_save_snapshot_24h, self._cache)
            return
        try:
            await self._refresh_forecast(force_refresh=True)
        except Exception as exc:
            logger.warning("Startup forecast warm-up failed: %s", exc)

    async def run_periodic_refresh(self, interval_s: float | None = None) -> None:
        """Periodically refresh Open-Meteo weather and re-score cells in the background."""
        sleep_s = float(interval_s if interval_s is not None else self.settings.refresh_interval_s)
        while True:
            await asyncio.sleep(sleep_s)
            try:
                await self._refresh_forecast(force_refresh=True)
                logger.info("Periodic Open-Meteo forecast refresh completed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Periodic forecast refresh failed: %s", exc)

    async def get_forecast(self, force_refresh: bool = False) -> CachedForecast:
        now = time.monotonic()
        if not force_refresh and self._cache is not None:
            if now < self._cache.expires_at:
                return self._cache
            # Serve stale disk/memory cache immediately while refreshing in the background.
            self._cache.is_stale = True
            self._schedule_background_refresh()
            return self._cache

        return await self._refresh_forecast(force_refresh=force_refresh)

    async def _refresh_forecast(self, force_refresh: bool = False) -> CachedForecast:
        async with self._lock:
            now = time.monotonic()
            if not force_refresh and self._cache is not None and now < self._cache.expires_at:
                return self._cache

            try:
                weather = await fetch_openmeteo_grid(
                    coords=self.baseline.grid_coords,
                    openmeteo_url=self.settings.openmeteo_url,
                    past_days=self.settings.past_days,
                    forecast_days=self.settings.forecast_days,
                    chunk_size=self.settings.chunk_size,
                    max_concurrency=self.settings.max_concurrency,
                )
            except Exception as exc:
                if self._cache is not None:
                    logger.warning("Open-Meteo refresh failed (%s); serving stale cached forecast", exc)
                    self._cache.expires_at = time.monotonic() + 60.0
                    self._cache.is_stale = True
                    return self._cache
                raise

            probs, stability = self._score_all_days(weather)
            new_cache = CachedForecast(
                generated_at=datetime.now(timezone.utc).isoformat(),
                expires_at=time.monotonic() + self.settings.cache_ttl_s,
                dates=weather.dates,
                probs=probs,
                stability=stability,
                weather=weather,
                is_stale=False,
            )
            self._cache = new_cache
            asyncio.create_task(asyncio.to_thread(self._save_disk_cache, new_cache))
            if self._snapshot_store is not None:
                asyncio.create_task(asyncio.to_thread(self._maybe_save_snapshot_24h, new_cache))
            return new_cache

    def _maybe_save_snapshot_24h(self, cached: CachedForecast) -> bool:
        """Persist today's 24h prediction snapshot without disrupting forecast serving."""
        if self._snapshot_store is None or len(cached.dates) == 0:
            return False
        try:
            issued_date = cached.generated_at[:10]
            probs_24h = cached.probs[:, 0]
            categories = self.predictor.categorize(probs_24h)
            return self._snapshot_store.save_snapshot_24h(
                issued_date=issued_date,
                target_date=cached.dates[0],
                generated_at=cached.generated_at,
                model_version=self.predictor.model_version,
                cell_ids=self.baseline.cell_id,
                probs_24h=probs_24h,
                risk_categories=categories,
            )
        except Exception as exc:
            logger.warning("Failed to persist 24h monitor snapshot: %s", exc)
            return False

    def _score_all_days(self, weather: WeatherGridForecast) -> tuple[np.ndarray, np.ndarray]:
        b = self.baseline
        n_cells = len(b.cell_id)
        n_days = len(weather.dates)
        probs = np.empty((n_cells, n_days), dtype=np.float32)
        stability = np.empty((n_cells, n_days), dtype=np.float16)
        g_idx = b.cell_to_grid

        for d_idx, date_str in enumerate(weather.dates):
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            mes_val = float(dt.month)
            doy_val = float(dt.timetuple().tm_yday)

            X = np.column_stack([
                b.lat_centro,
                b.lon_centro,
                np.full(n_cells, mes_val, dtype=np.float32),
                np.full(n_cells, doy_val, dtype=np.float32),
                b.focos_ultimos_7d,
                b.focos_ultimos_30d,
                b.frp_ultimos_7d,
                b.clim_months[:, dt.month - 1],
                b.anios_desde_ultimo_fuego,
                b.elevacion_m,
                weather.temperature_2m_max[g_idx, d_idx],
                weather.relative_humidity_2m[g_idx, d_idx],
                weather.wind_speed_10m_max[g_idx, d_idx],
                weather.precipitation_sum[g_idx, d_idx],
                weather.shortwave_radiation_sum[g_idx, d_idx],
                weather.lluvia_acum_7d[g_idx, d_idx],
                weather.lluvia_acum_15d[g_idx, d_idx],
                weather.lluvia_acum_30d[g_idx, d_idx],
                weather.dias_consecutivos_sin_lluvia[g_idx, d_idx],
                weather.vpd_approx[g_idx, d_idx],
            ])
            day_probs, day_stab = self.predictor.predict_with_stability(X)
            probs[:, d_idx] = day_probs
            stability[:, d_idx] = day_stab.astype(np.float16)

        return probs, stability

    def _compute_confidence(
        self,
        stability: np.ndarray,
        day_indices: np.ndarray,
        is_stale: bool,
        extra_factor: float = 1.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Combine ensemble stability, forecast horizon decay, and data freshness into `(pct, level)`."""
        horizon_factor = np.clip(
            1.0 - day_indices.astype(np.float32) * self.settings.confidence_horizon_decay_per_day,
            0.35,
            1.0,
        )
        freshness_factor = max(0.5, 1.0 - self.settings.confidence_stale_penalty) if is_stale else 1.0
        conf_pct = np.clip(
            stability.astype(np.float32) * horizon_factor * freshness_factor * float(extra_factor) * 100.0,
            5.0,
            99.0,
        )
        conf_levels = np.where(
            conf_pct >= self.settings.confidence_high_cutoff,
            "Alta",
            np.where(conf_pct >= self.settings.confidence_medium_cutoff, "Media", "Baja"),
        )
        return conf_pct, conf_levels

    def query_geojson(
        self,
        cached: CachedForecast,
        mode: str = "window",
        days: int = 1,
        day_offset: int = 0,
        min_risk: str = "Moderado",
        bbox: tuple[float, float, float, float] | None = None,
    ) -> dict:
        b = self.baseline
        n_avail = len(cached.dates)

        if mode == "day":
            idx = max(0, min(day_offset, n_avail - 1))
            prob = cached.probs[:, idx]
            w_idx = idx
            fecha_desde = cached.dates[idx]
            fecha_hasta = cached.dates[idx]
        else:
            span = max(1, min(days, n_avail))
            sub = cached.probs[:, :span]
            # Cumulative probability of >=1 fire event in [0..span-1]
            prob = (1.0 - np.prod(1.0 - sub, axis=1)).astype(np.float32)
            # Representative weather from the peak-risk day for each cell
            w_idx_arr = np.argmax(sub, axis=1)
            w_idx = int(0)  # handled below if array
            fecha_desde = cached.dates[0]
            fecha_hasta = cached.dates[span - 1]

        # Categorize using daily cutoffs (consistent scale)
        cats = self.predictor.categorize(prob)

        # Summary counts across ALL Argentina cells
        counts = {
            "Bajo": int(np.sum(cats == "Bajo")),
            "Moderado": int(np.sum(cats == "Moderado")),
            "Alto": int(np.sum(cats == "Alto")),
            "Extremo": int(np.sum(cats == "Extremo")),
        }

        min_rank = RISK_ORDER.get(min_risk, 1)
        ranks = np.where(cats == "Extremo", 3, np.where(cats == "Alto", 2, np.where(cats == "Moderado", 1, 0)))
        mask = ranks >= min_rank

        if bbox is not None:
            west, south, east, north = bbox
            mask &= (
                (b.lon_centro >= west)
                & (b.lon_centro <= east)
                & (b.lat_centro >= south)
                & (b.lat_centro <= north)
            )

        sel = np.nonzero(mask)[0]
        # Cap to 20,000 highest-risk cells to keep MapLibre GeoJSON snappy
        if len(sel) > 20_000:
            top = np.argpartition(prob[sel], -20_000)[-20_000:]
            sel = sel[top]

        g_sel = b.cell_to_grid[sel]
        if mode == "day":
            d_sel = np.full(len(sel), w_idx, dtype=np.int32)
        else:
            d_sel = w_idx_arr[sel]

        w = cached.weather
        tmax_s = w.temperature_2m_max[g_sel, d_sel]
        rh_s = w.relative_humidity_2m[g_sel, d_sel]
        wind_s = w.wind_speed_10m_max[g_sel, d_sel]
        rain_s = w.precipitation_sum[g_sel, d_sel]
        rain30_s = w.lluvia_acum_30d[g_sel, d_sel]
        dry_s = w.dias_consecutivos_sin_lluvia[g_sel, d_sel]
        vpd_s = w.vpd_approx[g_sel, d_sel]
        conf_pct_s, conf_lvl_s = self._compute_confidence(
            cached.stability[sel, d_sel], d_sel, cached.is_stale
        )

        features = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(float(b.lon_centro[i]), 4), round(float(b.lat_centro[i]), 4)],
                },
                "properties": {
                    "cell_id": int(b.cell_id[i]),
                    "riesgo_pct": round(float(prob[i]) * 100.0, 2),
                    "categoria": str(cats[i]),
                    "confianza_pct": int(round(float(conf_pct_s[k]))),
                    "confianza_nivel": str(conf_lvl_s[k]),
                    "tmax_c": round(float(tmax_s[k]), 1),
                    "rh_pct": round(float(rh_s[k]), 0),
                    "wind_kmh": round(float(wind_s[k]), 1),
                    "rain_mm": round(float(rain_s[k]), 1),
                    "rain_30d_mm": round(float(rain30_s[k]), 1),
                    "dry_days": int(dry_s[k]),
                    "vpd_kpa": round(float(vpd_s[k]), 2),
                    "elev_m": int(round(float(b.elevacion_m[i]))),
                    "years_since_fire": round(float(b.anios_desde_ultimo_fuego[i]), 1),
                },
            }
            for k, i in enumerate(sel.tolist())
        ]

        return {
            "type": "FeatureCollection",
            "meta": {
                "model_version": self.predictor.model_version,
                "generated_at": cached.generated_at,
                "mode": mode,
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
                "dates_available": cached.dates,
                "counts": counts,
                "returned": len(features),
            },
            "features": features,
        }

    def get_neighbor_graph(self) -> NeighborGraph:
        if self._neighbor_graph is None:
            b = self.baseline
            self._neighbor_graph = build_neighbor_graph(
                cell_id=b.cell_id,
                lat_centro=b.lat_centro,
                lon_centro=b.lon_centro,
                elevacion_m=b.elevacion_m,
            )
        return self._neighbor_graph

    def query_spread_geojson(
        self,
        cached: CachedForecast,
        horizon_hours: int = 24,
        day_offset: int = 0,
        min_risk: str = "Moderado",
        bbox: tuple[float, float, float, float] | None = None,
    ) -> dict:
        """Compute neighbor propagation probabilities for active or high-risk source cells."""
        if self.spread_predictor is None:
            raise RuntimeError("Spread model (`spread_bundle.joblib`) is not loaded")

        b = self.baseline
        n_cells = len(b.cell_id)
        n_avail = len(cached.dates)
        idx = max(0, min(day_offset, n_avail - 1))
        horizon_days = max(1, min(3, horizon_hours // 24))
        end_idx = min(n_avail - 1, idx + horizon_days - 1)

        p_risk = cached.probs[:, idx]
        is_ind = b.is_industrial if b.is_industrial is not None else np.zeros(n_cells, dtype=np.float32)
        # Active wildfire sources: non-industrial cells with recent fire memory OR extreme/high predicted risk today
        active_source_mask = ((b.focos_ultimos_7d >= 1.0) | (p_risk >= self.predictor.risk_cutoffs["Alto"])) & (is_ind < 0.5)
        graph = self.get_neighbor_graph()

        edge_mask = active_source_mask[graph.src_idx]
        s_idx = graph.src_idx[edge_mask]
        t_idx = graph.dst_idx[edge_mask]

        if len(s_idx) == 0:
            p_spread = np.zeros(n_cells, dtype=np.float32)
        else:
            dt = datetime.strptime(cached.dates[idx], "%Y-%m-%d")
            mes_val = float(dt.month)
            doy_val = float(dt.timetuple().tm_yday)
            n_edges = len(s_idx)

            # Neighborhood summary per target cell
            act_nbr_cnt = np.zeros(n_cells, dtype=np.float32)
            nbr_focos_sum = np.zeros(n_cells, dtype=np.float32)
            nbr_frp_sum = np.zeros(n_cells, dtype=np.float32)
            f1_arr = b.focos_ultimos_1d if b.focos_ultimos_1d is not None else (b.focos_ultimos_7d / 7.0)
            f2_arr = b.focos_ultimos_2d if b.focos_ultimos_2d is not None else (b.focos_ultimos_7d * (2.0 / 7.0))
            frp1_arr = b.frp_ultimos_1d if b.frp_ultimos_1d is not None else (b.frp_ultimos_7d / 7.0)
            s_focos = np.maximum(f1_arr[s_idx], 1.0)
            s_frp = np.maximum(frp1_arr[s_idx], 10.0)
            np.add.at(act_nbr_cnt, t_idx, 1.0)
            np.add.at(nbr_focos_sum, t_idx, s_focos)
            np.add.at(nbr_frp_sum, t_idx, s_frp)

            g_t = b.cell_to_grid[t_idx]
            g_s = b.cell_to_grid[s_idx]
            w = cached.weather

            wind_align = np.zeros(n_edges, dtype=np.float32)
            if w.wind_direction_10m_dominant is not None:
                wind_align = compute_wind_alignment(
                    w.wind_direction_10m_dominant[g_s, idx],
                    graph.bearing_deg[edge_mask],
                )
            upwind_speed = (w.wind_speed_10m_max[g_t, idx] * wind_align).astype(np.float32)

            frac_dentro = b.frac_dentro if b.frac_dentro is not None else np.ones(n_cells, dtype=np.float32)
            ind_share = b.industrial_focos_share if b.industrial_focos_share is not None else np.zeros(n_cells, dtype=np.float32)
            fuel_bosque = b.fuel_bosque if b.fuel_bosque is not None else np.full(n_cells, 0.27, dtype=np.float32)
            fuel_pastizal = b.fuel_pastizal if b.fuel_pastizal is not None else np.full(n_cells, 0.34, dtype=np.float32)
            fuel_agro = b.fuel_agro if b.fuel_agro is not None else np.full(n_cells, 0.28, dtype=np.float32)
            fuel_no_comb = b.fuel_no_combustible if b.fuel_no_combustible is not None else np.full(n_cells, 0.11, dtype=np.float32)

            X_pairs = np.column_stack([
                b.lat_centro[t_idx],
                b.lon_centro[t_idx],
                np.full(n_edges, mes_val, dtype=np.float32),
                np.full(n_edges, doy_val, dtype=np.float32),
                np.full(n_edges, float(horizon_days), dtype=np.float32),
                graph.dist_km[edge_mask],
                graph.sin_bearing[edge_mask],
                graph.cos_bearing[edge_mask],
                graph.delta_elev_m[edge_mask],
                graph.slope_deg[edge_mask],
                s_focos,
                s_frp,
                b.focos_ultimos_7d[s_idx],
                b.focos_ultimos_7d[t_idx],
                b.focos_ultimos_30d[t_idx],
                b.frp_ultimos_7d[t_idx],
                b.clim_months[t_idx, dt.month - 1],
                b.anios_desde_ultimo_fuego[t_idx],
                act_nbr_cnt[t_idx],
                nbr_focos_sum[t_idx],
                nbr_frp_sum[t_idx],
                b.elevacion_m[t_idx],
                w.temperature_2m_max[g_t, idx],
                w.relative_humidity_2m[g_t, idx],
                w.wind_speed_10m_max[g_t, idx],
                w.precipitation_sum[g_t, idx],
                w.shortwave_radiation_sum[g_t, idx],
                w.lluvia_acum_7d[g_t, idx],
                w.lluvia_acum_15d[g_t, idx],
                w.lluvia_acum_30d[g_t, idx],
                w.dias_consecutivos_sin_lluvia[g_t, idx],
                w.vpd_approx[g_t, idx],
                wind_align,
                upwind_speed,
                frac_dentro[t_idx],
                is_ind[s_idx],
                ind_share[s_idx],
                b.focos_ultimos_30d[s_idx],
                f1_arr[t_idx],
                f2_arr[t_idx],
                frp1_arr[t_idx],
                fuel_bosque[t_idx],
                fuel_pastizal[t_idx],
                fuel_agro[t_idx],
                fuel_no_comb[t_idx],
                fuel_bosque[s_idx],
                fuel_pastizal[s_idx],
            ])

            pair_probs = self.spread_predictor.predict_pair_probabilities(
                X_pairs,
                wind_alignment=wind_align if w.wind_direction_10m_dominant is not None else None,
                wind_speed_kmh=w.wind_speed_10m_max[g_s, idx],
            )
            p_spread = aggregate_target_probabilities(n_cells, t_idx, pair_probs)

        p_fused = fuse_risk_and_spread(p_risk, p_spread)
        cats = self.spread_predictor.categorize(p_spread)
        counts = {
            "Bajo": int(np.sum(cats == "Bajo")),
            "Moderado": int(np.sum(cats == "Moderado")),
            "Alto": int(np.sum(cats == "Alto")),
            "Extremo": int(np.sum(cats == "Extremo")),
        }

        min_rank = RISK_ORDER.get(min_risk, 1)
        ranks = np.where(cats == "Extremo", 3, np.where(cats == "Alto", 2, np.where(cats == "Moderado", 1, 0)))
        mask = (ranks >= min_rank) & (p_spread > 0.0)
        if bbox is not None:
            west, south, east, north = bbox
            mask &= (
                (b.lon_centro >= west)
                & (b.lon_centro <= east)
                & (b.lat_centro >= south)
                & (b.lat_centro <= north)
            )

        sel = np.nonzero(mask)[0]
        if len(sel) > 20_000:
            top = np.argpartition(p_spread[sel], -20_000)[-20_000:]
            sel = sel[top]

        d_sel = np.full(len(sel), idx, dtype=np.int32)
        conf_pct_s, conf_lvl_s = self._compute_confidence(
            cached.stability[sel, idx], d_sel, cached.is_stale, extra_factor=0.9
        )

        features = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(float(b.lon_centro[i]), 4), round(float(b.lat_centro[i]), 4)],
                },
                "properties": {
                    "cell_id": int(b.cell_id[i]),
                    "propagacion_pct": round(float(p_spread[i]) * 100.0, 2),
                    "riesgo_base_pct": round(float(p_risk[i]) * 100.0, 2),
                    "riesgo_fusionado_pct": round(float(p_fused[i]) * 100.0, 2),
                    "categoria": str(cats[i]),
                    "confianza_pct": int(round(float(conf_pct_s[k]))),
                    "confianza_nivel": str(conf_lvl_s[k]),
                    "horizon_hours": int(horizon_days * 24),
                },
            }
            for k, i in enumerate(sel.tolist())
        ]

        return {
            "type": "FeatureCollection",
            "meta": {
                "model_version": self.spread_predictor.model_version,
                "baseline_model_version": self.predictor.model_version,
                "generated_at": cached.generated_at,
                "horizon_hours": int(horizon_days * 24),
                "fecha_desde": cached.dates[idx],
                "fecha_hasta": cached.dates[end_idx],
                "active_source_cells": int(np.sum(active_source_mask)),
                "counts": counts,
                "returned": len(features),
            },
            "features": features,
        }
