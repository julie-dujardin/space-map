"""Probes attached to the bodies their curated events target.

The reverse of the events files: every event with a body ``target`` puts its
probe on that body's bundle as ``probes`` (ranked chronologically by launch,
the same record shape as ``notable_moons``) + ``probe_count``, with localized
labels in ``probe_names``. Targets are taken as written — no inheritance from
mission type or parent craft. Earth is skipped (its events are launches,
homecomings and gravity assists, not visits), and so is any flyby whose
``purpose`` is a gravity assist: a slingshot is not a visit either. An event
marked ``failed`` (a miss, an insertion that did not take) is skipped too;
planned events count, since the list is who is headed there.
"""

import datetime
import json
import logging

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.notable import NotableObject, notable_entries, notable_names
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.probes.landing_events import EVENTS_DIR
from space_map_data.probes.probe_id import load_registry

logger = logging.getLogger(__name__)

_MJD_ZERO = datetime.date(1858, 11, 17)
_EARTH = "naif-399"


def target_object_ids(naif: int) -> tuple[str, ...]:
    """Candidate object ids for an event-target NAIF (Horizons convention),
    best first. Numbered asteroids are SBDB rows, except the dwarf planets
    the renderer keeps under their NAIF id (Ceres is ``naif-2000001``).
    Mirrors ``probes/landing_events._resolve_body``."""
    if 2_000_000 < naif < 3_000_000:
        return (f"spkid-{naif + 18_000_000}", f"naif-{naif}")
    if 1_000_000 < naif < 2_000_000:
        return (f"spkid-{naif}",)
    return (f"naif-{naif}",)


def _probes_by_target(
    known_ids: set[str],
) -> tuple[dict[str, set[int]], dict[int, str]]:
    """Body object id → probe_ids of every probe whose events name it, plus
    each probe's ``launch`` event date. The registry's ``inception_mjd`` is
    kernel coverage, not launch (Dawn's reads 2013), so the events file is
    the date of record."""
    out: dict[str, set[int]] = {}
    launches: dict[int, str] = {}
    for path in sorted(EVENTS_DIR.glob("*.json")):
        try:
            probes = json.loads(path.read_text()).get("probes", [])
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Probe events file %s unreadable (%s); skipped", path, exc)
            continue
        for probe in probes:
            probe_id = probe.get("probe_id")
            if probe_id is None:
                continue
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
                if event.get("failed"):
                    continue
                candidates = target_object_ids(int(target["naif"]))
                body_id = next((c for c in candidates if c in known_ids), candidates[0])
                if body_id == _EARTH:
                    continue
                out.setdefault(body_id, set()).add(int(probe_id))
    return out, launches


def _launch_date(inception_mjd: int | None) -> str | None:
    if inception_mjd is None:
        return None
    return (_MJD_ZERO + datetime.timedelta(days=int(inception_mjd))).isoformat()


def build_probe_targets(known_ids: set[str]) -> dict[str, list[NotableObject]]:
    """Body object id → its probes, oldest launch first. Probes missing from
    the registry have no object of their own and are dropped; a target whose
    no candidate id is in ``known_ids`` keeps its first candidate, so the
    caller can log it."""
    registry = {int(r["probe_id"]): r for r in load_registry()}
    out: dict[str, list[NotableObject]] = {}
    unknown: set[int] = set()
    by_target, launches = _probes_by_target(known_ids)
    for body_id, probe_ids in by_target.items():
        rows = []
        for probe_id in probe_ids:
            row = registry.get(probe_id)
            if row is None:
                unknown.add(probe_id)
                continue
            rows.append(row)

        def launch(r: dict) -> str | None:
            return launches.get(int(r["probe_id"])) or _launch_date(
                r.get("inception_mjd")
            )

        rows.sort(key=lambda r: (launch(r) is None, launch(r) or ""))
        out[body_id] = [
            NotableObject(
                object_id=f"probe-{r['probe_id']}",
                wikidata_qid=r.get("wikidata_qid"),
                fallback_name=r.get("name") or f"probe-{r['probe_id']}",
                diameter_km=None,
                first_obs=launch(r),
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
