"""Load landed phases from probe event JSONs.

Walks ``DOWNLOAD_DIR/probes/events/*.json``, yields one ``LandingPhase`` per
``landing`` or ``reentry`` event that carries a ``site``. Phase end is the
next ``_DEPARTURE_TYPES`` event or ``end_date`` on the landing itself;
otherwise the probe stays landed forever (Apollo descent stages, Veneras,
Surveyors). Earth landings are capped to one month so sample-return capsules
and launch failures don't clutter Earth after touchdown.

The site sits on the event, not the probe, so a craft that touches down more
than once gets a phase per touchdown at its own coordinates (Hayabusa2's
three Ryugu contacts, LCROSS, the Chang'e 5/6 lander-ascenders):

    {
      "probe_id": 12345,
      "name": "...",
      "events": [
        ...,
        {"type": "landing", "date": "...", "outcome": "...",
         "target": {"naif": 299, "name": "Venus"},
         "site": {"lat_deg": 7.5, "lon_deg": 177.7, "name": "..." | null},
         "intentional"?: bool, "end_date"?: "...", ...}
      ]
    }

An event with no ``site`` — or a ``burnup_above_surface`` outcome — reached
no fixed surface point and yields no phase.

Asteroid landings use Horizons-NAIF in ``target.naif`` (``2_000_000+n``),
mapped to SBDB SPKID (``20_000_000+n``) to match the DB row (``spkid-N``).
Comets share the ``1_000_000+n`` scheme between NAIF and SPKID — only the
id-type byte changes.
"""

import datetime
import json
import logging
from dataclasses import dataclass

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.position.format import ID_TYPE_ORDINAL
from space_map_data.utils.paths import SOURCES_POSITION_DIR
from space_map_data.utils.time import jd_to_et

logger = logging.getLogger(__name__)

EVENTS_DIR = SOURCES_POSITION_DIR / "probe-events"

# Events that terminate a landed phase. ``mission_end``/``contact_lost``
# are excluded — dying on the surface (Apollo descent stages, every Venera,
# Surveyor 1) still counts as landed. ``stage_separation`` is excluded too:
# a piece falling off doesn't move the probe whose row this is; ascent
# stages get their own probe row and landing event.
_DEPARTURE_TYPES = frozenset(
    {
        "launch",
        "orbit_departure",
        "landing",
        "impact",
        "flyby",
        "earth_flyby",
        "gravity_assist",
        "decay",
        "splashdown",
        "sample_return",
        "atmospheric_entry",
        "interstellar_boundary_crossed",
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


def _parse_iso_to_jd(s: str) -> float:
    """Parse an ISO-ish date from the events files into a JD.

    Accepts ``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD``, ``YYYY-MM-DDTHH:MM[:SS]Z``.
    Treats UTC as TDB — the ~37 s offset is irrelevant for landed-phase
    bookkeeping where the probe is pinned to one body-fixed position.
    """
    s = s.rstrip("Z")
    if "T" in s:
        dt = datetime.datetime.fromisoformat(s)
    elif s.count("-") == 2:
        dt = datetime.datetime.fromisoformat(s)
    elif s.count("-") == 1:
        y, m = s.split("-")
        dt = datetime.datetime(int(y), int(m), 1)
    else:
        dt = datetime.datetime(int(s), 1, 1)
    frac = (
        dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6
    ) / 86400.0
    return dt.toordinal() + 1721424.5 + frac


def _resolve_body(naif: int) -> tuple[int, int]:
    """Map ``target_body_naif`` (Horizons convention) to the renderer's
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
    events: list[dict], landing_idx: int, start_et: float
) -> float | None:
    """ET at which the phase from ``events[landing_idx]`` ends, or ``None``
    if the probe stays landed indefinitely. Priority: ``end_date`` on the
    landing itself, then the next ``_DEPARTURE_TYPES`` event strictly later
    than ``start_et`` — skips same-instant/same-day lower-precision events
    that would otherwise compare equal or earlier (Chang'e returners follow
    a timestamped ``landing`` with a date-only ``sample_return`` at 00:00).
    """
    landing = events[landing_idx]
    if landing.get("end_date"):
        try:
            end = jd_to_et(_parse_iso_to_jd(landing["end_date"]))
            if end > start_et:
                return end
        except ValueError, TypeError:
            logger.warning(
                "events: unparseable end_date %r on %s; falling back to next-departure",
                landing.get("end_date"),
                landing.get("type"),
            )
    for nxt in events[landing_idx + 1 :]:
        if nxt.get("type") not in _DEPARTURE_TYPES:
            continue
        try:
            end = jd_to_et(_parse_iso_to_jd(nxt["date"]))
        except ValueError, TypeError, KeyError:
            continue
        if end > start_et:
            return end
    return None


def _spk_covered_probe_ids() -> set[int]:
    """Registry probe_ids already owned by an SPK kernel.

    Skips events-driven phases for missions that also publish a SPICE
    landed kernel — Viking 1/2 have both an events-DB entry and an SPK
    entry for the same lander. Emitting a phase here too would
    double-render the spacecraft.
    """
    from space_map_data.probes.probe_id import load_registry

    return {
        int(entry["probe_id"])
        for entry in load_registry()
        if not all(s["mission"] == "EVENTS-DB" for s in entry["kernel_sources"])
    }


def load_phases(end_et_for_indefinite: float) -> list[LandingPhase]:
    """Read every events JSON; emit one ``LandingPhase`` per ``landing`` or
    ``reentry`` event carrying a ``site``.
    ``end_et_for_indefinite`` is the upper bound for probes that stay on the
    surface (caller passes ``jd_to_et(year_to_jd(PROBE_EXPORT_END_YEAR))``).
    """
    if not EVENTS_DIR.exists():
        logger.info("No events dir at %s; no events-driven landings", EVENTS_DIR)
        return []
    spk_probe_ids = _spk_covered_probe_ids()
    out: list[LandingPhase] = []
    skipped_incomplete_site = 0
    skipped_spk_covered = 0
    for path in sorted(EVENTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except OSError, json.JSONDecodeError:
            logger.exception("events: failed to read %s; skipping", path)
            continue
        for probe in data.get("probes", []):
            pid = probe.get("probe_id")
            name = probe.get("name", "?")
            if pid is None:
                logger.warning(
                    "events: probe %r in %s has no probe_id", name, path.name
                )
                continue
            # SPK-covered missions (Viking 1/2 Lander, …) are handled by
            # the SPICE landed pipeline; emitting a phase here too would
            # double-render them.
            if int(pid) in spk_probe_ids:
                skipped_spk_covered += 1
                logger.debug(
                    "events: %s has SPK coverage; deferring to SPICE pipeline", name
                )
                continue
            events = probe.get("events", [])
            for i, ev in enumerate(events):
                if ev.get("type") not in _SITED_TYPES:
                    continue
                site = ev.get("site")
                if not isinstance(site, dict):
                    continue
                if ev.get("outcome") == "burnup_above_surface":
                    # A burn-up reached no surface, so any site on it is a
                    # ground track rather than a resting place.
                    continue
                naif = (ev.get("target") or {}).get("naif")
                lat = site.get("lat_deg")
                lng = site.get("lon_deg")
                if naif is None or lat is None or lng is None:
                    skipped_incomplete_site += 1
                    logger.info(
                        "events: %s %s site missing required field "
                        "(target.naif/lat_deg/lon_deg); skipping",
                        name,
                        ev.get("type"),
                    )
                    continue
                try:
                    start_et = jd_to_et(_parse_iso_to_jd(ev["date"]))
                except ValueError, TypeError, KeyError:
                    logger.exception(
                        "events: %s landing date %r unparseable; skipping",
                        name,
                        ev.get("date"),
                    )
                    continue
                body_id_type, body_id_value = _resolve_body(int(naif))
                end_et = _phase_end_et(events, i, start_et)
                if end_et is None:
                    end_et = end_et_for_indefinite
                if body_id_type == _NAIF and body_id_value == _EARTH_NAIF:
                    end_et = min(end_et, start_et + _EARTH_LANDING_MAX_S)
                out.append(
                    LandingPhase(
                        probe_id=int(pid),
                        probe_name=name,
                        body_id_type=body_id_type,
                        body_id_value=body_id_value,
                        lat_deg=float(lat),
                        lng_deg=float(lng),
                        start_et=start_et,
                        end_et=end_et,
                        site_name=site.get("name"),
                    )
                )
    logger.info(
        "events: loaded %d landed phases (skipped: %d incomplete site, "
        "%d deferred to SPICE)",
        len(out),
        skipped_incomplete_site,
        skipped_spk_covered,
    )
    return out


def probe_ids_with_phases(end_et_for_indefinite: float) -> set[int]:
    """Set of registry probe_ids that have at least one resolvable landed
    phase. Used by the ingestor to decide which EVENTS-DB-only registry
    entries need an Object row."""
    return {p.probe_id for p in load_phases(end_et_for_indefinite)}
