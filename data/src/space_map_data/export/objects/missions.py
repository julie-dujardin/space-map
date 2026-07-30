"""Probe missions, attached to probe object detail bundles + /g/mission-<slug>.

Mirrors ``objects/fragments.py``. The registry marks a mission's **primary**
row with ``primary_qid`` + ``mission_slug`` and each sibling **member** with
``primary_probe_id``. The member gets ``part_of_mission``; the primary gets
``mission`` + a ranked ``mission_members`` strip + ``mission_member_count``.
Both link to the mission group page, whose focus resolves to the primary probe.
"""

import datetime
import json
import logging
from dataclasses import dataclass, field

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.notable import NotableObject, notable_entries, notable_names
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.probes.landing_events import EVENTS_DIR
from space_map_data.probes.probe_id import load_registry

logger = logging.getLogger(__name__)

MISSION_SLUG_PREFIX = "mission-"

_MJD_ZERO = datetime.date(1858, 11, 17)

# The events files track each craft's physical fate; a mission page only wants
# to know whether anything is still flying it.
_STILL_FLYING = frozenset({"active", "in_transit"})
_LOST = frozenset({"lost"})


@dataclass
class ProbeMission:
    """A mission: its primary probe, sibling members, and Wikidata entity."""

    slug: str  # full /g/ slug, e.g. "mission-viking-2"
    mission_qid: str  # the mission's Wikidata QID
    primary_object_id: str  # "probe-<primary_probe_id>"
    primary: NotableObject
    members: list[NotableObject] = field(default_factory=list)  # siblings, ranked
    launch_year: int | None = None
    # "operating" | "lost" | "ended", from the primary's curated event row.
    status: str | None = None


def _probe_statuses() -> dict[str, str]:
    """Curated craft status by COSPAR id and by name, from the events files.

    Both keys are needed: pre-COSPAR and never-catalogued craft (Comet
    Interceptor) carry no id, and registry names match the events files.
    """
    out: dict[str, str] = {}
    for path in sorted(EVENTS_DIR.glob("*.json")):
        try:
            probes = json.loads(path.read_text()).get("probes", [])
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Probe events file %s unreadable (%s); skipped", path, exc)
            continue
        for probe in probes:
            status = probe.get("status")
            if not status:
                continue
            if cospar := probe.get("cospar_id"):
                out[cospar] = status
            if name := probe.get("name"):
                out.setdefault(name, status)
    return out


def _mission_status(raw: str | None) -> str | None:
    if raw is None:
        return None
    if raw in _STILL_FLYING:
        return "operating"
    return "lost" if raw in _LOST else "ended"


def _launch_year(inception_mjd: int | None) -> int | None:
    if inception_mjd is None:
        return None
    return (_MJD_ZERO + datetime.timedelta(days=int(inception_mjd))).year


def first_probe_launch_year() -> int | None:
    """Earliest launch year across every registered probe, for the Probes page.

    Wider than the mission pages: most probes fly outside a multi-craft mission,
    and the first of them predates every mission group.
    """
    years = [
        year
        for entry in load_registry()
        if (year := _launch_year(entry.get("inception_mjd"))) is not None
    ]
    return min(years) if years else None


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
    statuses = _probe_statuses()
    unmatched: list[str] = []
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
        # The mission's state is its primary craft's; siblings are stages and
        # landers whose own fates the page lists individually.
        raw_status = statuses.get(entry.get("cospar_id") or "") or statuses.get(
            entry.get("name") or ""
        )
        if raw_status is None:
            unmatched.append(entry.get("name") or slug)
        missions.append(
            ProbeMission(
                slug=f"{MISSION_SLUG_PREFIX}{slug}",
                mission_qid=qid,
                primary_object_id=f"probe-{entry['probe_id']}",
                primary=_notable(entry),
                members=[_notable(r) for r in member_rows],
                launch_year=_launch_year(entry.get("inception_mjd")),
                status=_mission_status(raw_status),
            )
        )
    logger.info(
        "Built %d probe missions (%d member craft total); %d with no curated "
        "status: %s",
        len(missions),
        sum(len(m.members) for m in missions),
        len(unmatched),
        ", ".join(sorted(unmatched)) if unmatched else "[]",
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
