"""Per-object atmosphere stat block, denormalized onto a body's global bundle.

Turns the cited constants in `constants/atmosphere/facts.py` into what the
object panel draws: one pressure at one named level, species as shares of the
listed set, and the works behind them. Shares are computed here rather than in
the frontend so every client normalizes the same way — and because what they
are shares *of* differs by body (volume fraction, mass fraction, or a set of
separately measured densities).
"""

import logging

from space_map_data.constants.atmosphere.facts import (
    ATMOSPHERE_FACTS,
    ATMOSPHERE_TYPES,
    COMPOSITION_UNITS,
    NOTES,
    PRESSURE_LEVELS,
    QUALIFIERS,
    BodyFacts,
)
from space_map_data.constants.atmosphere.references import ATMOSPHERE_FACT_SOURCES

logger = logging.getLogger(__name__)

# A share needs something to be a share of: one species is a detection, not a
# composition, and would draw a full bar of itself.
_MIN_SPECIES = 2


def atmosphere_block(object_id: str) -> dict | None:
    """Build the `atmosphere` block for `object_id`, or None if the body has no
    measured envelope."""
    facts = ATMOSPHERE_FACTS.get(object_id)
    if facts is None:
        return None
    _validate(object_id, facts)

    block: dict = {"type": facts.atmosphere_type}
    if facts.note is not None:
        block["note"] = facts.note
    sources: list[str] = []

    if facts.pressure is not None:
        pressure: dict = {
            "pa": facts.pressure.pascals,
            "level": facts.pressure.level,
        }
        if facts.pressure.qualifier is not None:
            pressure["qualifier"] = facts.pressure.qualifier
        block["pressure"] = pressure
        sources.append(facts.pressure.source)

    if len(facts.composition) >= _MIN_SPECIES:
        total = sum(s.value for s in facts.composition)
        species = []
        for s in sorted(facts.composition, key=lambda s: -s.value):
            entry = {"formula": s.formula, "share": _sig(s.value / total)}
            # Mercury's helium and the Moon's whole nighttime list are
            # non-detection limits; a bar that draws them as abundances would
            # be the most confident thing on the page about the least certain
            # numbers.
            if s.upper_limit:
                entry["limit"] = True
            species.append(entry)
        block["composition"] = {"unit": facts.composition_unit, "species": species}
        sources.extend(s.source for s in facts.composition)
    elif facts.composition:
        logger.info(
            "%s: %d species is too few for a composition bar; shipping the "
            "atmosphere type alone",
            object_id,
            len(facts.composition),
        )

    if facts.type_source is not None:
        sources.append(facts.type_source)

    block["sources"] = [
        {"title": ref.title, "url": ref.url}
        for ref in (ATMOSPHERE_FACT_SOURCES[key] for key in _unique(sources))
    ]
    return block


def _validate(object_id: str, facts: BodyFacts) -> None:
    """Enum and citation check — a typo here would ship a body with an
    unlabelled tag or an uncredited number."""
    if facts.atmosphere_type not in ATMOSPHERE_TYPES:
        raise ValueError(
            f"{object_id}: unknown atmosphere type {facts.atmosphere_type}"
        )
    if facts.composition_unit not in COMPOSITION_UNITS:
        raise ValueError(f"{object_id}: unknown unit {facts.composition_unit}")
    if facts.note is not None and facts.note not in NOTES:
        raise ValueError(f"{object_id}: unknown note {facts.note}")
    if facts.pressure is not None:
        if facts.pressure.level not in PRESSURE_LEVELS:
            raise ValueError(f"{object_id}: unknown level {facts.pressure.level}")
        if (
            facts.pressure.qualifier is not None
            and facts.pressure.qualifier not in QUALIFIERS
        ):
            raise ValueError(
                f"{object_id}: unknown qualifier {facts.pressure.qualifier}"
            )
    keys = [s.source for s in facts.composition]
    if facts.pressure is not None:
        keys.append(facts.pressure.source)
    if facts.type_source is not None:
        keys.append(facts.type_source)
    for key in keys:
        if key not in ATMOSPHERE_FACT_SOURCES:
            raise ValueError(f"{object_id}: no such source {key}")


def _unique(keys: list[str]) -> list[str]:
    """Dedupe, first occurrence wins — pressure before composition, so the
    panel lists the source of the headline number first."""
    return list(dict.fromkeys(keys))


def _sig(value: float, digits: int = 4) -> float:
    return float(f"{value:.{digits}g}")
