"""Probe missions, attached to probe object detail bundles + /g/mission-<slug>.

Mirrors ``objects/fragments.py``. The registry marks a mission's **primary**
row with ``primary_qid`` + ``mission_slug`` and each sibling **member** with
``primary_probe_id``. The member gets ``part_of_mission``; the primary gets
``mission`` + a ranked ``mission_members`` strip + ``mission_member_count``.
Both link to the mission group page, whose focus resolves to the primary probe.
"""

import logging
from dataclasses import dataclass, field

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.notable import NotableObject, notable_entries, notable_names
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.probes.probe_id import load_registry

logger = logging.getLogger(__name__)

MISSION_SLUG_PREFIX = "mission-"


@dataclass
class ProbeMission:
    """A mission: its primary probe, sibling members, and Wikidata entity."""

    slug: str  # full /g/ slug, e.g. "mission-viking-2"
    mission_qid: str  # the mission's Wikidata QID
    primary_object_id: str  # "probe-<primary_probe_id>"
    primary: NotableObject
    members: list[NotableObject] = field(default_factory=list)  # siblings, ranked


def _notable(entry: dict) -> NotableObject:
    probe_id = entry["probe_id"]
    return NotableObject(
        object_id=f"probe-{probe_id}",
        wikidata_qid=entry.get("wikidata_qid"),
        fallback_name=entry.get("name") or f"probe-{probe_id}",
        diameter_km=None,
        first_obs=None,
    )


def build_probe_missions() -> list[ProbeMission]:
    """Group registry rows into missions, keyed off each primary's mission_slug.

    A mission needs both ``primary_qid`` and ``mission_slug`` on its primary
    row; members are the rows whose ``primary_probe_id`` points at it. Members
    are ranked by Wikidata-label presence then fallback name for a stable strip.
    """
    registry = load_registry()
    members_by_primary: dict[int, list[dict]] = {}
    for entry in registry:
        primary = entry.get("primary_probe_id")
        if primary is not None:
            members_by_primary.setdefault(int(primary), []).append(entry)

    missions: list[ProbeMission] = []
    for entry in registry:
        qid = entry.get("primary_qid")
        slug = entry.get("mission_slug")
        if not qid or not slug:
            continue
        member_rows = members_by_primary.get(int(entry["probe_id"]), [])
        member_rows.sort(
            key=lambda r: (r.get("wikidata_qid") is None, r.get("name") or "")
        )
        missions.append(
            ProbeMission(
                slug=f"{MISSION_SLUG_PREFIX}{slug}",
                mission_qid=qid,
                primary_object_id=f"probe-{entry['probe_id']}",
                primary=_notable(entry),
                members=[_notable(r) for r in member_rows],
            )
        )
    logger.info(
        "Built %d probe missions (%d member craft total)",
        len(missions),
        sum(len(m.members) for m in missions),
    )
    return missions


def _mission_name(
    mission_qid: str, fallback: str, wikidata_entities: WikidataEntityCache
) -> str:
    wd = wikidata_entities.get_entity(mission_qid)
    return (wd["labels"].get("en") if wd else None) or fallback


def attach_probe_missions(
    chunk: ChunkObjectData,
    wikidata_entities: WikidataEntityCache,
) -> None:
    """Inject ``mission``/``mission_members`` onto primaries and
    ``part_of_mission`` onto each member. Mutates ``chunk`` in place."""
    missions = build_probe_missions()
    primaries_done = 0
    members_done = 0
    for mission in missions:
        name = _mission_name(
            mission.mission_qid, mission.primary.fallback_name, wikidata_entities
        )
        # Primary and members both link to the mission group page.
        link = {"name": name, "primary_type": "group", "primary_id": mission.slug}

        primary_global = chunk.global_data.get(mission.primary_object_id)
        if primary_global is not None:
            primary_global["mission"] = link
            entries = notable_entries(mission.members, wikidata_entities)
            if entries:
                primary_global["mission_members"] = entries
                primary_global["mission_member_count"] = len(mission.members)
                for lang in LANGUAGES:
                    localized = chunk.localized_data.get(lang, {}).get(
                        mission.primary_object_id
                    )
                    if localized is None:
                        continue
                    names = notable_names(
                        mission.members, entries, lang, wikidata_entities
                    )
                    if names:
                        localized["mission_member_names"] = names
            primaries_done += 1

        for member in mission.members:
            member_global = chunk.global_data.get(member.object_id)
            if member_global is not None:
                member_global["part_of_mission"] = link
                members_done += 1

    logger.info(
        "Attached mission to %d primaries and part_of_mission to %d members",
        primaries_done,
        members_done,
    )
