"""Unit tests for spatial hotspot propagation (`app.spread`) and directional weather features."""

from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import numpy as np

from app.main import create_app
from app.openmeteo import build_weather_features
from app.spread import (
    SPREAD_FEATURE_COLUMNS,
    SpreadPredictor,
    aggregate_target_probabilities,
    build_neighbor_graph,
    compute_bearing_and_distance,
    compute_wind_alignment,
    fuse_risk_and_spread,
)


def test_weather_features_include_wind_direction_and_gusts():
    times = [f"2026-11-{d:02d}" for d in range(1, 31)] + [f"2026-12-{d:02d}" for d in range(1, 16)]
    n = len(times)
    tmax = np.full((2, n), 30.0, dtype=np.float32)
    rh = np.full((2, n), 30.0, dtype=np.float32)
    wind = np.full((2, n), 25.0, dtype=np.float32)
    precip = np.zeros((2, n), dtype=np.float32)
    rad = np.full((2, n), 20.0, dtype=np.float32)
    wind_dir = np.full((2, n), 180.0, dtype=np.float32)
    wind_gusts = np.full((2, n), 40.0, dtype=np.float32)

    wf = build_weather_features(
        times, tmax, rh, wind, precip, rad, forecast_days=15, wind_dir=wind_dir, wind_gusts=wind_gusts
    )
    assert wf.wind_direction_10m_dominant is not None
    assert wf.wind_gusts_10m_max is not None
    assert wf.wind_direction_10m_dominant.shape == (2, 15)
    assert np.allclose(wf.wind_direction_10m_dominant, 180.0)
    assert np.allclose(wf.wind_gusts_10m_max, 40.0)


def test_bearing_distance_and_wind_alignment():
    # Source at (-31.50, -64.50), target due North at (-31.45, -64.50)
    lat_s = np.array([-31.50], dtype=np.float32)
    lon_s = np.array([-64.50], dtype=np.float32)
    lat_t = np.array([-31.45], dtype=np.float32)
    lon_t = np.array([-64.50], dtype=np.float32)

    bearing_deg, sin_b, cos_b, dist_km = compute_bearing_and_distance(lat_s, lon_s, lat_t, lon_t)
    assert np.allclose(bearing_deg, 0.0, atol=1e-2)
    assert np.allclose(sin_b, 0.0, atol=1e-3)
    assert np.allclose(cos_b, 1.0, atol=1e-3)
    assert 5.0 < float(dist_km[0]) < 6.0

    # Wind FROM South (180 deg) blows North (0 deg) -> aligned (+1.0) with target due North
    align_downwind = compute_wind_alignment(np.array([180.0], dtype=np.float32), bearing_deg)
    # Wind FROM North (0 deg) blows South (180 deg) -> opposite (-1.0) to target due North
    align_upwind = compute_wind_alignment(np.array([0.0], dtype=np.float32), bearing_deg)
    assert float(align_downwind[0]) > 0.99
    assert float(align_upwind[0]) < -0.99


def test_neighbor_graph_and_probability_aggregation():
    # 3x3 regular ~5km grid around (-31.5, -64.5)
    lats = []
    lons = []
    elevs = []
    cid = 1
    cell_ids = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            cell_ids.append(cid)
            cid += 1
            lats.append(-31.50 + di * 0.045)
            lons.append(-64.50 + dj * 0.050)
            elevs.append(500.0 + di * 50.0)

    graph = build_neighbor_graph(
        cell_id=np.array(cell_ids, dtype=np.int32),
        lat_centro=np.array(lats, dtype=np.float32),
        lon_centro=np.array(lons, dtype=np.float32),
        elevacion_m=np.array(elevs, dtype=np.float32),
        max_dist_km=8.5,
    )
    # Center cell (index 4) has 8 neighbors
    center_out = np.sum(graph.src_idx == 4)
    assert center_out == 8

    # Two active sources pointing to target cell 4 with probs 0.2 and 0.5 -> 1 - (0.8 * 0.5) = 0.6
    agg = aggregate_target_probabilities(
        n_cells=9,
        dst_idx=np.array([4, 4, 2], dtype=np.int32),
        pair_probs=np.array([0.2, 0.5, 0.3], dtype=np.float32),
    )
    assert np.isclose(agg[4], 0.6, atol=1e-5)
    assert np.isclose(agg[2], 0.3, atol=1e-5)
    assert np.isclose(agg[0], 0.0, atol=1e-5)

    fused = fuse_risk_and_spread(
        p_risk=np.array([0.1, 0.0], dtype=np.float32),
        p_spread=np.array([0.5, 0.4], dtype=np.float32),
    )
    assert np.isclose(fused[0], 0.55, atol=1e-5)
    assert np.isclose(fused[1], 0.40, atol=1e-5)


def test_spread_weights_unconfirmed_high_risk_sources_by_ignition_probability(tmp_path: Path):
    from app.config import Settings
    from app.openmeteo import WeatherGridForecast
    from app.service import CachedForecast, ForecastService

    models_dir = Path(__file__).resolve().parents[1] / "models"
    svc = ForecastService(Settings(models_dir=models_dir, monitor_dir=tmp_path / "mon"))
    n_cells = len(svc.baseline.cell_id)
    n_grid = len(svc.baseline.grid_coords)

    # Pick an interior source cell that has neighbors and is non-industrial
    graph = svc.get_neighbor_graph()
    is_ind = svc.baseline.is_industrial if svc.baseline.is_industrial is not None else np.zeros(n_cells)
    candidates = np.unique(graph.src_idx[is_ind[graph.src_idx] < 0.5])
    src_cell_idx = int(candidates[0])
    dst_cell_idx = int(graph.dst_idx[graph.src_idx == src_cell_idx][0])
    dst_cid = int(svc.baseline.cell_id[dst_cell_idx])

    zeros_gd = np.zeros((n_grid, 1), dtype=np.float32)
    weather = WeatherGridForecast(
        dates=["2026-11-18"],
        temperature_2m_max=np.full((n_grid, 1), 32.0, dtype=np.float32),
        relative_humidity_2m=np.full((n_grid, 1), 22.0, dtype=np.float32),
        wind_speed_10m_max=np.full((n_grid, 1), 25.0, dtype=np.float32),
        precipitation_sum=zeros_gd,
        shortwave_radiation_sum=np.full((n_grid, 1), 22.0, dtype=np.float32),
        lluvia_acum_7d=zeros_gd,
        lluvia_acum_15d=zeros_gd,
        lluvia_acum_30d=zeros_gd,
        dias_consecutivos_sin_lluvia=np.full((n_grid, 1), 12.0, dtype=np.float32),
        vpd_approx=np.full((n_grid, 1), 3.2, dtype=np.float32),
        wind_direction_10m_dominant=zeros_gd,
        wind_gusts_10m_max=np.full((n_grid, 1), 35.0, dtype=np.float32),
    )

    # Only src_cell_idx has Alto ignition risk (0.02); all observed fire memory is cleared
    svc.baseline.focos_ultimos_7d[:] = 0.0
    svc.baseline.focos_ultimos_30d[:] = 0.0
    if svc.baseline.focos_ultimos_1d is not None:
        svc.baseline.focos_ultimos_1d[:] = 0.0
    if svc.baseline.frp_ultimos_1d is not None:
        svc.baseline.frp_ultimos_1d[:] = 0.0

    probs = np.full((n_cells, 1), 0.0005, dtype=np.float32)
    probs[src_cell_idx, 0] = 0.02  # Alto risk, but no confirmed fire
    cached = CachedForecast(
        generated_at="2026-11-18T12:00:00+00:00",
        expires_at=9999999.0,
        dates=["2026-11-18"],
        probs=probs,
        stability=np.full((n_cells, 1), 0.9, dtype=np.float16),
        weather=weather,
    )

    unconfirmed_geo = svc.query_spread_geojson(cached=cached, horizon_hours=24, min_risk="Bajo")
    unconfirmed_map = {
        f["properties"]["cell_id"]: f["properties"]["propagacion_pct"]
        for f in unconfirmed_geo["features"]
    }

    # Now mark src_cell_idx as having an observed active fire
    svc.baseline.focos_ultimos_7d[src_cell_idx] = 3.0
    if svc.baseline.focos_ultimos_1d is not None:
        svc.baseline.focos_ultimos_1d[src_cell_idx] = 3.0
    if svc.baseline.frp_ultimos_1d is not None:
        svc.baseline.frp_ultimos_1d[src_cell_idx] = 35.0

    confirmed_geo = svc.query_spread_geojson(cached=cached, horizon_hours=24, min_risk="Bajo")
    confirmed_map = {
        f["properties"]["cell_id"]: f["properties"]["propagacion_pct"]
        for f in confirmed_geo["features"]
    }

    assert dst_cid in confirmed_map
    assert unconfirmed_map.get(dst_cid, 0.0) < confirmed_map[dst_cid] * 0.15


def test_spread_source_selection_aligns_with_daily_percentile_cutoffs(tmp_path: Path):
    from app.config import Settings
    from app.openmeteo import WeatherGridForecast
    from app.service import CachedForecast, ForecastService

    models_dir = Path(__file__).resolve().parents[1] / "models"
    svc = ForecastService(Settings(models_dir=models_dir, monitor_dir=tmp_path / "mon"))
    n_cells = len(svc.baseline.cell_id)
    n_grid = len(svc.baseline.grid_coords)

    idx = np.linspace(0.0, 1.0, n_cells, dtype=np.float64)
    day_probs = (1e-5 + 0.01 * (idx**30)).astype(np.float32)  # max 0.01001 < static Alto 0.01292
    probs = day_probs[:, None]

    # Clear all observed fire memory so only predicted risk can trigger sources
    svc.baseline.focos_ultimos_7d[:] = 0.0
    svc.baseline.focos_ultimos_30d[:] = 0.0
    if svc.baseline.focos_ultimos_1d is not None:
        svc.baseline.focos_ultimos_1d[:] = 0.0
    if svc.baseline.frp_ultimos_1d is not None:
        svc.baseline.frp_ultimos_1d[:] = 0.0

    zeros_gd = np.zeros((n_grid, 1), dtype=np.float32)
    weather = WeatherGridForecast(
        dates=["2026-11-18"],
        temperature_2m_max=np.full((n_grid, 1), 32.0, dtype=np.float32),
        relative_humidity_2m=np.full((n_grid, 1), 22.0, dtype=np.float32),
        wind_speed_10m_max=np.full((n_grid, 1), 25.0, dtype=np.float32),
        precipitation_sum=zeros_gd,
        shortwave_radiation_sum=np.full((n_grid, 1), 22.0, dtype=np.float32),
        lluvia_acum_7d=zeros_gd,
        lluvia_acum_15d=zeros_gd,
        lluvia_acum_30d=zeros_gd,
        dias_consecutivos_sin_lluvia=np.full((n_grid, 1), 12.0, dtype=np.float32),
        vpd_approx=np.full((n_grid, 1), 3.2, dtype=np.float32),
        wind_direction_10m_dominant=zeros_gd,
        wind_gusts_10m_max=np.full((n_grid, 1), 35.0, dtype=np.float32),
    )
    cached = CachedForecast(
        generated_at="2026-11-18T12:00:00+00:00",
        expires_at=9999999.0,
        dates=["2026-11-18"],
        probs=probs,
        stability=np.full((n_cells, 1), 0.9, dtype=np.float16),
        weather=weather,
    )

    forecast_geo = svc.query_geojson(cached=cached, mode="day", day_offset=0, min_risk="Alto")
    spread_geo = svc.query_spread_geojson(cached=cached, horizon_hours=24, day_offset=0, min_risk="Bajo")

    assert spread_geo["meta"]["source_cutoff"]["mode"] == "daily_percentile"
    assert spread_geo["meta"]["source_cutoff"]["Alto"] == forecast_geo["meta"]["cutoffs"]["Alto"]

    is_ind = svc.baseline.is_industrial if svc.baseline.is_industrial is not None else np.zeros(n_cells, dtype=np.float32)
    cutoffs, _ = svc._resolve_risk_cutoffs(day_probs)
    expected_sources = int(np.sum((day_probs >= cutoffs["Alto"]) & (is_ind < 0.5)))
    assert spread_geo["meta"]["active_source_cells"] == expected_sources
    assert spread_geo["meta"]["active_source_cells"] > 0

    # Static spread categorization + Law of Total Probability weighting prevent false high alerts
    assert spread_geo["meta"]["counts"]["Extremo"] == 0
    assert spread_geo["meta"]["counts"]["Alto"] == 0

    svc_static = ForecastService(
        Settings(models_dir=models_dir, monitor_dir=tmp_path / "mon_static", risk_cutoff_mode="static")
    )
    svc_static.baseline.focos_ultimos_7d[:] = 0.0
    svc_static.baseline.focos_ultimos_30d[:] = 0.0
    if svc_static.baseline.focos_ultimos_1d is not None:
        svc_static.baseline.focos_ultimos_1d[:] = 0.0
    if svc_static.baseline.frp_ultimos_1d is not None:
        svc_static.baseline.frp_ultimos_1d[:] = 0.0

    spread_static = svc_static.query_spread_geojson(cached=cached, horizon_hours=24, day_offset=0, min_risk="Bajo")
    assert spread_static["meta"]["source_cutoff"]["mode"] == "static"
    assert spread_static["meta"]["source_cutoff"]["Alto"] == round(float(svc_static.predictor.risk_cutoffs["Alto"]), 6)
    assert spread_static["meta"]["active_source_cells"] == 0

