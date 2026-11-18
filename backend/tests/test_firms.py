"""Tests for NASA FIRMS VIIRS ingestion, spatial cell mapping, and DuckDB storage (Slice 2)."""

from pathlib import Path
import asyncio
import httpx
import numpy as np
import pytest

from app.monitor.firms import (
    CellSpatialIndex,
    ViirsStore,
    aggregate_viirs_by_cell,
    fetch_firms_csv,
    parse_firms_csv,
)


SAMPLE_CSV = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
-31.401,-64.181,340.5,0.4,0.4,2026-11-18,1630,N,VIIRS,n,2.0NRT,295.1,12.4,D
-31.405,-64.185,355.2,0.4,0.4,2026-11-18,1630,N,VIIRS,h,2.0NRT,298.0,25.6,D
-31.402,-64.182,310.0,0.4,0.4,2026-11-18,1630,N,VIIRS,l,2.0NRT,290.0,4.0,D
-10.000,-60.000,350.0,0.4,0.4,2026-11-18,1630,N,VIIRS,h,2.0NRT,295.0,30.0,D
"""


def test_parse_firms_csv_filters_low_confidence():
    rows = parse_firms_csv(SAMPLE_CSV, exclude_low_confidence=True)
    assert len(rows["acq_date"]) == 3
    assert np.allclose(rows["frp"], [12.4, 25.6, 30.0], atol=1e-4)

    all_rows = parse_firms_csv(SAMPLE_CSV, exclude_low_confidence=False)
    assert len(all_rows["acq_date"]) == 4


def test_spatial_index_and_aggregation():
    cell_ids = np.array([10, 20], dtype=np.int32)
    lats = np.array([-31.40, -34.60], dtype=np.float32)
    lons = np.array([-64.18, -58.38], dtype=np.float32)
    index = CellSpatialIndex.from_cells(cell_ids, lats, lons, max_dist_km=6.0)

    parsed = parse_firms_csv(SAMPLE_CSV, exclude_low_confidence=True)
    mapped_cells = index.assign(parsed["latitude"], parsed["longitude"])
    # First two are near cell 10; third (-10, -60) is outside max_dist_km -> -1
    assert mapped_cells.tolist() == [10, 10, -1]

    agg = aggregate_viirs_by_cell(
        acq_dates=parsed["acq_date"],
        cell_ids=mapped_cells,
        frps=parsed["frp"],
    )
    assert agg["acq_date"].tolist() == ["2026-11-18"]
    assert agg["cell_id"].tolist() == [10]
    assert agg["detections_count"].tolist() == [2]
    assert np.allclose(agg["frp_sum"], [38.0], atol=1e-4)
    assert np.allclose(agg["frp_max"], [25.6], atol=1e-4)


def test_viirs_store_persists_and_replaces_by_date_and_source(tmp_path: Path):
    store = ViirsStore(db_path=tmp_path / "monitor.duckdb", memory_limit="128MB")
    n_saved = store.save_daily_detections(
        source="VIIRS_SNPP_NRT",
        acq_dates=np.array(["2026-11-18", "2026-11-18"]),
        cell_ids=np.array([10, 20], dtype=np.int32),
        detections_count=np.array([2, 1], dtype=np.int32),
        frp_sum=np.array([38.0, 11.5], dtype=np.float32),
        frp_max=np.array([25.6, 11.5], dtype=np.float32),
    )
    assert n_saved == 2

    # Re-ingesting same date+source updates cleanly without duplicate PK errors
    n_updated = store.save_daily_detections(
        source="VIIRS_SNPP_NRT",
        acq_dates=np.array(["2026-11-18"]),
        cell_ids=np.array([10], dtype=np.int32),
        detections_count=np.array([3], dtype=np.int32),
        frp_sum=np.array([50.0], dtype=np.float32),
        frp_max=np.array([25.6], dtype=np.float32),
    )
    assert n_updated == 1

    loaded = store.load_daily_detections("2026-11-18")
    assert loaded["cell_id"].tolist() == [10]
    assert loaded["detections_count"].tolist() == [3]
    assert np.allclose(loaded["frp_sum"], [50.0], atol=1e-4)


def test_fetch_firms_csv_requires_key_and_parses_mock_response():
    async def _run():
        with pytest.raises(ValueError, match="FIRMS"):
            await fetch_firms_csv(map_key="", source="VIIRS_SNPP_NRT", bbox="-73.6,-55.2,-53.5,-21.7")

        def handler(request: httpx.Request) -> httpx.Response:
            assert "/test-key/VIIRS_SNPP_NRT/-73.6,-55.2,-53.5,-21.7/1/2026-11-18" in str(request.url)
            return httpx.Response(200, text=SAMPLE_CSV)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            text = await fetch_firms_csv(
                map_key="test-key",
                source="VIIRS_SNPP_NRT",
                bbox="-73.6,-55.2,-53.5,-21.7",
                day_range=1,
                date="2026-11-18",
                client=client,
            )
        assert "bright_ti4" in text

    asyncio.run(_run())
