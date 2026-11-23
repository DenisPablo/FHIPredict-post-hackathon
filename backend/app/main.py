"""FastAPI entry point for FHIPredict."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .config import get_settings
from .monitor.service import MonitorService
from .service import ForecastService


_service: ForecastService | None = None
_monitor: MonitorService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _service, _monitor
    settings = get_settings()
    _service = ForecastService(settings)
    _monitor = MonitorService(
        settings,
        _service.baseline,
        static_risk_cutoffs=_service.predictor.risk_cutoffs,
    )
    warmup_task = asyncio.create_task(_service.warm_up())
    refresh_task = asyncio.create_task(_service.run_periodic_refresh())
    monitor_task = asyncio.create_task(_monitor.run_periodic_monitor())
    try:
        yield
    finally:
        for task in (warmup_task, refresh_task, monitor_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(warmup_task, refresh_task, monitor_task, return_exceptions=True)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="FHIPredict API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    async def health():
        assert _service is not None
        return {
            "status": "ok",
            "model_version": _service.predictor.model_version,
            "spread_model_version": (
                _service.spread_predictor.model_version if _service.spread_predictor is not None else None
            ),
            "cells_total": int(len(_service.baseline.cell_id)),
            "grid_points": int(len(_service.baseline.grid_coords)),
            "forecast_cached": _service._cache is not None,
        }

    @app.get("/api/v1/spread")
    async def spread(
        horizon_hours: int = Query(default=24, ge=24, le=72),
        day_offset: int = Query(default=0, ge=0, le=15),
        min_risk: Literal["Bajo", "Moderado", "Alto", "Extremo"] = "Moderado",
        bbox: str | None = None,
        refresh: bool = False,
    ):
        assert _service is not None
        if horizon_hours not in (24, 48, 72):
            raise HTTPException(status_code=400, detail="horizon_hours must be 24, 48, or 72")
        if _service.spread_predictor is None:
            raise HTTPException(status_code=503, detail="Spread model is not enabled or bundle is missing")

        parsed_bbox = None
        if bbox:
            try:
                parts = [float(x) for x in bbox.split(",")]
                if len(parts) != 4:
                    raise ValueError
                parsed_bbox = (parts[0], parts[1], parts[2], parts[3])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid bbox; expected west,south,east,north") from exc

        try:
            cached = await _service.get_forecast(force_refresh=refresh)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Forecast upstream unavailable (Open-Meteo rate limit or network error): {exc}",
            ) from exc

        return _service.query_spread_geojson(
            cached=cached,
            horizon_hours=horizon_hours,
            day_offset=day_offset,
            min_risk=min_risk,
            bbox=parsed_bbox,
        )

    @app.get("/api/v1/forecast")
    async def forecast(
        mode: Literal["window", "day"] = "window",
        days: int = Query(default=1, ge=1, le=16),
        day_offset: int = Query(default=0, ge=0, le=15),
        min_risk: Literal["Bajo", "Moderado", "Alto", "Extremo"] = "Moderado",
        bbox: str | None = None,
        refresh: bool = False,
    ):
        assert _service is not None
        parsed_bbox = None
        if bbox:
            try:
                parts = [float(x) for x in bbox.split(",")]
                if len(parts) != 4:
                    raise ValueError
                parsed_bbox = (parts[0], parts[1], parts[2], parts[3])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid bbox; expected west,south,east,north") from exc

        try:
            cached = await _service.get_forecast(force_refresh=refresh)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Forecast upstream unavailable (Open-Meteo rate limit or network error): {exc}",
            ) from exc
        return _service.query_geojson(
            cached=cached,
            mode=mode,
            days=days,
            day_offset=day_offset,
            min_risk=min_risk,
            bbox=parsed_bbox,
        )

    @app.get("/api/v1/monitor/status")
    async def monitor_status():
        assert _monitor is not None
        return _monitor.get_status()

    @app.get("/api/v1/monitor/metrics")
    async def monitor_metrics(limit: int = Query(default=30, ge=1, le=365)):
        assert _monitor is not None
        items = await asyncio.to_thread(_monitor.list_metrics, limit=limit)
        return {"items": items}

    @app.get("/api/v1/monitor/threshold-comparison")
    async def monitor_threshold_comparison(limit: int = Query(default=14, ge=1, le=90)):
        assert _monitor is not None
        return await asyncio.to_thread(_monitor.compare_threshold_profiles, limit=limit)

    @app.get("/api/v1/monitor/comparison")
    async def monitor_comparison(
        target_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
        issued_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        min_frp_mw: float = Query(default=10.0, ge=0.0),
        min_alert_risk: Literal["Moderado", "Alto", "Extremo"] = "Moderado",
    ):
        assert _monitor is not None
        try:
            return await asyncio.to_thread(
                _monitor.get_comparison_geojson,
                target_date=target_date,
                issued_date=issued_date,
                min_frp_mw=min_frp_mw,
                min_alert_risk=min_alert_risk,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/v1/monitor/run", status_code=202)
    async def monitor_run(
        date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        day_range: int = Query(default=1, ge=1, le=10),
        min_frp_mw: float = Query(default=10.0, ge=0.0),
    ):
        assert _monitor is not None
        try:
            return _monitor.trigger_run(
                date=date,
                day_range=day_range,
                min_frp_mw=min_frp_mw,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if settings.static_dir and settings.static_dir.is_dir():
        static_root = settings.static_dir.resolve()
        assets_dir = static_root / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            if full_path:
                candidate = (static_root / full_path).resolve()
                if candidate.is_relative_to(static_root) and candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(static_root / "index.html")

    return app


app = create_app()
