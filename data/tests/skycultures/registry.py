"""A small registry with IDs and catalogue claims, in the layout of
`extrasolar.registry`."""

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar import ids, sky
from space_map_data.extrasolar.registry import (
    IDS,
    LIVE,
    XIDS,
    ingest_name,
    sort_by_cell,
)
from space_map_data.extrasolar.store import region_file
from space_map_data.utils.files import write_parquet


def write_registry(
    root: Path, stars: list[tuple[float, float, list[tuple[str, str, str]]]]
) -> list[int]:
    """One ingest that minted a live ID for each (ra, dec, claims) star."""
    serials: dict[int, int] = defaultdict(int)
    minted, xids = [], []
    for ra, dec, claims in stars:
        cell = int(sky.cells(np.array([ra]), np.array([dec]))[0])
        id_ = ids.encode(serials[cell], 1, cell)
        serials[cell] += 1
        minted.append(id_)
        xids += [
            (catalogue, release, value, id_) for catalogue, release, value in claims
        ]
    id_table = pa.table(
        {
            "id": pa.array(minted, pa.int64()),
            "status": [LIVE] * len(minted),
            "alias_target": pa.array([None] * len(minted), pa.int64()),
            "ingest": pa.array([1] * len(minted), pa.uint32()),
        },
        schema=IDS,
    )
    xid_table = pa.table(
        {
            "catalogue": [x[0] for x in xids],
            "release": [x[1] for x in xids],
            "catalogue_id": [x[2] for x in xids],
            "id": pa.array([x[3] for x in xids], pa.int64()),
            "link": ["claim"] * len(xids),
            "score": pa.array([None] * len(xids), pa.float32()),
            "ingest": pa.array([1] * len(xids), pa.uint32()),
        },
        schema=XIDS,
    )
    segment = root / "registry" / "segments" / ingest_name(1)
    for part, table in (("ids", id_table), ("xids", xid_table)):
        region = sky.region_of(table["id"].to_numpy() & ids.CELL_MASK)
        for r in np.unique(region):
            rows = sort_by_cell(table.filter(pa.array(region == r)))
            write_parquet(rows, region_file(segment / part, int(r)))
    entry = {
        "ingest": 1,
        "date": "2026-10-24T00:00:00+00:00",
        "commit": "test",
        "dirty": False,
        "complete": True,
        "sources": [],
        "counts": {"merged": 0, "live": len(minted)},
        "reviewed": None,
    }
    manifest = {
        "host": "test-host",
        "created": entry["date"],
        "region_level": sky.REGION_LEVEL,
        "ingests": [entry],
        "tables": {},
    }
    (root / "registry" / "manifest.json").write_text(json.dumps(manifest))
    return minted
