"""The Wikidata items of exoplanets, linked to the rows of the planets table.

The planets ingest links the items again each time and stores the QID as a
`wikidata/qid` cross id of the planet, as the star ingest does for stars, so
both exports and the images ingest read one link.

An item reaches a planet by its ids: its NASA archive name (P5667), which is
the planet's designation, and the slug of its exoplanet.eu page (P5653). An
item whose ids reach two planets links to neither: the catalogues letter some
systems differently, μ Ara among them. When several items reach one planet,
the item with the most articles keeps it, then the lowest QID.
"""

import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

import pyarrow as pa

from space_map_data.download.providers.exoplanets.wikidata import ExoplanetItem
from space_map_data.extrasolar.exoplanets.catalogues import EU
from space_map_data.extrasolar.exoplanets.numbering import Number
from space_map_data.extrasolar.sources.wikidata import WIKIDATA
from space_map_data.extrasolar.tables import CROSS_ID

logger = logging.getLogger(__name__)

# A page id ends in the page's number: `11_umi_b--575`.
_EU_PAGE_NUMBER = re.compile(r"--\d+$")


def eu_slug(text: str) -> str:
    """The slug of an exoplanet.eu name or page id, without the page number."""
    text = _EU_PAGE_NUMBER.sub("", text.strip())
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


@dataclass
class Links:
    # The QID of each planet that an item reaches alone.
    qid: dict[Number, str] = field(default_factory=dict)
    # The items whose ids reach several planets.
    several: list[str] = field(default_factory=list)
    unlinked: int = 0


def link_items(planets: pa.Table, items: Iterable[ExoplanetItem]) -> Links:
    """The planet that each item reaches alone."""
    by_archive: dict[str, set[Number]] = defaultdict(set)
    by_eu: dict[str, set[Number]] = defaultdict(set)
    for row in planets.select(
        ["host", "number", "designation", "cross_ids"]
    ).to_pylist():
        number = (row["host"], row["number"])
        if row["designation"]:
            by_archive[row["designation"]].add(number)
        for cross_id in row["cross_ids"]:
            if cross_id["catalogue"] == EU:
                by_eu[eu_slug(cross_id["catalogue_id"])].add(number)

    links = Links()
    best: dict[Number, ExoplanetItem] = {}
    for item in items:
        reached = set().union(
            *(by_archive.get(name, ()) for name in item.archive),
            *(by_eu.get(eu_slug(page), ()) for page in item.eu),
        )
        if len(reached) > 1:
            links.several.append(item.qid)
            continue
        if not reached:
            links.unlinked += 1
            continue
        (number,) = reached
        held = best.get(number)
        if held is None or (-item.articles, int(item.qid[1:])) < (
            -held.articles,
            int(held.qid[1:]),
        ):
            best[number] = item
    links.qid = {number: item.qid for number, item in best.items()}
    links.several.sort(key=lambda qid: int(qid[1:]))
    logger.info(
        "Wikidata: %d planets have an item; %d items reach no planet, %d reach"
        " several and link to none",
        len(links.qid),
        links.unlinked,
        len(links.several),
    )
    return links


def with_items(planets: pa.Table, links: Links) -> pa.Table:
    """The planets table with the QID of each linked planet in its cross ids."""
    cross_ids = []
    for host, number, ids in zip(
        planets["host"].to_pylist(),
        planets["number"].to_pylist(),
        planets["cross_ids"].to_pylist(),
    ):
        qid = links.qid.get((host, number))
        if qid is not None:
            ids = [
                *ids,
                {
                    "catalogue": WIKIDATA.catalogue,
                    "release": WIKIDATA.release,
                    "catalogue_id": qid,
                },
            ]
        cross_ids.append(ids)
    at = planets.schema.get_field_index("cross_ids")
    return planets.set_column(
        at, planets.schema.field(at), pa.array(cross_ids, pa.list_(CROSS_ID))
    )


def planet_qid(cross_ids: Iterable[dict]) -> str | None:
    """The QID that the ingest stored in a planet's cross ids, if any."""
    return next(
        (c["catalogue_id"] for c in cross_ids if c["catalogue"] == WIKIDATA.catalogue),
        None,
    )
