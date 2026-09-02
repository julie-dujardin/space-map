"""Probe targets read as groups: the Probes category page's bar chart, the
Sun-Earth libration zones, and each small-body collection's probe list.

All three come from the reverse index the object bundles read. The chart
counts it, one row per place probes have been sent to, most-visited first;
rows the catalogue holds link to the body, the libration points to their zone.
The zones list it: no object sits at L1/L2, so each zone's members are the
probes whose events target it. The collections roll it up: a body's probe list
read one level out, so an orbit class or a flag answers what has been sent to
anything in it.
"""

import logging
from dataclasses import dataclass, field, replace

from sqlalchemy.orm import Session

from space_map_data.constants.categories import (
    ASTEROIDS_SLUG,
    COMET_ORBIT_CLASSES,
    COMETS_SLUG,
)
from space_map_data.constants.earth_sats.orbit_class import LAGRANGE_CLASS_BY_NAIF
from space_map_data.export.groups.registry import (
    CLASS_SLUG_PREFIX,
    SMALL_BODY_FLAG_SLUG_PREFIX,
)
from space_map_data.export.notable import NotableObject
from space_map_data.export.objects.probe_targets import (
    build_probe_targets,
    read_target_index,
    target_object_ids,
)
from space_map_data.models.object.main import Object, ObjectType
from space_map_data.models.object.sbdb import SBDB, OrbitClass

logger = logging.getLogger(__name__)

_LAGRANGE_GROUPS = {
    naif: f"{CLASS_SLUG_PREFIX}{cls.name}"
    for naif, cls in LAGRANGE_CLASS_BY_NAIF.items()
}

#: The zones whose members are probes rather than catalogued satellites, so
#: nothing that ranks a zone on satellite signals may touch them.
LAGRANGE_ZONE_SLUGS: frozenset[str] = frozenset(_LAGRANGE_GROUPS.values())


def build_lagrange_zones() -> dict[str, list[NotableObject]]:
    """Zone slug -> its probes, latest arrival first, for every Sun-Earth
    libration zone (empty when nothing targets it)."""
    by_target = build_probe_targets(set())
    zones = {
        slug: by_target.get(f"naif-{naif}", [])
        for naif, slug in _LAGRANGE_GROUPS.items()
    }
    logger.info(
        "Lagrange zones: %s",
        ", ".join(f"{slug}={len(probes)}" for slug, probes in zones.items()),
    )
    return zones


@dataclass
class ProbeTargetChart:
    """Bar-chart rows, plus the QIDs their labels localize from."""

    rows: list[dict] = field(default_factory=list)
    # Object id -> Wikidata QID, for the localized row labels.
    qids: dict[str, str] = field(default_factory=dict)


def build_probe_target_chart(session: Session) -> ProbeTargetChart:
    """Probes per target, most-visited first, ties by sitelink count."""
    index = read_target_index()
    candidates = {naif: target_object_ids(naif) for naif in index.events}
    bodies = {
        row.id: row
        for row in session.query(
            Object.id,
            Object.name,
            Object.object_type,
            Object.wikidata_qid,
            Object.sitelinks_count,
        )
        .filter(Object.id.in_({c for ids in candidates.values() for c in ids}))
        .all()
    }

    ranked: list[tuple[int, dict]] = []
    qids: dict[str, str] = {}
    unplaced: list[str] = []
    for naif, by_probe in index.events.items():
        # A barycenter is never the destination: the Earth-Moon L2 events
        # carry NAIF 3, which resolves to the pair's barycenter and would
        # label the row after it.
        body = next(
            (
                bodies[c]
                for c in candidates[naif]
                if c in bodies and bodies[c].object_type != ObjectType.barycenter
            ),
            None,
        )
        name = index.names.get(naif) or f"naif-{naif}"
        row = {"name": name, "n": len(by_probe)}
        if body is not None:
            row["name"] = body.name or name
            row["primary_type"] = "object"
            row["primary_id"] = body.id
            if body.wikidata_qid:
                qids[body.id] = body.wikidata_qid
        elif group_slug := _LAGRANGE_GROUPS.get(naif):
            row["primary_type"] = "group"
            row["primary_id"] = group_slug
        else:
            unplaced.append(name)
        ranked.append((body.sitelinks_count or 0 if body else 0, row))
    # Ties go to the better-known body: a page nobody wrote about is the one a
    # reader is least likely to be looking for.
    ranked.sort(key=lambda t: (-t[1]["n"], -t[0], t[1]["name"]))
    rows = [row for _, row in ranked]
    logger.info(
        "Probe targets chart: %d rows, %d with nothing to link to (%s)",
        len(rows),
        len(unplaced),
        ", ".join(sorted(unplaced)) if unplaced else "[]",
    )
    return ProbeTargetChart(rows=rows, qids=qids)


@dataclass
class GroupProbes:
    """Per-collection probe lists, plus the QIDs their target labels localize
    from (the same ``body_names`` map the per-body charts fill)."""

    probes: dict[str, list[NotableObject]] = field(default_factory=dict)
    # Group slug -> {target object id: Wikidata QID}.
    qids: dict[str, dict[str, str]] = field(default_factory=dict)


def _collection_slugs(
    orbit_class: OrbitClass, neo: bool | None, pha: bool | None, family: str | None
) -> list[str]:
    """Every collection page a visited small body belongs to."""
    is_comet = orbit_class in COMET_ORBIT_CLASSES
    slugs = [
        f"{CLASS_SLUG_PREFIX}{orbit_class.name}",
        COMETS_SLUG if is_comet else ASTEROIDS_SLUG,
    ]
    if neo:
        slugs.append(f"{SMALL_BODY_FLAG_SLUG_PREFIX}neo")
    if pha:
        slugs.append(f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha")
    if family:
        slugs.append(family)
    return slugs


def build_group_probes(
    session: Session, family_slugs: dict[str, str] | None = None
) -> GroupProbes:
    """Collection slug -> the probes sent to any of its members, latest arrival
    first.

    Covers the small-body orbit classes, the Asteroids/Comets roll-ups over
    them, the NEO/PHA flags and — through ``family_slugs``, a fragment object
    id to its family page — the parentless split comets. A probe that reached
    several members appears once and carries all of them.
    """
    index = read_target_index()
    bodies = {
        row.id: row
        for row in session.query(Object.id, Object.name, Object.wikidata_qid)
        .filter(
            Object.id.in_({c for naif in index.events for c in target_object_ids(naif)})
        )
        .all()
    }
    by_target = build_probe_targets(set(bodies))
    small_bodies = {
        object_id: (orbit_class, neo, pha)
        for object_id, orbit_class, neo, pha in session.query(
            SBDB.object_id, SBDB.class_, SBDB.neo, SBDB.pha
        )
        .filter(SBDB.object_id.in_(list(by_target)))
        .all()
    }

    out = GroupProbes()
    visits_by_slug: dict[str, dict[str, list[dict]]] = {}
    rows: dict[str, NotableObject] = {}
    for body_id, probes in by_target.items():
        classification = small_bodies.get(body_id)
        if classification is None:
            continue
        body = bodies[body_id]
        for slug in _collection_slugs(
            *classification, (family_slugs or {}).get(body_id)
        ):
            for probe in probes:
                rows.setdefault(probe.object_id, probe)
                # The kind of call is dropped: across a collection the bodies
                # are what the row has room to say.
                dates = {
                    k: v
                    for k, v in (probe.visit or {}).items()
                    if k in ("arrival", "end")
                }
                visits_by_slug.setdefault(slug, {}).setdefault(
                    probe.object_id, []
                ).append({"id": body_id, "name": body.name or body_id, **dates})
            if body.wikidata_qid:
                out.qids.setdefault(slug, {})[body_id] = body.wikidata_qid

    for slug, by_probe in visits_by_slug.items():
        ordered = sorted(
            (
                (probe_id, sorted(visits, key=lambda v: v["arrival"], reverse=True))
                for probe_id, visits in by_probe.items()
            ),
            key=lambda row: row[1][0]["arrival"],
            reverse=True,
        )
        out.probes[slug] = [
            replace(rows[probe_id], visit=None, visits=visits)
            for probe_id, visits in ordered
        ]
    logger.info(
        "Collection probe lists: %s",
        ", ".join(
            f"{slug}={len(probes)}"
            for slug, probes in sorted(
                out.probes.items(), key=lambda kv: (-len(kv[1]), kv[0])
            )
        )
        or "[]",
    )
    return out
