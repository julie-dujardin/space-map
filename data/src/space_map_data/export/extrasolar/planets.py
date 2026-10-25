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

The checks: every host and system ID is live and has a Metadata and a Point
source row, every host is in one system, and every planet of the served index
is still served, or its number is retired or an alias, or its host is no
longer live.
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
from space_map_data.export.extrasolar.tiles import Problems
from space_map_data.extrasolar.exoplanets import numbering
from space_map_data.extrasolar.exoplanets.ingest import hosts_with_several_systems
from space_map_data.extrasolar.exoplanets.table import SCHEMA, SLUG
from space_map_data.extrasolar.ids import cell_of
from space_map_data.extrasolar.placement import placement
from space_map_data.extrasolar.registry import ALIAS, LIVE, RETIRED, Registry
from space_map_data.extrasolar.sky import region_of
from space_map_data.extrasolar.tables import BINARY_ORBIT, METADATA

logger = logging.getLogger(__name__)

SECTION = "planets"
INDEX_FILE = f"{SECTION}/index.json.gz"
ZERO_TOKEN = "0" * container.TOKEN_SIZE
PARALLAX, CATALOGUE_DISTANCE = "parallax", "catalogue distance"
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
METADATA_COLUMNS = ["id", "name", "name_source", "class", "cross_ids"]
POINT_COLUMNS = [
    "id",
    "ra",
    "dec",
    "epoch",
    "parallax",
    "parallax_error",
    "fidelity_v2",
    "hipparcos_photometry_source",
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
    # The rows the checks refuse, by kind.
    problems: dict[str, list[int]] = field(default_factory=dict)


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
    point_table = job.registry.read_table("point-source", job.region, POINT_COLUMNS)
    points: dict[int, dict] = {}
    placed: dict[int, str | None] = {}
    distances: dict[int, float | None] = {}
    if point_table is not None:
        point_table = point_table.filter(pc.is_in(point_table["id"], wanted))
        orbit_table = job.registry.read_table(
            BINARY_ORBIT.slug, job.region, list(render.ORBIT_COLUMNS)
        )
        point_table = render.with_orbit_parallax(point_table, orbit_table)
        where = placement(point_table)
        distance, orbit = render.star_distance(point_table, where.by_parallax)
        for row, parallax, catalogue, by_orbit, parsecs in zip(
            point_table.to_pylist(),
            where.by_parallax.tolist(),
            where.by_catalogue.tolist(),
            orbit.tolist(),
            distance.tolist(),
        ):
            points[row["id"]] = row
            # An orbit parallax measures the distance as a parallax does, so a
            # catalogue host that has one is placed by parallax.
            measured = parallax or (catalogue and by_orbit)
            placed[row["id"]] = (
                PARALLAX if measured else CATALOGUE_DISTANCE if catalogue else None
            )
            if measured:
                distances[row["id"]] = parsecs
            elif catalogue:
                distances[row["id"]] = _f32(parsecs)
    positions: dict[int, list[float]] = {}
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
                positions[id_] = [float(v[at]) for v in xyz]
    for id_ in job.ids:
        if id_ not in metadata:
            out.problems.setdefault("no Metadata row", []).append(id_)
        elif id_ not in points:
            out.problems.setdefault("no Point source row", []).append(id_)
        else:
            out.hosts[id_] = _host(
                metadata[id_],
                points[id_],
                placed[id_],
                distances.get(id_),
                positions.get(id_),
            )
    return out


def _direction(host: dict) -> np.ndarray:
    """From us to the host: its render position, else its RA and Dec."""
    if host["position"] is not None:
        return np.array(host["position"])
    ra, dec = math.radians(host["ra"]), math.radians(host["dec"])
    return np.array(
        [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    )


def planet_record(row: dict, direction: np.ndarray) -> dict:
    """The planet entry of a system file from its planets table row."""
    record: dict = {"host": row["host"], "number": row["number"]}
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
    regions = region_of(cell_of(np.array(host_ids, np.int64)))
    by_region: dict[int, list[int]] = defaultdict(list)
    for id_, region in zip(host_ids, regions.tolist()):
        by_region[region].append(id_)
    jobs = [
        HostJob(registry, region, tuple(ids), scratch)
        for region, ids in sorted(by_region.items())
    ]
    hosts: dict[int, dict] = {}
    for found in run(host_rows, jobs, "planet hosts"):
        hosts.update(found.hosts)
        for kind, ids in found.problems.items():
            problems.add(f"planet host or system: {kind}", ids, len(ids))

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
