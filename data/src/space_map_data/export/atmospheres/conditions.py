"""The level the shell is rendered from, resolved against the published facts.

`constants/atmosphere/bodies.py` states only what rendering adds. A body's
composition lives once in `constants/atmosphere/facts.py` and its temperature
once in `constants/temperature/bodies.py`; this reads the render level off
those, applying an override only where the render table declares one. A
single source per fact rules out a body's numbers diverging between renderer
and consumers.
"""

import logging
from typing import NamedTuple

from space_map_data.constants.atmosphere.bodies import BodyAtmosphere
from space_map_data.constants.atmosphere.facts import (
    ATMOSPHERE_FACTS,
    VOLUME_FRACTION,
)
from space_map_data.constants.atmosphere.gases import GAS_OPTICS
from space_map_data.constants.temperature.bodies import TEMPERATURE_BODIES

logger = logging.getLogger(__name__)

# The deck a shell is drawn from, in the order it is looked for: a body with a
# visible cloud top is rendered against it, everything else against its
# surface. Matches how `facts.py` quotes its pressure.
_RENDER_PARTS = ("cloud_top", "surface")


class RenderConditions(NamedTuple):
    """Composition, pressure and temperature at the level the shell renders
    from — whether published or overridden."""

    composition: dict[str, float]
    pressure_pa: float
    temperature_k: float


def render_conditions(object_id: str, body: BodyAtmosphere) -> RenderConditions:
    """Resolve *body*'s render level, or raise if the facts cannot back it."""
    return RenderConditions(
        composition=body.composition or _composition(object_id),
        pressure_pa=body.pressure_pa
        if body.pressure_pa is not None
        else _pressure(object_id),
        temperature_k=body.temperature_k
        if body.temperature_k is not None
        else _temperature(object_id),
    )


def _composition(object_id: str) -> dict[str, float]:
    """The published mixture, minus what the Rayleigh model cannot see.

    A panel lists what was measured — Venus's SO₂, Titan's ⁴⁰Ar, the giants'
    deuterated hydrogen — and `gases.py` carries dispersion fits for seven
    gases. The rest are trace at these levels and the derivation renormalises
    what is left, so dropping them moves the mixture by ~1e-5.
    """
    facts = _facts(object_id)
    # Shares of a column or a number density are not mixing ratios, and the
    # Rayleigh derivation would read them as if they were. No rendered body
    # is quoted that way today; this is what stops the first one that is.
    if facts.composition_unit != VOLUME_FRACTION:
        raise ValueError(
            f"{object_id}: rendering needs volume fractions, "
            f"facts.py quotes {facts.composition_unit}"
        )
    kept = {s.formula: s.value for s in facts.composition if s.formula in GAS_OPTICS}
    if not kept:
        raise ValueError(f"{object_id}: no rendered species have Rayleigh optics")
    dropped = {s.formula: s.value for s in facts.composition if s.formula not in kept}
    if dropped:
        logger.debug(
            "%s: no Rayleigh optics for %s; renormalising the remaining %.4f",
            object_id,
            ", ".join(f"{gas} ({value:.3g})" for gas, value in dropped.items()),
            sum(kept.values()),
        )
    return kept


def _pressure(object_id: str) -> float:
    pressure = _facts(object_id).pressure
    if pressure is None:
        raise ValueError(f"{object_id}: no published pressure to render from")
    return pressure.pascals


def _temperature(object_id: str) -> float:
    parts = {p.part: p for p in TEMPERATURE_BODIES.get(object_id, ())}
    for name in _RENDER_PARTS:
        part = parts.get(name)
        if part is None:
            continue
        for reading in part.readings:
            if reading.kind == "mean":
                return reading.kelvin
    raise ValueError(
        f"{object_id}: no measured {' or '.join(_RENDER_PARTS)} temperature "
        "to render from"
    )


def _facts(object_id: str):
    facts = ATMOSPHERE_FACTS.get(object_id)
    if facts is None:
        raise ValueError(f"{object_id}: rendered but absent from facts.py")
    return facts
