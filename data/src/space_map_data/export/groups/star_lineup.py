"""The size and colour of a listed star, for the lineup of its page.

Gaia saturates on the brightest stars, so the best-known stars have no model
radius. The order is `measured_radius`, then the catalogue radius. Gaia fits
a normal star, so its radii do not count for a compact star: what it sees of
a pulsar is mostly the companion.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from space_map_data.constants.planets.families import SOLAR_RADIUS_KM
from space_map_data.constants.stars.literature import RADII, REFERENCES, Reference
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.extrasolar.render import bp_rp_from_v_i
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.stars import PREFIX
from space_map_data.extrasolar.measured_radius import MEASURED_COLUMNS, measured_radius
from space_map_data.extrasolar.sources.literature import LITERATURE, key_of
from space_map_data.extrasolar.tables import (
    METADATA,
    POINT_SOURCE,
    SYSTEM,
)

logger = logging.getLogger(__name__)

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
COMPACT_FAMILIES = ("neutron-star", "white-dwarf")
# A star's radius is known to a few percent at best.
RADIUS_DIGITS = 3

COLUMNS = [
    *MEASURED_COLUMNS,
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


def _paper(metadata: dict) -> Reference:
    """The work behind the radius of a star of the literature table."""
    ids = [c["catalogue_id"] for c in metadata["cross_ids"]]
    kinds = [c["catalogue"] for c in metadata["cross_ids"]]
    return REFERENCES[RADII[key_of(ids[kinds.index(LITERATURE.catalogue)])].reference]


def _radius(row: dict, compact: bool) -> tuple[float, str, Reference | None] | None:
    """The radius in solar radii, where it comes from, and the work behind it.
    A paper's work is in the star's metadata, so it is None here."""
    if (measured := measured_radius(row)) is not None:
        radius, source = measured
        return radius, source, None if source == "literature" else JMDC
    if row["host_radius"]:
        return row["host_radius"], "catalogue", NASA_EXOPLANET_ARCHIVE
    radius = row["radius_flame"] or row["radius_gspphot"]
    return (radius, "catalogue", GAIA_DR3) if radius and not compact else None


def _size(metadata: dict, row: dict, compact: bool = False) -> _Size | None:
    if (found := _radius(row, compact)) is None:
        return None
    radius, source, reference = found
    return _Size(radius, source, reference or _paper(metadata))


def _radius_km(radius_sun: float) -> float:
    return float(f"{radius_sun * SOLAR_RADIUS_KM:.{RADIUS_DIGITS}g}")


def _bp_rp(row: dict) -> float | None:
    """As the render tree colours the star, before it falls back on Teff."""
    bp, rp = row["phot_bp_mean_mag"], row["phot_rp_mean_mag"]
    if bp is not None and rp is not None:
        return round(bp - rp, 3)
    if row["v_i"] is None:
        return None
    return round(float(bp_rp_from_v_i(np.array([row["v_i"]]))[0]), 3)


def _compact_families(reader: ExportReader) -> int:
    """The bits of `COMPACT_FAMILIES` in a star's `families`."""
    order = [entry["slug"] for entry in reader.metadata["families"]]
    return sum(1 << order.index(family) for family in COMPACT_FAMILIES)


def drawable_star_radii(reader: ExportReader, ids: list[int]) -> dict[int, float]:
    """The radius in km of each of `ids` a row of stars can draw: those with a
    size and a colour, as `starObject` in the frontend's `compare/geometry.ts`
    asks. A star system stands for its main star."""
    points = reader.rows(POINT_SOURCE.slug, ids, COLUMNS)
    nodes = reader.rows(
        SYSTEM.slug, [id_ for id_ in ids if id_ not in points], ["primary"]
    )
    primaries = {
        id_: row["primary"] for id_, row in nodes.items() if row["primary"] is not None
    }
    points |= reader.rows(
        POINT_SOURCE.slug, sorted({*primaries.values()} - points.keys()), COLUMNS
    )
    metadata = reader.rows(
        METADATA.slug, list(points), ["families", "families_estimated"]
    )
    compact = _compact_families(reader)

    def radius_km(id_: int) -> float | None:
        row = points.get(id_)
        if row is None:
            return None
        tags = metadata[id_]["families"] | metadata[id_]["families_estimated"]
        found = _radius(row, bool(tags & compact))
        if found is None:
            return None
        if not (row["host_teff"] or row["teff_gspphot"]) and _bp_rp(row) is None:
            return None
        return _radius_km(found[0])

    radii = {id_: radius_km(primaries.get(id_, id_)) for id_ in ids}
    return {id_: radius for id_, radius in radii.items() if radius is not None}


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
    compact = _compact_families(reader)
    rows = reader.rows(POINT_SOURCE.slug, ids, COLUMNS)
    sized: dict[str, int] = defaultdict(int)
    for id_, row in rows.items():
        tags = metadata[id_]["families"] | metadata[id_]["families_estimated"]
        size = _size(metadata[id_], row, bool(tags & compact))
        if size is None:
            continue
        sized[size.source] += 1
        radius_km = _radius_km(size.radius_sun)
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
