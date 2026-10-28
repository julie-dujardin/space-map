"""A small registry with real Metadata, Point source, Binary orbit, System and
planets tables, written directly in the layout of `extrasolar.registry`."""

import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar import ids, sky
from space_map_data.extrasolar.exoplanets.table import SCHEMA as PLANETS_TABLE
from space_map_data.extrasolar.registry import (
    ALIAS,
    IDS,
    LIVE,
    MERGES,
    MERGES_FILE,
    PLANETS,
    RETIRED,
    ingest_name,
    sort_by_cell,
)
from space_map_data.extrasolar.store import region_file
from space_map_data.extrasolar.tables import (
    BINARY_ORBIT,
    METADATA,
    POINT_SOURCE,
    SYSTEM,
    SYSTEM_TABLE,
)
from space_map_data.utils.files import write_parquet

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
    simbad: bool = False,
    distance: float | None = None,
) -> dict:
    """A Point source row. `simbad` adds SIMBAD photometry, with `g` as its
    G. A row without `gaia` takes its astrometry from SIMBAD when `simbad`,
    else it is a Hipparcos-only star. `distance` fills the distance group."""
    if gaia:
        epoch, astrometry = 2016.0, "gaia-dr3"
    elif simbad:
        epoch, astrometry = 2000.0, "simbad"
    else:
        epoch, astrometry = 1991.25, "hipparcos-2007"
    row: dict = {
        "ra": ra,
        "dec": dec,
        "parallax": parallax,
        "parallax_error": parallax / snr,
        "pmra": 100.0,
        "pmdec": -50.0,
        "epoch": epoch,
        "astrometry_source": astrometry,
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
    if hipparcos or not (gaia or simbad):
        row |= {
            "hp_mag": 6.0,
            "v_mag": 5.9,
            "b_v": 0.6,
            "v_i": v_i,
            "hipparcos_photometry_source": "hipparcos-2007",
        }
    if simbad:
        row |= {
            "simbad_b_mag": 9.0,
            "simbad_v_mag": 8.4,
            "simbad_g_mag": g,
            "simbad_sp_type": "K0V",
            "simbad_photometry_source": "simbad",
        }
    if distance is not None:
        row |= {
            "distance": distance,
            "distance_lower": 0.9 * distance,
            "distance_upper": 1.1 * distance,
            "distance_method": "cluster",
            "distance_source": "hunt-reffert-2024",
        }
    row["_name"] = name
    return row


def planet(host: int, number: int, system: int | None = None, **values) -> dict:
    """A planets table row of star index `host`, around star index `system`
    (the host by default), with a 10-day circular orbit unless `values` say
    otherwise."""
    row: dict = {
        "_host": host,
        "_system": host if system is None else system,
        "number": number,
        "name": f"Planet {host} {number}",
        "name_source": "nasa-exoplanet-archive",
        "designation": f"Planet {host} {number}",
        "letter": "b",
        "aliases": [f"Planet {host} {number}"],
        "cross_ids": [
            {
                "catalogue": "nasa-exoplanet-archive",
                "release": "pscomppars",
                "catalogue_id": f"3.{host}{number}",
            }
        ],
        "class": "planet",
        "class_basis": "true mass",
        "status": "confirmed",
        "status_source": "nasa-exoplanet-archive",
        "discovery_method": "Radial Velocity",
        "discovery_year": 2000,
        "discovery_source": "nasa-exoplanet-archive",
        "period": 10.0,
        "semi_major_axis": 0.09,
        "eccentricity": 0.0,
        "inclination": 90.0,
        "omega": 90.0,
        "periastron_time": 2451545.0,
        "orbit_source": "nasa-exoplanet-archive",
        "node": 30.0,
        "mass": 1.0,
        "mass_kind": "true",
        "mass_source": "nasa-exoplanet-archive",
        "assumed": ["node", "periastron_time"],
        "estimated": [],
        "computed": [],
        "limits": [],
    }
    return row | values


@dataclass(frozen=True)
class Node:
    """A node of a star system. A member is ("star", star index, letter),
    ("system", node index, letter) or ("entry", None, letter). A point node
    holds the star `point`, whose ID it keeps, and its members are entries.
    A resolved node gets an ID of table 3 in the cell of its primary star."""

    members: tuple[tuple[str, int | None, str], ...]
    point: int | None = None
    label: str = "AB"
    name: str | None = None
    qid: str | None = None


@dataclass
class Built:
    root: Path
    ids: list[int]
    aliases: dict[int, int] = field(default_factory=dict)
    retired: list[int] = field(default_factory=list)
    # The ID of each node of `systems`.
    nodes: list[int] = field(default_factory=list)


def _primary(nodes: Sequence[Node], at: int) -> int:
    """The star index of a node's primary: its point, else its first member's."""
    node = nodes[at]
    if node.point is not None:
        return node.point
    kind, index, _ = node.members[0]
    assert index is not None
    return index if kind == "star" else _primary(nodes, index)


def _system_rows(
    nodes: Sequence[Node], stars: list[dict], minted: list[int]
) -> tuple[list[int], list[dict], dict[int, dict]]:
    """The ID and System row of each node, and the Metadata values of the IDs
    that the trees hold: `system`, and for a node its class and mask bit."""
    serials: dict[int, int] = defaultdict(int)
    node_ids = []
    for at, node in enumerate(nodes):
        if node.point is not None:
            node_ids.append(minted[node.point])
            continue
        primary = stars[_primary(nodes, at)]
        cell = _cell(primary["ra"], primary["dec"])
        node_ids.append(ids.encode(serials[cell], SYSTEM_TABLE, cell))
        serials[cell] += 1
    parent: dict[int, int] = {}
    for at, node in enumerate(nodes):
        for kind, index, _ in node.members:
            if kind == "system":
                assert index is not None
                parent[index] = at

    def root(at: int) -> int:
        return root(parent[at]) if at in parent else at

    def depth(at: int) -> int:
        return depth(parent[at]) + 1 if at in parent else 0

    def count(at: int) -> int:
        return sum(
            count(index) if kind == "system" and index is not None else 1
            for kind, index, _ in nodes[at].members
        )

    meta: dict[int, dict] = {}
    rows: list[dict[str, Any]] = []
    for at, node in enumerate(nodes):
        primary = stars[_primary(nodes, at)]
        top = node_ids[root(at)]
        members = []
        for kind, index, letter in node.members:
            if kind == "star":
                assert index is not None
                member = minted[index]
                meta[member] = {"system": top}
            elif kind == "system":
                assert index is not None
                member = node_ids[index]
            else:
                member = None
            members.append(
                {
                    "id": member,
                    "kind": kind,
                    "letter": letter,
                    "source": "msc",
                    "separation": 2.5,
                    "known": ["visual"],
                }
            )
        stars_below = count(at)
        meta[node_ids[at]] = {
            "system": None if at not in parent else top,
            "class": "binary star" if stars_below == 2 else "multiple star",
        }
        rows.append(
            {
                "id": node_ids[at],
                "point": node.point is not None,
                "depth": depth(at),
                "stars": stars_below,
                "ra": primary["ra"],
                "dec": primary["dec"],
                "label": node.label,
                "evidence": "msc" if node.point is not None else None,
                "sources": ["msc"],
                "tree_source": "star-systems",
                "parent": node_ids[parent[at]] if at in parent else None,
                "root": top,
                "primary": minted[_primary(nodes, at)],
                "members": members,
            }
        )
    for at, row in enumerate(rows):
        if at in parent:
            row["tree"] = None
            continue
        row["tree"] = sorted(
            (
                {
                    "id": other["id"],
                    "parent": other["parent"],
                    "point": other["point"],
                    "stars": other["stars"],
                    "class": meta[other["id"]]["class"],
                    "label": other["label"],
                }
                for other in rows
                if other["root"] == row["id"]
            ),
            key=lambda entry: entry["id"],
        )
    return node_ids, rows, meta


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
    orbits: Mapping[int, dict] | None = None,
    planets: Sequence[dict] = (),
    planet_status: Sequence[tuple[int, int, str, tuple[int, int] | None]] = (),
    systems: Sequence[Node] = (),
    tamper: Callable[[list[dict], list[dict]], None] | None = None,
) -> Built:
    """Write a registry of one ingest. `aliases` are (loser, survivor) pairs of
    star indexes: the loser's ID is an alias and has no data rows. A `retired`
    star index has a retired record and no rows. A `missing` star index takes
    its serial but has no record and no rows, as in a registry rolled back.
    `extra_table_ids` get rows but no registry record. `orbits` gives the
    Binary orbit row of a star index; without it the registry has no table 2.
    `planets` are rows of `planet`, each with a link record of its first
    cross-id in the Planets part; `planet_status` are (star index, number,
    status, alias target) status records there, the target a (star index,
    number). `systems` are the nodes of star systems, with System rows, and
    Metadata rows for the resolved ones. `tamper` may change the System rows
    and the Metadata rows before they are written."""
    serials: dict[int, int] = defaultdict(int)
    minted = []
    for row in stars:
        cell = _cell(row["ra"], row["dec"])
        minted.append(ids.encode(serials[cell], 1, cell))
        serials[cell] += 1

    node_ids, system_rows, system_meta = _system_rows(systems, stars, minted)
    records = []
    for index, id_ in enumerate(minted):
        if index not in missing:
            records.append((id_, RETIRED if index in retired else LIVE, None))
    records += [(row["id"], LIVE, None) for row in system_rows if not row["point"]]
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
    orbit_of = {minted[i]: values for i, values in (orbits or {}).items()}
    orbit = {f.name: [] for f in BINARY_ORBIT.schema}
    for id_, _ in data:
        if id_ in orbit_of:
            for name, column in orbit.items():
                column.append(id_ if name == "id" else orbit_of[id_].get(name))
    orbit_table = pa.table(orbit, schema=BINARY_ORBIT.schema)
    meta_rows: list[dict[str, Any]] = []
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
                ]
                + (
                    [{"catalogue": "wikidata", "release": "qid", "catalogue_id": qid}]
                    if (qid := row.get("_qid"))
                    else []
                ),
                "mask": 2 | (4 if id_ in orbit_of else 0),
                "object": bool(row.get("_qid")),
                "alias_target": None,
            }
        )
    for row in meta_rows:
        values = system_meta.get(row["id"], {})
        row["system"] = values.get("system")
        if "class" in values:
            row |= {"class": values["class"], "class_source": "star-systems"}
            row["mask"] |= 1 << SYSTEM_TABLE
    for at, (node, row) in enumerate(zip(systems, system_rows)):
        if node.point is not None:
            continue
        meta_rows.append(
            {
                "id": row["id"],
                "name": node.name or f"System {at}",
                "name_source": "star-systems",
                "class": system_meta[row["id"]]["class"],
                "class_source": "star-systems",
                "cross_ids": [
                    {
                        "catalogue": "star-system",
                        "release": "msc",
                        "catalogue_id": f"S{at}",
                    }
                ]
                + (
                    [{"catalogue": "wikidata", "release": "qid", "catalogue_id": qid}]
                    if (qid := node.qid)
                    else []
                ),
                "mask": 1 << SYSTEM_TABLE,
                "object": node.qid is not None,
                "alias_target": None,
                "system": system_meta[row["id"]]["system"],
            }
        )
    for loser, target in alias_map.items():
        meta_rows.append(
            {"id": loser, "mask": 0, "alias_target": target}
            | {name: None for name in ("name", "name_source", "class", "class_source")}
            | {"cross_ids": None, "object": None}
        )
    if tamper is not None:
        tamper(system_rows, meta_rows)
    meta_table = pa.Table.from_pylist(meta_rows, schema=METADATA.schema)
    tables = {"point-source": point_table, "metadata": meta_table}
    if orbits is not None:
        tables["binary-orbit"] = orbit_table
    if systems:
        tables["system"] = pa.Table.from_pylist(
            [
                {name: row.get(name) for name in SYSTEM.schema.names}
                for row in system_rows
            ],
            schema=SYSTEM.schema,
        )
    for slug, table in tables.items():
        for region, part in by_region(table).items():
            write_parquet(part, region_file(root / "tables" / slug / "000001", region))

    versions = dict.fromkeys(tables, 1)
    if planets:
        rows = []
        for row in planets:
            values = {k: v for k, v in row.items() if not k.startswith("_")}
            values |= {"host": minted[row["_host"]], "system": minted[row["_system"]]}
            rows.append(values)
        table = pa.Table.from_pylist(
            [{name: r.get(name) for name in PLANETS_TABLE.names} for r in rows],
            schema=PLANETS_TABLE,
        )
        region = sky.region_of(table["host"].to_numpy() & ids.CELL_MASK)
        for r in np.unique(region):
            part = table.filter(pa.array(region == r))
            write_parquet(part, region_file(root / "tables" / "planets" / "000001", r))
        versions["planets"] = 1
    part = [
        {
            "host": minted[row["_host"]],
            "number": row["number"],
            "status": LIVE,
            **row["cross_ids"][0],
            "ingest": 1,
        }
        for row in planets
    ]
    part += [
        {
            "host": minted[host],
            "number": number,
            "status": status,
            "alias_host": None if target is None else minted[target[0]],
            "alias_target": None if target is None else target[1],
            "ingest": 1,
        }
        for host, number, status, target in planet_status
    ]
    if part:
        records = pa.Table.from_pylist(part, schema=PLANETS)
        region = sky.region_of(records["host"].to_numpy() & ids.CELL_MASK)
        for r in np.unique(region):
            piece = records.filter(pa.array(region == r))
            write_parquet(piece, region_file(segment / "planets", r))

    entry = {
        "ingest": 1,
        "date": "2026-10-23T00:00:00+00:00",
        "commit": "test",
        "dirty": False,
        "complete": True,
        "sources": [
            {
                "source": "wikidata",
                "catalogue": "wikidata",
                "release": "qid",
                "permanent": False,
                "complete": True,
            }
        ],
        "counts": {"merged": len(alias_map), "live": len(data)},
        "reviewed": "2026-10-23T00:00:00+00:00" if reviewed or not alias_map else None,
    }
    manifest = {
        "host": HOST,
        "created": entry["date"],
        "region_level": sky.REGION_LEVEL,
        "ingests": [entry],
        "tables": versions,
    }
    (root / "registry").mkdir(parents=True, exist_ok=True)
    (root / "registry" / "manifest.json").write_text(json.dumps(manifest))
    return Built(root, minted, alias_map, [minted[i] for i in retired], node_ids)


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
