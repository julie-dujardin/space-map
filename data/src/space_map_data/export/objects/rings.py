"""Per-object ring catalogue, denormalized onto a ringed body's bundles.

The `rings[]` render bundle says what the scene draws; this says what the
rings *are* — every named ring, division, gap, ringlet, region and arc from
`constants/rings/catalog.py`, nested by `parent`.

Only eight bodies carry it, and the biggest table is Saturn's forty-odd rows,
so it rides the object's own bundles rather than a lazily-fetched tier.

PDS notes are language-independent and ship in the global block; Wikipedia
extracts go in the localized block. Coverage is thin — English Wikipedia
folds every ring into "Rings of X", so only the Cassini Division has its own
English article, while French and Italian cover nearly the full set.
"""

import logging
from collections.abc import Iterable
from functools import cache

from sqlalchemy.orm import Session, aliased

from space_map_data.constants.rings.attribution import RingSource
from space_map_data.constants.rings.catalog import (
    RING_CATALOGS,
    CatalogFeature,
    feature_mid,
    feature_span,
    feature_width,
)
from space_map_data.constants.rings.wikidata import (
    RING_FEATURE_PAGES,
    RING_SYSTEM_PAGES,
)
from space_map_data.export.images import collect_ring_images
from space_map_data.export.objects.wikipedia import load_wikipedia_summaries_for_qid
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object.main import Object, ObjectType

logger = logging.getLogger(__name__)


def feature_qids(body_id: str, slug: str) -> tuple[str, ...]:
    return RING_FEATURE_PAGES.get(f"{body_id}/{slug}", ())


@cache
def _summaries(qid: str):
    """Memoized per QID: the same feature is read once per language otherwise."""
    return load_wikipedia_summaries_for_qid(qid)


def load_ring_moon_ids(session: Session) -> dict[str, str]:
    """Object id per moon named in the catalogue, keyed "{host}/{moon name}".

    Scoped to the host's own system so the lookup can't match a same-named
    asteroid (4450 Pan vs Saturn's Pan). Only a barycentre parent is followed
    to find a planet's moons; small-body hosts are parented on the Sun, whose
    children aren't searched.
    """
    wanted = {
        (body, moon)
        for body, catalog in RING_CATALOGS.items()
        for feature in catalog.features
        for moon in feature.moons
    }
    parent = aliased(Object)
    hosts: dict[str, str] = {}
    for body, parent_id, parent_type in (
        session.query(Object.id, Object.parent_id, parent.object_type)
        .outerjoin(parent, Object.parent_id == parent.id)
        .filter(Object.id.in_(sorted(RING_CATALOGS)))
        .all()
    ):
        hosts[body] = body
        if parent_id is not None and parent_type == ObjectType.barycenter.value:
            hosts[parent_id] = body
    rows = (
        session.query(Object.id, Object.name, Object.parent_id)
        .filter(Object.parent_id.in_(sorted(hosts)))
        .filter(Object.name.in_(sorted({moon for _, moon in wanted})))
        .all()
    )
    found = {
        f"{hosts[parent]}/{name}": obj_id for obj_id, name, parent in rows if parent
    }
    if missing := sorted(f"{b}/{m}" for b, m in wanted if f"{b}/{m}" not in found):
        logger.warning(
            "Ring catalogue: %d associated moons unresolved, shipping names "
            "without links: %s",
            len(missing),
            ", ".join(missing),
        )
    return found


def _optical_depth(feature: CatalogFeature) -> dict | None:
    tau = feature.optical_depth
    if tau is None:
        return None
    block: dict = {"low": tau.low}
    if tau.high is not None:
        block["high"] = tau.high
    if tau.approximate:
        block["approximate"] = True
    if tau.upper_limit:
        block["upper_limit"] = True
    return block


def _feature_entry(
    body_id: str, feature: CatalogFeature, moon_ids: dict[str, str]
) -> dict:
    entry: dict = {"name": feature.name, "kind": feature.kind}
    if feature.parent:
        entry["parent"] = feature.parent
    if span := feature_span(feature):
        entry["inner_radius_km"], entry["outer_radius_km"] = span
    # Always present, derived from the boundaries where the source tabulates
    # those instead: the panel places every feature on one radial axis.
    entry["mid_radius_km"] = feature_mid(feature)
    if (width := feature_width(feature)) is not None:
        entry["width_km"] = width
    if feature.radius_approximate:
        entry["radius_approximate"] = True
    if (tau := _optical_depth(feature)) is not None:
        entry["optical_depth"] = tau
    for field in ("thickness_km", "eccentricity", "inclination_deg"):
        if (value := getattr(feature, field)) is not None:
            entry[field] = value
    if feature.designation:
        entry["designation"] = feature.designation
    if feature.particles:
        entry["particles"] = feature.particles
    if feature.moons:
        entry["moons"] = [
            {"name": moon, "id": moon_ids[key]}
            if (key := f"{body_id}/{moon}") in moon_ids
            else {"name": moon}
            for moon in feature.moons
        ]
    if qids := feature_qids(body_id, feature.slug):
        entry["wikidata_qid"] = qids[0]
    if feature.description:
        entry["note"] = feature.description
    return entry


def ring_features_block(
    body_id: str, moon_ids: dict[str, str]
) -> dict[str, dict] | None:
    """The body's catalogue rows, keyed by slug so lookups match the localized
    map, and emitted in the catalogue's radial order."""
    catalog = RING_CATALOGS.get(body_id)
    if catalog is None:
        return None
    return {f.slug: _feature_entry(body_id, f, moon_ids) for f in catalog.features}


def ring_mass_block(body_id: str) -> dict | None:
    """The system's total mass, shared with the Ring Systems collection page
    so both readers carry the same hedges."""
    catalog = RING_CATALOGS.get(body_id)
    if catalog is None or (mass := catalog.mass) is None:
        return None
    entry: dict = {"low_kg": mass.low_kg}
    if mass.high_kg is not None:
        entry["high_kg"] = mass.high_kg
    if mass.approximate:
        entry["approximate"] = True
    if mass.upper_limit:
        entry["upper_limit"] = True
    if mass.uncertainty_kg is not None:
        entry["uncertainty_kg"] = mass.uncertainty_kg
    return entry


def ring_stats_block(body_id: str) -> dict | None:
    """System-wide figures behind the Rings tab's stat cards.

    Named `ring_stats`, not `ring_system` — the localized bundle already uses
    that for the "Rings of X" article. Fields are absent where no source
    states them (e.g. Neptune's mass, most systems' vertical extent).
    """
    catalog = RING_CATALOGS.get(body_id)
    if catalog is None:
        return None
    block: dict = {}
    if catalog.discovery_year is not None:
        block["discovery_year"] = catalog.discovery_year
    if (mass := ring_mass_block(body_id)) is not None:
        block["mass"] = mass
    if (thickness := catalog.thickness) is not None:
        entry: dict = {"low_m": thickness.low_m}
        if thickness.high_m is not None:
            entry["high_m"] = thickness.high_m
        if thickness.feature:
            entry["feature"] = thickness.feature
        block["thickness"] = entry
    return block or None


def ring_images_block(body_id: str) -> list[dict] | None:
    """Pictures of this body's ring system, the first of which opens the tab.

    Language-independent, so they ride the global block: the credit under
    each is a name, not prose.
    """
    return collect_ring_images(body_id)


def _source_entry(source: RingSource) -> dict:
    """Titles and links only — the per-source `contribution` is the level of
    detail the credits page wants, not a footer under a chart."""
    return {
        "title": source.work,
        "url": source.url,
        "organisation": source.organisation,
    }


def ring_sources_block(body_id: str) -> list[dict] | None:
    """The works the catalogue draws on, for the Rings tab's credit line."""
    catalog = RING_CATALOGS.get(body_id)
    if catalog is None:
        return None
    return [_source_entry(source) for source in catalog.sources]


def ring_catalog_sources(body_ids: Iterable[str]) -> list[dict]:
    """The same works across several systems, deduped by URL.

    For the Ring Systems collection page, which reads every figure off these
    tables but has no per-body bundle to credit them from.
    """
    out: dict[str, dict] = {}
    for body_id in body_ids:
        catalog = RING_CATALOGS.get(body_id)
        if catalog is None:
            continue
        for source in catalog.sources:
            out.setdefault(source.url, _source_entry(source))
    return list(out.values())


def ring_system_localized(
    body_id: str, lang: str, wikidata_entities: WikidataEntityCache
) -> dict | None:
    """The "Rings of X" article for this locale — the panel's opening blurb.
    Unlike individual features, all four system articles exist in every
    language we ship."""
    entry: dict = {}
    for qid in RING_SYSTEM_PAGES.get(body_id, ()):
        entity = wikidata_entities.get_referenced(qid)
        if entity and (
            label := entity["labels"].get(lang) or entity["labels"].get("mul")
        ):
            entry.setdefault("name", label)
        if summary := _summaries(qid).get(lang):
            if summary.extract:
                entry.setdefault("extract", summary.extract)
            if summary.url:
                entry.setdefault("url", summary.url)
    return entry or None


def ring_feature_localized(
    body_id: str, lang: str, wikidata_entities: WikidataEntityCache
) -> dict[str, dict]:
    """Localized names, Wikipedia extracts and article links, keyed by slug.

    Only what this language has; a feature without one falls back to the
    global name and PDS note.
    """
    catalog = RING_CATALOGS.get(body_id)
    if catalog is None:
        return {}
    out: dict[str, dict] = {}
    for feature in catalog.features:
        entry: dict = {}
        for qid in feature_qids(body_id, feature.slug):
            entity = wikidata_entities.get_referenced(qid)
            # English keeps the catalogue name: Wikidata's English label is a
            # translation of the French/Italian title, e.g. IAU's "Huygens Gap"
            # would become "Huygens Division".
            if (
                lang != "en"
                and entity
                and (label := entity["labels"].get(lang) or entity["labels"].get("mul"))
            ):
                entry.setdefault("name", label)
            if summary := _summaries(qid).get(lang):
                if summary.extract:
                    entry.setdefault("extract", summary.extract)
                if summary.url:
                    entry.setdefault("url", summary.url)
        if entry:
            out[feature.slug] = entry
    return out
