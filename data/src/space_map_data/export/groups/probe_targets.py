"""Probes per target, for the Probes category page's bar chart.

The same reverse index the object bundles read, counted rather than listed:
one row per place probes have been sent to, most-visited first. Rows the
catalogue holds link to the body; the Sun-Earth libration points have no object
to focus but do have a collection page, so they link to that instead.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from space_map_data.constants.earth_sats.orbit_class import EarthOrbitClass
from space_map_data.export.groups.registry import CLASS_SLUG_PREFIX
from space_map_data.export.objects.probe_targets import (
    read_target_index,
    target_object_ids,
)
from space_map_data.models.object.main import Object, ObjectType

logger = logging.getLogger(__name__)

# The events write the Sun-Earth libration points as NAIF 391/392; no object
# sits there, but each is an Earth-orbit zone with a page of its own.
_LAGRANGE_GROUPS = {
    391: f"{CLASS_SLUG_PREFIX}{EarthOrbitClass.EL1.name}",
    392: f"{CLASS_SLUG_PREFIX}{EarthOrbitClass.EL2.name}",
}


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
