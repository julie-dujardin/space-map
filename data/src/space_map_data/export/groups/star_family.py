"""Star family (``star-``) group pages, and the Stars category page.

One page per family of ``constants/stars/families.py``. The extrasolar export
tags the stars, so the counts and the stars that a page lists come from its
served files, as the planets of the sitemap do: a page then tells what the
site serves. A page lists the stars with a Wikipedia article first, then the
brightest other stars of the family, which the extrasolar export picks.

The Stars category page stands for the root family. It counts every star, but
no node of a star system, and the classified ones are those of the root
family. Its diagram plots a random sample of the stars.
"""

import gzip
import json
import logging
import random
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path

import numpy as np
import orjson

from space_map_data.constants.categories import STARS_SLUG
from space_map_data.constants.stars.families import (
    FAMILIES,
    FAMILY_SLUG_PREFIX,
    PARENTS,
    ROOT_FAMILY,
    SUN_ABSOLUTE_G,
    SUN_BP_RP,
    SUN_SPECTRAL_TYPE,
)
from space_map_data.export.extrasolar.build import families_file, served
from space_map_data.export.extrasolar.container import Container
from space_map_data.export.extrasolar.radius import FLAME, FLAME_SPEC, GSPPHOT
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.extrasolar.tiles import LISTED_STARS
from space_map_data.export.groups.family_pages import (
    FamilyGroups,
    FamilyPages,
    object_sitelink_rank,
    served_metadata,
    sitelink_rank,
)
from space_map_data.export.groups.star_lineup import RADIUS_COLUMNS, add_lineup_fields
from space_map_data.export.groups.stats import GroupExtraStats
from space_map_data.export.names import Names, ObjectNames
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.stars import PREFIX, TYPE, StarObject
from space_map_data.extrasolar.families import of_spectral_type
from space_map_data.extrasolar.measured_radius import MEASURED_SOURCES
from space_map_data.extrasolar.tables import METADATA, POINT_SOURCE, SYSTEM
from space_map_data.utils.content_stamp import content_stamp
from space_map_data.utils.paths import EXTRASOLAR_DIR

logger = logging.getLogger(__name__)

PAGES = FamilyPages(
    FAMILY_SLUG_PREFIX,
    {f: parents for f, parents in PARENTS.items() if parents != (ROOT_FAMILY,)},
    "published_star_count",
    "estimated_star_count",
    root=STARS_SLUG,
)


PLOT_FILE = "__star_plot__.json.gz"
# A tile holds about 400 stars of a part of the sky that the export sizes by
# star count, so random tiles are a random sample of the stars.
PLOT_TILES = 60
PLOT_SEED = 1
PLOT_DIGITS = 3
# The stage of a plotted star: the first of these that it has.
PLOT_STAGES = ("white-dwarf", "supergiant", "giant", "subgiant", "main-sequence")
# A card quotes a star's Metadata radius when that value is precise: a
# measurement, a planet catalogue's radius whose error is within
# CARD_PRECISION of it, or a FLAME radius whose bounds are. A radius with no
# error is not precise. A GSP-Phot radius is never precise. Alone, it gave
# CM Vel 1416 ± 1 R☉ at log g −0.5, which no measurement backs.
FLAME_BOUNDS = {
    FLAME: ("radius_flame_lower", "radius_flame_upper"),
    FLAME_SPEC: ("radius_flame_spec_lower", "radius_flame_spec_upper"),
}
# As on the planet cards: a card shows no uncertainty.
CARD_PRECISION = 0.1


def star_pages(families: Iterable[str]) -> list[str]:
    """The pages that a star of `families` is on. The root family has no page."""
    return PAGES.pages_of(family for family in families if family != ROOT_FAMILY)


@dataclass
class StarGroups(FamilyGroups):
    """The family pages and the Stars page."""

    # The names of the star that the stat card names, by object id.
    card_names: dict[str, Names] = field(default_factory=dict)
    # Columns of PLOT_FILE.
    plot: dict | None = None


def served_families_stamp(extrasolar_dir: Path = EXTRASOLAR_DIR) -> dict | None:
    """The family counts, the star count, a stamp of the family lists and the
    Metadata, Point source and System tokens of the served extrasolar export,
    None with no export served. The pages read the counts and the lists, the
    families and radii of their stars from the Metadata tiles, the diagram and
    the colours from the Point source tiles, and the held stars' values from
    the System tiles."""
    # Under the lock, so both files come from one export.
    with served(extrasolar_dir):
        metadata = served_metadata(extrasolar_dir)
        if metadata is None:
            return None
        return {
            "families": metadata["families"],
            "stars": metadata["objects"]["star"]["count"],
            "lists": content_stamp(families_file(extrasolar_dir / "v1" / "x")),
            "metadata": metadata["tables"]["metadata"]["token"],
            "point_source": metadata["tables"][POINT_SOURCE.slug]["token"],
            "system": metadata["tables"][SYSTEM.slug]["token"],
        }


def build_star_family_groups(
    star_objects: list[StarObject],
    names: ObjectNames,
    extrasolar_dir: Path = EXTRASOLAR_DIR,
    sun: NotableObject | None = None,
) -> StarGroups:
    """Counts, child families and listed stars of every star- page and of the
    Stars page.

    With no extrasolar export served, the pages have their text only. The
    Sun is in no catalogue of that export, so `sun` adds it to the families
    of its spectral type.
    """
    out = StarGroups()
    sun_families = set(of_spectral_type(SUN_SPECTRAL_TYPE)) if sun else set()
    root = extrasolar_dir / "v1" / "x"
    with served(extrasolar_dir):
        if not (root / "metadata.json").exists():
            logger.warning("Star family pages without stars: no export at %s", root)
            return out
        reader = ExportReader(root)
        listed = reader.metadata["families"]
        star_count = reader.metadata["objects"]["star"]["count"]
        out.notable_members = _notable_stars(
            reader,
            [entry["slug"] for entry in listed],
            star_objects,
            names,
            sun,
        )
        add_lineup_fields(reader, out.notable_members)
        largest = _largest_star(reader, star_objects, names)
        out.plot = _plot(reader, out.notable_members.get(STARS_SLUG, []))

    counts = {
        entry["slug"]: (
            entry["published"] + (entry["slug"] in sun_families),
            entry["estimated"],
        )
        for entry in listed
    }
    root_published, root_estimated = counts.pop(ROOT_FAMILY)
    PAGES.count(out, ((family, *n) for family, n in counts.items()))
    out.member_counts[STARS_SLUG] = star_count + bool(sun)
    out.extra_stats[STARS_SLUG] = GroupExtraStats(
        published_star_count=root_published,
        estimated_star_count=root_estimated,
    )
    if largest is not None:
        card, page = largest
        out.extra_stats[STARS_SLUG].largest_star = card
        out.card_names[card["primary_id"]] = page
    logger.info(
        "Star family pages: %d families, %d with stars, %d with listed stars",
        len(FAMILIES),
        sum(1 for n in out.member_counts.values() if n),
        len(out.notable_members),
    )
    return out


def _card_radius(size: dict, error: float | None) -> float | None:
    """The radius of a star that a card can show, in R☉, from its Metadata
    `size` and the larger error of that value."""
    value, source = size["radius"], size["radius_source"]
    if value is None or source == GSPPHOT:
        return None
    if source in MEASURED_SOURCES:
        return value
    precise = error is not None and error <= CARD_PRECISION * value
    return value if precise else None


def _radius_errors(reader: ExportReader, sizes: dict[int, dict]) -> dict[int, float]:
    """The larger error of the Metadata radius of each star of `sizes` that a
    FLAME or a planet catalogue radius has: FLAME's bounds or the catalogue's
    error, on the Point source row, else on the held star's System row. A held
    star's FLAME radius is that of the point it stands for, so the bounds are
    on that point's row. FLAME stands for either FLAME run."""
    wanted = [
        id_
        for id_, size in sizes.items()
        if size["radius"] is not None
        and size["radius_source"] not in (*MEASURED_SOURCES, GSPPHOT)
    ]
    columns = [c for bounds in FLAME_BOUNDS.values() for c in bounds]
    points = reader.rows(POINT_SOURCE.slug, wanted, [*columns, "host_radius_error"])
    held = reader.rows(
        SYSTEM.slug, [i for i in wanted if i not in points], ["parent", "star"]
    )
    fitted = {
        id_: row["parent"]
        for id_, row in held.items()
        if sizes[id_]["radius_source"] in FLAME_BOUNDS
    }
    fits = reader.rows(POINT_SOURCE.slug, sorted(set(fitted.values())), columns)
    out: dict[int, float] = {}
    for id_ in wanted:
        value, source = sizes[id_]["radius"], sizes[id_]["radius_source"]
        if id_ in points:
            row = points[id_]
        elif id_ in fitted:
            row = fits.get(fitted[id_], {})
        elif id_ in held:
            # The tiles serve a struct as a list of at most one item.
            row = held[id_]["star"][0]
        else:
            continue
        if source not in FLAME_BOUNDS:
            error = row.get("host_radius_error")
        elif None not in (bounds := [row.get(c) for c in FLAME_BOUNDS[source]]):
            error = max(bounds[1] - value, value - bounds[0])
        else:
            error = None
        if error is not None:
            out[id_] = error
    return out


def _largest_star(
    reader: ExportReader, star_objects: list[StarObject], names: ObjectNames
) -> tuple[dict, Names] | None:
    """The star with an entry and the largest radius that a card can show
    (`_card_radius`), as {primary_type, primary_id, name, radius_sun}, and the
    names of its page.

    The stars with an entry only: the tiles of every star are too many to read
    here, and an unknown star on the card would say little. A system is no
    star, so it has no radius."""
    entries = {star.id: star for star in star_objects if star.object_type == TYPE}
    sizes = reader.rows(METADATA.slug, sorted(entries), RADIUS_COLUMNS)
    errors = _radius_errors(reader, sizes)
    radii = {
        id_: radius
        for id_, size in sizes.items()
        if (radius := _card_radius(size, errors.get(id_)))
    }
    if not radii:
        return None
    best = max(radii, key=lambda id_: (radii[id_], id_))
    page = names.star(entries[best])
    return {
        "primary_type": "object",
        "primary_id": f"{PREFIX}{best}",
        "name": page.name,
        "radius_sun": _round(radii[best]),
    }, page


def _round(x: float) -> float:
    return float(f"{x:.{PLOT_DIGITS + 1}g}")


def _colour_and_magnitude(tile: Container) -> tuple[np.ndarray, np.ndarray]:
    """BP−RP and absolute G of each row of a Point source tile, NaN without
    a positive parallax or a colour. No extinction is removed: Gaia's
    estimate of it is missing for one star in eight."""

    def number(name: str) -> np.ndarray:
        return tile.column(name).to_numpy(zero_copy_only=False).astype(float)

    parallax = number("parallax")
    parallax[parallax <= 0] = np.nan
    return (
        number("phot_bp_mean_mag") - number("phot_rp_mean_mag"),
        number("phot_g_mean_mag") + 5 * np.log10(parallax / 100),
    )


def _plot(reader: ExportReader, listed: list[NotableObject]) -> dict:
    """Columns of a random sample of the stars: BP−RP, absolute G and an index
    into `stages`, null with none of them. `named` holds the listed stars with
    both values, and the Sun."""
    leaves = len(reader.split(POINT_SOURCE.slug).level)
    chosen = random.Random(PLOT_SEED).sample(range(leaves), min(PLOT_TILES, leaves))
    ids, colours, magnitudes = [], [], []
    for leaf in chosen:
        tile = reader.leaf(POINT_SOURCE.slug, leaf)
        colour, magnitude = _colour_and_magnitude(tile)
        at = np.flatnonzero(np.isfinite(colour) & np.isfinite(magnitude))
        ids.append(tile.numpy("id")[at])
        colours.append(colour[at])
        magnitudes.append(magnitude[at])
    star_ids = np.concatenate(ids).tolist()
    rows = reader.rows(METADATA.slug, star_ids, ["families", "families_estimated"])
    order = [entry["slug"] for entry in reader.metadata["families"]]
    bits = [1 << order.index(stage) for stage in PLOT_STAGES]

    def stage(id_: int) -> int | None:
        row = rows.get(id_)
        mask = (row["families"] | row["families_estimated"]) if row else 0
        return next((n for n, bit in enumerate(bits) if mask & bit), None)

    named = [{"id": "naif-10", "bp_rp": SUN_BP_RP, "abs_g": SUN_ABSOLUTE_G}]
    found = [
        int(member.object_id.removeprefix(PREFIX))
        for member in listed
        if member.object_id.startswith(PREFIX)
    ]
    for id_, values in _listed_values(reader, found).items():
        named.append({"id": f"{PREFIX}{id_}", **values})
    return {
        "bp_rp": np.round(np.concatenate(colours), PLOT_DIGITS).tolist(),
        "abs_g": np.round(np.concatenate(magnitudes), PLOT_DIGITS).tolist(),
        "stage": [stage(id_) for id_ in star_ids],
        "stages": list(PLOT_STAGES),
        "named": named,
    }


def _listed_values(reader: ExportReader, ids: list[int]) -> dict[int, dict]:
    """BP−RP and absolute G of each of `ids` that has both. Gaia saturates on
    the brightest stars, so many have none."""
    columns = ["parallax", "phot_g_mean_mag", "phot_bp_mean_mag", "phot_rp_mean_mag"]
    out = {}
    for id_, row in reader.rows(POINT_SOURCE.slug, ids, columns).items():
        if None in row.values() or row["parallax"] <= 0:
            continue
        out[id_] = {
            "bp_rp": round(
                row["phot_bp_mean_mag"] - row["phot_rp_mean_mag"], PLOT_DIGITS
            ),
            "abs_g": round(
                row["phot_g_mean_mag"] + 5 * np.log10(row["parallax"] / 100).item(),
                PLOT_DIGITS,
            ),
        }
    return out


def write_star_plot(out_dir: Path, plot: dict) -> None:
    """Write groups/__star_plot__.json.gz."""
    path = out_dir / "groups" / PLOT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(orjson.dumps(plot)))
    logger.info("Wrote the star plot: %d stars → %s", len(plot["stage"]), path.name)


def _notable_stars(
    reader: ExportReader,
    bits: list[str],
    star_objects: list[StarObject],
    names: ObjectNames,
    sun: NotableObject | None,
) -> dict[str, list[NotableObject]]:
    """The stars that each family lists, and the best-known stars of the
    Stars page. A published family only: a page lists what catalogues say.

    The stars with a Wikipedia article and the Sun come first, most sitelinks
    first. The brightest other stars of the family fill the rest of the list
    (`_add_brightest`)."""
    wikidata_entities = names.entities
    entries = {star.id: star for star in star_objects}
    stars = {id_: star for id_, star in entries.items() if star.qid}
    rows = reader.rows(METADATA.slug, sorted(stars), ["families"])
    if missing := len(stars) - len(rows):
        logger.info("Star family pages: %d stars with an entry are not served", missing)
    tagged = [id_ for id_, row in rows.items() if row["families"]]
    rank = partial(sitelink_rank, wikidata_entities)
    with ThreadPoolExecutor(8) as pool:
        ranks = dict(zip(tagged, pool.map(rank, [stars[id_].qid for id_ in tagged])))

    def member(id_: int, sitelinks: int) -> NotableObject:
        return NotableObject(
            object_id=f"{PREFIX}{id_}",
            wikidata_qid=stars[id_].qid,
            names=names.star(stars[id_]),
            diameter_km=None,
            first_obs=None,
            extrasolar=True,
            sitelinks_count=sitelinks,
        )

    # A star gets its names only when a list takes it: the names read its
    # item into the shared LRU, and most tagged stars are in no list.
    ranked: list[tuple[int, int, str, Callable[[], NotableObject]]] = [
        (
            sitelinks,
            rows[id_]["families"],
            f"{PREFIX}{id_}",
            partial(member, id_, sitelinks),
        )
        for id_, (sitelinks, article) in ranks.items()
        if article
    ]
    if sun is not None:
        sitelinks, _ = object_sitelink_rank(wikidata_entities, sun.wikidata_qid)
        families = set(of_spectral_type(SUN_SPECTRAL_TYPE))
        mask = sum(1 << bit for bit, family in enumerate(bits) if family in families)
        listed_sun = replace(sun, sitelinks_count=sitelinks)
        ranked.append((sitelinks, mask, sun.object_id, lambda: listed_sun))
    ranked.sort(key=lambda each: (-each[0], each[2]))
    out: dict[str, list[NotableObject]] = defaultdict(list)
    for _, mask, _, make in ranked:
        found = None
        for bit, family in enumerate(bits):
            members = out[STARS_SLUG if family == ROOT_FAMILY else PAGES.slug(family)]
            if mask >> bit & 1 and len(members) < LISTED_STARS:
                if found is None:
                    found = make()
                members.append(found)
    _add_brightest(reader, out, entries, names)
    return {slug: members for slug, members in out.items() if members}


def _add_brightest(
    reader: ExportReader,
    out: dict[str, list[NotableObject]],
    entries: dict[int, StarObject],
    names: ObjectNames,
) -> None:
    """Fill each list up to LISTED_STARS with the brightest stars of its
    family in FAMILIES_FILE that it does not list yet. A star with no entry
    takes the name of its Metadata row, as its own page does."""
    brightest = json.loads(families_file(reader.root).read_text())["brightest"]
    published = {
        entry["slug"]: entry["published"] for entry in reader.metadata["families"]
    }
    added = 0
    short = []
    for family, stars in brightest.items():
        members = out[PAGES.slug(family)]
        known = {member.object_id for member in members}
        for star in stars:
            if len(members) >= LISTED_STARS:
                break
            object_id = f"{PREFIX}{star['id']}"
            if object_id in known:
                continue
            found = entries.get(star["id"])
            members.append(
                NotableObject(
                    object_id=object_id,
                    wikidata_qid=found.qid if found else None,
                    names=(
                        names.star(found)
                        if found
                        else Names(star["name"] or str(star["id"]))
                    ),
                    diameter_km=None,
                    first_obs=None,
                    extrasolar=True,
                )
            )
            added += 1
        wanted = min(LISTED_STARS, published[family])
        if len(members) < wanted:
            short.append(f"{family} {len(members)}/{wanted}")
    logger.info("Star family pages: %d of the brightest stars added", added)
    # The export fills each list, but leaves out held stars with no magnitude.
    # So a short list means that, or that the two files disagree.
    if short:
        logger.warning("Star family pages short of their family: %s", ", ".join(short))
