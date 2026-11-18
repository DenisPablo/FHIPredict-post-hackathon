"""Empirical evaluation engine comparing 24h snapshots against VIIRS detections."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import duckdb
import numpy as np

from .firms import ViirsStore
from .snapshots import SnapshotStore


RISK_ORDER = {"Bajo": 0, "Moderado": 1, "Alto": 2, "Extremo": 3}
RISK_CATEGORIES = ("Extremo", "Alto", "Moderado", "Bajo")

_CREATE_EVAL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_eval_metrics (
    target_date DATE NOT NULL,
    issued_date DATE NOT NULL,
    min_frp_mw FLOAT NOT NULL,
    n_cells INTEGER NOT NULL,
    n_positives INTEGER NOT NULL,
    observed_rate FLOAT NOT NULL,
    mean_predicted_prob FLOAT NOT NULL,
    calibration_ratio FLOAT,
    brier_score FLOAT NOT NULL,
    roc_auc FLOAT,
    pr_auc FLOAT,
    hits_count INTEGER NOT NULL,
    misses_count INTEGER NOT NULL,
    false_alarms_count INTEGER NOT NULL,
    category_metrics_json VARCHAR NOT NULL,
    evaluated_at VARCHAR NOT NULL,
    PRIMARY KEY (target_date, issued_date, min_frp_mw)
)
"""


def _roc_auc_numpy(probs: np.ndarray, y_true: np.ndarray) -> float | None:
    n_pos = int(np.sum(y_true))
    n_neg = int(len(y_true) - n_pos)
    if n_pos == 0 or n_neg == 0:
        return None

    order = np.argsort(-probs, kind="mergesort")
    y_sorted = y_true[order]
    p_sorted = probs[order]

    distinct_mask = np.r_[np.diff(p_sorted) != 0, True]
    tps = np.cumsum(y_sorted)[distinct_mask].astype(np.float64)
    fps = np.cumsum(1 - y_sorted)[distinct_mask].astype(np.float64)

    tpr = np.r_[0.0, tps / n_pos]
    fpr = np.r_[0.0, fps / n_neg]
    return float(np.trapezoid(tpr, fpr))


def _pr_auc_numpy(probs: np.ndarray, y_true: np.ndarray) -> float | None:
    n_pos = int(np.sum(y_true))
    if n_pos == 0:
        return None

    order = np.argsort(-probs, kind="mergesort")
    y_sorted = y_true[order]
    p_sorted = probs[order]

    distinct_mask = np.r_[np.diff(p_sorted) != 0, True]
    tps = np.cumsum(y_sorted)[distinct_mask].astype(np.float64)
    fps = np.cumsum(1 - y_sorted)[distinct_mask].astype(np.float64)

    precision = tps / np.maximum(tps + fps, 1.0)
    recall = tps / n_pos
    recall_prev = np.r_[0.0, recall[:-1]]
    return float(np.sum((recall - recall_prev) * precision))


def compute_binary_metrics(
    *,
    probs: np.ndarray,
    y_true: np.ndarray,
    risk_categories: np.ndarray,
) -> dict[str, Any]:
    """Compute calibration, discrimination, and per-category metrics using pure NumPy."""
    p = np.asarray(probs, dtype=np.float64)
    y = np.asarray(y_true, dtype=np.int32)
    cats = np.asarray(risk_categories, dtype=str)

    n_cells = int(len(y))
    n_pos = int(np.sum(y))
    obs_rate = float(n_pos / n_cells) if n_cells > 0 else 0.0
    mean_pred = float(np.mean(p)) if n_cells > 0 else 0.0
    cal_ratio = float(mean_pred / obs_rate) if obs_rate > 0.0 else None
    brier = float(np.mean((p - y) ** 2)) if n_cells > 0 else 0.0

    categories_out: dict[str, dict[str, Any]] = {}
    for cat in RISK_CATEGORIES:
        mask = cats == cat
        count = int(np.sum(mask))
        pos = int(np.sum(y[mask])) if count > 0 else 0
        precision = float(pos / count) if count > 0 else None
        recall = float(pos / n_pos) if n_pos > 0 else None
        lift = float(precision / obs_rate) if (precision is not None and obs_rate > 0.0) else None
        categories_out[cat] = {
            "cells_count": count,
            "positives_count": pos,
            "precision": precision,
            "recall": recall,
            "lift": lift,
        }

    return {
        "n_cells": n_cells,
        "n_positives": n_pos,
        "observed_rate": obs_rate,
        "mean_predicted_prob": mean_pred,
        "calibration_ratio": cal_ratio,
        "brier_score": brier,
        "roc_auc": _roc_auc_numpy(p, y),
        "pr_auc": _pr_auc_numpy(p, y),
        "categories": categories_out,
    }


def classify_cell_outcomes(
    *,
    cell_ids: np.ndarray,
    probs: np.ndarray,
    risk_categories: np.ndarray,
    y_true: np.ndarray,
    min_alert_risk: str = "Moderado",
) -> dict[str, np.ndarray]:
    """Return only actionable cell outcomes (`hit`, `miss`, `false_alarm`), omitting true negatives."""
    min_level = RISK_ORDER[min_alert_risk]
    levels = np.array([RISK_ORDER.get(str(c), 0) for c in risk_categories], dtype=np.int32)
    is_alert = levels >= min_level
    is_pos = np.asarray(y_true, dtype=np.int32) == 1

    keep = is_alert | is_pos
    kept_alerts = is_alert[keep]
    kept_pos = is_pos[keep]

    outcomes = np.where(
        kept_alerts & kept_pos,
        "hit",
        np.where(kept_alerts & ~kept_pos, "false_alarm", "miss"),
    )
    return {
        "cell_id": np.asarray(cell_ids[keep], dtype=np.int32),
        "prob_24h": np.asarray(probs[keep], dtype=np.float32),
        "risk_category": np.asarray(risk_categories[keep], dtype=str),
        "outcome": outcomes,
    }


def build_ground_truth_vector(
    snapshot_cell_ids: np.ndarray,
    viirs_rows: dict[str, np.ndarray],
    *,
    min_detections: int = 1,
    min_frp_mw: float = 10.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Align sparse VIIRS detections onto dense snapshot `cell_id` order."""
    n = len(snapshot_cell_ids)
    det_counts = np.zeros(n, dtype=np.int32)
    frp_sums = np.zeros(n, dtype=np.float32)

    if len(viirs_rows["cell_id"]) > 0:
        idx_map = {int(cid): idx for idx, cid in enumerate(snapshot_cell_ids.tolist())}
        for cid, cnt, frp in zip(
            viirs_rows["cell_id"].tolist(),
            viirs_rows["detections_count"].tolist(),
            viirs_rows["frp_sum"].tolist(),
        ):
            pos = idx_map.get(int(cid))
            if pos is not None:
                det_counts[pos] = int(cnt)
                frp_sums[pos] = float(frp)

    y_true = ((det_counts >= min_detections) & (frp_sums >= min_frp_mw)).astype(np.int32)
    return y_true, det_counts, frp_sums


class EvaluationStore:
    """Bounded-memory DuckDB store for daily empirical evaluation metrics."""

    def __init__(self, db_path: Path, memory_limit: str = "256MB") -> None:
        self.db_path = Path(db_path)
        self.memory_limit = memory_limit

    def _connect(self) -> duckdb.DuckDBPyConnection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(
            self.db_path.as_posix(),
            config={"memory_limit": self.memory_limit, "threads": 1},
        )
        con.execute(_CREATE_EVAL_TABLE_SQL)
        return con

    def save_metrics(self, record: dict[str, Any]) -> None:
        """Upsert one daily evaluation record into `daily_eval_metrics`."""
        con = self._connect()
        try:
            con.begin()
            try:
                con.execute(
                    """
                    DELETE FROM daily_eval_metrics
                    WHERE target_date = CAST(? AS DATE)
                      AND issued_date = CAST(? AS DATE)
                      AND min_frp_mw = ?
                    """,
                    [record["target_date"], record["issued_date"], float(record["min_frp_mw"])],
                )
                con.execute(
                    """
                    INSERT INTO daily_eval_metrics (
                        target_date, issued_date, min_frp_mw, n_cells, n_positives,
                        observed_rate, mean_predicted_prob, calibration_ratio,
                        brier_score, roc_auc, pr_auc,
                        hits_count, misses_count, false_alarms_count,
                        category_metrics_json, evaluated_at
                    )
                    VALUES (
                        CAST(? AS DATE), CAST(? AS DATE), ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?,
                        ?, ?
                    )
                    """,
                    [
                        record["target_date"],
                        record["issued_date"],
                        float(record["min_frp_mw"]),
                        int(record["n_cells"]),
                        int(record["n_positives"]),
                        float(record["observed_rate"]),
                        float(record["mean_predicted_prob"]),
                        record["calibration_ratio"],
                        float(record["brier_score"]),
                        record["roc_auc"],
                        record["pr_auc"],
                        int(record["hits_count"]),
                        int(record["misses_count"]),
                        int(record["false_alarms_count"]),
                        json.dumps(record["categories"]),
                        record["evaluated_at"],
                    ],
                )
                con.commit()
            except Exception:
                con.rollback()
                raise
        finally:
            con.close()

    def list_metrics(self, limit: int = 30) -> list[dict[str, Any]]:
        """Return recent daily evaluation records ordered newest first."""
        con = self._connect()
        try:
            rows = con.execute(
                """
                SELECT
                    CAST(target_date AS VARCHAR),
                    CAST(issued_date AS VARCHAR),
                    min_frp_mw,
                    n_cells,
                    n_positives,
                    observed_rate,
                    mean_predicted_prob,
                    calibration_ratio,
                    brier_score,
                    roc_auc,
                    pr_auc,
                    hits_count,
                    misses_count,
                    false_alarms_count,
                    category_metrics_json,
                    evaluated_at
                FROM daily_eval_metrics
                ORDER BY target_date DESC, issued_date DESC
                LIMIT ?
                """,
                [int(limit)],
            ).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                out.append(
                    {
                        "target_date": r[0],
                        "issued_date": r[1],
                        "min_frp_mw": float(r[2]),
                        "n_cells": int(r[3]),
                        "n_positives": int(r[4]),
                        "observed_rate": float(r[5]),
                        "mean_predicted_prob": float(r[6]),
                        "calibration_ratio": float(r[7]) if r[7] is not None else None,
                        "brier_score": float(r[8]),
                        "roc_auc": float(r[9]) if r[9] is not None else None,
                        "pr_auc": float(r[10]) if r[10] is not None else None,
                        "hits_count": int(r[11]),
                        "misses_count": int(r[12]),
                        "false_alarms_count": int(r[13]),
                        "categories": json.loads(r[14]),
                        "evaluated_at": r[15],
                    }
                )
            return out
        finally:
            con.close()


def evaluate_snapshot_vs_viirs(
    *,
    snap_store: SnapshotStore,
    viirs_store: ViirsStore,
    eval_store: EvaluationStore,
    target_date: str,
    issued_date: str | None = None,
    min_detections: int = 1,
    min_frp_mw: float = 10.0,
    min_alert_risk: str = "Moderado",
) -> dict[str, Any]:
    """Evaluate a persisted 24h snapshot against VIIRS detections and persist metrics."""
    iss = issued_date or target_date
    snap = snap_store.load_snapshot_24h(iss)
    if len(snap["cell_id"]) == 0:
        raise ValueError(f"No 24h snapshot found for issued_date={iss}")

    viirs = viirs_store.load_daily_detections(target_date)
    y_true, _, _ = build_ground_truth_vector(
        snap["cell_id"],
        viirs,
        min_detections=min_detections,
        min_frp_mw=min_frp_mw,
    )
    metrics = compute_binary_metrics(
        probs=snap["prob_24h"],
        y_true=y_true,
        risk_categories=snap["risk_category"],
    )
    outcomes = classify_cell_outcomes(
        cell_ids=snap["cell_id"],
        probs=snap["prob_24h"],
        risk_categories=snap["risk_category"],
        y_true=y_true,
        min_alert_risk=min_alert_risk,
    )
    outcome_arr = outcomes["outcome"]
    record: dict[str, Any] = {
        "target_date": target_date,
        "issued_date": iss,
        "min_frp_mw": float(min_frp_mw),
        **metrics,
        "hits_count": int(np.sum(outcome_arr == "hit")),
        "misses_count": int(np.sum(outcome_arr == "miss")),
        "false_alarms_count": int(np.sum(outcome_arr == "false_alarm")),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    eval_store.save_metrics(record)
    return record
