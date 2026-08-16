"""Equilibrium temperature for bodies nobody has measured.

Wikidata's hand-entered values mix semi-major-axis and perihelion sources, so
comparable objects can land 25 K apart for no reason. Recomputing here keeps
the catalogue consistent across the million-odd unmeasured objects, at the
cost of being an estimate (export marks it as such).

Radiative equilibrium only — no greenhouse, no internal heat, no thermal
inertia. Wrong for Venus, so measured values always win.
"""

import logging
import math

from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.interior.references import INTERIOR_SOURCES
from space_map_data.constants.temperature.bodies import TEMPERATURE_BODIES
from space_map_data.constants.temperature.references import TEMPERATURE_SOURCES
from space_map_data.export.objects.sources import source_row

logger = logging.getLogger(__name__)

# Headline first, so a star leads with its photosphere and a giant with the
# deck you can actually see.
PART_ORDER = ("surface", "cloud_top", "photosphere", "corona", "core")
READING_ORDER = ("min", "mean", "max")
CONDITIONS = ("night", "day", "record", "modelled")

# IAU nominal total solar irradiance at 1 AU, W/m^2.
_SOLAR_CONSTANT = 1361.0
_STEFAN_BOLTZMANN = 5.670374419e-8

# Phase integral, H-G system at default G = 0.15 (Bowell et al. 1989).
_PHASE_INTEGRAL = 0.39

# Beyond this the "surface" is a cloud deck with its own heat budget, and
# radiative equilibrium stops describing anything.
_MAX_GEOMETRIC_ALBEDO = 1.0

# Which interior layers a `part="core"` reading may be read off.
_CORE_ROLES = frozenset({"core", "outer_core", "inner_core"})


def bond_albedo(geometric_albedo: float | None) -> float:
    """Bond albedo from the catalogue's geometric albedo, 0 when unknown.

    Zero matches what the published temperatures this replaces assumed, and
    for the dark bodies dominating the catalogue the correction is under 1 K.
    """
    if geometric_albedo is None:
        return 0.0
    if not 0.0 <= geometric_albedo <= _MAX_GEOMETRIC_ALBEDO:
        logger.warning("Ignoring out-of-range geometric albedo %s", geometric_albedo)
        return 0.0
    return _PHASE_INTEGRAL * geometric_albedo


def equilibrium_temperature(
    distance_au: float, geometric_albedo: float | None = None
) -> float | None:
    """Isothermal equilibrium temperature in kelvin at *distance_au*.

    Isothermal, not subsolar, so the result reads as a mean, not a hottest point.
    """
    if distance_au <= 0.0:
        logger.warning("Skipping equilibrium temperature: distance %s AU", distance_au)
        return None
    flux = _SOLAR_CONSTANT * (1.0 - bond_albedo(geometric_albedo)) / distance_au**2
    return (flux / (4.0 * _STEFAN_BOLTZMANN)) ** 0.25


# Planetary semi-major axes, AU, keyed by the barycentre a moon orbits — a
# moon's own `a` is relative to its planet, not the Sun.
_BARYCENTRE_DISTANCE_AU = {
    "naif-1": 0.387,
    "naif-2": 0.723,
    "naif-3": 1.000,
    "naif-4": 1.524,
    "naif-5": 5.203,
    "naif-6": 9.537,
    "naif-7": 19.191,
    "naif-8": 30.069,
    "naif-9": 39.482,
}

_SUN_ID = "naif-10"


def heliocentric_distance_au(
    semi_major_axis: float | None, parent_id: str | None
) -> float | None:
    """Distance to use for a body's insolation, or None if it can't be known."""
    if parent_id is not None and parent_id != _SUN_ID:
        return _BARYCENTRE_DISTANCE_AU.get(parent_id)
    # Hyperbolic orbits (negative a) have no characteristic distance, so no
    # estimate — not worth logging per object.
    if (
        semi_major_axis is not None
        and math.isfinite(semi_major_axis)
        and semi_major_axis > 0.0
    ):
        return semi_major_axis
    return None


def _core_readings(object_id: str) -> tuple[list[dict], list[dict]]:
    """The hottest the body gets, as a low-high pair, plus its citations.

    Deepest available interior temperature: centre if known, else the innermost
    *core*-role boundary. Core roles only — Titan's ice-ocean interface is its
    innermost number but 250 K a thousand km above the rock, worse than
    reporting nothing.

    Nobody has measured a planetary core, so the bracket is model spread, not
    error — hence `condition="modelled"`. Rides in `readings` like any other
    part, but never shares a bar with the outside: the Sun's core is 15.5
    million K against a 5772 K photosphere.
    """
    facts = INTERIOR_FACTS.get(object_id)
    if facts is None:
        return [], []

    deepest = (
        facts.centre_temperature_k,
        facts.centre_temperature_range_k,
        facts.centre_temperature_sources,
    )
    if deepest[0] is None and deepest[1] is None:
        for layer in reversed(facts.layers):
            if layer.role not in _CORE_ROLES:
                continue
            if layer.outer_temperature_k is not None or layer.outer_temperature_range_k:
                deepest = (
                    layer.outer_temperature_k,
                    layer.outer_temperature_range_k,
                    layer.temperature_sources,
                )
                break
    value, width, sources = deepest
    if width is not None:
        low, high = width
    elif value is not None:
        low = high = value
    else:
        return [], []

    return (
        [
            _reading("core", "min", low, "modelled"),
            _reading("core", "max", high, "modelled"),
        ],
        [source_row(INTERIOR_SOURCES[k]) for k in dict.fromkeys(sources)],
    )


def _source_entries(keys: list[str]) -> list[dict]:
    return [source_row(TEMPERATURE_SOURCES[k]) for k in dict.fromkeys(keys)]


def temperature_block(
    object_id: str,
    wikidata_readings: list[dict] | None = None,
    distance_au: float | None = None,
    geometric_albedo: float | None = None,
) -> dict | None:
    """Build the `temperatures` block, or None if the body has no temperature.

    Three sources for the *outside* of the body, in descending confidence:
    cited constant, Wikidata, computed estimate. Not merged — one origin per
    body, since a mixed measured/estimated bar reads as neither. The modelled
    core rides along with any of them, flagged, since it's drawn separately.
    """
    core, core_sources = _core_readings(object_id)

    if constants := TEMPERATURE_BODIES.get(object_id):
        _validate(object_id, constants)
        readings = [
            _reading(part.part, r.kind, r.kelvin, r.condition)
            for part in constants
            for r in part.readings
        ]
        keys = [k for part in constants for k in part.sources]
        return {
            "readings": _sorted(readings + core),
            "origin": "measured",
            "sources": _dedupe(_source_entries(keys) + core_sources),
        }

    if wikidata_readings:
        # No work to cite — Wikidata's own item is the whole provenance, so the
        # block names it rather than leaving a measurement uncredited.
        block = {
            "readings": _sorted(wikidata_readings + core),
            "origin": "measured",
            "provenance": "wikidata",
        }
        if core_sources:
            block["sources"] = core_sources
        return block

    if distance_au is not None:
        kelvin = equilibrium_temperature(distance_au, geometric_albedo)
        if kelvin is not None:
            block = {
                "readings": _sorted([_reading("surface", "mean", kelvin)] + core),
                "origin": "estimated",
            }
            if core_sources:
                block["sources"] = core_sources
            return block

    # A body with nothing but a modelled core still has something to say.
    if core:
        return {"readings": core, "origin": "measured", "sources": core_sources}
    return None


def _dedupe(entries: list[dict]) -> list[dict]:
    """One credit per work. The interior and temperature reference tables both
    carry a few of the same papers, so the same url can arrive twice."""
    seen: dict[str, dict] = {}
    for entry in entries:
        seen.setdefault(entry["url"], entry)
    return list(seen.values())


def _reading(part: str, kind: str, kelvin: float, condition: str | None = None) -> dict:
    entry = {"part": part, "kind": kind, "k": round(kelvin, 2)}
    if condition is not None:
        entry["condition"] = condition
    return entry


def _sorted(readings: list[dict]) -> list[dict]:
    return sorted(
        readings,
        key=lambda r: (PART_ORDER.index(r["part"]), READING_ORDER.index(r["kind"])),
    )


def _validate(object_id: str, parts: tuple) -> None:
    """Enum and citation check — a typo here ships an unlabelled reading or an
    uncredited number, neither of which the frontend can detect."""
    for part in parts:
        if part.part not in PART_ORDER:
            raise ValueError(f"{object_id}: unknown part {part.part}")
        for reading in part.readings:
            if reading.kind not in READING_ORDER:
                raise ValueError(f"{object_id}: unknown kind {reading.kind}")
            if reading.condition is not None and reading.condition not in CONDITIONS:
                raise ValueError(f"{object_id}: unknown condition {reading.condition}")
        for key in part.sources:
            if key not in TEMPERATURE_SOURCES:
                raise ValueError(f"{object_id}: no such source {key}")
