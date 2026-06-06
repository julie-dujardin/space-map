"""Load landed phases from probe event JSONs.

Walks ``DOWNLOAD_DIR/probes/events/*.json``, yields one ``LandingPhase``
per landing/touchdown event whose coordinates are known. Phase end =
the next event in ``_DEPARTURE_TYPES`` (re-launch, departure, next
touchdown, …) or ``end_date`` on the landing itself; otherwise the
probe is considered landed forever (Apollo descent stages, Veneras,
Surveyors, mission_end on the surface).

Asteroid landings use Horizons-NAIF in the source JSON
(``2_000_000+n``); the body-id resolver maps to SBDB SPKID
(``20_000_000+n``) so the encoded id matches the asteroid's row in the
DB (keyed ``spkid-N``). Comets share the ``1_000_000+n`` scheme between
NAIF and SPKID; only the id-type byte changes.
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

# Events that terminate a landed phase. `mission_end` / `contact_lost` are
# deliberately excluded — a probe that dies on the surface (Apollo descent
# stages, every Venera, Surveyor 1) is still landed. `stage_separation` is
# also excluded: a piece falling off (heatshield, ascent stage release from
# the descent stage's POV) doesn't move the probe whose row this is. Ascent
# stages crash back to the surface as their own probe with their own
# landing event.
_DEPARTURE_TYPES = frozenset(
    {
        "launch",
        "orbit_departure",
        "landing",
        "touchdown",
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

# Mission-type → (body_id_type ordinal, body_id_value) for events without a
# `metadata.target_body_naif`. Sample-return capsules etc. land on Earth.
_NAIF = ID_TYPE_ORDINAL[ID_TYPES.NAIF]
_SPKID = ID_TYPE_ORDINAL[ID_TYPES.SPKID]
_MISSION_TYPE_TO_BODY: dict[str, tuple[int, int]] = {
    "lunar_lander": (_NAIF, 301),
    "lunar_module_descent": (_NAIF, 301),
    "lunar_rover": (_NAIF, 301),
    "lunar_sample_return": (_NAIF, 301),
    "commercial_lunar_lander": (_NAIF, 301),
    "lunar_flyby_orbiter": (_NAIF, 301),
    "mars_lander": (_NAIF, 499),
    "mars_rover": (_NAIF, 499),
    "venus_lander": (_NAIF, 299),
    "venus_atmospheric_probe": (_NAIF, 299),
    "titan_lander": (_NAIF, 606),
    "phobos_sample_return": (_NAIF, 401),
    "asteroid_sample_return_capsule": (_NAIF, 399),
    "comet_sample_return_capsule": (_NAIF, 399),
    "lunar_sample_return_capsule": (_NAIF, 399),
    "circumlunar_test_capsule": (_NAIF, 399),
    "sample_return_bus": (_NAIF, 399),
}


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


def _coords(event: dict) -> tuple[float, float] | None:
    """Two equivalent shapes in the source: ``{latitude, longitude}`` (Soviet/
    Apollo files) and ``{lat_deg, lon_deg}`` (Mars/Spirit/Curiosity files).
    Both are accepted.

    Longitude is normalised to ``[-180, 180]`` because the wire format packs
    it as ``int32 × 1e7``: 351°E quantises to 3.51e9, which overflows int32
    (max 2.15e9) and clamps to ~214.7°. Source files mix conventions —
    Apollo lunar coords are already signed (``-23.42157``), Soviet Venus
    coords use 0–360°E (``351``, ``291.64``) — so we standardise here.
    """
    meta = event.get("metadata") or {}
    c = meta.get("landing_coordinates") or meta.get("touchdown_coordinates")
    if not isinstance(c, dict):
        # Outer-planets file has Huygens with a free-form "10.573°S, 192.335°W"
        # string. Huygens has SPK coverage anyway; rather than parsing the
        # string, skip the events-driven landing and let the SPICE pipeline
        # handle it.
        return None
    lat = c.get("latitude", c.get("lat_deg"))
    lng = c.get("longitude", c.get("lon_deg"))
    if lat is None or lng is None:
        return None
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return None
    # Wrap to [-180, 180] regardless of input convention.
    lng_f = ((lng_f + 180.0) % 360.0) - 180.0
    return lat_f, lng_f


def _resolve_body(event: dict, mission_type: str) -> tuple[int, int] | None:
    """Resolve ``(body_id_type, body_id_value)`` for a landing event.

    Priority: explicit ``metadata.target_body_naif`` (Horizons-NAIF) →
    ``mission_type`` table. ``target_body_name`` lookups are deferred (would
    need DB access); affected bodies (67P, Didymos) are skipped + logged.
    """
    meta = event.get("metadata") or {}
    naif = meta.get("target_body_naif")
    if naif is not None:
        n = int(naif)
        # Numbered asteroids: Horizons 2_000_000+i → SBDB spkid 20_000_000+i
        # (NAIF and SPKID use different offsets per the SBDB mapping memory).
        if 2_000_000 < n < 3_000_000:
            return _SPKID, n + 18_000_000
        # Comets share the 1_000_000+i scheme between NAIF and SPKID; the
        # value is identical, only the id-type differs (the DB rows for
        # comets are spkid-keyed).
        if 1_000_000 < n < 2_000_000:
            return _SPKID, n
        return _NAIF, n
    body = _MISSION_TYPE_TO_BODY.get(mission_type)
    if body is not None:
        return body
    return None


def _phase_end_et(
    events: list[dict], landing_idx: int, start_et: float
) -> float | None:
    """Return ET at which the landed phase started by ``events[landing_idx]``
    ends, or ``None`` if the probe stays landed indefinitely (dies on the
    surface). Priority: ``end_date`` on the landing event itself → next
    event in ``_DEPARTURE_TYPES`` whose parsed ET is strictly later than
    ``start_et`` (skip same-instant duplicates and same-day lower-precision
    events that would otherwise compare equal or earlier — Vega landers have
    duplicate ``landing``+``touchdown`` records at the same UTC; Chang'e
    returners follow a timestamped ``landing`` with a date-only
    ``sample_return`` that resolves to the day's 00:00).
    """
    landing = events[landing_idx]
    if landing.get("end_date"):
        try:
            end = jd_to_et(_parse_iso_to_jd(landing["end_date"]))
            if end > start_et:
                return end
        except (ValueError, TypeError):
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
        except (ValueError, TypeError, KeyError):
            continue
        if end > start_et:
            return end
    return None


def _spk_covered_cospars() -> set[str]:
    """COSPAR IDs already owned by an SPK-covered probe in the registry.

    Used to skip events-driven phases for missions that also publish a SPICE
    landed kernel — Viking 1/2 have both an events-DB registry entry (named
    after the mission) and an SPK entry (named after the lander), pointing at
    the same physical lander via COSPAR. The SPICE landed pipeline already
    emits METHOD_LANDED for the SPK probe; emitting another phase here would
    double-render the spacecraft.
    """
    from space_map_data.probes.probe_id import load_registry

    out: set[str] = set()
    for entry in load_registry():
        if all(s["mission"] == "EVENTS-DB" for s in entry["kernel_sources"]):
            continue
        cospar = entry.get("cospar_id")
        if cospar:
            out.add(cospar)
    return out


def load_phases(end_et_for_indefinite: float) -> list[LandingPhase]:
    """Read every events JSON; emit one ``LandingPhase`` per resolvable
    landing/touchdown. ``end_et_for_indefinite`` is the upper bound for
    probes that stay on the surface (caller passes
    ``jd_to_et(year_to_jd(PROBE_EXPORT_END_YEAR))``).
    """
    if not EVENTS_DIR.exists():
        logger.info("No events dir at %s; no events-driven landings", EVENTS_DIR)
        return []
    spk_cospars = _spk_covered_cospars()
    out: list[LandingPhase] = []
    skipped_no_body = 0
    skipped_no_coords = 0
    skipped_spk_covered = 0
    for path in sorted(EVENTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            logger.exception("events: failed to read %s; skipping", path)
            continue
        for probe in data.get("probes", []):
            pid = probe.get("probe_id")
            name = probe.get("name", "?")
            mt = probe.get("mission_type", "")
            if pid is None:
                logger.warning(
                    "events: probe %r in %s has no probe_id", name, path.name
                )
                continue
            # SPK-covered missions (Viking 1/2 Lander, …) are handled by the
            # SPICE landed pipeline; the events file carries them too for
            # completeness but they'd double-render if we emitted phases.
            cospar = probe.get("cospar_id")
            if cospar and cospar in spk_cospars:
                skipped_spk_covered += 1
                logger.info(
                    "events: %s has SPK coverage (COSPAR %s); deferring to SPICE pipeline",
                    name,
                    cospar,
                )
                continue
            events = probe.get("events", [])
            for i, ev in enumerate(events):
                if ev.get("type") not in ("landing", "touchdown"):
                    continue
                coords = _coords(ev)
                if coords is None:
                    skipped_no_coords += 1
                    logger.info(
                        "events: %s landing on %s has no coordinates; skipping",
                        name,
                        ev.get("date"),
                    )
                    continue
                body = _resolve_body(ev, mt)
                if body is None:
                    skipped_no_body += 1
                    meta = ev.get("metadata") or {}
                    logger.warning(
                        "events: %s landing on %s: cannot resolve body "
                        "(mission_type=%r, target_body_name=%r); skipping",
                        name,
                        ev.get("date"),
                        mt,
                        meta.get("target_body_name"),
                    )
                    continue
                try:
                    start_et = jd_to_et(_parse_iso_to_jd(ev["date"]))
                except (ValueError, TypeError, KeyError):
                    logger.exception(
                        "events: %s landing date %r unparseable; skipping",
                        name,
                        ev.get("date"),
                    )
                    continue
                end_et = _phase_end_et(events, i, start_et)
                if end_et is None:
                    end_et = end_et_for_indefinite
                lat, lng = coords
                meta = ev.get("metadata") or {}
                out.append(
                    LandingPhase(
                        probe_id=int(pid),
                        probe_name=name,
                        body_id_type=body[0],
                        body_id_value=body[1],
                        lat_deg=lat,
                        lng_deg=lng,
                        start_et=start_et,
                        end_et=end_et,
                        site_name=meta.get("landing_site_name"),
                    )
                )
    logger.info(
        "events: loaded %d landed phases (skipped: %d no body, %d no coords, "
        "%d deferred to SPICE)",
        len(out),
        skipped_no_body,
        skipped_no_coords,
        skipped_spk_covered,
    )
    return out


def probe_ids_with_phases(end_et_for_indefinite: float) -> set[int]:
    """Set of registry probe_ids that have at least one resolvable landed
    phase. Used by the ingestor to decide which EVENTS-DB-only registry
    entries need an Object row."""
    return {p.probe_id for p in load_phases(end_et_for_indefinite)}
