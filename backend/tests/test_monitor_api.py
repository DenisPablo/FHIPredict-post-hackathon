"""Tests for empirical monitor FastAPI endpoints (Slice 4)."""

from pathlib import Path
from fastapi.testclient import TestClient
import numpy as np

from app.config import Settings
import app.main as main_module
from app.monitor.firms import ViirsStore
from app.monitor.service import MonitorService
from app.monitor.snapshots import SnapshotStore
from app.service import ForecastService


def test_monitor_metrics_and_comparison_endpoints(tmp_path: Path, monkeypatch):
    settings = Settings(
        monitor_dir=tmp_path / "monitor_data",
        enable_monitor_snapshots=True,
        enable_spread=False,
        firms_map_key="",
    )
    app = main_module.create_app()

    with TestClient(app) as client:
        # Inject isolated monitor service using tmp_path DuckDB
        assert main_module._service is not None
        baseline = main_module._service.baseline
        monitor = MonitorService(settings=settings, baseline=baseline)
        monkeypatch.setattr(main_module, "_monitor", monitor)

        # Empty metrics initially
        resp = client.get("/api/v1/monitor/metrics")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

        # Missing snapshot -> 404
        resp_missing = client.get("/api/v1/monitor/comparison?target_date=2026-11-18")
        assert resp_missing.status_code == 404

        # Seed a snapshot + VIIRS detection using real baseline cell_ids
        cids = baseline.cell_id[:4]
        monitor.snap_store.save_snapshot_24h(
            issued_date="2026-11-18",
            target_date="2026-11-18",
            generated_at="2026-11-18T12:00:00+00:00",
            model_version="lgbm-risk-24h-v2",
            cell_ids=cids,
            probs_24h=np.array([0.08, 0.02, 0.001, 0.001], dtype=np.float32),
            risk_categories=np.array(["Extremo", "Alto", "Bajo", "Bajo"]),
        )
        monitor.viirs_store.save_daily_detections(
            source="VIIRS_SNPP_NRT",
            acq_dates=np.array(["2026-11-18", "2026-11-18"]),
            cell_ids=np.array([cids[0], cids[2]], dtype=np.int32),
            detections_count=np.array([2, 1], dtype=np.int32),
            frp_sum=np.array([25.0, 15.0], dtype=np.float32),
            frp_max=np.array([15.0, 15.0], dtype=np.float32),
        )

        # Run evaluation via helper
        monitor.evaluate_date(target_date="2026-11-18", issued_date="2026-11-18")
        metrics_resp = client.get("/api/v1/monitor/metrics")
        assert metrics_resp.status_code == 200
        items = metrics_resp.json()["items"]
        assert len(items) == 1
        assert items[0]["hits_count"] == 1
        assert items[0]["misses_count"] == 1
        assert items[0]["false_alarms_count"] == 1

        # Comparison GeoJSON omits true negative (cids[3])
        comp_resp = client.get("/api/v1/monitor/comparison?target_date=2026-11-18")
        assert comp_resp.status_code == 200
        geo = comp_resp.json()
        assert geo["type"] == "FeatureCollection"
        assert len(geo["features"]) == 3
        outcomes = {f["properties"]["outcome"] for f in geo["features"]}
        assert outcomes == {"hit", "miss", "false_alarm"}

        # POST /run without FIRMS_MAP_KEY -> 400
        run_resp = client.post("/api/v1/monitor/run")
        assert run_resp.status_code == 400


def test_monitor_run_ingests_and_evaluates(tmp_path: Path, monkeypatch):
    settings = Settings(
        monitor_dir=tmp_path / "monitor_data",
        enable_monitor_snapshots=True,
        enable_spread=False,
        firms_map_key="dummy-key",
        firms_sources=("VIIRS_SNPP_NRT",),
    )
    app = main_module.create_app()

    with TestClient(app) as client:
        assert main_module._service is not None
        baseline = main_module._service.baseline
        monitor = MonitorService(settings=settings, baseline=baseline)
        monkeypatch.setattr(main_module, "_monitor", monitor)

        lat0 = float(baseline.lat_centro[0])
        lon0 = float(baseline.lon_centro[0])
        sample_csv = (
            "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
            f"{lat0},{lon0},345.0,0.4,0.4,2026-11-18,1600,N,VIIRS,h,2.0NRT,295.0,22.0,D\n"
        )

        async def fake_fetch(**kwargs):
            return sample_csv

        monkeypatch.setattr("app.monitor.service.fetch_firms_csv", fake_fetch)

        cids = baseline.cell_id[:2]
        monitor.snap_store.save_snapshot_24h(
            issued_date="2026-11-18",
            target_date="2026-11-18",
            generated_at="2026-11-18T12:00:00+00:00",
            model_version="lgbm-risk-24h-v2",
            cell_ids=cids,
            probs_24h=np.array([0.08, 0.001], dtype=np.float32),
            risk_categories=np.array(["Extremo", "Bajo"]),
        )

        run_resp = client.post("/api/v1/monitor/run?date=2026-11-18")
        assert run_resp.status_code == 202
        body = run_resp.json()
        assert body["status"] == "started"

        # Wait briefly for background task to complete and check status + metrics
        import time

        for _ in range(30):
            st = client.get("/api/v1/monitor/status").json()
            if not st["running"] and st["last_result"] is not None:
                break
            time.sleep(0.05)

        st = client.get("/api/v1/monitor/status").json()
        assert st["running"] is False
        assert st["last_error"] is None
        assert st["last_result"]["ingested_rows"] == 1
        assert "2026-11-18" in st["last_result"]["evaluated_dates"]


def test_monitor_threshold_comparison_endpoint(tmp_path: Path, monkeypatch):
    settings = Settings(
        monitor_dir=tmp_path / "monitor_data",
        enable_monitor_snapshots=True,
        enable_spread=False,
        firms_map_key="",
    )
    app = main_module.create_app()

    with TestClient(app) as client:
        assert main_module._service is not None
        baseline = main_module._service.baseline
        monitor = MonitorService(
            settings=settings,
            baseline=baseline,
            static_risk_cutoffs=main_module._service.predictor.risk_cutoffs,
        )
        monkeypatch.setattr(main_module, "_monitor", monitor)

        n_cells = 500
        cids = baseline.cell_id[:n_cells]
        day_probs = (1e-5 + 0.008 * (np.linspace(0.0, 1.0, n_cells) ** 30)).astype(np.float32)
        monitor.snap_store.save_snapshot_24h(
            issued_date="2026-11-22",
            target_date="2026-11-22",
            generated_at="2026-11-22T12:00:00+00:00",
            model_version="lgbm-risk-24h-v2",
            cell_ids=cids,
            probs_24h=day_probs,
            risk_categories=np.full(n_cells, "Bajo"),
        )
        monitor.viirs_store.save_daily_detections(
            source="VIIRS_SNPP_NRT",
            acq_dates=np.array(["2026-11-22"]),
            cell_ids=np.array([cids[-1]], dtype=np.int32),
            detections_count=np.array([2], dtype=np.int32),
            frp_sum=np.array([25.0], dtype=np.float32),
            frp_max=np.array([15.0], dtype=np.float32),
        )
        monitor.evaluate_date(target_date="2026-11-22", issued_date="2026-11-22")

        resp = client.get("/api/v1/monitor/threshold-comparison?limit=14")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["previous"]["false_alarms_count"] > item["current"]["false_alarms_count"]
        assert item["current"]["hits_count"] == 1
        assert body["summary"]["false_alarm_reduction_pct"] > 0

