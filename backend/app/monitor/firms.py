"""NASA FIRMS VIIRS ingestion, spatial mapping to 5 km cells, and DuckDB persistence."""

from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
import io
from pathlib import Path
from typing import Any
import duckdb
import httpx
import numpy as np
import pyarrow as pa


_CREATE_VIIRS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS viirs_cell_daily (
    acq_date DATE NOT NULL,
    source VARCHAR NOT NULL,
    cell_id INTEGER NOT NULL,
    detections_count INTEGER NOT NULL,
    frp_sum FLOAT NOT NULL,
    frp_max FLOAT NOT NULL,
    PRIMARY KEY (acq_date, source, cell_id)
)
"""


def parse_firms_csv(csv_text: str, exclude_low_confidence: bool = True) -> dict[str, np.ndarray]:
    """Parse NASA FIRMS VIIRS area CSV into compact NumPy arrays."""
    lats: list[float] = []
    lons: list[float] = []
    frps: list[float] = []
    dates: list[str] = []

    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        conf = (row.get("confidence") or "").strip().lower()
        if exclude_low_confidence and conf == "l":
            continue
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
            frp = float(row.get("frp") or 0.0)
            acq_date = (row.get("acq_date") or "").strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not acq_date:
            continue
        lats.append(lat)
        lons.append(lon)
        frps.append(max(0.0, frp))
        dates.append(acq_date)

    return {
        "latitude": np.asarray(lats, dtype=np.float32),
        "longitude": np.asarray(lons, dtype=np.float32),
        "frp": np.asarray(frps, dtype=np.float32),
        "acq_date": np.asarray(dates, dtype=str),
    }


@dataclass
class CellSpatialIndex:
    """Lightweight bucketed spatial index for mapping hotspots to nearest 5 km `cell_id`."""

    cell_id: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    buckets: dict[tuple[int, int], np.ndarray]
    bin_deg: float
    max_dist_km: float

    @classmethod
    def from_cells(
        cls,
        cell_id: np.ndarray,
        lat_centro: np.ndarray,
        lon_centro: np.ndarray,
        max_dist_km: float = 6.0,
        bin_deg: float = 0.06,
    ) -> CellSpatialIndex:
        lat_bins = np.floor(lat_centro / bin_deg).astype(np.int32)
        lon_bins = np.floor(lon_centro / bin_deg).astype(np.int32)
        grouped: dict[tuple[int, int], list[int]] = defaultdict(list)
        for idx, (blat, blon) in enumerate(zip(lat_bins.tolist(), lon_bins.tolist())):
            grouped[(blat, blon)].append(idx)
        buckets = {k: np.asarray(v, dtype=np.int32) for k, v in grouped.items()}
        return cls(
            cell_id=np.asarray(cell_id, dtype=np.int32),
            lat=np.asarray(lat_centro, dtype=np.float32),
            lon=np.asarray(lon_centro, dtype=np.float32),
            buckets=buckets,
            bin_deg=bin_deg,
            max_dist_km=max_dist_km,
        )

    def assign(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """Return nearest `cell_id` for each `(lat, lon)`, or `-1` if beyond `max_dist_km`."""
        n = len(lats)
        out = np.full(n, -1, dtype=np.int32)
        if n == 0:
            return out

        km_per_deg_lat = 111.195
        max_dist_sq = self.max_dist_km * self.max_dist_km
        lat_bins = np.floor(lats / self.bin_deg).astype(np.int32)
        lon_bins = np.floor(lons / self.bin_deg).astype(np.int32)

        for i in range(n):
            la = float(lats[i])
            lo = float(lons[i])
            blat = int(lat_bins[i])
            blon = int(lon_bins[i])
            cos_lat = float(np.cos(np.radians(la)))

            best_dist_sq = max_dist_sq
            best_cell = -1
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    cand = self.buckets.get((blat + di, blon + dj))
                    if cand is None:
                        continue
                    dlat = (self.lat[cand] - la) * km_per_deg_lat
                    dlon = (self.lon[cand] - lo) * km_per_deg_lat * cos_lat
                    d2 = dlat * dlat + dlon * dlon
                    pos = int(np.argmin(d2))
                    if float(d2[pos]) <= best_dist_sq:
                        best_dist_sq = float(d2[pos])
                        best_cell = int(self.cell_id[cand[pos]])
            out[i] = best_cell
        return out


def aggregate_viirs_by_cell(
    acq_dates: np.ndarray,
    cell_ids: np.ndarray,
    frps: np.ndarray,
) -> dict[str, np.ndarray]:
    """Aggregate mapped VIIRS hotspots by `(acq_date, cell_id)`, ignoring `cell_id == -1`."""
    buckets: dict[tuple[str, int], list[float]] = defaultdict(list)
    for d, cid, frp in zip(acq_dates.tolist(), cell_ids.tolist(), frps.tolist()):
        if cid < 0:
            continue
        buckets[(str(d), int(cid))].append(float(frp))

    if not buckets:
        return {
            "acq_date": np.empty(0, dtype=str),
            "cell_id": np.empty(0, dtype=np.int32),
            "detections_count": np.empty(0, dtype=np.int32),
            "frp_sum": np.empty(0, dtype=np.float32),
            "frp_max": np.empty(0, dtype=np.float32),
        }

    sorted_keys = sorted(buckets.keys())
    out_dates = [k[0] for k in sorted_keys]
    out_cells = [k[1] for k in sorted_keys]
    out_counts = [len(buckets[k]) for k in sorted_keys]
    out_sums = [sum(buckets[k]) for k in sorted_keys]
    out_maxs = [max(buckets[k]) for k in sorted_keys]

    return {
        "acq_date": np.asarray(out_dates, dtype=str),
        "cell_id": np.asarray(out_cells, dtype=np.int32),
        "detections_count": np.asarray(out_counts, dtype=np.int32),
        "frp_sum": np.asarray(out_sums, dtype=np.float32),
        "frp_max": np.asarray(out_maxs, dtype=np.float32),
    }


async def fetch_firms_csv(
    *,
    map_key: str,
    source: str,
    bbox: str,
    day_range: int = 1,
    date: str | None = None,
    base_url: str = "https://firms.modaps.eosdis.nasa.gov/api/area/csv",
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 30.0,
) -> str:
    """Fetch raw CSV from NASA FIRMS area API."""
    if not map_key.strip():
        raise ValueError("FIRMS MAP_KEY is required to fetch VIIRS detections")
    url = f"{base_url.rstrip('/')}/{map_key.strip()}/{source}/{bbox}/{day_range}"
    if date:
        url = f"{url}/{date}"

    if client is not None:
        resp = await client.get(url, timeout=timeout_s)
        resp.raise_for_status()
        return resp.text

    async with httpx.AsyncClient(timeout=timeout_s) as owned:
        resp = await owned.get(url)
        resp.raise_for_status()
        return resp.text


class ViirsStore:
    """Bounded-memory DuckDB store for daily cell-aggregated VIIRS detections."""

    def __init__(self, db_path: Path, memory_limit: str = "256MB") -> None:
        self.db_path = Path(db_path)
        self.memory_limit = memory_limit

    def _connect(self) -> duckdb.DuckDBPyConnection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(
            self.db_path.as_posix(),
            config={"memory_limit": self.memory_limit, "threads": 1},
        )
        con.execute(_CREATE_VIIRS_TABLE_SQL)
        return con

    def save_daily_detections(
        self,
        *,
        source: str,
        acq_dates: np.ndarray,
        cell_ids: np.ndarray,
        detections_count: np.ndarray,
        frp_sum: np.ndarray,
        frp_max: np.ndarray,
    ) -> int:
        """Upsert aggregated VIIRS detections per `(acq_date, source, cell_id)`."""
        n = len(cell_ids)
        if n == 0:
            return 0

        arrow_tbl = pa.table(
            {
                "acq_date": np.asarray(acq_dates, dtype=str),
                "cell_id": np.asarray(cell_ids, dtype=np.int32),
                "detections_count": np.asarray(detections_count, dtype=np.int32),
                "frp_sum": np.asarray(frp_sum, dtype=np.float32),
                "frp_max": np.asarray(frp_max, dtype=np.float32),
            }
        )
        unique_dates = sorted({str(d) for d in acq_dates.tolist()})

        con = self._connect()
        try:
            con.register("viirs_batch", arrow_tbl)
            con.begin()
            try:
                for d in unique_dates:
                    con.execute(
                        "DELETE FROM viirs_cell_daily WHERE acq_date = CAST(? AS DATE) AND source = ?",
                        [d, source],
                    )
                con.execute(
                    """
                    INSERT INTO viirs_cell_daily (
                        acq_date, source, cell_id, detections_count, frp_sum, frp_max
                    )
                    SELECT
                        CAST(acq_date AS DATE),
                        ?,
                        cell_id,
                        detections_count,
                        frp_sum,
                        frp_max
                    FROM viirs_batch
                    """,
                    [source],
                )
                con.commit()
            except Exception:
                con.rollback()
                raise
            return n
        finally:
            con.close()

    def load_daily_detections(self, acq_date: str) -> dict[str, np.ndarray]:
        """Load aggregated detections across all sources for `acq_date`."""
        con = self._connect()
        try:
            return con.execute(
                """
                SELECT
                    cell_id,
                    CAST(SUM(detections_count) AS INTEGER) AS detections_count,
                    CAST(SUM(frp_sum) AS FLOAT) AS frp_sum,
                    CAST(MAX(frp_max) AS FLOAT) AS frp_max
                FROM viirs_cell_daily
                WHERE acq_date = CAST(? AS DATE)
                GROUP BY cell_id
                ORDER BY cell_id
                """,
                [acq_date],
            ).fetchnumpy()
        finally:
            con.close()

    def load_rolling_fire_memory(self, ref_date: str) -> dict[str, Any]:
        """Aggregate 1d, 2d, 7d, and 30d rolling fire memory up to `ref_date` from DuckDB."""
        empty = {
            "covered_days_1d": 0,
            "covered_days_2d": 0,
            "covered_days_7d": 0,
            "covered_days_30d": 0,
            "cell_id": np.empty(0, dtype=np.int32),
            "focos_1d": np.empty(0, dtype=np.float32),
            "focos_2d": np.empty(0, dtype=np.float32),
            "frp_1d": np.empty(0, dtype=np.float32),
            "focos_7d": np.empty(0, dtype=np.float32),
            "focos_30d": np.empty(0, dtype=np.float32),
            "frp_7d": np.empty(0, dtype=np.float32),
            "frp_30d": np.empty(0, dtype=np.float32),
            "days_since_pos": np.empty(0, dtype=np.float32),
        }
        if not self.db_path.exists():
            return empty

        con = self._connect()
        try:
            cov = con.execute(
                """
                SELECT
                    COUNT(DISTINCT CASE WHEN acq_date = CAST(? AS DATE) THEN acq_date END),
                    COUNT(DISTINCT CASE WHEN acq_date >= CAST(? AS DATE) - INTERVAL 1 DAY THEN acq_date END),
                    COUNT(DISTINCT CASE WHEN acq_date >= CAST(? AS DATE) - INTERVAL 6 DAY THEN acq_date END),
                    COUNT(DISTINCT acq_date)
                FROM viirs_cell_daily
                WHERE acq_date BETWEEN CAST(? AS DATE) - INTERVAL 29 DAY AND CAST(? AS DATE)
                """,
                [ref_date, ref_date, ref_date, ref_date, ref_date],
            ).fetchone()
            if cov is None or int(cov[3] or 0) == 0:
                return empty

            rows = con.execute(
                """
                WITH daily_cell AS (
                    SELECT
                        acq_date,
                        cell_id,
                        CAST(SUM(detections_count) AS FLOAT) AS det,
                        CAST(SUM(frp_sum) AS FLOAT) AS frp
                    FROM viirs_cell_daily
                    WHERE acq_date BETWEEN CAST(? AS DATE) - INTERVAL 29 DAY AND CAST(? AS DATE)
                    GROUP BY acq_date, cell_id
                )
                SELECT
                    cell_id,
                    CAST(COALESCE(SUM(CASE WHEN acq_date = CAST(? AS DATE) THEN det ELSE 0 END), 0) AS FLOAT) AS focos_1d,
                    CAST(COALESCE(SUM(CASE WHEN acq_date >= CAST(? AS DATE) - INTERVAL 1 DAY THEN det ELSE 0 END), 0) AS FLOAT) AS focos_2d,
                    CAST(COALESCE(SUM(CASE WHEN acq_date = CAST(? AS DATE) THEN frp ELSE 0 END), 0) AS FLOAT) AS frp_1d,
                    CAST(COALESCE(SUM(CASE WHEN acq_date >= CAST(? AS DATE) - INTERVAL 6 DAY THEN det ELSE 0 END), 0) AS FLOAT) AS focos_7d,
                    CAST(COALESCE(SUM(det), 0) AS FLOAT) AS focos_30d,
                    CAST(COALESCE(SUM(CASE WHEN acq_date >= CAST(? AS DATE) - INTERVAL 6 DAY THEN frp ELSE 0 END), 0) AS FLOAT) AS frp_7d,
                    CAST(COALESCE(SUM(frp), 0) AS FLOAT) AS frp_30d,
                    CAST(COALESCE(
                        DATEDIFF(
                            'day',
                            MAX(CASE WHEN det >= 1.0 AND frp >= 10.0 THEN acq_date END),
                            CAST(? AS DATE) + INTERVAL 1 DAY
                        ),
                        -1
                    ) AS FLOAT) AS days_since_pos
                FROM daily_cell
                GROUP BY cell_id
                ORDER BY cell_id
                """,
                [ref_date, ref_date, ref_date, ref_date, ref_date, ref_date, ref_date, ref_date],
            ).fetchnumpy()
            return {
                "covered_days_1d": int(cov[0] or 0),
                "covered_days_2d": int(cov[1] or 0),
                "covered_days_7d": int(cov[2] or 0),
                "covered_days_30d": int(cov[3] or 0),
                **rows,
            }
        finally:
            con.close()
