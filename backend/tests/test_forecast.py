"""Tests for FHIPredict backend inference and rolling weather features."""

from pathlib import Path
from fastapi.testclient import TestClient
import numpy as np

from app.config import Settings
from app.main import create_app
from app.openmeteo import build_weather_features
from app.predictor import FireRiskPredictor


def test_rolling_weather_features():
    times = [f"2026-11-{d:02d}" for d in range(1, 31)] + [f"2026-12-{d:02d}" for d in range(1, 16)]
    n = len(times)
    precip = np.zeros((2, n), dtype=np.float32)
    precip[0, -16] = 5.0  # rain 1 day before forecast starts
    tmax = np.full((2, n), 32.0, dtype=np.float32)
    rh = np.full((2, n), 25.0, dtype=np.float32)
    wind = np.full((2, n), 28.0, dtype=np.float32)
    rad = np.full((2, n), 22.0, dtype=np.float32)

    wf = build_weather_features(times, tmax, rh, wind, precip, rad, forecast_days=15)
    assert len(wf.dates) == 15
    assert wf.temperature_2m_max.shape == (2, 15)
    assert wf.vpd_approx[0, 0] > 2.5


def test_bundle_loads_and_predicts():
    models_dir = Path(__file__).resolve().parents[1] / "models"
    predictor = FireRiskPredictor.from_bundle(models_dir / "fire_risk_bundle.joblib")
    assert predictor.model_version == "lgbm-risk-24h-v2"
    X = np.zeros((4, len(predictor.feature_columns)), dtype=np.float32)
    probs = predictor.predict_probabilities(X)
    assert probs.shape == (4,)
    assert np.all((probs > 0.0) & (probs < 1.0))


def test_health_endpoint():
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["cells_total"] == 64653
        assert body["grid_points"] == 971


def test_predict_with_stability_and_confidence_decay():
    models_dir = Path(__file__).resolve().parents[1] / "models"
    predictor = FireRiskPredictor.from_bundle(models_dir / "fire_risk_bundle.joblib")
    X = np.zeros((4, len(predictor.feature_columns)), dtype=np.float32)

    probs_ref = predictor.predict_probabilities(X)
    probs, stability = predictor.predict_with_stability(X)

    assert np.allclose(probs, probs_ref, atol=1e-6)
    assert stability.shape == (4,)
    assert np.all((stability >= 0.2) & (stability <= 1.0))

    from app.service import ForecastService

    svc = ForecastService(Settings(models_dir=models_dir))
    stab = np.array([0.95, 0.95], dtype=np.float32)
    pct_day0, lvl_day0 = svc._compute_confidence(stab, np.array([0, 0], dtype=np.int32), is_stale=False)
    pct_day14, lvl_day14 = svc._compute_confidence(stab, np.array([14, 14], dtype=np.int32), is_stale=False)
    pct_stale, _ = svc._compute_confidence(stab, np.array([0, 0], dtype=np.int32), is_stale=True)

    assert np.all(pct_day0 > pct_day14)
    assert np.all(pct_day0 > pct_stale)
    assert lvl_day0[0] == "Alta"
    assert lvl_day14[0] in ("Media", "Baja")


def test_periodic_refresh_recovers_from_error_and_stops():
    import asyncio
    from app.service import ForecastService

    models_dir = Path(__file__).resolve().parents[1] / "models"
    svc = ForecastService(Settings(models_dir=models_dir))

    calls = 0

    async def fake_refresh(force_refresh: bool = False):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient 429")
        return svc._cache

    svc._refresh_forecast = fake_refresh  # type: ignore[method-assign]

    async def runner():
        task = asyncio.create_task(svc.run_periodic_refresh(interval_s=0.01))
        for _ in range(30):
            if calls >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(runner())
    assert calls >= 2


def test_window_mode_uses_peak_daily_probability_scale(tmp_path: Path):
    from app.openmeteo import WeatherGridForecast
    from app.service import CachedForecast, ForecastService

    models_dir = Path(__file__).resolve().parents[1] / "models"
    svc = ForecastService(
        Settings(models_dir=models_dir, monitor_dir=tmp_path / "mon", enable_spread=False)
    )
    n_cells = len(svc.baseline.cell_id)
    n_grid = len(svc.baseline.grid_coords)
    n_days = 15
    dates = [f"2026-11-{d:02d}" for d in range(18, 33)][:n_days]

    # Constant daily Moderado probability (0.0045 < Alto 0.01292).
    # Under independent 15-day accumulation 1 - (1 - 0.0045)^15 = 0.0654 > Extremo (0.05785).
    probs = np.full((n_cells, n_days), 0.0045, dtype=np.float32)
    stability = np.full((n_cells, n_days), 0.9, dtype=np.float16)
    zeros_gd = np.zeros((n_grid, n_days), dtype=np.float32)
    weather = WeatherGridForecast(
        dates=dates,
        temperature_2m_max=zeros_gd,
        relative_humidity_2m=zeros_gd,
        wind_speed_10m_max=zeros_gd,
        precipitation_sum=zeros_gd,
        shortwave_radiation_sum=zeros_gd,
        lluvia_acum_7d=zeros_gd,
        lluvia_acum_15d=zeros_gd,
        lluvia_acum_30d=zeros_gd,
        dias_consecutivos_sin_lluvia=zeros_gd,
        vpd_approx=zeros_gd,
    )
    cached = CachedForecast(
        generated_at="2026-11-18T12:00:00+00:00",
        expires_at=9999999.0,
        dates=dates,
        probs=probs,
        stability=stability,
        weather=weather,
    )

    geo = svc.query_geojson(cached=cached, mode="window", days=15, min_risk="Moderado")
    assert geo["meta"]["counts"]["Extremo"] == 0
    assert geo["meta"]["counts"]["Alto"] == 0
    assert geo["meta"]["counts"]["Moderado"] == n_cells


def test_fire_memory_updates_from_viirs_and_decays_over_horizon(tmp_path: Path):
    from app.monitor.firms import ViirsStore
    from app.service import ForecastService

    models_dir = Path(__file__).resolve().parents[1] / "models"
    mon_dir = tmp_path / "mon"
    svc = ForecastService(
        Settings(models_dir=models_dir, monitor_dir=mon_dir, enable_spread=False)
    )
    target_cid = int(svc.baseline.cell_id[0])

    viirs = ViirsStore(db_path=mon_dir / "monitor.duckdb", memory_limit="128MB")
    viirs.save_daily_detections(
        source="VIIRS_SNPP_NRT",
        acq_dates=np.array(["2026-11-18"]),
        cell_ids=np.array([target_cid], dtype=np.int32),
        detections_count=np.array([4], dtype=np.int32),
        frp_sum=np.array([45.0], dtype=np.float32),
        frp_max=np.array([25.0], dtype=np.float32),
    )

    mem = svc._resolve_fire_memory("2026-11-18")
    assert float(mem.focos_7d[0]) >= 4.0
    assert float(mem.frp_7d[0]) >= 45.0
    assert float(mem.anios_desde_ultimo_fuego[0]) < 0.01

    decayed_d7 = svc._decay_fire_memory_for_horizon(mem, day_idx=7)
    assert float(decayed_d7.focos_7d[0]) == 0.0
    assert float(decayed_d7.frp_7d[0]) == 0.0
    assert np.isclose(
        float(decayed_d7.focos_30d[0]),
        float(mem.focos_30d[0]) * (23.0 / 30.0),
        rtol=1e-4,
    )
    assert float(decayed_d7.anios_desde_ultimo_fuego[0]) > float(mem.anios_desde_ultimo_fuego[0])
