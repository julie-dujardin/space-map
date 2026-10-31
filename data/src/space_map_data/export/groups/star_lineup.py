"""The size and colour of a listed star, for the lineup of its page.

Gaia saturates on the brightest stars, so the best-known stars have no radius
in the Point source table. JMDC holds their measured angular diameters, which
the star's distance turns into a radius. So the order is: a paper
(`RADII` in `constants/stars/literature.py`), then JMDC, then the radius that
the star page shows (`starRadiusKm` in the frontend). Gaia fits a normal star,
so its radii do not count for a compact star: what it sees of a pulsar is
mostly the companion.
"""

import gzip
import logging
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from space_map_data.constants.stars.literature import RADII, REFERENCES, Reference
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.extrasolar.render import bp_rp_from_v_i
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.stars import PREFIX
from space_map_data.extrasolar.sources.literature import LITERATURE
from space_map_data.extrasolar.tables import METADATA, POINT_SOURCE
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

JMDC_FILE = SOURCES_STARS_DIR / "cds" / "II" / "345" / "jmdc.dat.gz"
JMDC = Reference(
    "Duvert 2016",
    "JMDC: JMMC Measured Stellar Diameters Catalogue (VizieR II/345)",
    "https://cdsarc.cds.unistra.fr/viz-bin/cat/II/345",
)
GAIA_DR3 = Reference(
    "Gaia Collaboration 2023",
    "Gaia Data Release 3: summary of the content and survey properties",
    "https://doi.org/10.1051/0004-6361/202243940",
)
NASA_EXOPLANET_ARCHIVE = Reference(
    "NASA Exoplanet Archive",
    "NASA Exoplanet Archive",
    "https://exoplanetarchive.ipac.caltech.edu",
)
# Mid-infrared rows see the dust around a giant, not its surface.
FIRST_DUST_BAND = 11
# A diameter becomes a radius by a paper's distance or a parallax of this many
# sigma: the distance of a saturated supergiant from a prior can be off tenfold.
MIN_PARALLAX_SIGMA = 5
COMPACT_FAMILIES = ("neutron-star", "white-dwarf")
# The name of a JMDC row that holds no HD number, with that number.
JMDC_HD = {"CCDM J16294-2626 AB": "148478"}  # Antares
SOLAR_RADIUS_KM = 695700.0
# A star's radius is known to a few percent at best.
RADIUS_DIGITS = 3
MAS_TO_RAD = np.pi / 180 / 3.6e6
KM_PER_PC = 3.0856775814914e13

COLUMNS = [
    "parallax",
    "parallax_error",
    "distance",
    "distance_source",
    "host_radius",
    "radius_flame",
    "radius_gspphot",
    "host_teff",
    "teff_gspphot",
    "phot_bp_mean_mag",
    "phot_rp_mean_mag",
    "v_i",
]


@dataclass
class _Size:
    radius_sun: float
    source: str
    reference: Reference


def measured_diameters(path: Path = JMDC_FILE) -> dict[str, float]:
    """The median angular diameter (mas) of each star of JMDC by HD number,
    limb-darkened where the row gives it, else uniform-disk. A median: the
    rows run from Michelson's to CHARA's, and a star's rows can disagree."""
    rows: dict[str, list[float]] = defaultdict(list)
    with gzip.open(path, "rt", encoding="latin-1") as lines:
        for line in lines:
            band = line[106:108].strip()
            if band.isdigit() and int(band) >= FIRST_DUST_BAND:
                continue
            value = _float(line[68:75]) or _float(line[58:67])
            name = line[:28].strip()
            match = re.fullmatch(r"HD\s*0*(\d+)", name)
            hd = match[1] if match else JMDC_HD.get(name)
            if value and hd:
                rows[hd].append(value)
    return {hd: statistics.median(values) for hd, values in rows.items()}


def _float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _distance_pc(row: dict) -> float | None:
    if row["distance_source"] == LITERATURE.name:
        return row["distance"]
    parallax, error = row["parallax"], row["parallax_error"]
    if parallax and error and parallax >= MIN_PARALLAX_SIGMA * error:
        return 1000 / parallax
    return None


def _size(
    metadata: dict, row: dict, diameters: dict[str, float], compact: bool = False
) -> _Size | None:
    keys = {
        (cross["catalogue"], cross["release"], cross["catalogue_id"].strip())
        for cross in metadata["cross_ids"]
    }
    for key in keys:
        if (paper := RADII.get(key)) is not None:
            return _Size(paper.value, "literature", REFERENCES[paper.reference])
    distance = _distance_pc(row)
    if distance:
        for _, _, hd in filter(lambda key: key[0] == "hd", keys):
            if hd in diameters:
                radius_km = diameters[hd] * MAS_TO_RAD / 2 * distance * KM_PER_PC
                return _Size(radius_km / SOLAR_RADIUS_KM, "interferometry", JMDC)
    if row["host_radius"]:
        return _Size(row["host_radius"], "catalogue", NASA_EXOPLANET_ARCHIVE)
    radius = row["radius_flame"] or row["radius_gspphot"]
    return _Size(radius, "catalogue", GAIA_DR3) if radius and not compact else None


def _bp_rp(row: dict) -> float | None:
    """As the render tree colours the star, before it falls back on Teff."""
    bp, rp = row["phot_bp_mean_mag"], row["phot_rp_mean_mag"]
    if bp is not None and rp is not None:
        return round(bp - rp, 3)
    if row["v_i"] is None:
        return None
    return round(float(bp_rp_from_v_i(np.array([row["v_i"]]))[0]), 3)


def add_lineup_fields(
    reader: ExportReader, listed: dict[str, list[NotableObject]]
) -> None:
    """Set `radii`, `teff` and `bp_rp` on the listed stars of the extrasolar
    export, which the lists share. A star with no size keeps none of them."""
    members = {
        member.object_id: member
        for page in listed.values()
        for member in page
        if member.extrasolar
    }
    ids = [int(object_id.removeprefix(PREFIX)) for object_id in members]
    metadata = reader.rows(
        METADATA.slug, ids, ["cross_ids", "families", "families_estimated"]
    )
    order = [entry["slug"] for entry in reader.metadata["families"]]
    compact = sum(1 << order.index(family) for family in COMPACT_FAMILIES)
    rows = reader.rows(POINT_SOURCE.slug, ids, COLUMNS)
    diameters = measured_diameters()
    sized: dict[str, int] = defaultdict(int)
    for id_, row in rows.items():
        tags = metadata[id_]["families"] | metadata[id_]["families_estimated"]
        size = _size(metadata[id_], row, diameters, bool(tags & compact))
        if size is None:
            continue
        sized[size.source] += 1
        radius_km = float(f"{size.radius_sun * SOLAR_RADIUS_KM:.{RADIUS_DIGITS}g}")
        member = members[f"{PREFIX}{id_}"]
        member.radii = {
            "a": radius_km,
            "b": radius_km,
            "c": radius_km,
            "source": size.source,
            "reference": dict(size.reference._asdict()),
        }
        member.teff = row["host_teff"] or row["teff_gspphot"]
        member.bp_rp = _bp_rp(row)
    logger.info(
        "Star lineup: %d of %d stars sized %s",
        sum(sized.values()),
        len(ids),
        dict(sized),
    )
