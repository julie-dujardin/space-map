"""Probes attached to the bodies their curated events target.

The reverse of the events files: every event with a body ``target`` puts its
probe on that body's bundle as ``probes`` (latest arrival first,
the same record shape as ``notable_moons``) + ``probe_count``, with localized
labels in ``probe_names``. Targets are taken as written — no inheritance from
mission type or parent craft. Earth is skipped (its events are launches,
homecomings and gravity assists, not visits), and so is any flyby whose
``purpose`` is a gravity assist: a slingshot is not a visit either. An event
marked ``failed`` (a miss, an insertion that did not take) is skipped too;
planned events count, since the list is who is headed there.

Each entry also carries a ``visit``: the most involved kind of event at that
body (rover > lander > atmospheric > sample > orbiter > impactor > flyby >
observer — an orbiter's disposal impact stays an orbiter; a remote-sensing
campaign at the Sun is an observer), the arrival date and, unless
the probe is still alive there, the end date.

The same index rolls up one level to each planetary system's barycenter,
where a probe appears once and names the bodies in the system it reached.
"""

import datetime
import json
import logging
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from space_map_data.constants.providers import LANGUAGES
from space_map_data.probes.events import target_object_ids
from space_map_data.export.notable import NotableObject, notable_entries, notable_names
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.probes.landing_events import EVENTS_DIR
from space_map_data.models.object.main import Object, ObjectType
from space_map_data.probes.probe_id import load_registry

logger = logging.getLogger(__name__)

_MJD_ZERO = datetime.date(1858, 11, 17)
_EARTH_NAIF = 399
_KIND_RANK = (
    "observer",
    "flyby",
    "impactor",
    "orbiter",
    "sample",
    "atmospheric",
    "lander",
    "rover",
)
_PROBE_END_EVENTS = {"mission_end", "contact_loss", "reentry"}


def _event_kind(event: dict, mission_type: str) -> str | None:
    """Visit kind of one target event; None for events that say nothing."""
    match event.get("type"):
        case "observation":
            return "observer"
        case "flyby":
            return "flyby"
        case "orbit_insertion" | "orbit_departure":
            return "orbiter"
        case "sample_collection":
            return "sample"
        case "landing":
            if "atmospheric" in mission_type or "balloon" in mission_type:
                return "atmospheric"
            if event.get("outcome") == "destroyed_at_landing" and event.get(
                "intentional"
            ):
                return "impactor"
            if "rover" in mission_type or "helicopter" in mission_type:
                return "rover"
            return "lander"
        case "atmospheric_entry":
            return "atmospheric"
    return None


def _visit(probe: dict, events: list[dict]) -> dict:
    """``visit`` block from this probe's non-skipped events at one body."""
    events = sorted(events, key=lambda e: e["date"])
    kinds = [k for e in events if (k := _event_kind(e, probe.get("mission_type", "")))]
    kind = max(kinds, key=_KIND_RANK.index) if kinds else "flyby"
    arrival = events[0]["date"][:10]
    departure = next(
        (e["date"][:10] for e in events if e.get("type") == "orbit_departure"), None
    )
    end: str | None
    if departure:
        end = departure
    elif kind == "flyby":
        end = arrival
    elif closed := events[-1].get("end_date"):
        # A campaign with an end_date is over; the probe's own later end
        # (a reentry somewhere else) says nothing about this body.
        end = closed[:10]
    else:
        end = next(
            (
                e["date"][:10]
                for e in sorted(probe.get("events", []), key=lambda e: e["date"])
                if e.get("type") in _PROBE_END_EVENTS
                and e["date"][:10] >= arrival
                # A contact loss with an end_date was recovered from.
                and not (e.get("type") == "contact_loss" and e.get("end_date"))
            ),
            None,
        )
        if end is None and probe.get("status", {}).get("alive") is not True:
            end = events[-1]["date"][:10]
    out = {"kind": kind, "arrival": arrival}
    if end:
        out["end"] = end
    return out


@dataclass(frozen=True)
class TargetIndex:
    """The curated events read backwards: what each probe was sent to."""

    #: Target NAIF -> probe id -> its dated events naming that target.
    events: dict[int, dict[int, list[dict]]]
    #: Target NAIF -> the name the events give it, the only label a target
    #: with no catalogue row of its own has.
    names: dict[int, str]
    #: Probe id -> its whole record, which a visit reads for the mission type
    #: and for the probe's own end.
    probes: dict[int, dict]
    #: Probe id -> launch date. The registry's ``inception_mjd`` is kernel
    #: coverage rather than launch (Dawn's reads 2013), so the ``launch``
    #: event is the date of record.
    launches: dict[int, str]


def read_target_index() -> TargetIndex:
    """Parse the events files into their target index.

    Earth is skipped: its events are launches, homecomings and assists, not
    visits. So is any flyby whose ``purpose`` is a gravity assist — a
    slingshot is not a visit either — and any event marked ``failed`` or
    undated. Planned events count: the index is who has been sent, not who
    arrived.
    """
    events: dict[int, dict[int, list[dict]]] = {}
    names: dict[int, str] = {}
    probes_by_id: dict[int, dict] = {}
    launches: dict[int, str] = {}
    for path in sorted(EVENTS_DIR.glob("*.json")):
        try:
            entries = json.loads(path.read_text()).get("probes", [])
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Probe events file %s unreadable (%s); skipped", path, exc)
            continue
        for probe in entries:
            probe_id = probe.get("probe_id")
            if probe_id is None:
                continue
            probes_by_id[int(probe_id)] = probe
            for event in probe.get("events", []):
                if event.get("type") == "launch" and event.get("date"):
                    launches.setdefault(int(probe_id), event["date"][:10])
                target = event.get("target")
                if not isinstance(target, dict) or target.get("naif") is None:
                    continue
                if (
                    event.get("type") == "flyby"
                    and event.get("purpose") == "gravity_assist"
                ):
                    continue
                if event.get("failed") or not event.get("date"):
                    continue
                naif = int(target["naif"])
                if naif == _EARTH_NAIF:
                    continue
                events.setdefault(naif, {}).setdefault(int(probe_id), []).append(event)
                if name := target.get("name"):
                    names.setdefault(naif, name)
    return TargetIndex(
        events=events, names=names, probes=probes_by_id, launches=launches
    )


def _probes_by_target(
    known_ids: set[str],
) -> tuple[dict[str, dict[int, dict]], dict[int, str]]:
    """Body object id -> {probe_id: visit} for every probe whose events name
    it, plus each probe's launch date. A target none of whose candidate ids
    is known keeps its first candidate, so the caller can log it."""
    index = read_target_index()
    hits: dict[str, dict[int, list[dict]]] = {}
    for naif, by_probe in index.events.items():
        candidates = target_object_ids(naif)
        body_id = next((c for c in candidates if c in known_ids), candidates[0])
        for probe_id, events in by_probe.items():
            hits.setdefault(body_id, {}).setdefault(probe_id, []).extend(events)
    out = {
        body_id: {
            probe_id: _visit(index.probes[probe_id], events)
            for probe_id, events in by_probe.items()
        }
        for body_id, by_probe in hits.items()
    }
    return out, index.launches


def _launch_date(inception_mjd: int | None) -> str | None:
    if inception_mjd is None:
        return None
    return (_MJD_ZERO + datetime.timedelta(days=int(inception_mjd))).isoformat()


def build_probe_targets(known_ids: set[str]) -> dict[str, list[NotableObject]]:
    """Body object id → its probes, latest arrival first. Probes missing from
    the registry have no object of their own and are dropped; a target whose
    no candidate id is in ``known_ids`` keeps its first candidate, so the
    caller can log it."""
    registry = {int(r["probe_id"]): r for r in load_registry()}
    out: dict[str, list[NotableObject]] = {}
    unknown: set[int] = set()
    by_target, launches = _probes_by_target(known_ids)
    for body_id, visits in by_target.items():
        rows = []
        for probe_id in visits:
            row = registry.get(probe_id)
            if row is None:
                unknown.add(probe_id)
                continue
            rows.append(row)

        def launch(r: dict) -> str | None:
            return launches.get(int(r["probe_id"])) or _launch_date(
                r.get("inception_mjd")
            )

        rows.sort(key=lambda r: visits[int(r["probe_id"])]["arrival"], reverse=True)
        out[body_id] = [
            NotableObject(
                object_id=f"probe-{r['probe_id']}",
                wikidata_qid=r.get("wikidata_qid"),
                fallback_name=r.get("name") or f"probe-{r['probe_id']}",
                diameter_km=None,
                first_obs=launch(r),
                visit=visits[int(r["probe_id"])],
            )
            for r in rows
        ]
    if unknown:
        logger.warning(
            "%d event probes not in the registry, dropped: %s",
            len(unknown),
            sorted(unknown),
        )
    return out


def attach_probe_targets(
    chunk: ChunkObjectData, wikidata_entities: WikidataEntityCache
) -> None:
    """Inject ``probes``/``probe_count`` (+ localized ``probe_names``) onto
    each targeted body. Mutates ``chunk`` in place."""
    attached = 0
    missing: list[str] = []
    for body_id, probes in build_probe_targets(set(chunk.global_data)).items():
        global_data = chunk.global_data.get(body_id)
        if global_data is None:
            missing.append(body_id)
            continue
        entries = notable_entries(probes, wikidata_entities)
        global_data["probes"] = entries
        global_data["probe_count"] = len(entries)
        for lang in LANGUAGES:
            localized = chunk.localized_data.get(lang, {}).get(body_id)
            if localized is None:
                continue
            names = notable_names(probes, entries, lang, wikidata_entities)
            if names:
                localized["probe_names"] = names
        attached += 1
    logger.info(
        "Attached probes to %d bodies; %d targets without a bundle: %s",
        attached,
        len(missing),
        ", ".join(sorted(missing)) if missing else "[]",
    )


def _system_members(session: Session) -> dict[str, dict[str, str]]:
    """Planetary system barycenter id -> {member object id: English name}.

    Members are the barycenter itself, its dominant planet and every moon
    hanging off either — the same set the system map draws, plus the
    barycenter, which the Earth-Moon L2 halo orbiters name as their target.
    """
    barycenters = {
        f"naif-{n}": f"naif-{n}99" for n in range(1, 10)
    }  # SPICE convention, matching the frontend's `dominantPlanetId`
    rows = {
        row.id: row.name or row.id
        for row in session.query(Object.id, Object.name, Object.parent_id).filter(
            Object.id.in_(set(barycenters) | set(barycenters.values()))
        )
    }
    moons = (
        session.query(Object.id, Object.name, Object.parent_id)
        .filter(
            Object.object_type == ObjectType.moon,
            Object.parent_id.in_(set(barycenters) | set(barycenters.values())),
        )
        .all()
    )
    out: dict[str, dict[str, str]] = {}
    for bary_id, primary_id in barycenters.items():
        if bary_id not in rows:
            continue
        members = {mid: rows[mid] for mid in (bary_id, primary_id) if mid in rows}
        for moon in moons:
            if moon.parent_id in (bary_id, primary_id):
                members[moon.id] = moon.name or moon.id
        out[bary_id] = members
    return out


def attach_system_probes(
    session: Session, chunk: ChunkObjectData, wikidata_entities: WikidataEntityCache
) -> None:
    """Inject ``probes``/``probe_count`` onto each planetary system's
    barycenter: the probes sent to anything in the system, latest arrival
    first. Mutates ``chunk`` in place.

    A system page repeats what its planet's own page says, on purpose — the
    system is where a reader looks for what has been there, and a probe that
    called at Mars and both moons is one row here and three separate lists
    otherwise. Each row names the bodies it reached rather than the kind of
    call, as a collection's rows do: one probe rarely did the same thing at
    all of them.
    """
    by_target = build_probe_targets(set(chunk.global_data))
    attached: dict[str, int] = {}
    for bary_id, members in _system_members(session).items():
        global_data = chunk.global_data.get(bary_id)
        if global_data is None:
            continue
        rows: dict[str, NotableObject] = {}
        visits: dict[str, list[dict]] = {}
        for member_id, member_name in members.items():
            for probe in by_target.get(member_id, []):
                rows.setdefault(probe.object_id, probe)
                dates = {
                    k: v
                    for k, v in (probe.visit or {}).items()
                    if k in ("arrival", "end")
                }
                visits.setdefault(probe.object_id, []).append(
                    {"id": member_id, "name": member_name, **dates}
                )
        if not rows:
            continue
        ordered = sorted(
            (
                (probe_id, sorted(v, key=lambda x: x["arrival"], reverse=True))
                for probe_id, v in visits.items()
            ),
            key=lambda row: row[1][0]["arrival"],
            reverse=True,
        )
        probes = [
            replace(rows[probe_id], visit=None, visits=v) for probe_id, v in ordered
        ]
        entries = notable_entries(probes, wikidata_entities)
        global_data["probes"] = entries
        global_data["probe_count"] = len(entries)
        attached[bary_id] = len(entries)
        for lang in LANGUAGES:
            localized = chunk.localized_data.get(lang, {}).get(bary_id)
            if localized is None:
                continue
            if names := notable_names(probes, entries, lang, wikidata_entities):
                localized["probe_names"] = names
            # The bodies each row names, in this language — read off the members'
            # own bundles rather than Wikidata, which already localized them.
            body_names = {
                member_id: name
                for member_id in {v["id"] for vs in visits.values() for v in vs}
                if (member := chunk.localized_data[lang].get(member_id))
                and (name := member.get("name"))
                and name != members[member_id]
            }
            if body_names:
                localized["body_names"] = body_names
    logger.info(
        "System probe lists: %s",
        ", ".join(f"{bary}={n}" for bary, n in sorted(attached.items())) or "[]",
    )
