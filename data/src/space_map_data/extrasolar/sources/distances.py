"""Distance catalogues as ingest sources.

Each source fills the distance group of Point source for the stars that it
reaches, in the order of that group. No row mints, and no row has a catalogue
id. A row claims one id only, so it never joins two objects.

A row that claims a Gaia DR3 id goes by that claim only. When the ingest does
not store that star, the row is left out. So a row never puts its id on
another star, and the sources add no cross-ids. A row without a Gaia DR3 id
can match by position. The passes come after all other passes: a row that
reaches no star becomes an object that never mints, and a later pass that
matches by position could take it.

- REYLE_2021: the 10 pc sample (Reylé et al. 2021, A&A 650, A201, update of
  2023-08; VizieR J/A+A/650/A201). The distance comes from the parallax of
  the row. A row claims its Gaia DR3 id (EDR3 and DR3 ids are equal), else
  its HIP number, else it goes by position. Planets are left out. CC BY 4.0
  (Zenodo 7576096).
- ULTRACOOLSHEET: Best, Liu, Magnier & Dupuy, The UltracoolSheet 2.1.0,
  doi:10.5281/zenodo.4169085. The distance comes from a parallax, else from
  photometry. A row claims its Gaia DR3 id, else it goes by position. Imaged
  exoplanets are left out. CC BY 4.0.
- HUNT_REFFERT_2024: the distance of the host cluster (Hunt & Reffert 2024,
  A&A 686, A42; the catalogue of 2023 with classes and Jacobi radii). A member
  counts when it is inside the tidal or the Jacobi radius with a probability
  of at least 0.5, and its cluster is open, globular or too far to classify.
  A star in two such clusters takes the one with the higher probability. It
  takes a row only where the render does not place it by its own parallax:
  it is a named row, which has no 5σ parallax, or its fidelity_v2 is under
  0.5. No licence is stated; the article is CC BY 4.0, and the values derive
  from Gaia.
- MAGELLANIC_CLOUDS: the distance of the host cloud, LMC 49.59 kpc
  (Pietrzyński et al. 2019, Nature 567, 200) and SMC 62.44 kpc (Graczyk et
  al. 2020, ApJ 904, 13), for the gaia_named rows that pass the selection of
  Gaia Collaboration, Luri et al. 2021 (A&A 649, A7). Their proper-motion
  ellipse is fitted to the full Gaia data; here it is the mean and spread of
  their clean samples, with no correlation. The bounds are the error of the
  cloud's distance, not the depth of the cloud.
- BAILER_JONES_2021: the geometric distance of Bailer-Jones et al. 2021,
  AJ 161, 147, for the gaia_named rows. The values derive from Gaia, CC BY-NC
  3.0 IGO.
- SIMBAD_PARALLAX: the parallax that SIMBAD gives a gaia_named row, where it
  is 5σ. Such a row has no 5σ Gaia parallax, so this one is another
  measurement. ODbL, as SIMBAD.
"""

import csv
import gzip
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from space_map_data.download.cds import README, byte_by_byte, read_fixed_width
from space_map_data.download.providers.stars import (
    bailer_jones,
    gaia_fidelity,
    gaia_source,
    ultracoolsheet,
)
from space_map_data.download.providers.stars import cds as cds_stars
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import Source
from space_map_data.extrasolar.match import PositionMatcher
from space_map_data.extrasolar.sources import gaia
from space_map_data.extrasolar.sources.hipparcos import claim_lists, to_gaia_epoch
from space_map_data.extrasolar.sources.simbad import SimbadList
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR

logger = logging.getLogger(__name__)

# Beyond 3σ the magnitudes must agree. The rows have no kind, so they also
# match a SIMBAD star that has no optical magnitude, such as a cool brown
# dwarf.
MATCHER = PositionMatcher(
    n_sigma=5.0,
    near_sigma=3.0,
    min_error=0.3,
    reach=0.1,
    max_mag_diff=1.5,
    mag_sigma=0.5,
)
REYLE_2021 = Source(
    name="reyle-2021",
    catalogue="reyle",
    release="2021",
    home=1,
    matcher=MATCHER,
)
ULTRACOOLSHEET = Source(
    name="ultracoolsheet",
    catalogue="ultracoolsheet",
    release="2.1.0",
    home=1,
    matcher=MATCHER,
)
HUNT_REFFERT_2024 = Source(
    name="hunt-reffert-2024", catalogue="hunt-reffert", release="2024", home=1
)
MAGELLANIC_CLOUDS = Source(
    name="magellanic-clouds", catalogue="magellanic-clouds", release="2021", home=1
)
BAILER_JONES_2021 = Source(
    name="bailer-jones-2021", catalogue="bailer-jones", release="2021", home=1
)
SIMBAD_PARALLAX = Source(
    name="simbad-parallax", catalogue="simbad", release="parallax", home=1
)
GAIA_DR3, HIP = ("gaia", "dr3"), ("hip", "2007")

REYLE_DIR = cds_stars.OUT_DIR / "J/A+A/650/A201"
REYLE_FILE = "tablea1.dat.gz"
HUNT_REFFERT_DIR = SOURCES_CATALOGUES_DIR / "star-clusters" / "hunt-reffert-2024"
CLUSTERS_FILE, MEMBERS_FILE = "clusters.dat.gz", "members.dat.gz"

# Arcsec.
REYLE_ERROR = 0.3
ULTRACOOL_ERROR = 1.0
MIN_PARALLAX_SNR = 5.0
MIN_MEMBERSHIP = 0.5
# Open, globular, too far to classify. Moving groups are not bound, and the
# rejected ones are not clusters.
CLUSTER_TYPES = frozenset({"o", "g", "d"})
# GCode of the 10 pc sample: G from Gaia DR2 or EDR3, G from the spectral type.
GAIA_G_CODES = frozenset({2, 3})
ESTIMATED_G_CODE = 10


@dataclass(frozen=True)
class Cloud:
    name: str
    ra: float
    dec: float
    # Degrees.
    radius: float
    # Mean and spread of μα* and μδ, mas/yr.
    pm: tuple[float, float]
    pm_spread: tuple[float, float]
    # pc.
    distance: float
    error: float


# The SMC first: the field of the LMC holds it.
CLOUDS = (
    Cloud("SMC", 12.80, -73.15, 11.0, (0.7321, -1.2256), (0.3728, 0.2992), 62_440, 936),
    Cloud("LMC", 81.28, -69.78, 20.0, (1.7608, 0.3038), (0.4472, 0.6375), 49_590, 547),
)
MAX_G = 20.5
# χ² of the 99% region for two degrees of freedom.
MAX_PM_CHI2 = 9.21
# Threads that read the Gaia chunks.
READ_WORKERS = 8


def _chunk_rows(
    ids: np.ndarray, directory: Path, prefix: str, column: str | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Whether the chunks `prefix`<pixels>.parquet of `directory` have a row
    of each Gaia DR3 id, and its float `column`, NaN where none."""
    paths = sorted(directory.glob(f"{prefix}*.parquet"))
    high = np.array([gaia_source.pixel_range(p.name)[1] for p in paths], np.int64)
    chunk = np.searchsorted(high, ids >> gaia_source.PIXEL_SHIFT)
    order = np.argsort(chunk, kind="stable")
    bounds = np.searchsorted(chunk[order], np.arange(len(paths) + 1))
    found = np.zeros(ids.size, bool)
    values = np.full(ids.size, np.nan)
    names = ["source_id"] if column is None else ["source_id", column]

    def read(index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        at = order[bounds[index] : bounds[index + 1]]
        table = pq.read_table(paths[index], columns=names)
        row = pc.index_in(pa.array(ids[at]), value_set=table["source_id"])
        has = row.is_valid().to_numpy(zero_copy_only=False)
        if column is None:
            return at, has, None
        value = pc.cast(table[column].take(row), pa.float64())
        return at, has, value.to_numpy(zero_copy_only=False)

    wanted = [i for i in range(len(paths)) if bounds[i] < bounds[i + 1]]
    with ThreadPoolExecutor(READ_WORKERS) as pool:
        for at, has, value in pool.map(read, wanted):
            found[at] = has
            if value is not None:
                values[at] = value
    return found, values


@dataclass(frozen=True)
class StoredGaia:
    """The Gaia DR3 stars that the ingest stores: the positionable download
    and the named rows."""

    named: np.ndarray
    source_dir: Path = gaia.SOURCE_DIR
    fidelity_dir: Path = gaia.FIDELITY_DIR

    def holds(self, ids: np.ndarray) -> np.ndarray:
        """Whether the ingest stores each id."""
        found, _ = _chunk_rows(ids, self.source_dir, gaia_source.CHUNK_PREFIX)
        return found | np.isin(ids, self.named)

    def flagged(self, ids: np.ndarray) -> np.ndarray:
        """Whether each id is positionable with a fidelity under MIN_FIDELITY."""
        _, fidelity = _chunk_rows(
            ids, self.fidelity_dir, gaia_fidelity.CHUNK_PREFIX, "fidelity_v2"
        )
        return fidelity < gaia.MIN_FIDELITY


def stored_claims(rows: pa.Table, stored: StoredGaia, name: str) -> pa.Table:
    """The rows that claim no Gaia DR3 id, and the rows whose Gaia DR3 star the
    ingest stores."""
    claimed = np.array(
        [
            int(c[0]["catalogue_id"])
            if c and (c[0]["catalogue"], c[0]["release"]) == GAIA_DR3
            else 0
            for c in rows["claims"].to_pylist()
        ],
        np.int64,
    )
    keep = claimed == 0
    keep[~keep] = stored.holds(claimed[~keep])
    logger.info(
        "%s: %d rows claim a Gaia DR3 star that the ingest does not store, left out",
        name,
        int((~keep).sum()),
    )
    return rows.filter(pa.array(keep))


def _f32(values: np.ndarray) -> pa.Array:
    return pa.array(values, pa.float32(), from_pandas=True)


def rows(
    ra: np.ndarray,
    dec: np.ndarray,
    claims: list[tuple[str, str, str] | None],
    distance: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    method: list[str],
    mag: np.ndarray | None = None,
    error: float | None = None,
    catalogue_ids: list[str] | None = None,
) -> pa.Table:
    """Pass rows: a position at J2016.0, at most one claim, and a distance."""
    n = len(claims)
    nan = np.full(n, np.nan)
    table = pa.table(
        {
            "catalogue_id": pa.array(catalogue_ids or [None] * n, pa.string()),
            "mint": pa.array(np.zeros(n, bool)),
            "match_ra": pa.array(np.asarray(ra, np.float64)),
            "match_dec": pa.array(np.asarray(dec, np.float64)),
            "match_mag": _f32(nan if mag is None else mag),
            "match_error": _f32(np.full(n, np.nan if error is None else error)),
            "claims": claim_lists([[c] if c else [] for c in claims]),
            "distance": _f32(distance),
            "distance_lower": _f32(lower),
            "distance_upper": _f32(upper),
            "distance_method": pa.array(method, pa.string()),
        }
    )
    return table.filter(pc.is_valid(table["distance"]))


def parallax_bounds(
    parallax: np.ndarray, error: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The distance (pc) of a parallax (mas), and of the parallax ± its error.

    The far bound is NaN when the error reaches the parallax.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        distance = np.where(parallax > 0, 1000 / parallax, np.nan)
        lower = 1000 / (parallax + error)
        upper = np.where(parallax > error, 1000 / (parallax - error), np.nan)
    return distance, lower, upper


def _floats(values: list) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in values], np.float64)


def reyle_rows(stored: StoredGaia, directory: Path = REYLE_DIR) -> pa.Table:
    """The rows of the 10 pc sample, planets left out."""
    readme = (directory / README).read_text(encoding="latin-1")
    table = read_fixed_width(
        directory / REYLE_FILE,
        readme,
        [
            "Seq",
            "ObjType",
            "RAdeg",
            "DEdeg",
            "Epoch",
            "plx",
            "e_plx",
            "pmRA",
            "pmDE",
            "GCode",
            "Gmag",
            "Gest",
            "GaiaEDR3",
            "HIP",
        ],
        nulls=("---", "-"),
    )
    table = table.filter(pc.not_equal(table["ObjType"], "Planet"))
    table = table.take(pc.sort_indices(table["Seq"]))
    column = {
        name: _floats(table[name].to_pylist())
        for name in table.column_names
        if name not in ("ObjType", "HIP")
    }
    ra, dec = to_gaia_epoch(
        column["RAdeg"],
        column["DEdeg"],
        column["pmRA"],
        column["pmDE"],
        column["Epoch"],
    )
    code = np.nan_to_num(column["GCode"])
    mag = np.where(
        np.isin(code, list(GAIA_G_CODES)),
        column["Gmag"],
        np.where(code == ESTIMATED_G_CODE, column["Gest"], np.nan),
    )
    claims: list[tuple[str, str, str] | None] = []
    seen_hip: set[str] = set()
    for gaia_id, hip in zip(table["GaiaEDR3"].to_pylist(), table["HIP"].to_pylist()):
        number = hip.removeprefix("HIP").strip() if hip else None
        if gaia_id:
            claims.append((*GAIA_DR3, str(gaia_id)))
        # The components of a system share its HIP number; the first takes it.
        elif number and number not in seen_hip:
            seen_hip.add(number)
            claims.append((*HIP, number))
        else:
            claims.append(None)
    distance, lower, upper = parallax_bounds(column["plx"], column["e_plx"])
    n = table.num_rows
    found = rows(
        ra, dec, claims, distance, lower, upper, ["parallax"] * n, mag, REYLE_ERROR
    )
    return stored_claims(found, stored, REYLE_2021.name)


def _ucs_float(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return np.nan


def ultracool_rows(
    stored: StoredGaia, directory: Path = ultracoolsheet.OUT_DIR
) -> pa.Table:
    """The rows of the UltracoolSheet, imaged exoplanets left out."""
    with (directory / ultracoolsheet.MAIN_FILE).open(newline="") as handle:
        found = [
            row
            for row in csv.DictReader(handle)
            if not row["exoplanet"].strip().startswith("Y")
        ]

    def column(name: str) -> np.ndarray:
        return np.array([_ucs_float(row[name]) for row in found], np.float64)

    ra, dec = to_gaia_epoch(
        column("ra_j2000_formula"),
        column("dec_j2000_formula"),
        column("pmra_formula"),
        column("pmdec_formula"),
        2000.0,
    )
    claims: list[tuple[str, str, str] | None] = []
    for row in found:
        gaia = row["sourceID_Gaia_DR3"].strip()
        claims.append((*GAIA_DR3, gaia) if gaia.isdigit() else None)
    distance, error = column("dist_formula"), column("disterr_formula")
    lower = np.where(distance > error, distance - error, np.nan)
    method = [
        "parallax"
        if row["dist_formula_source"] == "dist_plx_formula"
        else "photometric"
        for row in found
    ]
    found = rows(
        ra,
        dec,
        claims,
        distance,
        lower,
        distance + error,
        method,
        column("G_Gaia"),
        ULTRACOOL_ERROR,
    )
    return stored_claims(found, stored, ULTRACOOLSHEET.name)


def cluster_rows(stored: StoredGaia, directory: Path = HUNT_REFFERT_DIR) -> pa.Table:
    """The member rows that take the distance of their cluster."""
    readme = (directory / README).read_text(encoding="latin-1")
    clusters = read_fixed_width(
        directory / CLUSTERS_FILE,
        readme,
        ["Name", "Type", "dist16", "dist50", "dist84"],
    )
    kept = {
        name: (low, mid, high)
        for name, kind, low, mid, high in zip(
            *(clusters[c].to_pylist() for c in clusters.column_names)
        )
        if kind in CLUSTER_TYPES and mid is not None
    }
    fields = {f.label: f for f in byte_by_byte(readme, MEMBERS_FILE)}
    names = ("Name", "GaiaDR3", "inrj", "inrt", "Prob", "RAdeg", "DEdeg")
    spans = {name: (fields[name].start, fields[name].end) for name in names}
    picked: dict[str, list] = {name: [] for name in names}
    # A line at a time: the file holds 1.3 M members of 1.2 kB.
    with gzip.open(directory / MEMBERS_FILE, "rt", encoding="latin-1") as handle:
        for line in handle:
            value = {name: line[a:b].strip() for name, (a, b) in spans.items()}
            if value["Name"] not in kept or float(value["Prob"]) < MIN_MEMBERSHIP:
                continue
            if "1" not in (value["inrj"], value["inrt"]):
                continue
            for name in names:
                picked[name].append(value[name])
    source_id = np.array(picked["GaiaDR3"], np.int64)
    probability = np.array(picked["Prob"], np.float64)
    # One row per star: its most probable cluster, then the first in the file.
    order = np.lexsort((-probability, source_id))
    best = np.sort(order[np.unique(source_id[order], return_index=True)[1]])
    named = np.isin(source_id[best], stored.named)
    placed = named.copy()
    placed[~named] = stored.flagged(source_id[best[~named]])
    at = best[placed]
    bounds = np.array([kept[picked["Name"][i]] for i in at], np.float64)
    bounds = bounds.reshape(-1, 3)
    logger.info(
        "Hunt & Reffert: %d of %d member stars take the distance of their"
        " cluster, %d of them named rows",
        at.size,
        best.size,
        int(named.sum()),
    )
    return rows(
        np.array(picked["RAdeg"], np.float64)[at],
        np.array(picked["DEdeg"], np.float64)[at],
        [(*GAIA_DR3, str(source_id[i])) for i in at],
        bounds[:, 1],
        bounds[:, 0],
        bounds[:, 2],
        ["cluster"] * at.size,
    )


def orthographic_pm(
    ra: np.ndarray,
    dec: np.ndarray,
    pmra: np.ndarray,
    pmdec: np.ndarray,
    centre: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Proper motions in the orthographic projection about `centre` (Gaia
    Collaboration, Helmi et al. 2018, A&A 616, A12, eq. 2)."""
    a, d = np.radians(ra), np.radians(dec)
    a0, d0 = np.radians(centre[0]), np.radians(centre[1])
    da = a - a0
    pm_x = pmra * np.cos(da) - pmdec * np.sin(d) * np.sin(da)
    pm_y = pmra * np.sin(d0) * np.sin(da) + pmdec * (
        np.cos(d) * np.cos(d0) + np.sin(d) * np.sin(d0) * np.cos(da)
    )
    return pm_x, pm_y


def cloud_of(
    ra: np.ndarray,
    dec: np.ndarray,
    parallax: np.ndarray,
    parallax_error: np.ndarray,
    pmra: np.ndarray,
    pmdec: np.ndarray,
    g: np.ndarray,
) -> np.ndarray:
    """The index in CLOUDS of the cloud of each Gaia star, -1 for none."""
    found = np.full(ra.size, -1)
    with np.errstate(invalid="ignore", divide="ignore"):
        base = (parallax / parallax_error < MIN_PARALLAX_SNR) & (g < MAX_G)
    for index, cloud in enumerate(CLOUDS):
        near = sky.separation(ra, dec, cloud.ra, cloud.dec) <= cloud.radius * 3600
        pm_x, pm_y = orthographic_pm(ra, dec, pmra, pmdec, (cloud.ra, cloud.dec))
        chi2 = ((pm_x - cloud.pm[0]) / cloud.pm_spread[0]) ** 2 + (
            (pm_y - cloud.pm[1]) / cloud.pm_spread[1]
        ) ** 2
        found[(found < 0) & base & near & (chi2 < MAX_PM_CHI2)] = index
    return found


def _named_column(stars: pa.Table, name: str) -> np.ndarray:
    return stars[name].to_numpy(zero_copy_only=False).astype(np.float64)


def magellanic_rows(named: pa.Table) -> pa.Table:
    """The rows of the gaia_named stars that belong to a Magellanic Cloud."""
    ra, dec = _named_column(named, "ra"), _named_column(named, "dec")
    found = cloud_of(
        ra,
        dec,
        _named_column(named, "parallax"),
        _named_column(named, "parallax_error"),
        _named_column(named, "pmra"),
        _named_column(named, "pmdec"),
        _named_column(named, "phot_g_mean_mag"),
    )
    at = np.flatnonzero(found >= 0)
    clouds = [CLOUDS[i] for i in found[at]]
    ids = named["source_id"].to_numpy()[at]
    distance = np.array([c.distance for c in clouds], np.float64)
    error = np.array([c.error for c in clouds], np.float64)
    logger.info(
        "Magellanic Clouds: %d named Gaia stars, %d in the SMC",
        at.size,
        sum(c.name == "SMC" for c in clouds),
    )
    return rows(
        ra[at],
        dec[at],
        [(*GAIA_DR3, str(i)) for i in ids],
        distance,
        distance - error,
        distance + error,
        ["galaxy"] * at.size,
    )


def bailer_jones_rows(
    named: pa.Table, path: Path = bailer_jones.OUT_DIR / bailer_jones.OUT_FILE
) -> pa.Table:
    """The geometric distances of the gaia_named stars, at their positions."""
    found = pq.read_table(path)
    at = pc.index_in(found["source_id"], value_set=named["source_id"])
    found = found.filter(pc.is_valid(at))
    at = at.drop_null()
    return rows(
        named["ra"].take(at).to_numpy(),
        named["dec"].take(at).to_numpy(),
        [(*GAIA_DR3, str(i)) for i in found["source_id"].to_pylist()],
        found["r_med_geo"].to_numpy(zero_copy_only=False),
        found["r_lo_geo"].to_numpy(zero_copy_only=False),
        found["r_hi_geo"].to_numpy(zero_copy_only=False),
        ["geometric"] * found.num_rows,
    )


def simbad_parallax_rows(stars: SimbadList, named: pa.Table) -> pa.Table:
    """The 5σ SIMBAD parallaxes of the gaia_named stars, at their positions.
    Of two objects with one Gaia DR3 id, the smaller relative error wins."""
    at = {source_id: i for i, source_id in enumerate(named["source_id"].to_pylist())}
    best: dict[int, tuple[float, float]] = {}
    for found in stars.objects.values():
        if found.gaia is None or int(found.gaia) not in at:
            continue
        value, value_error = found.row.get("plx_value"), found.row.get("plx_err")
        if not value or not value_error:
            continue
        parallax, error = float(value), float(value_error)
        if not (error > 0 and parallax > gaia_source.MIN_PARALLAX_OVER_ERROR * error):
            continue
        kept = best.get(int(found.gaia))
        if kept is None or error / parallax < kept[1] / kept[0]:
            best[int(found.gaia)] = (parallax, error)
    ids = sorted(best)
    index = pa.array([at[i] for i in ids], pa.int64())
    distance, lower, upper = parallax_bounds(
        np.array([best[i][0] for i in ids], np.float64),
        np.array([best[i][1] for i in ids], np.float64),
    )
    logger.info("SIMBAD parallax: %d named Gaia stars", len(ids))
    return rows(
        named["ra"].take(index).to_numpy(),
        named["dec"].take(index).to_numpy(),
        [(*GAIA_DR3, str(i)) for i in ids],
        distance,
        lower,
        upper,
        ["parallax"] * len(ids),
    )
