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
    assert predictor.model_version == "lgbm-risk-24h-v3"
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


def test_daily_percentile_cutoffs_adapt_underestimated_distribution():
    models_dir = Path(__file__).resolve().parents[1] / "models"
    predictor = FireRiskPredictor.from_bundle(models_dir / "fire_risk_bundle.joblib")

    probs = np.concatenate(
        [
            np.linspace(1e-5, 0.0015, 9750),
            np.linspace(0.00151, 0.005, 190),
            np.linspace(0.0051, 0.02, 52),
            np.linspace(0.0201, 0.04, 8),
        ]
    ).astype(np.float32)

    cutoffs = predictor.compute_daily_percentile_cutoffs(probs)
    assert 0.015 <= cutoffs["Extremo"] < predictor.risk_cutoffs["Extremo"]
    assert 0.005 <= cutoffs["Alto"] < predictor.risk_cutoffs["Alto"]
    assert 0.0005 <= cutoffs["Moderado"] < predictor.risk_cutoffs["Moderado"]
    assert cutoffs["Extremo"] >= cutoffs["Alto"] >= cutoffs["Moderado"]

    cats = predictor.categorize(probs, cutoffs=cutoffs)
    n = len(probs)
    ext_share = float(np.sum(cats == "Extremo")) / n
    high_share = float(np.sum(np.isin(cats, ["Extremo", "Alto"]))) / n
    mod_share = float(np.sum(np.isin(cats, ["Extremo", "Alto", "Moderado"]))) / n

    assert 0.0003 <= ext_share <= 0.0008
    assert 0.003 <= high_share <= 0.005
    assert 0.023 <= mod_share <= 0.027


def test_daily_percentile_cutoffs_guards():
    models_dir = Path(__file__).resolve().parents[1] / "models"
    predictor = FireRiskPredictor.from_bundle(models_dir / "fire_risk_bundle.joblib")

    # Severe outbreak: quantiles exceed static cutoffs -> capped at static bundle cutoffs
    outbreak = np.linspace(0.001, 0.20, 10_000, dtype=np.float32)
    outbreak_cutoffs = predictor.compute_daily_percentile_cutoffs(outbreak)
    assert outbreak_cutoffs == predictor.risk_cutoffs

    # Near-zero rainy day: quantiles fall below safety floors -> clamped at floors, zero alerts
    rainy = np.linspace(1e-7, 5e-5, 10_000, dtype=np.float32)
    rainy_cutoffs = predictor.compute_daily_percentile_cutoffs(rainy)
    assert rainy_cutoffs == {"Extremo": 0.015, "Alto": 0.005, "Moderado": 0.0005}
    assert np.all(predictor.categorize(rainy, cutoffs=rainy_cutoffs) == "Bajo")

    # Quiet low-risk day (< 0.04%): quantiles fall below two-tier safety floors -> zero alerts
    quiet = np.linspace(1e-5, 0.0004, 10_000, dtype=np.float32)
    quiet_cutoffs = predictor.compute_daily_percentile_cutoffs(quiet)
    assert quiet_cutoffs == {"Extremo": 0.015, "Alto": 0.005, "Moderado": 0.0005}
    assert np.all(predictor.categorize(quiet, cutoffs=quiet_cutoffs) == "Bajo")

    # Constant or too-small arrays -> fall back to static cutoffs
    assert predictor.compute_daily_percentile_cutoffs(np.full(10_000, 0.0045, dtype=np.float32)) == predictor.risk_cutoffs
    assert predictor.compute_daily_percentile_cutoffs(np.linspace(1e-4, 0.02, 10, dtype=np.float32)) == predictor.risk_cutoffs

    # Tied-minimum array (q95 == vmin) -> fall back to static cutoffs
    tied = np.concatenate(
        [np.full(9_990, 0.0005, dtype=np.float32), np.full(10, 0.02, dtype=np.float32)]
    )
    tied_cutoffs = predictor.compute_daily_percentile_cutoffs(tied)
    assert tied_cutoffs == predictor.risk_cutoffs
    assert int(np.sum(predictor.categorize(tied, cutoffs=tied_cutoffs) == "Bajo")) == 9_990


def test_query_geojson_and_snapshot_use_daily_percentile_cutoffs(tmp_path: Path):
    from app.openmeteo import WeatherGridForecast
    from app.service import CachedForecast, ForecastService

    models_dir = Path(__file__).resolve().parents[1] / "models"
    svc = ForecastService(
        Settings(models_dir=models_dir, monitor_dir=tmp_path / "mon", enable_spread=False)
    )
    n_cells = len(svc.baseline.cell_id)
    n_grid = len(svc.baseline.grid_coords)
    n_days = 3
    dates = ["2026-11-18", "2026-11-19", "2026-11-20"]

    idx = np.linspace(0.0, 1.0, n_cells, dtype=np.float64)
    day_probs = (1e-5 + 0.018 * (idx**140)).astype(np.float32)
    probs = np.repeat(day_probs[:, None], n_days, axis=1)
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

    geo = svc.query_geojson(cached=cached, mode="day", day_offset=0, min_risk="Moderado")
    assert geo["meta"]["cutoffs"]["mode"] == "daily_percentile"
    assert 25 <= geo["meta"]["counts"]["Extremo"] <= 40
    assert 210 <= geo["meta"]["counts"]["Alto"] <= 245
    assert 1320 <= geo["meta"]["counts"]["Moderado"] <= 1400

    assert svc._maybe_save_snapshot_24h(cached) is True
    assert svc._snapshot_store is not None
    snap = svc._snapshot_store.load_snapshot_24h("2026-11-18")
    snap_counts = {
        cat: int(np.sum(snap["risk_category"] == cat))
        for cat in ("Bajo", "Moderado", "Alto", "Extremo")
    }
    assert snap_counts == geo["meta"]["counts"]

    svc_static = ForecastService(
        Settings(
            models_dir=models_dir,
            monitor_dir=tmp_path / "mon_static",
            enable_spread=False,
            risk_cutoff_mode="static",
        )
    )
    geo_static = svc_static.query_geojson(cached=cached, mode="day", day_offset=0, min_risk="Moderado")
    assert geo_static["meta"]["cutoffs"]["mode"] == "static"
    assert geo_static["meta"]["cutoffs"]["Extremo"] == round(float(svc_static.predictor.risk_cutoffs["Extremo"]), 6)
    assert geo_static["meta"]["cutoffs"]["Alto"] == round(float(svc_static.predictor.risk_cutoffs["Alto"]), 6)
    assert geo_static["meta"]["cutoffs"]["Moderado"] == round(float(svc_static.predictor.risk_cutoffs["Moderado"]), 6)


def test_snapshot_24h_aligns_issued_and_target_date_across_utc_midnight(tmp_path: Path):
    from app.openmeteo import WeatherGridForecast
    from app.service import CachedForecast, ForecastService

    models_dir = Path(__file__).resolve().parents[1] / "models"
    svc = ForecastService(
        Settings(models_dir=models_dir, monitor_dir=tmp_path / "mon_tz", enable_spread=False)
    )
    n_cells = len(svc.baseline.cell_id)
    n_grid = len(svc.baseline.grid_coords)
    dates = ["2026-11-19", "2026-11-20", "2026-11-21"]

    probs = np.column_stack(
        [
            np.full(n_cells, 0.002, dtype=np.float32),
            np.full(n_cells, 0.018, dtype=np.float32),
            np.full(n_cells, 0.001, dtype=np.float32),
        ]
    )
    stability = np.full((n_cells, 3), 0.9, dtype=np.float16)
    zeros_gd = np.zeros((n_grid, 3), dtype=np.float32)
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

    # 22:40 ART on 2026-11-19 is 01:40 UTC on 2026-11-20: must save 2026-11-19 and NOT lock 2026-11-20.
    late_night_cached = CachedForecast(
        generated_at="2026-11-20T01:40:00+00:00",
        expires_at=9999999.0,
        dates=dates,
        probs=probs,
        stability=stability,
        weather=weather,
    )
    assert svc._maybe_save_snapshot_24h(late_night_cached) is True
    assert svc._snapshot_store is not None
    assert svc._snapshot_store.has_snapshot("2026-11-19") is True
    assert svc._snapshot_store.has_snapshot("2026-11-20") is False
    snap_19 = svc._snapshot_store.load_snapshot_24h("2026-11-19")
    assert np.allclose(snap_19["prob_24h"], 0.002)

    # After 00:00 ART (03:15 UTC on 2026-11-20): must save 2026-11-20 with day 2026-11-20 probabilities.
    next_day_cached = CachedForecast(
        generated_at="2026-11-20T03:15:00+00:00",
        expires_at=9999999.0,
        dates=dates,
        probs=probs,
        stability=stability,
        weather=weather,
    )
    assert svc._maybe_save_snapshot_24h(next_day_cached) is True
    assert svc._snapshot_store.has_snapshot("2026-11-20") is True
    snap_20 = svc._snapshot_store.load_snapshot_24h("2026-11-20")
    assert np.allclose(snap_20["prob_24h"], 0.018)
