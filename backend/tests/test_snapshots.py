"""Tests for 24h forecast snapshot persistence (Slice 1)."""

from pathlib import Path
import numpy as np
import pytest

from app.monitor.snapshots import SnapshotStore


def test_save_snapshot_24h_is_idempotent_and_persists_all_cells(tmp_path: Path):
    db_path = tmp_path / "monitor.duckdb"
    store = SnapshotStore(db_path=db_path, memory_limit="128MB")

    cell_ids = np.array([101, 102, 103, 104], dtype=np.int32)
    probs = np.array([0.001, 0.005, 0.020, 0.080], dtype=np.float32)
    categories = np.array(["Bajo", "Moderado", "Alto", "Extremo"])

    saved_first = store.save_snapshot_24h(
        issued_date="2026-11-18",
        target_date="2026-11-18",
        generated_at="2026-11-18T12:00:00+00:00",
        model_version="lgbm-risk-24h-v2",
        cell_ids=cell_ids,
        probs_24h=probs,
        risk_categories=categories,
    )
    assert saved_first is True
    assert store.has_snapshot("2026-11-18") is True

    # Second call on same issued_date is a no-op unless overwrite=True
    saved_second = store.save_snapshot_24h(
        issued_date="2026-11-18",
        target_date="2026-11-18",
        generated_at="2026-11-18T15:00:00+00:00",
        model_version="lgbm-risk-24h-v2",
        cell_ids=cell_ids,
        probs_24h=np.zeros(4, dtype=np.float32),
        risk_categories=np.array(["Bajo"] * 4),
    )
    assert saved_second is False

    rows = store.load_snapshot_24h("2026-11-18")
    assert len(rows["cell_id"]) == 4
    assert rows["cell_id"].tolist() == [101, 102, 103, 104]
    assert np.allclose(rows["prob_24h"], probs, atol=1e-6)
    assert rows["risk_category"].tolist() == ["Bajo", "Moderado", "Alto", "Extremo"]


def test_save_snapshot_24h_rejects_mismatched_lengths(tmp_path: Path):
    store = SnapshotStore(db_path=tmp_path / "monitor.duckdb", memory_limit="128MB")
    with pytest.raises(ValueError, match="length"):
        store.save_snapshot_24h(
            issued_date="2026-11-18",
            target_date="2026-11-18",
            generated_at="2026-11-18T12:00:00+00:00",
            model_version="lgbm-risk-24h-v2",
            cell_ids=np.array([1, 2], dtype=np.int32),
            probs_24h=np.array([0.1], dtype=np.float32),
            risk_categories=np.array(["Alto", "Bajo"]),
        )


def test_forecast_service_maybe_save_snapshot_24h(tmp_path: Path):
    from app.config import Settings
    from app.service import CachedForecast, ForecastService

    settings = Settings(
        monitor_dir=tmp_path / "monitor_data",
        enable_monitor_snapshots=True,
        enable_spread=False,
    )
    service = ForecastService(settings)
    n_cells = len(service.baseline.cell_id)
    probs = np.full((n_cells, 2), 0.015, dtype=np.float32)
    stability = np.ones((n_cells, 2), dtype=np.float16)
    cached = CachedForecast(
        generated_at="2026-11-18T14:00:00+00:00",
        expires_at=9999999.0,
        dates=["2026-11-18", "2026-11-19"],
        probs=probs,
        stability=stability,
        weather=None,  # type: ignore[arg-type]
    )

    assert service._maybe_save_snapshot_24h(cached) is True
    assert service._maybe_save_snapshot_24h(cached) is False

    loaded = service._snapshot_store.load_snapshot_24h("2026-11-18")  # type: ignore[union-attr]
    assert len(loaded["cell_id"]) == n_cells
    assert np.allclose(loaded["prob_24h"], 0.015, atol=1e-6)
    assert loaded["risk_category"][0] == "Alto"
