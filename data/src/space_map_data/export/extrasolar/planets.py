"""The planets of the extrasolar export: a planet index and one file per system.

The input is the planets table, one row per live planet keyed by its host
and number, with the ID of the star that keys its system. The hosts come
from Metadata and Point source, and their places from the render rows of the
tree build, so a host sits at its point of the render tree.

Files, JSON in gzip:
- planets/index.json.gz: per host, its system, its planet numbers, its place
  and its outer orbit; and every alias number, with the planet it leads to,
  which can be on another host when the old host merged;
- planets/{system}.json.gz: the hosts and the planets of one system, with
  each planet's orbit in the scene's frame (`orbits`) and its catalogue values.

Every file has the token of the section in its `token` field. The token
hashes each file with 16 zeros in that field, as for the sky cultures.

A host or a key is a point with a Point source row, or a resolved star system
with a System row: the host of a circumbinary planet whose pair Gaia resolves,
or the root of a host's system, which keys the system's file. A resolved
system is not drawn as a star. It takes the render position and distance of
its primary point, else of its first member point that the render tree draws,
so that its planets are drawn there.

The checks: every host and system ID is live and has a Metadata row and a
Point source or System row, every host is in one system, a host in a star
system has its root as the key, and every planet of the served index is still
served, or its number is retired or an alias, or its host is no longer live.
"""

import gzip
import hashlib
import json
import logging
import math
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.export.extrasolar import container, orbits, render
from space_map_data.export.extrasolar.container import Written
from space_map_data.export.extrasolar.systems import SYSTEM_BIT
from space_map_data.export.extrasolar.tiles import Problems
from space_map_data.extrasolar.exoplanets import numbering
from space_map_data.extrasolar.exoplanets.ingest import hosts_with_several_systems
from space_map_data.extrasolar.exoplanets.table import SCHEMA, SLUG
from space_map_data.extrasolar.exoplanets.wikidata import planet_qid
from space_map_data.extrasolar.ids import cell_of
from space_map_data.extrasolar.placement import placement
from space_map_data.extrasolar.registry import ALIAS, LIVE, RETIRED, Registry
from space_map_data.extrasolar.sky import region_of
from space_map_data.extrasolar.tables import BINARY_ORBIT, METADATA, SYSTEM

logger = logging.getLogger(__name__)

SECTION = "planets"
INDEX_FILE = f"{SECTION}/index.json.gz"
ZERO_TOKEN = "0" * container.TOKEN_SIZE
EXAMPLES = 10

KEY_COLUMNS = ("host", "number", "system")
TOP_COLUMNS = (
    "name",
    "name_source",
    "designation",
    "letter",
    "aliases",
    "cross_ids",
    "class",
    "class_basis",
    "mass_ratio",
    "status",
)
FLAG_COLUMNS = ("assumed", "estimated", "computed", "limits")
SOURCE_SUFFIX = "_source"
METADATA_COLUMNS = ["id", "name", "name_source", "class", "cross_ids", "system", "mask"]
SYSTEM_COLUMNS = ["id", "ra", "dec", "primary", "members"]
POINT_COLUMNS = [
    "id",
    "ra",
    "dec",
    "epoch",
    "parallax",
    "parallax_error",
    "fidelity_v2",
    "astrometry_source",
    "hipparcos_photometry_source",
    "simbad_photometry_source",
    "distance",
    "distance_lower",
    "distance_upper",
    "distance_source",
    "distance_method",
    "phot_bp_mean_mag",
    "phot_rp_mean_mag",
    "teff_gspphot",
    "radius_gspphot",
    "host_name",
    "host_distance",
    "host_teff",
    "host_radius",
    "host_mass",
    "host_metallicity",
    "host_spectral_type",
    "host_star_source",
]

CREDITS = (
    {
        "name": "NASA Exoplanet Archive, Planetary Systems Composite Parameters",
        "organisation": "NASA Exoplanet Science Institute, Caltech/IPAC",
        "source": "https://exoplanetarchive.ipac.caltech.edu/",
        "attribution": (
            "This research has made use of the NASA Exoplanet Archive, which is"
            " operated by the California Institute of Technology, under contract"
            " with the National Aeronautics and Space Administration under the"
            " Exoplanet Exploration Program."
        ),
        "citation": (
            "NASA Exoplanet Archive, Planetary Systems Composite Parameters,"
            " doi:10.26133/NEA13; Christiansen et al. 2025, Planet. Sci. J.,"
            " doi:10.3847/PSJ/ade3c2"
        ),
    },
    {
        "name": "The Extrasolar Planets Encyclopaedia",
        "organisation": "exoplanet.eu, Observatoire de Paris",
        "source": "https://exoplanet.eu/",
        "license": "CC BY 4.0",
        "citation": "Schneider et al. 2011, A&A 532, A79",
    },
    {
        "name": "Open Exoplanet Catalogue",
        "organisation": "Hanno Rein and contributors",
        "source": "https://github.com/OpenExoplanetCatalogue/open_exoplanet_catalogue",
        "license": "MIT",
        "attribution": "Copyright (C) 2012 Hanno Rein",
        "citation": "Rein 2012, arXiv:1211.7121",
    },
    {
        "name": "NameExoWorlds",
        "organisation": "International Astronomical Union",
        "source": "https://nameexoworlds.iau.org/",
    },
)

type Runner = Callable[[Callable, list, str], list]


def system_path(key: int | str) -> str:
    return f"{SECTION}/{key}.json.gz"


def _finite(value):
    """`value` with a NaN or infinite float as None."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _f32(value) -> float | None:
    """A float32 value as the shortest decimal that reads back to it."""
    if value is None or not math.isfinite(value):
        return None
    return float(str(np.float32(value)))


def read_planets(registry: Registry) -> pa.Table | None:
    """Every row of the planets table, or None with no table."""
    tables = [
        registry.read_table(SLUG, region) for region in registry.table_regions(SLUG)
    ]
    tables = [table for table in tables if table is not None]
    if not tables:
        return None
    return pa.concat_tables(tables).cast(SCHEMA)


@dataclass(frozen=True)
class HostJob:
    registry: Registry
    region: int
    ids: tuple[int, ...]
    scratch: Path


@dataclass
class HostRows:
    hosts: dict[int, dict] = field(default_factory=dict)
    # The root of the star system of each ID that is in one.
    roots: dict[int, int] = field(default_factory=dict)
    # The points whose place each resolved system takes, first choice first.
    places: dict[int, list[int]] = field(default_factory=dict)
    # The rows the checks refuse, by kind.
    problems: dict[str, list[int]] = field(default_factory=dict)


@dataclass
class Places:
    """The Point source rows of some IDs, and how the render tree places them."""

    points: dict[int, dict] = field(default_factory=dict)
    placed: dict[int, str | None] = field(default_factory=dict)
    distances: dict[int, float | None] = field(default_factory=dict)
    positions: dict[int, list[float]] = field(default_factory=dict)


def _host(
    meta: dict, point: dict, placed: str | None, distance: float | None, position
) -> dict:
    """The host record of a system file, before its planets. `distance` is
    the render row's, from `render.star_distance`."""
    catalogue = point["host_star_source"]
    teff, teff_source = _f32(point["host_teff"]), catalogue
    if teff is None:
        teff, teff_source = _f32(point["teff_gspphot"]), "gaia-dr3"
    radius, radius_source = _f32(point["host_radius"]), catalogue
    if radius is None:
        radius, radius_source = _f32(point["radius_gspphot"]), "gaia-dr3"
    bp, rp = point["phot_bp_mean_mag"], point["phot_rp_mean_mag"]
    return {
        "id": meta["id"],
        "name": meta["name"],
        "name_source": meta["name_source"],
        "class": meta["class"],
        "cross_ids": meta["cross_ids"] or [],
        "placement": placed,
        "position": position,
        "distance": distance,
        "ra": point["ra"],
        "dec": point["dec"],
        "epoch": _f32(point["epoch"]),
        "teff": teff,
        "teff_source": teff_source if teff is not None else None,
        "radius": radius,
        "radius_source": radius_source if radius is not None else None,
        "mass": _f32(point["host_mass"]),
        "metallicity": _f32(point["host_metallicity"]),
        "spectral_type": point["host_spectral_type"],
        "bp_rp": _f32(bp - rp) if bp is not None and rp is not None else None,
        "catalogue": catalogue,
        "catalogue_name": point["host_name"],
    }


def _system_host(meta: dict, node: dict) -> dict:
    """The host record of a resolved star system: the fields of a star's
    record, of a point with no values. It is not drawn as a star, and the
    values of its stars stay in their own records. `build` gives it the
    place of one of its points."""
    record = _host(meta, dict.fromkeys(POINT_COLUMNS), None, None, None)
    return record | {"ra": node["ra"], "dec": node["dec"], "epoch": render.EPOCH}


def _places(job: HostJob) -> Places:
    """The Point source rows of the job's IDs, and the place of each that the
    render tree draws."""
    wanted = pa.array(job.ids, pa.int64())
    out = Places()
    point_table = job.registry.read_table("point-source", job.region, POINT_COLUMNS)
    if point_table is not None:
        point_table = point_table.filter(pc.is_in(point_table["id"], wanted))
        orbit_table = job.registry.read_table(
            BINARY_ORBIT.slug, job.region, list(render.ORBIT_COLUMNS)
        )
        point_table = render.with_orbit_parallax(point_table, orbit_table)
        where = placement(point_table)
        distance, orbit = render.star_distance(point_table, where)
        for at, row in enumerate(point_table.to_pylist()):
            out.points[row["id"]] = row
            # An orbit parallax measures the distance as a parallax does.
            if where.by_parallax[at] or (orbit[at] and not where.by_suspect[at]):
                label = render.PARALLAX
            elif where.by_suspect[at]:
                label = render.SUSPECT_PARALLAX
            elif where.by_group[at]:
                label = row["distance_source"]
            elif where.by_catalogue[at]:
                label = render.CATALOGUE_DISTANCE
            else:
                continue
            out.placed[row["id"]] = label
            parsecs = float(distance[at])
            # A parallax distance is a quotient. The other distances are float32.
            measured = label in (render.PARALLAX, render.SUSPECT_PARALLAX)
            out.distances[row["id"]] = parsecs if measured else _f32(parsecs)
    ids_file = render.scratch_file(job.scratch, job.region, "id")
    if ids_file.exists():
        tree_ids = np.load(ids_file)
        hit = np.flatnonzero(np.isin(tree_ids, np.array(job.ids, np.int64)))
        if hit.size:
            xyz = [
                np.load(render.scratch_file(job.scratch, job.region, axis))[hit]
                for axis in "xyz"
            ]
            for at, id_ in enumerate(tree_ids[hit].tolist()):
                out.positions[id_] = [float(v[at]) for v in xyz]
    return out


def host_rows(job: HostJob) -> HostRows:
    """The host records of one region, with the place each has in the tree."""
    wanted = pa.array(job.ids, pa.int64())
    out = HostRows()
    states = job.registry.id_states([job.region])
    live = states.has_status(np.array(job.ids, np.int64), LIVE)
    if not live.all():
        out.problems["not live"] = [i for i, ok in zip(job.ids, live) if not ok]

    def rows(slug: str, columns: list[str]) -> dict[int, dict]:
        table = job.registry.read_table(slug, job.region, columns)
        if table is None:
            return {}
        table = table.filter(pc.is_in(table["id"], wanted))
        return {row["id"]: row for row in table.to_pylist()}

    metadata = rows(METADATA.slug, METADATA_COLUMNS)
    places = _places(job)
    nodes = rows(SYSTEM.slug, SYSTEM_COLUMNS)
    for id_ in job.ids:
        meta = metadata.get(id_)
        if meta is None:
            out.problems.setdefault("no Metadata row", []).append(id_)
            continue
        # A root has no `system`.
        if meta["system"] is not None or meta["mask"] & SYSTEM_BIT:
            out.roots[id_] = meta["system"] or id_
        if id_ in places.points:
            out.hosts[id_] = _host(
                meta,
                places.points[id_],
                places.placed.get(id_),
                places.distances.get(id_),
                places.positions.get(id_),
            )
        elif id_ in nodes:
            out.hosts[id_] = _system_host(meta, nodes[id_])
            out.places[id_] = _system_points(nodes[id_])
        else:
            out.problems.setdefault("no Point source or System row", []).append(id_)
    return out


def _system_points(node: dict) -> list[int]:
    """The points whose place a resolved system takes: its primary, then its
    members in member order. A member that is a resolved system has no place."""
    found = [node["primary"], *(member["id"] for member in node["members"] or [])]
    return list(dict.fromkeys(id_ for id_ in found if id_ is not None))


def drawn_places(job: HostJob) -> dict[int, tuple[list[float], float | None]]:
    """The render position and the distance of each of the job's IDs that the
    render tree draws."""
    places = _places(job)
    return {
        id_: (at, places.distances.get(id_)) for id_, at in places.positions.items()
    }


def _jobs(registry: Registry, ids: list[int], scratch: Path) -> list[HostJob]:
    """One job per region of the IDs."""
    regions = region_of(cell_of(np.array(ids, np.int64)))
    by_region: dict[int, list[int]] = defaultdict(list)
    for id_, region in zip(ids, regions.tolist()):
        by_region[region].append(id_)
    return [
        HostJob(registry, region, tuple(found), scratch)
        for region, found in sorted(by_region.items())
    ]


def _place_systems(
    registry: Registry,
    scratch: Path,
    run: Runner,
    hosts: dict[int, dict],
    wanted: dict[int, list[int]],
) -> int:
    """Give each resolved system the render position and distance of the
    first of its points that the render tree draws, so that its planets are
    drawn there. It returns the number of systems that get a place."""
    # The point hosts are read already. Most systems take the place of one.
    places = {
        id_: (host["position"], host["distance"])
        for id_, host in hosts.items()
        if id_ not in wanted and host["position"] is not None
    }
    points = sorted({id_ for found in wanted.values() for id_ in found} - hosts.keys())
    if points:
        jobs = _jobs(registry, points, scratch)
        for found in run(drawn_places, jobs, "system places"):
            places.update(found)
    placed = 0
    for id_, choices in wanted.items():
        place = next((places[p] for p in choices if p in places), None)
        if place is not None:
            hosts[id_]["position"], hosts[id_]["distance"] = place
            placed += 1
    return placed


def _direction(host: dict) -> np.ndarray:
    """From us to the host: its render position, else its RA and Dec."""
    if host["position"] is not None:
        return np.array(host["position"])
    ra, dec = math.radians(host["ra"]), math.radians(host["dec"])
    return np.array(
        [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    )


def planet_record(row: dict, direction: np.ndarray) -> dict:
    """The planet entry of a system file from its planets table row. A planet
    with a Wikidata item has an object entry."""
    record: dict = {
        "host": row["host"],
        "number": row["number"],
        "object": planet_qid(row["cross_ids"]) is not None,
    }
    for name in TOP_COLUMNS:
        record[name] = _finite(row[name])
    record["elements"] = orbits.elements(row, direction)
    sources = {}
    values = {}
    for name, value in row.items():
        if name in KEY_COLUMNS or name in TOP_COLUMNS or name in FLAG_COLUMNS:
            continue
        value = _finite(value)
        if value is None:
            continue
        if name.endswith(SOURCE_SUFFIX):
            sources[name.removesuffix(SOURCE_SUFFIX)] = value
        else:
            values[name] = value
    record["values"] = values
    record["sources"] = sources
    for name in FLAG_COLUMNS:
        record[name] = row[name] or []
    return record


def _payload(content: dict) -> bytes:
    return (
        json.dumps(content, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def alias_key(number: tuple[int, int]) -> str:
    """The key of an alias number in the index: `<host>/<number>`."""
    return f"{number[0]}/{number[1]}"


def _previous_planets(live: Path) -> set[tuple[int, int]]:
    """(host, number) of every planet and alias that the served export lists."""
    path = live / INDEX_FILE
    if not path.exists():
        return set()
    index = json.loads(gzip.decompress(path.read_bytes()))
    found = set()
    for host in index["hosts"]:
        found.update((host["id"], n) for n in host["planets"])
    for key in index["aliases"]:
        host, number = key.split("/")
        found.add((int(host), int(number)))
    return found


def _gone(
    registry: Registry,
    served: set[tuple[int, int]],
    previous: set[tuple[int, int]],
    state: numbering.PartState,
) -> list[str]:
    """The planets of the served index that this export would drop for no
    recorded reason."""
    missing = sorted(previous - served)
    if not missing:
        return []
    hosts = np.unique(np.array([host for host, _ in missing], np.int64))
    regions = np.unique(region_of(cell_of(hosts))).tolist()
    states = registry.id_states(regions)
    host_live = dict(
        zip(hosts.tolist(), states.has_status(hosts, LIVE).tolist(), strict=True)
    )
    return [
        f"{host}/b/{number}"
        for host, number in missing
        if host_live[host] and state.status.get((host, number)) not in (RETIRED, ALIAS)
    ]


@dataclass
class Result:
    files: list[Written]
    entry: dict
    problems: Problems
    counts: Counter


def build(
    registry: Registry, out: Path, scratch: Path, run: Runner, live: Path
) -> Result | None:
    """Write the planet files below `out`, or None when the registry has no
    planets table.

    `scratch` holds the render rows of the tree build, `run` maps a task over
    jobs in the export's workers, and `live` is the served `v1/x/`.
    """
    table = read_planets(registry)
    if table is None:
        logger.warning("no planets table: the export has no planets")
        return None
    problems = Problems()
    counts: Counter = Counter()
    rows = table.to_pylist()
    numbers = [(row["host"], row["number"]) for row in rows]
    doubled = [k for k, n in Counter(numbers).items() if n > 1]
    problems.add("a planet number given twice", [f"{h}/b/{n}" for h, n in doubled])
    problems.add("a host in two systems", hosts_with_several_systems(table))

    host_ids = sorted({row["host"] for row in rows} | {row["system"] for row in rows})
    hosts: dict[int, dict] = {}
    roots: dict[int, int] = {}
    wanted: dict[int, list[int]] = {}
    for found in run(host_rows, _jobs(registry, host_ids, scratch), "planet hosts"):
        hosts.update(found.hosts)
        roots.update(found.roots)
        wanted.update(found.places)
        for kind, ids in found.problems.items():
            problems.add(f"planet host or system: {kind}", ids, len(ids))
    counts["resolved system placed at one of its points"] = _place_systems(
        registry, scratch, run, hosts, wanted
    )
    # The planet files group the hosts as the star systems do. A host in no
    # star system takes the root of its file key's system.
    astray = sorted(
        {
            f"{row['host']} in {row['system']}, root {root}"
            for row in rows
            if (root := roots.get(row["host"], roots.get(row["system"]))) is not None
            and row["system"] != root
        }
    )
    problems.add(
        "a host whose system file is not keyed by its root", astray, len(astray)
    )

    state = numbering.read_state(registry)
    served_numbers = set(numbers)
    aliases: dict[tuple[int, int], tuple[int, int]] = {}
    for number, status in sorted(state.status.items()):
        if status != ALIAS:
            continue
        end = state.live_end(number)
        if end in served_numbers:
            aliases[number] = end
        else:
            logger.warning(
                "planets: alias %d/b/%d ends at no served planet (%s): a 404",
                *number,
                end,
            )
    counts["alias numbers"] = len(aliases)
    counts["alias numbers to another host"] = sum(
        1 for alias, end in aliases.items() if alias[0] != end[0]
    )

    planets_of: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        host = hosts.get(row["host"])
        if host is None:
            continue
        record = planet_record(row, _direction(host))
        planets_of[row["system"]].append(record)
        elements = record["elements"]
        if elements is None:
            counts["no semi-major axis, a fixed dot"] += 1
            logger.debug("planets: %s has no semi-major axis", row["designation"])
            continue
        counts[f"phase from {elements['phase']}"] += 1
        if not elements["n"]:
            counts["no period, at rest on its orbit"] += 1
        if "replaced" in elements:
            counts["eccentricity outside [0, 1), drawn as 0"] += 1
            logger.warning(
                "planets: %s has eccentricity %s; its orbit is drawn with 0",
                row["designation"],
                row["eccentricity"],
            )

    previous = _previous_planets(live)
    gone = _gone(registry, served_numbers | set(aliases), previous, state)
    problems.add("a served planet is gone", gone, len(gone))
    if problems:
        return Result([], {}, problems, counts)

    contents: dict[int, dict] = {}
    index_hosts: list[dict] = []
    for key in sorted(planets_of):
        planets = sorted(planets_of[key], key=lambda p: (p["host"], p["number"]))
        members = sorted(
            {p["host"] for p in planets} | {key}, key=lambda h: (h != key, h)
        )
        system_hosts = []
        for id_ in members:
            mine = [p for p in planets if p["host"] == id_]
            axes = [
                p["values"]["semi_major_axis"]
                for p in mine
                if "semi_major_axis" in p["values"]
            ]
            host = dict(hosts[id_])
            host["planets"] = [p["number"] for p in mine]
            system_hosts.append(host)
            counts[f"host placed by {host['placement']}"] += 1
            if not mine:
                continue
            entry: dict = {
                "id": id_,
                "system": key,
                "planets": host["planets"],
                "position": host["position"],
                "outer_orbit": max(axes) if axes else None,
            }
            index_hosts.append(entry)
        contents[key] = {
            "token": ZERO_TOKEN,
            "system": key,
            "hosts": system_hosts,
            "planets": planets,
        }
    index_hosts.sort(key=lambda h: h["id"])
    index = {
        "token": ZERO_TOKEN,
        "hosts": index_hosts,
        "aliases": {alias_key(alias): list(end) for alias, end in aliases.items()},
    }

    named_files = [(INDEX_FILE, index)] + [
        (system_path(key), content) for key, content in contents.items()
    ]
    digests = [hashlib.sha256(_payload(c)).digest() for _, c in named_files]
    token = container.token_of(
        [Written(path, digest, 0, 0) for (path, _), digest in zip(named_files, digests)]
    )
    written = []
    for (path, content), digest in zip(named_files, digests):
        content["token"] = token
        data = gzip.compress(_payload(content), compresslevel=9, mtime=0)
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        rows_in = (
            len(content["hosts"]) if path == INDEX_FILE else len(content["planets"])
        )
        written.append(Written(path, digest, rows_in, len(data)))

    counts["systems"] = len(contents)
    counts["hosts"] = len(index_hosts)
    counts["planets"] = len(rows)
    counts["planets with an object entry"] = sum(
        planet["object"] for planets in planets_of.values() for planet in planets
    )
    entry = {
        "token": token,
        "index": INDEX_FILE,
        "system": system_path("{key}"),
        "systems": len(contents),
        "hosts": len(index_hosts),
        "planets": len(rows),
        "units": {
            "position": "pc",
            "distance": "pc",
            "a": "AU",
            "angles": "deg",
            "n": "deg/day",
            "epoch": "JD TDB",
        },
        "elements_frame": (
            "ecliptic and mean equinox of J2000, the planet around its host;"
            f" obliquity {orbits.OBLIQUITY} deg"
        ),
        "credits": list(CREDITS),
    }
    return Result(written, entry, problems, counts)
