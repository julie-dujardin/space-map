"""Landed phases, read off the curated probe events.

One ``LandingPhase`` per ``landing`` or ``reentry`` event that names a site:
the probe sits at that lat/lng on that body until it leaves. The phase ends at the landing's
own ``end_date``, else at the next ``_DEPARTURE_TYPES`` event; otherwise the
probe stays landed forever (Apollo descent stages, every Venera, Surveyor 1).
Earth landings are capped to one month so sample-return capsules and launch
failures don't clutter Earth after touchdown.

Asteroid landings use Horizons-NAIF in the event target (``2_000_000+n``),
mapped to SBDB SPKID (``20_000_000+n``) to match the DB row (``spkid-N``).
Comets share the ``1_000_000+n`` scheme between NAIF and SPKID — only the
id-type byte changes.
"""

import logging
from dataclasses import dataclass

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.position.format import ID_TYPE_ORDINAL
from space_map_data.probes.events import EVENTS_DIR, ProbeEvent, load_event_probes
from space_map_data.utils.time import jd_to_et

logger = logging.getLogger(__name__)

__all__ = ["EVENTS_DIR", "LandingPhase", "load_phases", "probe_ids_with_phases"]

# Events that terminate a landed phase. `mission_end`/`contact_loss` are
# excluded — dying on the surface still counts as landed. `stage_separation`
# is excluded too: a piece falling off doesn't move the probe whose row this
# is; ascent stages get their own probe row and landing event.
_DEPARTURE_TYPES = frozenset(
    {
        "launch",
        "orbit_departure",
        "landing",
        "flyby",
        "reentry",
        "sample_return",
        "atmospheric_entry",
    }
)

# Events that can pin the probe to a surface point. ``reentry`` carries the
# splashdown coordinates for craft that never reached their target and came
# down on Earth instead (Mars 96, Fobos-Grunt, Yinghuo-1).
_SITED_TYPES = frozenset({"landing", "reentry"})

_NAIF = ID_TYPE_ORDINAL[ID_TYPES.NAIF]
_SPKID = ID_TYPE_ORDINAL[ID_TYPES.SPKID]

# Earth landings (sample-return capsules, launch failures) are only interesting
# near touchdown; keeping them indefinitely clutters Earth. Cap to one month.
_EARTH_NAIF = 399
_EARTH_LANDING_MAX_S = 30 * 86400.0


@dataclass(frozen=True)
class LandingPhase:
    """One landed phase: the probe is at a fixed lat/lng on ``body`` from
    ``start_et`` to ``end_et``."""

    probe_id: int
    probe_name: str  # logging only
    body_id_type: int  # ID_TYPE_ORDINAL[NAIF/SPKID]
    body_id_value: int
    lat_deg: float
    lng_deg: float
    start_et: float
    end_et: float
    site_name: str | None


def _resolve_body(naif: int) -> tuple[int, int]:
    """Map an event target's NAIF id (Horizons convention) to the renderer's
    ``(id_type, id_value)`` pair.

    Numbered asteroids: Horizons ``2_000_000+i`` -> SBDB SPKID
    ``20_000_000+i``. Comets share ``1_000_000+i`` between NAIF and SPKID
    unchanged — only the id-type differs (comet rows are spkid-keyed).
    """
    if 2_000_000 < naif < 3_000_000:
        return _SPKID, naif + 18_000_000
    if 1_000_000 < naif < 2_000_000:
        return _SPKID, naif
    return _NAIF, naif


def _phase_end_et(
    events: list[ProbeEvent], landing_idx: int, start_et: float
) -> float | None:
    """ET at which the phase from ``events[landing_idx]`` ends, or ``None``
    if the probe stays landed indefinitely.

    The next departure has to be strictly later than the landing — a
    day-precision ``sample_return`` written against a timestamped ``landing``
    reads as midnight, before the touchdown it followed.
    """
    landing = events[landing_idx]
    if landing.end_jd is not None:
        end = jd_to_et(landing.end_jd)
        if end > start_et:
            return end
    for nxt in events[landing_idx + 1 :]:
        if nxt.type not in _DEPARTURE_TYPES:
            continue
        end = jd_to_et(nxt.jd)
        if end > start_et:
            return end
    return None


def _spk_covered_probe_ids() -> set[int]:
    """Probe_ids whose craft a SPICE kernel already flies.

    The SPICE landed pipeline owns those, and a phase from here as well would
    double-render the spacecraft. Matched through COSPAR as well as the id
    itself: Viking 1/2 carry an events-DB row and an SPK row for the same
    lander, and only the COSPAR joins them.
    """
    from space_map_data.probes.probe_id import load_registry

    flagged = [
        (entry, any(s["mission"] != "EVENTS-DB" for s in entry["kernel_sources"]))
        for entry in load_registry()
    ]
    spk_cospars = {
        e["cospar_id"] for e, has_spk in flagged if has_spk and e.get("cospar_id")
    }
    return {
        int(e["probe_id"])
        for e, has_spk in flagged
        if has_spk or e.get("cospar_id") in spk_cospars
    }


def load_phases(end_et_for_indefinite: float) -> list[LandingPhase]:
    """Every landed phase the curated events describe.
    ``end_et_for_indefinite`` is the upper bound for probes that stay on the
    surface (caller passes ``jd_to_et(year_to_jd(PROBE_EXPORT_END_YEAR))``).
    """
    spk_covered = _spk_covered_probe_ids()
    out: list[LandingPhase] = []
    skipped_no_target = 0
    skipped_spk_covered = 0
    for probe in load_event_probes():
        if probe.probe_id in spk_covered:
            skipped_spk_covered += 1
            logger.debug(
                "events: %s has SPK coverage; deferring to the SPICE pipeline",
                probe.name,
            )
            continue
        for i, ev in enumerate(probe.events):
            # No site means no fixed surface point was reached: an impact whose
            # place was never established. A burn-up's site is a ground track,
            # not a resting place.
            if ev.type not in _SITED_TYPES or ev.site is None:
                continue
            if ev.target is None or ev.target.naif is None:
                skipped_no_target += 1
                logger.info(
                    "events: %s %s on %s names no body; skipping",
                    probe.name,
                    ev.type,
                    ev.date,
                )
                continue
            body_id_type, body_id_value = _resolve_body(ev.target.naif)
            start_et = jd_to_et(ev.jd)
            end_et = _phase_end_et(probe.events, i, start_et)
            if end_et is None:
                end_et = end_et_for_indefinite
            if body_id_type == _NAIF and body_id_value == _EARTH_NAIF:
                end_et = min(end_et, start_et + _EARTH_LANDING_MAX_S)
            out.append(
                LandingPhase(
                    probe_id=probe.probe_id,
                    probe_name=probe.name,
                    body_id_type=body_id_type,
                    body_id_value=body_id_value,
                    lat_deg=ev.site.lat_deg,
                    lng_deg=ev.site.lon_deg,
                    start_et=start_et,
                    end_et=end_et,
                    site_name=ev.site.name,
                )
            )
    logger.info(
        "events: loaded %d landed phases (skipped: %d landings with no body, "
        "%d deferred to SPICE)",
        len(out),
        skipped_no_target,
        skipped_spk_covered,
    )
    return out


def probe_ids_with_phases(end_et_for_indefinite: float) -> set[int]:
    """Set of registry probe_ids that have at least one resolvable landed
    phase. Used by the ingestor to decide which EVENTS-DB-only registry
    entries need an Object row."""
    return {p.probe_id for p in load_phases(end_et_for_indefinite)}
