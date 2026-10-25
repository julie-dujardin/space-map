"""PASTEL (Soubiran et al. 2016, version of 2020) as an ingest source.

PASTEL compiles [Fe/H] from detailed analyses of high-resolution spectra,
each with its bibcode, under the designation that each paper used. A few
determinations give [M/H] or [Fe II/H] instead; they count as [Fe/H].

Each designation gets one star, the first that holds of:
1. its HD or HIP number, through Hipparcos and the Gaia best neighbour. When
   SIMBAD puts the name on another Gaia source near that star, the source of
   SIMBAD wins: Hipparcos and HD often give a double's name to the wrong
   component.
2. the star at its J2000 position. Gaia and Hipparcos stars move to J2000.0
   by their own proper motion and must lie within 3″. Where PASTEL gives V,
   the candidate's V must agree; where it does not, the candidate must be
   the only one and within 1″. A match beyond 1″ also fails when SIMBAD
   gives the name a Gaia source that is not a candidate. Of several that
   agree, SIMBAD's source wins, else the nearest: a bright star often has
   two Gaia sources.
3. the Gaia DR3 id that SIMBAD gives the name.
A designation without one is dropped. The designations of one star become
one row: the median of their determinations, their range and number, and the
bibcodes. Designations that SIMBAD keeps apart are not merged.

The rows join the Gaia rows by source_id and the Hipparcos rows by HIP
number at each ingest. A star with a HIP number whose Gaia source is a
candidate of none of its designations joins by HIP number: that source is
often a best neighbour without a 5σ parallax, which has no Gaia row. The rows
hold no catalogue id in the registry.

Licence: none stated, so the data are non-commercial. Cite Soubiran et al.
2016, A&A 591, A118. SIMBAD: Wenger et al. 2000, ODbL.
"""

import csv
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import astropy.units as u
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from astropy.coordinates import SkyCoord, search_around_sky

from space_map_data.download.cds import README, read_fixed_width
from space_map_data.download.providers.stars import gaia_source
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.sources import gaia, hipparcos
from space_map_data.extrasolar.sources.gaia import BestNeighbours
from space_map_data.utils.arrays import floats
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR, SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

PASTEL_DIR = SOURCES_CATALOGUES_DIR / "stellar-parameters" / "pastel"
PASTEL_FILE = "pastel.dat.gz"
SIMBAD_FILE = SOURCES_STARS_DIR / "pastel-simbad" / "names.csv"
FIELDS = {
    "ID": "designation",
    "RAdeg": "ra",
    "DEdeg": "dec",
    "Vmag": "v_mag",
    "[Fe/H]": "feh",
    "bibcode": "bibcode",
}
EPOCH = 2000.0
CLAIM_RADIUS = 3.0
# Largest |V - expected V| of a candidate. On the 4,903 stars that the HD
# route and SIMBAD place on one Gaia source the scatter is 0.02 mag and 98.9%
# are within 0.3 mag; the rest are variables and saturated bright stars.
MAX_V_DIFF = 0.3
# G - V from BP - RP in ascending powers, valid for BP - RP from -0.5 to 5
# (Riello et al. 2021, Table C.2).
G_MINUS_V = (-0.02704, 0.01424, -0.2156, 0.01426)
BP_RP_RANGE = (-0.5, 5.0)
# A position match this near needs no more evidence. Of the stars that the
# HD route and SIMBAD place on one Gaia source, all 5,693 within 3″ are this
# near.
TIGHT_RADIUS = 1.0
# SIMBAD's source this near the Hipparcos star is another component of the
# same system, or the same star.
COMPONENT_RADIUS = 10.0
# The level-8 pixels of a position and of points this far around it find
# the Gaia chunks of a star that crossed a pixel edge since J2000.
PIXEL_MARGIN = 60.0
COLUMNS = (
    "pastel_designation",
    "feh_pastel",
    "feh_pastel_min",
    "feh_pastel_max",
    "feh_pastel_count",
    "pastel_bibcodes",
)

_HD = re.compile(r"HD (\d+)")
_HIP = re.compile(r"HIP (\d+)")


def read_determinations(directory: Path = PASTEL_DIR) -> pa.Table:
    """The determinations that give [Fe/H] and a position.

    A designation is padded as in SIMBAD; it is kept with single spaces.
    """
    readme = (directory / README).read_text(encoding="latin-1")
    rows = read_fixed_width(directory / PASTEL_FILE, readme, FIELDS)
    rows = rows.filter(pc.and_(pc.is_valid(rows["feh"]), pc.is_valid(rows["ra"])))
    spoken = [" ".join(name.split()) for name in rows["designation"].to_pylist()]
    return rows.set_column(0, "designation", pa.array(spoken, pa.string()))


@dataclass(frozen=True)
class SimbadObject:
    oid: int
    ra: float
    dec: float
    # 0 where SIMBAD gives the object no Gaia DR3 id.
    gaia: int


def read_simbad(path: Path = SIMBAD_FILE) -> dict[str, SimbadObject]:
    """The SIMBAD object of each designation that SIMBAD resolves."""
    with path.open(newline="") as fh:
        return {
            row["name"]: SimbadObject(
                int(row["oid"]),
                float(row["ra"] or "nan"),
                float(row["dec"] or "nan"),
                int(row["gaia_dr3"] or 0),
            )
            for row in csv.DictReader(fh)
            if row["oid"]
        }


def expected_v(g: np.ndarray, bp_rp: np.ndarray) -> np.ndarray:
    """Johnson V from Gaia G and BP - RP; NaN outside the fit range."""
    ok = (bp_rp >= BP_RP_RANGE[0]) & (bp_rp <= BP_RP_RANGE[1])
    v = g - np.polynomial.polynomial.polyval(bp_rp, G_MINUS_V)
    return np.where(ok, v, np.nan)


def _summary(feh: list[float], bibcodes: list[str | None]) -> dict:
    """Median, range, number and bibcodes of a star's determinations."""
    values = np.sort(np.asarray(feh))
    unique = list(dict.fromkeys(code for code in bibcodes if code))
    return {
        "feh_pastel": float(np.median(values)),
        "feh_pastel_min": float(values[0]),
        "feh_pastel_max": float(values[-1]),
        "feh_pastel_count": int(values.size),
        "pastel_bibcodes": " ".join(unique) or None,
    }


def name_hip(designation: str, hip_of_hd: dict[int, int]) -> int:
    """The HIP number that an HD or HIP designation names, 0 where none."""
    if match := _HIP.fullmatch(designation):
        return int(match[1])
    if match := _HD.fullmatch(designation):
        return hip_of_hd.get(int(match[1]), 0)
    return 0


def designations(rows: pa.Table) -> pa.Table:
    """One row per designation, with the position and V of its first line."""
    names = rows["designation"].to_pylist()
    first = sorted({name: at for at, name in reversed(list(enumerate(names)))}.items())
    at = pa.array([index for _, index in first])
    return pa.table(
        {
            "designation": pa.array([name for name, _ in first], pa.string()),
            "ra": rows["ra"].take(at),
            "dec": rows["dec"].take(at),
            "v_mag": rows["v_mag"].take(at),
        }
    )


@dataclass
class Candidates:
    """Stars near each J2000 position: Gaia sources and Hipparcos stars."""

    row: np.ndarray
    # The Gaia DR3 id; for a Hipparcos star, its best neighbour or 0.
    source_id: np.ndarray
    hip: np.ndarray
    separation: np.ndarray
    expected_v: np.ndarray


def _chunk_pixels(ra: np.ndarray, dec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(level-8 pixel, position index) pairs near each position, by pixel."""
    step = PIXEL_MARGIN / 3600
    pixels = np.concatenate(
        [
            sky.cells(
                (ra + dra) % 360, np.clip(dec + ddec, -90, 90), gaia_source.PIXEL_LEVEL
            )
            for dra, ddec in ((0, 0), (step, 0), (-step, 0), (0, step), (0, -step))
        ]
    )
    index = np.tile(np.arange(ra.size), 5)
    pairs = np.unique(np.stack([pixels, index], axis=1), axis=0)
    return pairs[:, 0], pairs[:, 1]


def _pairs(
    ra: np.ndarray, dec: np.ndarray, their_ra: np.ndarray, their_dec: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not ra.size or not their_ra.size:
        empty = np.zeros(0, np.int64)
        return empty, empty, np.zeros(0)
    i, j, separation, _ = search_around_sky(
        SkyCoord(ra * u.deg, dec * u.deg),
        SkyCoord(their_ra * u.deg, their_dec * u.deg),
        CLAIM_RADIUS * u.arcsec,
    )
    return i, j, separation.arcsec


def candidates(
    stars: pa.Table,
    chunks: list[Path],
    hip_stars: pa.Table,
    best: BestNeighbours,
    workers: int = 8,
) -> Candidates:
    """Every Gaia source and Hipparcos star within 3″ of each position.

    A Hipparcos star whose best neighbour is also a candidate of the row is
    the same candidate.
    """
    ra, dec = floats(stars, "ra"), floats(stars, "dec")
    hip_ra, hip_dec = hipparcos.propagate(
        np.degrees(floats(hip_stars, "ra_rad")),
        np.degrees(floats(hip_stars, "dec_rad")),
        floats(hip_stars, "pmra"),
        floats(hip_stars, "pmdec"),
        EPOCH - hipparcos.EPOCH,
    )
    i, j, sep = _pairs(ra, dec, hip_ra, hip_dec)
    hip = hip_stars["hip"].to_numpy()[j]
    parts = [(i, best.source_of_hip(hip), hip, sep, floats(hip_stars, "v_mag")[j])]

    pixel, index = _chunk_pixels(ra, dec)
    wanted = []
    for path in chunks:
        low, high = gaia_source.pixel_range(path.name)
        found = index[
            np.searchsorted(pixel, low) : np.searchsorted(pixel, high, "right")
        ]
        if found.size:
            wanted.append((path, np.unique(found)))

    def chunk(job: tuple[Path, np.ndarray]) -> tuple:
        path, at = job
        found = pq.read_table(
            path,
            columns=[
                "source_id",
                "ra",
                "dec",
                "pmra",
                "pmdec",
                "phot_g_mean_mag",
                "phot_bp_mean_mag",
                "phot_rp_mean_mag",
            ],
        )
        moved_ra, moved_dec = hipparcos.propagate(
            floats(found, "ra"),
            floats(found, "dec"),
            np.nan_to_num(floats(found, "pmra")),
            np.nan_to_num(floats(found, "pmdec")),
            EPOCH - gaia.EPOCH,
        )
        a, b, d = _pairs(ra[at], dec[at], moved_ra, moved_dec)
        v = expected_v(
            floats(found, "phot_g_mean_mag")[b],
            floats(found, "phot_bp_mean_mag")[b] - floats(found, "phot_rp_mean_mag")[b],
        )
        return at[a], found["source_id"].to_numpy()[b], d, v

    with ThreadPoolExecutor(workers) as pool:
        for a, ids, d, v in pool.map(chunk, wanted):
            parts.append((a, ids, np.zeros(a.size, np.int64), d, v))
    joined = [np.concatenate([part[k] for part in parts]) for k in range(5)]
    found = Candidates(*joined)
    # A Hipparcos star and its best neighbour near one row are one star.
    gaia_pairs = {
        (r, s) for r, s, h in zip(found.row, found.source_id, found.hip) if not h
    }
    keep = np.array(
        [
            not (h and s and (r, s) in gaia_pairs)
            for r, s, h in zip(found.row, found.source_id, found.hip)
        ],
        bool,
    )
    return Candidates(
        *(getattr(found, name)[keep] for name in Candidates.__dataclass_fields__)
    )


@dataclass
class Placed:
    """Where each designation goes, and by which route."""

    source_id: np.ndarray
    hip: np.ndarray
    route: list[str] = field(default_factory=list)


def place(
    stars: pa.Table,
    found: Candidates,
    simbad: dict[str, SimbadObject],
    hip_stars: pa.Table,
    best: BestNeighbours,
) -> Placed:
    """The star of each designation by the routes of the module docstring."""
    names = stars["designation"].to_pylist()
    v = floats(stars, "v_mag")
    hd = hip_stars["hd"].fill_null(0).to_numpy()
    hd_numbers, counts = np.unique(hd[hd > 0], return_counts=True)
    unique_hd = set(hd_numbers[counts == 1].tolist())
    hip_numbers = hip_stars["hip"].to_numpy()
    hip_of_hd = {
        int(h): int(n) for h, n in zip(hd.tolist(), hip_numbers) if h in unique_hd
    }
    hip_at = {int(n): k for k, n in enumerate(hip_numbers.tolist())}
    hip_source = best.source_of()
    hip_ra, hip_dec = hipparcos.propagate(
        np.degrees(floats(hip_stars, "ra_rad")),
        np.degrees(floats(hip_stars, "dec_rad")),
        floats(hip_stars, "pmra"),
        floats(hip_stars, "pmdec"),
        EPOCH - hipparcos.EPOCH,
    )
    by_row: dict[int, list[int]] = {}
    for k, r in enumerate(found.row.tolist()):
        by_row.setdefault(r, []).append(k)

    source = np.zeros(len(names), np.int64)
    hip = np.zeros(len(names), np.int64)
    route = []
    for r, name in enumerate(names):
        named = name_hip(name, hip_of_hd)
        known = simbad.get(name)
        if named and named in hip_at:
            source[r], hip[r] = hip_source.get(named, 0), named
            route.append("name")
            if known and known.gaia and known.gaia != source[r]:
                k = hip_at[named]
                near = _separation(known.ra, known.dec, hip_ra[k], hip_dec[k])
                if near > COMPONENT_RADIUS:
                    pass
                elif not source[r]:
                    # A star without a best neighbour: SIMBAD gives its source.
                    source[r] = known.gaia
                else:
                    source[r], hip[r] = known.gaia, 0
                    route[-1] = "name, component from SIMBAD"
            continue
        ks = by_row.get(r, [])
        if ks:
            ks = np.array(ks)
            if np.isfinite(v[r]):
                agree = ks[np.abs(found.expected_v[ks] - v[r]) <= MAX_V_DIFF]
                # SIMBAD's star is not among them: only a close one is the star.
                if known and known.gaia and known.gaia not in found.source_id[ks]:
                    agree = agree[found.separation[agree] <= TIGHT_RADIUS]
            else:
                agree = ks if ks.size == 1 else ks[:0]
                agree = agree[found.separation[agree] <= TIGHT_RADIUS]
            if agree.size:
                # Of a bright star's duplicate Gaia sources, SIMBAD's is kept.
                # Source 0 is a HIP star without a best neighbour, never SIMBAD's.
                simbad_gaia = known.gaia if known and known.gaia else -1
                named_k = agree[found.source_id[agree] == simbad_gaia]
                pick = named_k if named_k.size else agree
                k = pick[np.argmin(found.separation[pick])]
                source[r], hip[r] = found.source_id[k], found.hip[k]
                route.append("position")
                continue
        if known and known.gaia:
            source[r] = known.gaia
            route.append("simbad")
            continue
        route.append("none")
    # A best neighbour without a 5σ parallax has no Gaia row, but the
    # Hipparcos star is always stored. A star whose source is a candidate of
    # none of its designations joins by HIP number, all designations alike.
    gaia_near = {
        (r, s) for r, s, h in zip(found.row, found.source_id, found.hip) if not h
    }
    of_source: dict[int, list[int]] = {}
    for r in np.flatnonzero(source > 0).tolist():
        of_source.setdefault(int(source[r]), []).append(r)
    for s, rows in of_source.items():
        hips = hip[rows]
        if hips.any() and not any((r, s) in gaia_near for r in rows):
            # The first HIP number, as by_star takes it.
            source[rows], hip[rows] = 0, hips[hips > 0][0]
    return Placed(source, hip, route)


def _separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Arcsec between two positions in degrees."""
    a = SkyCoord(ra1 * u.deg, dec1 * u.deg)
    return float(a.separation(SkyCoord(ra2 * u.deg, dec2 * u.deg)).arcsec)


def by_star(
    rows: pa.Table,
    placed: dict[str, tuple[int, int]],
    simbad: dict[str, SimbadObject],
) -> pa.Table:
    """One row per star from the determinations of its designations.

    Designations of one star merge when SIMBAD has them as one object. Of
    designations that SIMBAD keeps apart, only those that SIMBAD puts on the
    star's own Gaia source stay; the star has no row when there are none.
    """
    names = rows["designation"].to_pylist()
    # A star is its Gaia source, else its HIP number.
    groups: dict[int, list[str]] = {}
    hip_of: dict[int, int] = {}
    for name in sorted(set(names)):
        source, hip = placed.get(name, (0, 0))
        if source or hip:
            key = source or -hip
            groups.setdefault(key, []).append(name)
            if hip:
                hip_of.setdefault(key, hip)
    feh = rows["feh"].to_pylist()
    bibcodes = rows["bibcode"].to_pylist()
    lines: dict[str, list[int]] = {}
    for at, name in enumerate(names):
        lines.setdefault(name, []).append(at)
    out = []
    for key, members in groups.items():
        source, hip = max(key, 0), hip_of.get(key, 0)
        objects = {simbad[name].oid for name in members if name in simbad}
        if len(objects) > 1:
            members = [
                name
                for name in members
                if source and name in simbad and simbad[name].gaia == source
            ]
            if not members:
                continue
        chosen = next(
            (name for name in members if _HD.fullmatch(name) or _HIP.fullmatch(name)),
            members[0],
        )
        at = [k for name in members for k in lines[name]]
        out.append(
            {
                "source_id": source,
                "hip": hip,
                "pastel_designation": chosen,
                "designations": len(members),
                **_summary([feh[k] for k in at], [bibcodes[k] for k in at]),
            }
        )
    out.sort(key=lambda star: star["pastel_designation"])
    kinds = {
        "source_id": pa.int64(),
        "hip": pa.int64(),
        "pastel_designation": pa.string(),
        "designations": pa.int16(),
        "feh_pastel": pa.float32(),
        "feh_pastel_min": pa.float32(),
        "feh_pastel_max": pa.float32(),
        "feh_pastel_count": pa.int16(),
        "pastel_bibcodes": pa.string(),
    }
    return pa.table(
        {name: pa.array([s[name] for s in out], kind) for name, kind in kinds.items()}
    )


def read_stars(
    chunks: list[Path],
    hip_stars: pa.Table,
    best: BestNeighbours,
    workers: int = 8,
    directory: Path = PASTEL_DIR,
    simbad_file: Path = SIMBAD_FILE,
) -> pa.Table:
    """One row per star, with the Gaia DR3 id and HIP number it joins by."""
    rows = read_determinations(directory)
    stars = designations(rows)
    simbad = read_simbad(simbad_file)
    found = candidates(stars, chunks, hip_stars, best, workers)
    placed = place(stars, found, simbad, hip_stars, best)
    keys = {
        name: (int(s), int(h))
        for name, s, h in zip(
            stars["designation"].to_pylist(), placed.source_id, placed.hip
        )
    }
    out = by_star(rows, keys, simbad)
    routes: dict[str, int] = {}
    for route in placed.route:
        routes[route] = routes.get(route, 0) + 1
    merged = int(pc.sum(pc.greater(out["designations"], 1)).as_py() or 0)
    logger.info(
        "PASTEL: %d designations placed by %s; %d stars, %d of several designations",
        stars.num_rows,
        routes,
        out.num_rows,
        merged,
    )
    return out
