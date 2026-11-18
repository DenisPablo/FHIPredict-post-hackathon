"""Tests for empirical evaluation engine (Slice 3)."""

from pathlib import Path
import numpy as np

from app.monitor.evaluator import (
    EvaluationStore,
    classify_cell_outcomes,
    compute_binary_metrics,
    evaluate_snapshot_vs_viirs,
)
from app.monitor.firms import ViirsStore
from app.monitor.snapshots import SnapshotStore


def test_compute_binary_metrics_and_edge_cases():
    probs = np.array([0.90, 0.80, 0.30, 0.20, 0.05, 0.01], dtype=np.float32)
    y_true = np.array([1, 1, 0, 1, 0, 0], dtype=np.int32)
    cats = np.array(["Extremo", "Extremo", "Alto", "Moderado", "Bajo", "Bajo"])

    metrics = compute_binary_metrics(probs=probs, y_true=y_true, risk_categories=cats)
    assert metrics["n_cells"] == 6
    assert metrics["n_positives"] == 3
    assert metrics["roc_auc"] is not None and metrics["roc_auc"] > 0.85
    assert metrics["pr_auc"] is not None and metrics["pr_auc"] > 0.85
    assert 0.0 < metrics["brier_score"] < 0.2
    assert metrics["categories"]["Extremo"]["positives_count"] == 2
    assert metrics["categories"]["Extremo"]["precision"] == 1.0

    # Zero positives should not divide by zero
    zero_metrics = compute_binary_metrics(
        probs=probs,
        y_true=np.zeros(6, dtype=np.int32),
        risk_categories=cats,
    )
    assert zero_metrics["n_positives"] == 0
    assert zero_metrics["roc_auc"] is None
    assert zero_metrics["pr_auc"] is None
    assert zero_metrics["calibration_ratio"] is None


def test_classify_cell_outcomes_filters_true_negatives():
    cell_ids = np.array([1, 2, 3, 4], dtype=np.int32)
    probs = np.array([0.08, 0.02, 0.001, 0.001], dtype=np.float32)
    cats = np.array(["Extremo", "Alto", "Bajo", "Bajo"])
    y_true = np.array([1, 0, 1, 0], dtype=np.int32)

    outcomes = classify_cell_outcomes(
        cell_ids=cell_ids,
        probs=probs,
        risk_categories=cats,
        y_true=y_true,
        min_alert_risk="Moderado",
    )
    # cell 1 -> Hit, cell 2 -> False Alarm, cell 3 -> Miss, cell 4 -> True Negative (omitted)
    assert outcomes["cell_id"].tolist() == [1, 2, 3]
    assert outcomes["outcome"].tolist() == ["hit", "false_alarm", "miss"]


def test_evaluate_snapshot_vs_viirs_end_to_end_and_persists(tmp_path: Path):
    db_path = tmp_path / "monitor.duckdb"
    snap_store = SnapshotStore(db_path=db_path, memory_limit="128MB")
    viirs_store = ViirsStore(db_path=db_path, memory_limit="128MB")
    eval_store = EvaluationStore(db_path=db_path, memory_limit="128MB")

    snap_store.save_snapshot_24h(
        issued_date="2026-11-18",
        target_date="2026-11-18",
        generated_at="2026-11-18T12:00:00+00:00",
        model_version="lgbm-risk-24h-v2",
        cell_ids=np.array([10, 20, 30, 40], dtype=np.int32),
        probs_24h=np.array([0.08, 0.02, 0.004, 0.001], dtype=np.float32),
        risk_categories=np.array(["Extremo", "Alto", "Moderado", "Bajo"]),
    )
    viirs_store.save_daily_detections(
        source="VIIRS_SNPP_NRT",
        acq_dates=np.array(["2026-11-18", "2026-11-18"]),
        cell_ids=np.array([10, 30], dtype=np.int32),
        detections_count=np.array([2, 1], dtype=np.int32),
        frp_sum=np.array([25.0, 5.0], dtype=np.float32),  # cell 30 below default 10 MW cutoff
        frp_max=np.array([15.0, 5.0], dtype=np.float32),
    )

    result = evaluate_snapshot_vs_viirs(
        snap_store=snap_store,
        viirs_store=viirs_store,
        eval_store=eval_store,
        target_date="2026-11-18",
        issued_date="2026-11-18",
        min_frp_mw=10.0,
    )
    assert result["n_cells"] == 4
    assert result["n_positives"] == 1
    assert result["hits_count"] == 1
    assert result["misses_count"] == 0
    assert result["false_alarms_count"] == 2

    history = eval_store.list_metrics(limit=10)
    assert len(history) == 1
    assert history[0]["target_date"] == "2026-11-18"
    assert history[0]["hits_count"] == 1
