"""A small registry with real Point source and Metadata tables, written
directly in the layout of `extrasolar.registry`."""

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar import ids, sky
from space_map_data.extrasolar.registry import (
    ALIAS,
    IDS,
    LIVE,
    MERGES,
    MERGES_FILE,
    RETIRED,
    ingest_name,
    sort_by_cell,
)
from space_map_data.extrasolar.store import region_file, write_parquet
from space_map_data.extrasolar.tables import METADATA, POINT_SOURCE

HOST = "test-host"


def star(
    ra: float,
    dec: float,
    parallax: float = 10.0,
    g: float | None = 8.0,
    *,
    hipparcos: bool = False,
    gaia: bool = True,
    fidelity: float | None = 1.0,
    snr: float = 50.0,
    v_i: float | None = None,
    name: str | None = None,
) -> dict:
    """A Point source row; a row without `gaia` is a Hipparcos-only star."""
    row: dict = {
        "ra": ra,
        "dec": dec,
        "parallax": parallax,
        "parallax_error": parallax / snr,
        "pmra": 100.0,
        "pmdec": -50.0,
        "epoch": 2016.0 if gaia else 1991.25,
        "astrometry_source": "gaia-dr3" if gaia else "hipparcos-2007",
    }
    if gaia:
        row |= {
            "phot_g_mean_mag": g,
            "phot_bp_mean_mag": None if g is None else g + 0.5,
            "phot_rp_mean_mag": None if g is None else g - 0.4,
            "gaia_photometry_source": "gaia-dr3",
            "fidelity_v2": fidelity,
            "fidelity_source": "gaia-dr3",
        }
    if hipparcos or not gaia:
        row |= {
            "hp_mag": 6.0,
            "v_mag": 5.9,
            "b_v": 0.6,
            "v_i": v_i,
            "hipparcos_photometry_source": "hipparcos-2007",
        }
    row["_name"] = name
    return row


@dataclass
class Built:
    root: Path
    ids: list[int]
    aliases: dict[int, int] = field(default_factory=dict)
    retired: list[int] = field(default_factory=list)


def _cell(ra: float, dec: float) -> int:
    return int(sky.cells(np.array([ra]), np.array([dec]))[0])


def write_registry(
    root: Path,
    stars: list[dict],
    aliases: Sequence[tuple[int, int]] = (),
    retired: Sequence[int] = (),
    reviewed: bool = True,
    extra_table_ids: Sequence[int] = (),
    missing: Sequence[int] = (),
) -> Built:
    """Write a registry of one ingest. `aliases` are (loser, survivor) pairs of
    star indexes: the loser's ID is an alias and has no data rows. A `retired`
    star index has a retired record and no rows. A `missing` star index takes
    its serial but has no record and no rows, as in a registry rolled back.
    `extra_table_ids` get rows but no registry record."""
    serials: dict[int, int] = defaultdict(int)
    minted = []
    for row in stars:
        cell = _cell(row["ra"], row["dec"])
        minted.append(ids.encode(serials[cell], 1, cell))
        serials[cell] += 1

    records = []
    for index, id_ in enumerate(minted):
        if index not in missing:
            records.append((id_, RETIRED if index in retired else LIVE, None))
    alias_map = {}
    for loser, survivor in aliases:
        alias_map[minted[loser]] = minted[survivor]
    for loser, target in alias_map.items():
        records = [r for r in records if r[0] != loser]
        records.append((loser, ALIAS, target))

    def by_region(table: pa.Table) -> dict[int, pa.Table]:
        region = sky.region_of(table["id"].to_numpy() & ids.CELL_MASK)
        return {
            int(r): sort_by_cell(table.filter(pa.array(region == r)))
            for r in np.unique(region)
        }

    id_table = pa.table(
        {
            "id": pa.array([r[0] for r in records], pa.int64()),
            "status": [r[1] for r in records],
            "alias_target": pa.array([r[2] for r in records], pa.int64()),
            "ingest": pa.array([1] * len(records), pa.uint32()),
        },
        schema=IDS,
    )
    segment = root / "registry" / "segments" / ingest_name(1)
    for region, part in by_region(id_table).items():
        write_parquet(part, region_file(segment / "ids", region))
    if alias_map:
        write_parquet(
            pa.table(
                {
                    "survivor": list(alias_map.values()),
                    "loser": list(alias_map),
                    "evidence": ["test"] * len(alias_map),
                },
                schema=MERGES,
            ),
            segment / MERGES_FILE,
        )

    data = [
        (minted[i], row)
        for i, row in enumerate(stars)
        if i not in retired and i not in missing and minted[i] not in alias_map
    ]
    data += [(id_, stars[0]) for id_ in extra_table_ids]
    point = {f.name: [] for f in POINT_SOURCE.schema}
    for id_, row in data:
        for name, column in point.items():
            column.append(id_ if name == "id" else row.get(name))
    point_table = pa.table(point, schema=POINT_SOURCE.schema)
    meta_rows = []
    for id_, row in data:
        meta_rows.append(
            {
                "id": id_,
                "name": row["_name"] or f"Star {id_}",
                "name_source": "gaia-dr3",
                "class": "star",
                "class_source": "gaia-dr3",
                "cross_ids": [
                    {
                        "catalogue": "gaia",
                        "release": "dr3",
                        "catalogue_id": row.get("_xid") or str(id_ * 7),
                    }
                ],
                "mask": 2,
                "object": False,
                "alias_target": None,
            }
        )
    for loser, target in alias_map.items():
        meta_rows.append(
            {"id": loser, "mask": 0, "alias_target": target}
            | {name: None for name in ("name", "name_source", "class", "class_source")}
            | {"cross_ids": None, "object": None}
        )
    meta_table = pa.Table.from_pylist(meta_rows, schema=METADATA.schema)
    for slug, table in (("point-source", point_table), ("metadata", meta_table)):
        for region, part in by_region(table).items():
            write_parquet(part, region_file(root / "tables" / slug / "000001", region))

    entry = {
        "ingest": 1,
        "date": "2026-10-23T00:00:00+00:00",
        "commit": "test",
        "dirty": False,
        "complete": True,
        "sources": [],
        "counts": {"merged": len(alias_map), "live": len(data)},
        "reviewed": "2026-10-23T00:00:00+00:00" if reviewed or not alias_map else None,
    }
    manifest = {
        "host": HOST,
        "created": entry["date"],
        "region_level": sky.REGION_LEVEL,
        "ingests": [entry],
        "tables": {"metadata": 1, "point-source": 1},
    }
    (root / "registry").mkdir(parents=True, exist_ok=True)
    (root / "registry" / "manifest.json").write_text(json.dumps(manifest))
    return Built(root, minted, alias_map, [minted[i] for i in retired])


def random_stars(count: int, seed: int = 1, around: tuple[float, float] | None = None):
    """Gaia stars spread over the sky, or within a few degrees of `around`."""
    rng = np.random.default_rng(seed)
    if around is None:
        ra = rng.uniform(0, 360, count)
        dec = np.degrees(np.arcsin(rng.uniform(-1, 1, count)))
    else:
        ra = (around[0] + rng.normal(0, 2, count)) % 360
        dec = np.clip(around[1] + rng.normal(0, 2, count), -89, 89)
    parallax = 10 ** rng.uniform(-0.5, 2.5, count)
    g = rng.uniform(3, 18, count)
    return [
        star(float(a), float(d), float(p), float(m))
        for a, d, p, m in zip(ra, dec, parallax, g)
    ]
