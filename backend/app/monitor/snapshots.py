"""Daily 24h forecast snapshot persistence backed by DuckDB."""

from __future__ import annotations

from pathlib import Path
import duckdb
import numpy as np
import pyarrow as pa


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS forecast_snapshots_24h (
    issued_date DATE NOT NULL,
    target_date DATE NOT NULL,
    generated_at VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    cell_id INTEGER NOT NULL,
    prob_24h FLOAT NOT NULL,
    risk_category VARCHAR NOT NULL,
    PRIMARY KEY (issued_date, cell_id)
)
"""


class SnapshotStore:
    """Bounded-memory DuckDB store for daily 24h fire-risk snapshots."""

    def __init__(self, db_path: Path, memory_limit: str = "256MB") -> None:
        self.db_path = Path(db_path)
        self.memory_limit = memory_limit

    def _connect(self) -> duckdb.DuckDBPyConnection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(
            self.db_path.as_posix(),
            config={"memory_limit": self.memory_limit, "threads": 1},
        )
        con.execute(_CREATE_TABLE_SQL)
        return con

    def has_snapshot(self, issued_date: str) -> bool:
        """Return True when a snapshot for `issued_date` (YYYY-MM-DD) already exists."""
        con = self._connect()
        try:
            row = con.execute(
                "SELECT 1 FROM forecast_snapshots_24h WHERE issued_date = CAST(? AS DATE) LIMIT 1",
                [issued_date],
            ).fetchone()
            return row is not None
        finally:
            con.close()

    def save_snapshot_24h(
        self,
        *,
        issued_date: str,
        target_date: str,
        generated_at: str,
        model_version: str,
        cell_ids: np.ndarray,
        probs_24h: np.ndarray,
        risk_categories: np.ndarray,
        overwrite: bool = False,
    ) -> bool:
        """Persist 24h cell probabilities for `issued_date`; returns False if already present."""
        n = len(cell_ids)
        if len(probs_24h) != n or len(risk_categories) != n:
            raise ValueError(
                f"Mismatched array lengths: cell_ids={n}, probs_24h={len(probs_24h)}, "
                f"risk_categories={len(risk_categories)}"
            )
        if n == 0:
            raise ValueError("Cannot save an empty snapshot (length 0)")

        con = self._connect()
        try:
            exists = (
                con.execute(
                    "SELECT 1 FROM forecast_snapshots_24h WHERE issued_date = CAST(? AS DATE) LIMIT 1",
                    [issued_date],
                ).fetchone()
                is not None
            )
            if exists and not overwrite:
                return False

            arrow_tbl = pa.table(
                {
                    "cell_id": np.asarray(cell_ids, dtype=np.int32),
                    "prob_24h": np.asarray(probs_24h, dtype=np.float32),
                    "risk_category": np.asarray(risk_categories, dtype=str),
                }
            )
            con.register("snapshot_batch", arrow_tbl)
            con.begin()
            try:
                if exists:
                    con.execute(
                        "DELETE FROM forecast_snapshots_24h WHERE issued_date = CAST(? AS DATE)",
                        [issued_date],
                    )
                con.execute(
                    """
                    INSERT INTO forecast_snapshots_24h (
                        issued_date, target_date, generated_at, model_version,
                        cell_id, prob_24h, risk_category
                    )
                    SELECT
                        CAST(? AS DATE),
                        CAST(? AS DATE),
                        ?,
                        ?,
                        cell_id,
                        prob_24h,
                        risk_category
                    FROM snapshot_batch
                    """,
                    [issued_date, target_date, generated_at, model_version],
                )
                con.commit()
            except Exception:
                con.rollback()
                raise
            return True
        finally:
            con.close()

    def load_snapshot_24h(self, issued_date: str) -> dict[str, np.ndarray]:
        """Load persisted 24h snapshot arrays ordered by `cell_id`."""
        con = self._connect()
        try:
            return con.execute(
                """
                SELECT cell_id, prob_24h, risk_category
                FROM forecast_snapshots_24h
                WHERE issued_date = CAST(? AS DATE)
                ORDER BY cell_id
                """,
                [issued_date],
            ).fetchnumpy()
        finally:
            con.close()
