"""Equilibrium temperature for bodies nobody has measured.

Wikidata carries a hand-entered temperature for about sixty small bodies, and
almost every one of them is this same formula recomputed by an editor — but
inconsistently: some used the semi-major axis, others perihelion, so two
comparable objects can land 25 K apart for no physical reason. Computing it
here instead makes the whole catalogue consistent and covers the other
million-odd objects, at the cost of being an estimate, which the export marks.

Radiative equilibrium only: no greenhouse, no internal heat, no thermal
inertia. It is close for airless fast rotators and wrong for Venus, which is
why measured values (constants/temperature/bodies.py) always win.
"""

import logging
import math

from space_map_data.constants.temperature.bodies import TEMPERATURE_BODIES
from space_map_data.constants.temperature.references import TEMPERATURE_SOURCES

logger = logging.getLogger(__name__)

# Headline first, so a star leads with its photosphere and a giant with the
# deck you can actually see.
PART_ORDER = ("surface", "cloud_top", "photosphere", "corona", "core")
READING_ORDER = ("min", "mean", "max")
CONDITIONS = ("night", "day", "record")

# IAU nominal total solar irradiance at 1 AU, W/m^2.
_SOLAR_CONSTANT = 1361.0
_STEFAN_BOLTZMANN = 5.670374419e-8

# Phase integral for the H-G system at the default G = 0.15 (Bowell et al.
# 1989), turning the catalogue's geometric albedo into the Bond albedo the
# energy balance needs.
_PHASE_INTEGRAL = 0.39

# Beyond this the "surface" is a cloud deck with its own heat budget, and
# radiative equilibrium stops describing anything.
_MAX_GEOMETRIC_ALBEDO = 1.0


def bond_albedo(geometric_albedo: float | None) -> float:
    """Bond albedo from the catalogue's geometric albedo, 0 when unknown.

    Zero is the right default rather than a survey mean: it is what the
    published equilibrium temperatures this replaces assumed, and for the dark
    bodies that dominate the catalogue the correction is under a kelvin.
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

    Isothermal (whole-surface reradiation) rather than subsolar, so the result
    reads as the body's mean rather than its hottest point.
    """
    if distance_au <= 0.0:
        logger.warning("Skipping equilibrium temperature: distance %s AU", distance_au)
        return None
    flux = _SOLAR_CONSTANT * (1.0 - bond_albedo(geometric_albedo)) / distance_au**2
    return (flux / (4.0 * _STEFAN_BOLTZMANN)) ** 0.25


# Planetary semi-major axes, AU, keyed by the barycentre a moon orbits. A
# moon's own `a` is measured from its planet and says nothing about how much
# sunlight it gets; beside the planet's distance its orbit is a rounding error.
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
    # Hyperbolic orbits carry a negative semi-major axis — tens of thousands of
    # comets and recent discoveries. They have no characteristic distance to
    # equilibrate at, so they simply get no estimate; not an error worth logging
    # per object.
    if (
        semi_major_axis is not None
        and math.isfinite(semi_major_axis)
        and semi_major_axis > 0.0
    ):
        return semi_major_axis
    return None


def temperature_block(
    object_id: str,
    wikidata_readings: list[dict] | None = None,
    distance_au: float | None = None,
    geometric_albedo: float | None = None,
) -> dict | None:
    """Build the `temperatures` block, or None if the body has no temperature.

    Three sources in descending order of confidence: a cited constant, then
    whatever Wikidata carries, then the computed estimate. They are not merged
    — a body gets exactly one origin, because a bar mixing a measured mean with
    an estimated maximum would be readable as neither.
    """
    if constants := TEMPERATURE_BODIES.get(object_id):
        _validate(object_id, constants)
        readings = [
            _reading(part.part, r.kind, r.kelvin, r.condition)
            for part in constants
            for r in part.readings
        ]
        keys = list(dict.fromkeys(k for part in constants for k in part.sources))
        return {
            "readings": _sorted(readings),
            "origin": "measured",
            "sources": [
                {
                    "title": TEMPERATURE_SOURCES[k].title,
                    "url": TEMPERATURE_SOURCES[k].url,
                }
                for k in keys
            ],
        }

    if wikidata_readings:
        return {"readings": _sorted(wikidata_readings), "origin": "measured"}

    if distance_au is not None:
        kelvin = equilibrium_temperature(distance_au, geometric_albedo)
        if kelvin is not None:
            return {
                "readings": [_reading("surface", "mean", kelvin)],
                "origin": "estimated",
            }
    return None


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
