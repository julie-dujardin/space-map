"""Curated mission events, attached to probe object detail bundles.

The whole record ships: every event the file holds, in date order, with the
fields that event carries. Which of them a timeline shows, and how many, is
the frontend's call.

Events keep the order the file lists them in — the validator already holds
that to date order, and a bare year sorted against a timestamp inside it
would shuffle a day's worth of record for nothing.

Each event gets a ``jd`` beside its ``date`` so the drawer can seek the clock
without re-parsing reduced-precision ISO, and ``precision`` so it can print
"1965" as a year rather than as New Year's Day. ``target`` becomes a link
when the body or craft it names has an object bundle of its own, and stays a
bare name otherwise — MASCOT and Juventas have no row to point at.

The curators' ``description`` prose is working notes and never ships; the
type labels are message keys the frontend owns.
"""

import functools
import logging

from space_map_data.export.images import collect_object_images, pick_thumbnail
from space_map_data.export.objects.wikidata_claims import EntityRef
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.probes.events import (
    EventTarget,
    ProbeEvent,
    ProbeStatus,
    load_event_probes,
    target_object_ids,
)

logger = logging.getLogger(__name__)


def _target_object_id(target: EventTarget, known_ids: set[str]) -> str | None:
    """Object id for what an event names, in the renderer's id space."""
    if target.probe_id is not None:
        object_id = f"probe-{target.probe_id}"
        return object_id if object_id in known_ids else None
    if target.naif is None:
        return None
    return next((c for c in target_object_ids(target.naif) if c in known_ids), None)


@functools.lru_cache(maxsize=None)
def _target_thumbnail(object_id: str) -> dict | None:
    """Card thumbnail for a target, once per unique id — the Moon alone is
    named by ~190 events, and each image lookup touches the disk."""
    return pick_thumbnail(collect_object_images(object_id))


def _target_dict(target: EventTarget, known_ids: set[str]) -> dict:
    """The event's subject: a focus link where one resolves, else the name.
    Linked targets carry the same card ``thumbnail`` the notable strips use."""
    object_id = _target_object_id(target, known_ids)
    if object_id is None:
        return {"name": target.name}
    prefix, _, value = object_id.partition("-")
    out = EntityRef(name=target.name, primary_type=prefix, primary_id=value).to_dict()
    if thumbnail := _target_thumbnail(object_id):
        out["thumbnail"] = thumbnail
    return out


def _event_dict(event: ProbeEvent, known_ids: set[str]) -> dict:
    out: dict = {
        "type": event.type,
        "date": event.date,
        "jd": round(event.jd, 6),
        "precision": event.precision,
    }
    if event.end_date is not None:
        out["end_date"] = event.end_date
        end_jd = event.end_jd
        if end_jd is not None:
            out["end_jd"] = round(end_jd, 6)
    if event.approximate:
        out["approximate"] = True
    if event.failed:
        out["failed"] = True
    if event.target is not None:
        out["target"] = _target_dict(event.target, known_ids)
    for key in ("purpose", "outcome", "intentional"):
        value = getattr(event, key)
        if value is not None:
            out[key] = value
    if event.site is not None:
        site: dict = {"lat_deg": event.site.lat_deg, "lon_deg": event.site.lon_deg}
        if event.site.name:
            site["name"] = event.site.name
        out["site"] = site
    if event.stated:
        out["stated"] = event.stated
    if event.computed:
        out["computed"] = event.computed
    return out


def _status_dict(status: ProbeStatus) -> dict:
    out: dict = {"where": status.where}
    if status.alive is not None:
        out["alive"] = status.alive
    if status.lost:
        out["lost"] = True
    return out


def attach_probe_events(chunk: ChunkObjectData) -> None:
    """Inject ``events`` onto every probe bundle the curated files cover.
    Mutates ``chunk`` in place."""
    known_ids = set(chunk.global_data)
    attached = 0
    total = 0
    missing: list[str] = []
    for probe in load_event_probes():
        entry = chunk.global_data.get(f"probe-{probe.probe_id}")
        if entry is None:
            missing.append(probe.name)
            continue
        if not probe.events:
            continue
        items = [_event_dict(e, known_ids) for e in probe.events]
        entry["events"] = {"status": _status_dict(probe.status), "items": items}
        attached += 1
        total += len(items)
    logger.info(
        "Attached %d curated events to %d probes; %d curated craft have no "
        "object bundle: %s",
        total,
        attached,
        len(missing),
        ", ".join(sorted(missing)) if missing else "[]",
    )
