"""Orchestration service for empirical VIIRS monitoring and comparison endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import TYPE_CHECKING, Any
import numpy as np

from ..config import Settings
from ..predictor import DEFAULT_STATIC_RISK_CUTOFFS, compute_daily_percentile_cutoffs
from .evaluator import (
    EvaluationStore,
    build_ground_truth_vector,
    classify_cell_outcomes,
    evaluate_snapshot_vs_viirs,
)
from .firms import (
    CellSpatialIndex,
    ViirsStore,
    aggregate_viirs_by_cell,
    fetch_firms_csv,
    parse_firms_csv,
)
from .snapshots import SnapshotStore

if TYPE_CHECKING:
    from ..service import CellBaseline


logger = logging.getLogger(__name__)

PREVIOUS_THRESHOLD_PROFILE: dict[str, float] = {
    "top_frac_extremo": 0.001,
    "top_frac_alto": 0.01,
    "top_frac_moderado": 0.05,
    "floor_extremo": 0.001,
    "floor_alto": 0.0003,
    "floor_moderado": 0.0001,
}


class MonitorService:
    """Coordinates FIRMS VIIRS ingestion, daily evaluation, and lightweight API queries."""

    def __init__(
        self,
        settings: Settings,
        baseline: CellBaseline,
        static_risk_cutoffs: dict[str, float] | None = None,
    ) -> None:
        self.settings = settings
        self.baseline = baseline
        self.static_risk_cutoffs = (
            dict(static_risk_cutoffs)
            if static_risk_cutoffs is not None
            else dict(DEFAULT_STATIC_RISK_CUTOFFS)
        )
        db_path = settings.monitor_dir / "monitor.duckdb"
        self.snap_store = SnapshotStore(db_path=db_path, memory_limit=settings.monitor_duckdb_memory_limit)
        self.viirs_store = ViirsStore(db_path=db_path, memory_limit=settings.monitor_duckdb_memory_limit)
        self.eval_store = EvaluationStore(db_path=db_path, memory_limit=settings.monitor_duckdb_memory_limit)
        self._spatial_index: CellSpatialIndex | None = None
        self._cell_idx_map: dict[int, int] | None = None
        self._lock = asyncio.Lock()
        self._run_task: asyncio.Task[None] | None = None
        self._status: dict[str, Any] = {
            "running": False,
            "last_run_at": None,
            "last_result": None,
            "last_error": None,
        }

    def get_status(self) -> dict[str, Any]:
        """Return current background monitor job state without running heavy work."""
        return dict(self._status)

    def trigger_run(
        self,
        *,
        date: str | None = None,
        day_range: int = 1,
        min_frp_mw: float = 10.0,
    ) -> dict[str, Any]:
        """Schedule a non-blocking VIIRS ingest+eval job if one is not already active."""
        if not self.settings.firms_map_key.strip():
            raise ValueError("FIRMS_MAP_KEY is not configured")

        if self._run_task is not None and not self._run_task.done():
            return {"status": "already_running", **self.get_status()}

        self._status["running"] = True
        self._status["last_error"] = None

        async def _job() -> None:
            try:
                result = await self.ingest_and_evaluate(
                    date=date,
                    day_range=day_range,
                    min_frp_mw=min_frp_mw,
                )
                self._status["last_result"] = result
                self._status["last_error"] = None
            except Exception as exc:
                logger.warning("Background monitor run failed: %s", exc)
                self._status["last_error"] = str(exc)
            finally:
                self._status["running"] = False
                self._status["last_run_at"] = datetime.now(timezone.utc).isoformat()

        self._run_task = asyncio.create_task(_job())
        return {"status": "started", **self.get_status()}

    async def run_periodic_monitor(self, interval_s: float | None = None) -> None:
        """Periodically ingest VIIRS detections and evaluate snapshots in the background."""
        sleep_s = float(interval_s if interval_s is not None else self.settings.monitor_refresh_interval_s)
        while True:
            await asyncio.sleep(sleep_s)
            if not self.settings.firms_map_key.strip():
                continue
            try:
                await self.ingest_and_evaluate()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Periodic monitor run failed: %s", exc)

    def _get_spatial_index(self) -> CellSpatialIndex:
        if self._spatial_index is None:
            self._spatial_index = CellSpatialIndex.from_cells(
                self.baseline.cell_id,
                self.baseline.lat_centro,
                self.baseline.lon_centro,
            )
        return self._spatial_index

    def _get_cell_idx_map(self) -> dict[int, int]:
        if self._cell_idx_map is None:
            self._cell_idx_map = {
                int(cid): idx for idx, cid in enumerate(self.baseline.cell_id.tolist())
            }
        return self._cell_idx_map

    async def ingest_and_evaluate(
        self,
        *,
        date: str | None = None,
        day_range: int = 1,
        min_frp_mw: float = 10.0,
    ) -> dict[str, Any]:
        """Fetch VIIRS detections from NASA FIRMS, map to cells, and evaluate available snapshots."""
        if not self.settings.firms_map_key.strip():
            raise ValueError("FIRMS_MAP_KEY is not configured")

        async with self._lock:
            spatial_index = self._get_spatial_index()
            total_rows = 0
            seen_dates: set[str] = set()

            for source in self.settings.firms_sources:
                csv_text = await fetch_firms_csv(
                    map_key=self.settings.firms_map_key,
                    source=source,
                    bbox=self.settings.firms_bbox,
                    day_range=day_range,
                    date=date,
                    base_url=self.settings.firms_base_url,
                )
                parsed = parse_firms_csv(csv_text, exclude_low_confidence=True)
                mapped = spatial_index.assign(parsed["latitude"], parsed["longitude"])
                agg = aggregate_viirs_by_cell(parsed["acq_date"], mapped, parsed["frp"])
                saved = await asyncio.to_thread(
                    self.viirs_store.save_daily_detections,
                    source=source,
                    acq_dates=agg["acq_date"],
                    cell_ids=agg["cell_id"],
                    detections_count=agg["detections_count"],
                    frp_sum=agg["frp_sum"],
                    frp_max=agg["frp_max"],
                )
                total_rows += saved
                seen_dates.update(str(d) for d in agg["acq_date"].tolist())

            evaluated_dates: list[str] = []
            for target_d in sorted(seen_dates):
                if await asyncio.to_thread(self.snap_store.has_snapshot, target_d):
                    await asyncio.to_thread(
                        self.evaluate_date,
                        target_date=target_d,
                        issued_date=target_d,
                        min_frp_mw=min_frp_mw,
                    )
                    evaluated_dates.append(target_d)

            return {
                "sources": list(self.settings.firms_sources),
                "ingested_rows": total_rows,
                "dates_seen": sorted(seen_dates),
                "evaluated_dates": evaluated_dates,
            }

    def evaluate_date(
        self,
        *,
        target_date: str,
        issued_date: str | None = None,
        min_frp_mw: float = 10.0,
        min_alert_risk: str = "Alto",
    ) -> dict[str, Any]:
        """Run and persist empirical evaluation for one `(target_date, issued_date)` pair."""
        return evaluate_snapshot_vs_viirs(
            snap_store=self.snap_store,
            viirs_store=self.viirs_store,
            eval_store=self.eval_store,
            target_date=target_date,
            issued_date=issued_date,
            min_frp_mw=min_frp_mw,
            min_alert_risk=min_alert_risk,
        )

    def list_metrics(self, limit: int = 30) -> list[dict[str, Any]]:
        return self.eval_store.list_metrics(limit=limit)

    def _count_near_hits_12km(
        self,
        cell_ids: np.ndarray,
        fa_mask: np.ndarray,
        y_true: np.ndarray,
    ) -> int:
        """Count false-alarm cells that had a real VIIRS fire within `<= 12 km` on the same day."""
        if self.baseline is None or not np.any(fa_mask) or not np.any(y_true == 1):
            return 0
        pos_ids = set(int(c) for c in cell_ids[y_true == 1].tolist())
        fa_ids = set(int(c) for c in cell_ids[fa_mask].tolist())
        b = self.baseline
        b_cids = b.cell_id.tolist()
        pos_mask_b = np.array([int(c) in pos_ids for c in b_cids], dtype=bool)
        fa_mask_b = np.array([int(c) in fa_ids for c in b_cids], dtype=bool)
        if not np.any(pos_mask_b) or not np.any(fa_mask_b):
            return 0
        lats_p = np.radians(b.lat_centro[pos_mask_b])
        lons_p = np.radians(b.lon_centro[pos_mask_b])
        lats_f = np.radians(b.lat_centro[fa_mask_b])
        lons_f = np.radians(b.lon_centro[fa_mask_b])
        near = 0
        for lf, lof in zip(lats_f.tolist(), lons_f.tolist()):
            dlat = lats_p - lf
            dlon = lons_p - lof
            a = np.sin(dlat / 2.0) ** 2 + np.cos(lf) * np.cos(lats_p) * (np.sin(dlon / 2.0) ** 2)
            min_km = float(np.min(6371.0 * 2.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))))
            if min_km <= 12.0:
                near += 1
        return near

    def _eval_threshold_profile(
        self,
        probs_24h: np.ndarray,
        y_true: np.ndarray,
        n_pos: int,
        profile: dict[str, float],
        *,
        alert_min_risk: str = "Moderado",
        cell_ids: np.ndarray | None = None,
    ) -> dict[str, Any]:
        cutoffs = compute_daily_percentile_cutoffs(
            probs_24h,
            self.static_risk_cutoffs,
            top_frac_extremo=profile["top_frac_extremo"],
            top_frac_alto=profile["top_frac_alto"],
            top_frac_moderado=profile["top_frac_moderado"],
            floor_extremo=profile["floor_extremo"],
            floor_alto=profile["floor_alto"],
            floor_moderado=profile["floor_moderado"],
        )
        alerts_mask = probs_24h >= cutoffs[alert_min_risk]
        watch_mask = (probs_24h >= cutoffs["Moderado"]) & (~alerts_mask)
        fa_mask = alerts_mask & (y_true == 0)
        alerts_count = int(np.sum(alerts_mask))
        hits_count = int(np.sum(alerts_mask & (y_true == 1)))
        misses_count = int(np.sum((~alerts_mask) & (y_true == 1)))
        false_alarms_count = int(np.sum(fa_mask))
        near_hits_count = (
            self._count_near_hits_12km(cell_ids, fa_mask, y_true)
            if cell_ids is not None
            else 0
        )
        watch_cells_count = int(np.sum(watch_mask))
        watch_hits_count = int(np.sum(watch_mask & (y_true == 1)))
        return {
            "alert_min_risk": alert_min_risk,
            "alerts_count": alerts_count,
            "hits_count": hits_count,
            "near_hits_count": near_hits_count,
            "misses_count": misses_count,
            "false_alarms_count": false_alarms_count,
            "watch_cells_count": watch_cells_count,
            "watch_hits_count": watch_hits_count,
            "capture_rate": (hits_count / n_pos) if n_pos > 0 else None,
            "precision": (hits_count / alerts_count) if alerts_count > 0 else None,
            "operational_precision": ((hits_count + near_hits_count) / alerts_count) if alerts_count > 0 else None,
            "cutoffs": {k: round(float(v), 6) for k, v in cutoffs.items()},
        }

    def compare_threshold_profiles(self, limit: int = 14) -> dict[str, Any]:
        """Compare previous (`Moderado+` 0.1/1/5%) vs. current two-tier (`Alto+` 0.05/0.4% + `Moderado` 2.5% watch) thresholds."""
        records = self.eval_store.list_metrics(limit=limit)
        current_profile: dict[str, float] = {
            "top_frac_extremo": self.settings.risk_top_frac_extremo,
            "top_frac_alto": self.settings.risk_top_frac_alto,
            "top_frac_moderado": self.settings.risk_top_frac_moderado,
            "floor_extremo": self.settings.risk_floor_extremo,
            "floor_alto": self.settings.risk_floor_alto,
            "floor_moderado": self.settings.risk_floor_moderado,
        }

        items: list[dict[str, Any]] = []
        tot_pos = prev_hits = curr_hits = prev_fa = curr_fa = curr_watch_hits = curr_near_hits = curr_alerts = 0

        for rec in records:
            target_date = str(rec["target_date"])
            issued_date = str(rec["issued_date"])
            snap = self.snap_store.load_snapshot_24h(issued_date)
            if len(snap["cell_id"]) == 0:
                continue

            viirs = self.viirs_store.load_daily_detections(target_date)
            y_true, _, _ = build_ground_truth_vector(
                snap["cell_id"],
                viirs,
                min_detections=1,
                min_frp_mw=float(rec["min_frp_mw"]),
            )
            n_pos = int(np.sum(y_true))
            prev_stats = self._eval_threshold_profile(
                snap["prob_24h"],
                y_true,
                n_pos,
                PREVIOUS_THRESHOLD_PROFILE,
                alert_min_risk="Moderado",
            )
            curr_stats = self._eval_threshold_profile(
                snap["prob_24h"],
                y_true,
                n_pos,
                current_profile,
                alert_min_risk="Alto",
                cell_ids=snap["cell_id"],
            )

            tot_pos += n_pos
            prev_hits += prev_stats["hits_count"]
            curr_hits += curr_stats["hits_count"]
            prev_fa += prev_stats["false_alarms_count"]
            curr_fa += curr_stats["false_alarms_count"]
            curr_watch_hits += curr_stats["watch_hits_count"]
            curr_near_hits += curr_stats["near_hits_count"]
            curr_alerts += curr_stats["alerts_count"]

            items.append(
                {
                    "target_date": target_date,
                    "issued_date": issued_date,
                    "n_positives": n_pos,
                    "previous": prev_stats,
                    "current": curr_stats,
                }
            )

        fa_reduction_pct = round((1.0 - (curr_fa / prev_fa)) * 100.0, 1) if prev_fa > 0 else None
        op_prec_pct = round(((curr_hits + curr_near_hits) / curr_alerts) * 100.0, 1) if curr_alerts > 0 else None
        return {
            "profiles": {
                "previous": {
                    "label": "previous_0.1_1_5pct",
                    "alert_min_risk": "Moderado",
                    **PREVIOUS_THRESHOLD_PROFILE,
                },
                "current": {
                    "label": "current_2tier_alto_alert",
                    "alert_min_risk": "Alto",
                    **current_profile,
                },
            },
            "summary": {
                "days_compared": len(items),
                "total_positives": tot_pos,
                "previous_total_hits": prev_hits,
                "current_total_hits": curr_hits,
                "current_total_near_hits": curr_near_hits,
                "current_operational_precision_pct": op_prec_pct,
                "current_total_watch_hits": curr_watch_hits,
                "current_total_combined_hits": curr_hits + curr_watch_hits,
                "previous_total_false_alarms": prev_fa,
                "current_total_false_alarms": curr_fa,
                "false_alarm_reduction_pct": fa_reduction_pct,
            },
            "items": items,
        }

    def get_comparison_geojson(
        self,
        *,
        target_date: str,
        issued_date: str | None = None,
        min_frp_mw: float = 10.0,
        min_alert_risk: str = "Alto",
    ) -> dict[str, Any]:
        """Return GeoJSON Point FeatureCollection of `hit`, `miss`, and `false_alarm` cells."""
        iss = issued_date or target_date
        snap = self.snap_store.load_snapshot_24h(iss)
        if len(snap["cell_id"]) == 0:
            raise FileNotFoundError(f"No 24h snapshot found for issued_date={iss}")

        viirs = self.viirs_store.load_daily_detections(target_date)
        y_true, det_counts, frp_sums = build_ground_truth_vector(
            snap["cell_id"],
            viirs,
            min_detections=1,
            min_frp_mw=min_frp_mw,
        )
        outcomes = classify_cell_outcomes(
            cell_ids=snap["cell_id"],
            probs=snap["prob_24h"],
            risk_categories=snap["risk_category"],
            y_true=y_true,
            min_alert_risk=min_alert_risk,
        )

        # Map kept cell_ids back to detection counts/FRP and lat/lon
        snap_idx_by_cid = {int(cid): i for i, cid in enumerate(snap["cell_id"].tolist())}
        cell_idx_map = self._get_cell_idx_map()

        features: list[dict[str, Any]] = []
        for cid, prob, cat, out in zip(
            outcomes["cell_id"].tolist(),
            outcomes["prob_24h"].tolist(),
            outcomes["risk_category"].tolist(),
            outcomes["outcome"].tolist(),
        ):
            b_idx = cell_idx_map.get(int(cid))
            if b_idx is None:
                continue
            s_idx = snap_idx_by_cid[int(cid)]
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            round(float(self.baseline.lon_centro[b_idx]), 5),
                            round(float(self.baseline.lat_centro[b_idx]), 5),
                        ],
                    },
                    "properties": {
                        "cell_id": int(cid),
                        "outcome": str(out),
                        "prob_24h": round(float(prob), 6),
                        "risk_category": str(cat),
                        "detections_count": int(det_counts[s_idx]),
                        "frp_sum": round(float(frp_sums[s_idx]), 2),
                    },
                }
            )

        return {
            "type": "FeatureCollection",
            "metadata": {
                "target_date": target_date,
                "issued_date": iss,
                "min_frp_mw": float(min_frp_mw),
                "min_alert_risk": min_alert_risk,
                "features_count": len(features),
            },
            "features": features,
        }
