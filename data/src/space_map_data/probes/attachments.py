"""Resolve which craft rode on another one, and until when.

A carried craft has no trajectory of its own while it is bolted to its
carrier — Huygens is wherever Cassini is until 2004-12-25, Ingenuity is
wherever Perseverance is until it is set down. The archives publish no SPK
for the passenger over that stretch because there is nothing separate to
publish, so the export borrows the carrier's position instead of leaving
the craft unplaceable.

Direction comes from the trajectories, not from the mission hierarchy. The
events files name a craft's relatives (``parent_mission``, a separation or
launch event's ``target``) and the registry names its mission primary, but
none of those say which one *carried* which: the Apollo CSM separates from
the S-IVB while the registry calls the CSM the mission primary, so either
field alone points the wrong way for one of the pair. Whichever relative
has a real trajectory over the window is the carrier — a passenger by
definition has none.

Coverage is read from both ``missions/`` and ``landed-missions/``: the
Viking landers have their own descent kernels, and a lander that looks
uncovered gets attached to its orbiter for a descent the archive already
describes.
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass

from space_map_data.download.providers.spice.naif_http import merge_intervals
from space_map_data.download.providers.spice.probes import (
    LANDED_MISSIONS_DIR,
    MISSIONS_DIR,
)
from space_map_data.probes.landing_events import EVENTS_DIR, parse_event_jd
from space_map_data.probes.probe_id import load_registry
from space_map_data.utils.time import et_to_jd

logger = logging.getLogger(__name__)

# Below this the attachment is a rounding artefact of same-day event dates
# (the Apollo 15 LM stages separate the day they are recorded), not a window
# worth drawing.
_MIN_ATTACHMENT_DAYS = 1.0

# A carrier tracked for only a sliver of the window leaves the passenger
# unplaceable for the rest, which is what it already was.
_MIN_CARRIER_FRACTION = 0.10

# Above this share of the window the craft has its own solution and is no
# passenger — the Viking landers fly their own descent kernels.
_MAX_PASSENGER_FRACTION = 0.5

# Synthetic registry NAIFs (EVENTS-DB) never index a kernel.
_MIN_REAL_NAIF = -90_000_000


@dataclass(frozen=True)
class Attachment:
    """``probe_id`` sits at ``carrier_probe_id``'s position over the window."""

    probe_id: int
    carrier_probe_id: int
    start_jd: float
    end_jd: float


def naif_coverage_jd() -> dict[int, list[tuple[float, float]]]:
    """Merged JD coverage per spacecraft NAIF, across every mission index."""
    by_naif: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for base in (MISSIONS_DIR, LANDED_MISSIONS_DIR):
        if not base.exists():
            continue
        for mission_dir in sorted(base.iterdir()):
            index_path = mission_dir / "_index.json"
            if not mission_dir.is_dir() or not index_path.exists():
                continue
            try:
                index = json.loads(index_path.read_text())
            except OSError, json.JSONDecodeError:
                logger.exception("attachments: unreadable %s; skipping", index_path)
                continue
            for naif_str, spans in (index.get("targets_coverage") or {}).items():
                try:
                    naif = int(naif_str)
                except ValueError:
                    continue
                if naif >= 0:
                    continue
                by_naif[naif].extend(
                    (et_to_jd(float(s)), et_to_jd(float(e))) for s, e in spans
                )
    return {naif: merge_intervals(spans) for naif, spans in by_naif.items()}


def _covered_days(spans: list[tuple[float, float]], start: float, end: float) -> float:
    return sum(max(0.0, min(e, end) - max(s, start)) for s, e in spans)


def _load_events() -> dict[int, dict]:
    """Every events-file probe that carries a probe_id, keyed by it."""
    out: dict[int, dict] = {}
    for path in sorted(EVENTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except OSError, json.JSONDecodeError:
            logger.exception("attachments: unreadable %s; skipping", path)
            continue
        for probe in data.get("probes", []):
            if probe.get("probe_id") is not None:
                out[int(probe["probe_id"])] = probe
    return out


def _first_separation_jd(probe: dict) -> float | None:
    for event in probe.get("events", []):
        if event.get("type") != "stage_separation":
            continue
        try:
            return parse_event_jd(event["date"])
        except ValueError, TypeError, KeyError:
            logger.warning(
                "attachments: %s has an unparseable separation date %r",
                probe.get("name"),
                event.get("date"),
            )
            return None
    return None


def _relatives(
    probe_id: int, probe: dict, by_name: dict[str, int], primary: int | None
) -> list[int]:
    """Craft the data names as this one's mission relatives.

    A separation or launch ``target`` is a statement about hardware; the
    registry primary and ``parent_mission`` only say what the mission was.
    Order is a tiebreak — the caller picks whichever has the most coverage.
    """
    out: list[int] = []
    for event in probe.get("events", []):
        if event.get("type") not in ("stage_separation", "launch"):
            continue
        name = (event.get("target") or {}).get("name")
        if name in by_name and by_name[name] != probe_id:
            out.append(by_name[name])
    if primary is not None and primary != probe_id:
        out.append(primary)
    parent = probe.get("parent_mission")
    if parent in by_name and by_name[parent] != probe_id:
        out.append(by_name[parent])
    return list(dict.fromkeys(out))


def resolve_attachments() -> list[Attachment]:
    """Every carried craft, its carrier, and the window it rode for."""
    events = _load_events()
    if not events:
        return []
    by_name = {p["name"]: pid for pid, p in events.items() if p.get("name")}
    registry = {int(e["probe_id"]): e for e in load_registry()}
    coverage = naif_coverage_jd()

    def spans(probe_id: int) -> list[tuple[float, float]]:
        naif = registry.get(probe_id, {}).get("naif_id")
        if naif is None or not _MIN_REAL_NAIF < int(naif) < 0:
            return []
        return coverage.get(int(naif), [])

    out: list[Attachment] = []
    unresolved: list[str] = []
    for probe_id, probe in events.items():
        entry = registry.get(probe_id, {})
        if not (probe.get("parent_mission") or entry.get("primary_probe_id")):
            continue
        end_jd = _first_separation_jd(probe)
        if end_jd is None:
            unresolved.append(f"{probe.get('name')} (no separation event)")
            continue
        launch = next(
            (e for e in probe.get("events", []) if e.get("type") == "launch"), None
        )
        primary = entry.get("primary_probe_id")
        best: tuple[float, int, float] | None = None
        for relative in _relatives(
            probe_id, probe, by_name, int(primary) if primary else None
        ):
            carrier_spans = spans(relative)
            if not carrier_spans:
                continue
            try:
                start_jd = (
                    parse_event_jd(launch["date"]) if launch else carrier_spans[0][0]
                )
            except ValueError, TypeError, KeyError:
                continue
            window = end_jd - start_jd
            if window < _MIN_ATTACHMENT_DAYS:
                continue
            fraction = _covered_days(carrier_spans, start_jd, end_jd) / window
            if fraction < _MIN_CARRIER_FRACTION:
                continue
            # A passenger the archives track for most of the window is not a
            # passenger — that is a craft with its own solution.
            if _covered_days(spans(probe_id), start_jd, end_jd) > (
                _MAX_PASSENGER_FRACTION * window
            ):
                continue
            if best is None or fraction > best[0]:
                best = (fraction, relative, start_jd)
        if best is None:
            unresolved.append(probe.get("name") or str(probe_id))
            continue
        _, carrier, start_jd = best
        out.append(Attachment(probe_id, carrier, start_jd, end_jd))

    out.sort(key=lambda a: a.probe_id)
    logger.info(
        "attachments: %d carried craft resolved; %d mission members left "
        "unattached (no separation instant, or no relative with a trajectory): %s",
        len(out),
        len(unresolved),
        ", ".join(sorted(unresolved)) if unresolved else "[]",
    )
    return out
