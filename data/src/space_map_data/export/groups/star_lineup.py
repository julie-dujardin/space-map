"""The size and colour of a listed star, for the lineup of its page.

The size is the star's `radius` in its Metadata row, which the extrasolar
export takes from `export.extrasolar.radius`, and its work follows
`radius_source`. A paper's work is that of the paper's star: the star of a
literature cross-id, else the pair of a held star, which its System row cites
first, else the point whose measurement the held star takes. A paper radius
that none of these traces credits no work. The colour comes from the Point
source row, as the render tree colours the star. A held star has no Point
source row: its Teff is the one of its System row.
"""

import logging
from collections import defaultdict

import numpy as np

from space_map_data.constants.planets.families import SOLAR_RADIUS_KM
from space_map_data.constants.stars import binaries
from space_map_data.constants.stars.literature import RADII, REFERENCES, Reference
from space_map_data.export.extrasolar.radius import FLAME, FLAME_SPEC, GSPPHOT
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.extrasolar.render import bp_rp_from_v_i
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.stars import PREFIX
from space_map_data.extrasolar.exoplanets.catalogues import ARCHIVE, EU, OEC
from space_map_data.extrasolar.sources.jmdc import JMDC as JMDC_SOURCE
from space_map_data.extrasolar.sources.literature import LITERATURE, key_of
from space_map_data.extrasolar.tables import METADATA, POINT_SOURCE, SYSTEM

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
# A star's radius is known to a few percent at best.
RADIUS_DIGITS = 3
# The work behind a radius of each source other than a paper.
WORKS = {
    JMDC_SOURCE.name: JMDC,
    ARCHIVE: Reference(
        "NASA Exoplanet Archive",
        "NASA Exoplanet Archive",
        "https://exoplanetarchive.ipac.caltech.edu",
    ),
    EU: Reference(
        "Schneider et al. 2011",
        "The Extrasolar Planets Encyclopaedia",
        "https://exoplanet.eu/",
    ),
    OEC: Reference(
        "Rein 2012",
        "Open Exoplanet Catalogue",
        "https://github.com/OpenExoplanetCatalogue/open_exoplanet_catalogue",
    ),
    FLAME: GAIA_DR3,
    FLAME_SPEC: GAIA_DR3,
    GSPPHOT: GAIA_DR3,
}
RADIUS_COLUMNS = ["radius", "radius_source"]
COLOUR_COLUMNS = [
    "host_teff",
    "teff_gspphot",
    "phot_bp_mean_mag",
    "phot_rp_mean_mag",
    "v_i",
]


def _literature_key(cross_ids: list[dict]) -> str | None:
    return next(
        (
            c["catalogue_id"]
            for c in cross_ids
            if c["catalogue"] == LITERATURE.catalogue
        ),
        None,
    )


def _works(reader: ExportReader, metadata: dict[int, dict]) -> dict[int, Reference]:
    """The work behind the radius of each star of `metadata`, which has
    `cross_ids` and RADIUS_COLUMNS. A paper radius that no paper traces has
    none."""
    papers = {
        id_: key
        for id_, row in metadata.items()
        if row["radius_source"] == LITERATURE.name
        and (key := _literature_key(row["cross_ids"])) is not None
    }
    held_ids = [
        id_
        for id_, row in metadata.items()
        if row["radius_source"] == LITERATURE.name and id_ not in papers
    ]
    held = reader.rows(SYSTEM.slug, held_ids, ["parent", "star"])
    # The tiles serve a struct as a list of at most one item.
    stars = {id_: row["star"][0] for id_, row in held.items() if row["star"]}
    pairs = {
        id_: work
        for id_, star in stars.items()
        if star["radius_source"] == LITERATURE.name
        and (
            work := next(
                (
                    r["reference"]
                    for r in star["references"] or []
                    if r["source"] == LITERATURE.name
                ),
                None,
            )
        )
        is not None
    }
    parents = {
        id_: row["parent"]
        for id_, row in held.items()
        if id_ in stars
        and stars[id_]["radius_source"] != LITERATURE.name
        and row["parent"] is not None
    }
    points = reader.rows(METADATA.slug, sorted(set(parents.values())), ["cross_ids"])
    for id_, parent in parents.items():
        found = points.get(parent)
        if found and (key := _literature_key(found["cross_ids"] or [])) is not None:
            papers[id_] = key
    out = {id_: REFERENCES[RADII[key_of(key)].reference] for id_, key in papers.items()}
    out |= {id_: binaries.REFERENCES[work] for id_, work in pairs.items()}
    out |= {
        id_: WORKS[row["radius_source"]]
        for id_, row in metadata.items()
        if row["radius_source"] in WORKS and id_ not in out
    }
    untraced = [
        id_
        for id_, row in metadata.items()
        if row["radius"] is not None and id_ not in out
    ]
    if untraced:
        logger.warning(
            "Star lineup: %d radii credit no work: no paper traces them, e.g. %s",
            len(untraced),
            untraced[:5],
        )
    return out


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


def _colours(reader: ExportReader, ids: list[int]) -> dict[int, tuple]:
    """(Teff, BP − RP) of each of `ids`: of its Point source row, else the
    Teff of its System row."""
    points = reader.rows(POINT_SOURCE.slug, ids, COLOUR_COLUMNS)
    held = reader.rows(SYSTEM.slug, [i for i in ids if i not in points], ["star"])
    out = {
        id_: (row["host_teff"] or row["teff_gspphot"], _bp_rp(row))
        for id_, row in points.items()
    }
    # The tiles serve a struct as a list of at most one item.
    for id_, row in held.items():
        if row["star"]:
            out[id_] = (row["star"][0]["teff"], None)
    return out


def stand_ins(reader: ExportReader, ids: list[int]) -> dict[int, int]:
    """The star that each of `ids` stands for where a star is sized: a
    resolved star system its primary, and a point that holds several stars
    its first member when that held star dominates the point's light
    (`star.dominant`). A point whose light can blend stands for no one star,
    so it stands for itself, at its own radius."""
    nodes = reader.rows(SYSTEM.slug, ids, ["primary"])
    main = {
        id_: node["primary"] if node["primary"] is not None else id_
        for id_, node in nodes.items()
    }
    points = reader.rows(SYSTEM.slug, sorted(set(main.values())), ["point", "members"])
    first = {
        id_: row["members"][0]["id"]
        for id_, row in points.items()
        if row["point"] and row["members"] and row["members"][0]["id"] is not None
    }
    held = reader.rows(SYSTEM.slug, sorted(set(first.values())), ["star"])
    # The tiles serve a struct as a list of at most one item.
    lead = {
        id_: member
        for id_, member in first.items()
        if (star := held.get(member, {}).get("star")) and star[0]["dominant"]
    }
    out = {id_: main.get(id_, id_) for id_ in ids}
    return {id_: lead.get(star, star) for id_, star in out.items()}


def drawable_star_radii(reader: ExportReader, ids: list[int]) -> dict[int, float]:
    """The radius in km of each of `ids` a row of stars can draw: those with a
    size and a colour, as `starObject` in the frontend's `compare/geometry.ts`
    asks. The size is that of the star that it stands for (`stand_ins`), and
    the colour that star's, else its own: a point's light is its dominant
    star's."""
    main = stand_ins(reader, ids)
    sizes = reader.rows(METADATA.slug, sorted(set(main.values())), RADIUS_COLUMNS)
    sized = [id_ for id_ in ids if sizes.get(main[id_], {}).get("radius")]
    colours = _colours(reader, sorted({i for id_ in sized for i in (id_, main[id_])}))

    def coloured(id_: int) -> bool:
        return any(
            value is not None
            for star in (main[id_], id_)
            for value in colours.get(star, (None, None))
        )

    return {
        id_: _radius_km(sizes[main[id_]]["radius"]) for id_ in sized if coloured(id_)
    }


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
    metadata = reader.rows(METADATA.slug, ids, ["cross_ids", *RADIUS_COLUMNS])
    sized_ids = [id_ for id_, row in metadata.items() if row["radius"] is not None]
    colours = _colours(reader, sized_ids)
    works = _works(reader, {id_: metadata[id_] for id_ in sized_ids})
    sized: dict[str, int] = defaultdict(int)
    for id_ in sized_ids:
        row = metadata[id_]
        sized[row["radius_source"]] += 1
        radius_km = _radius_km(row["radius"])
        member = members[f"{PREFIX}{id_}"]
        member.radii = {
            "a": radius_km,
            "b": radius_km,
            "c": radius_km,
            "source": row["radius_source"],
        }
        if id_ in works:
            member.radii["reference"] = dict(works[id_]._asdict())
        member.teff, member.bp_rp = colours.get(id_, (None, None))
    logger.info(
        "Star lineup: %d of %d stars sized %s",
        sum(sized.values()),
        len(ids),
        dict(sized),
    )
