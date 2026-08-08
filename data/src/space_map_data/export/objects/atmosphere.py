"""Per-object atmosphere stat block, denormalized onto a body's global bundle.

Turns the cited constants in `constants/atmosphere/facts.py` into what the
object panel draws: one pressure at one named level, species as shares of the
listed set, and the works behind them. Shares are computed here rather than in
the frontend so every client normalizes the same way — and because what they
are shares *of* differs by body (volume fraction, mass fraction, or a set of
separately measured densities).

`constants/atmosphere/structure.py` adds the vertical axis that pressure sits
on, for the twelve bodies whose layers anyone has named. It ships under
`structure` for the Structure tab's cross-section; the Overview reads only the
flat facts above it.
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
    Pressure,
)
from space_map_data.constants.atmosphere.references import ATMOSPHERE_FACT_SOURCES
from space_map_data.constants.atmosphere.structure import (
    ATMOSPHERE_STRUCTURE,
    DATUMS,
)
from space_map_data.constants.atmosphere.structure import (
    LAYER_ROLES as STRUCTURE_LAYER_ROLES,
)
from space_map_data.constants.atmosphere.structure import (
    NOTES as STRUCTURE_NOTES,
)
from space_map_data.constants.atmosphere.structure import (
    AtmosphereLayer,
    BodyStructure,
)
from space_map_data.constants.temperature.bodies import TEMPERATURE_BODIES
from space_map_data.export.objects.sources import source_row

logger = logging.getLogger(__name__)

# A share needs something to be a share of: one species is a detection, not a
# composition, and would draw a full bar of itself.
_MIN_SPECIES = 2

# Which datum a flat `Pressure.level` is a reading at. Sea level and the areoid
# are the surface with a shape attached; a cloud top is a level inside the
# atmosphere and no datum at all.
_DATUM_OF_LEVEL = {
    "surface": "surface",
    "sea_level": "surface",
    "areoid": "surface",
    "photosphere": "photosphere",
    "one_bar": "one_bar",
}

_ONE_BAR_PA = 1.0e5


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
        block["pressure"] = pressure_block(facts.pressure)
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

    structure = ATMOSPHERE_STRUCTURE.get(object_id)
    if structure is not None:
        _validate_structure(object_id, structure)
        block["structure"] = _structure(object_id, structure, facts)
        sources.extend(_structure_source_keys(structure))

    block["sources"] = [
        source_row(ATMOSPHERE_FACT_SOURCES[key]) for key in _unique(sources)
    ]
    return block


def pressure_block(pressure: Pressure) -> dict:
    """One published pressure, as the bundle carries it.

    Its own function because the Atmospheres collection page charts the same
    reading the body's own panel prints, and a second formatting of it is a
    second thing to keep in step. The level rides along because the number is
    meaningless without it: the four giants all read 0.1 bar, and that is a
    cloud top rather than a surface.
    """
    out: dict = {"pa": pressure.pascals, "level": pressure.level}
    if pressure.qualifier is not None:
        out["qualifier"] = pressure.qualifier
    return out


def _structure(object_id: str, structure: BodyStructure, facts: BodyFacts) -> dict:
    """The vertical stack, lowest layer first.

    Each layer is described by its top; its base is the layer below's top, and
    the lowest one's base is `datum`. Every field is optional because a
    boundary is a turning point in temperature rather than a surface, so a
    source pins sometimes a height, sometimes a pressure, rarely both.
    """
    out: dict = {"datum": structure.datum}
    if structure.note is not None:
        out["note"] = structure.note
    datum_k = _datum_temperature(object_id, structure)
    if datum_k is not None:
        out["datum_temperature_k"] = datum_k
    datum_pa = _datum_pressure(object_id, structure, facts)
    if datum_pa is not None:
        out["datum_pressure_pa"] = datum_pa
    if structure.homopause_km is not None:
        out["homopause_km"] = structure.homopause_km
    if structure.homopause_pressure_pa is not None:
        out["homopause_pressure_pa"] = structure.homopause_pressure_pa
    # An exosphere-only body has no boundaries to draw, so how fast it thins
    # is its whole vertical structure.
    if structure.scale_height_km is not None:
        out["scale_height_km"] = structure.scale_height_km

    layers = []
    for layer in structure.layers:
        entry: dict = {"role": layer.role}
        if layer.top_km is not None:
            entry["top_km"] = layer.top_km
        if layer.top_km_range is not None:
            entry["top_km_range"] = list(layer.top_km_range)
        if layer.top_pressure_pa is not None:
            entry["top_pressure_pa"] = layer.top_pressure_pa
        top_k = layer_temperature(object_id, layer)
        if top_k is not None:
            entry["top_temperature_k"] = top_k
        if layer.top_temperature_range_k is not None:
            entry["top_temperature_range_k"] = list(layer.top_temperature_range_k)
        if layer.note is not None:
            entry["note"] = layer.note
        if layer.composition:
            # Raw mixing ratios in the body's own unit, not shares of a set:
            # a layer lists a species only where its abundance differs from
            # the body's, and Titan's stratospheric methane normalized against
            # itself would draw as a pure-methane layer.
            entry["species"] = [
                {"formula": s.formula, "value": s.value} for s in layer.composition
            ]
        layers.append(entry)
    out["layers"] = layers
    return out


def layer_temperature(object_id: str, layer: AtmosphereLayer) -> float | None:
    """A boundary's temperature, resolved where it is a published reading.

    Venus's tropopause is its cloud top and the Sun's corona is the corona:
    the same claim the `temperatures` block ships, so it is read from there
    rather than restated beside the altitude.
    """
    if layer.top_temperature_from is None:
        return layer.top_temperature_k
    part_name, kind = layer.top_temperature_from
    for part in TEMPERATURE_BODIES.get(object_id, ()):
        if part.part != part_name:
            continue
        for reading in part.readings:
            if reading.kind == kind:
                return reading.kelvin
    raise ValueError(f"{object_id}: no {kind} {part_name} temperature to read")


def _datum_temperature(object_id: str, structure: BodyStructure) -> float | None:
    """The temperature at altitude 0, which is the lowest layer's base.

    Without it that layer has one end and reads as a single value, which is
    the tropopause rather than the troposphere. On a surface it is the body's
    own measured temperature — the same reading the `temperatures` block
    ships, taken from the constants so the two cannot drift — and only the
    giants, whose datum is the 1 bar level, state one of their own.
    """
    if structure.datum_temperature_k is not None:
        return structure.datum_temperature_k
    wanted = "photosphere" if structure.datum == "photosphere" else "surface"
    for part in TEMPERATURE_BODIES.get(object_id, ()):
        if part.part != wanted:
            continue
        for reading in part.readings:
            if reading.kind == "mean":
                return reading.kelvin
    logger.info(
        "%s: no %s temperature, so its lowest layer ships with an open base",
        object_id,
        wanted,
    )
    return None


def _datum_pressure(
    object_id: str, structure: BodyStructure, facts: BodyFacts
) -> float | None:
    """The pressure at altitude 0, which is the lowest layer's base.

    The mirror of `_datum_temperature`: without it that layer states only the
    boundary at its top, and Earth's troposphere reads as 226 mb under a 1 bar
    sky. On a datum the body already quotes a pressure at it is that number,
    read from the flat facts so the two cannot drift; on the giants the datum
    *is* one bar, by definition rather than by measurement.
    """
    if structure.datum == "one_bar":
        return _ONE_BAR_PA
    if facts.pressure is None:
        return None
    if _DATUM_OF_LEVEL.get(facts.pressure.level) != structure.datum:
        logger.info(
            "%s: its pressure is quoted at %s, not at the %s its layers hang "
            "off, so its lowest layer ships with an open base",
            object_id,
            facts.pressure.level,
            structure.datum,
        )
        return None
    # A non-detection limit is not a reading to span a layer between: Mercury's
    # "below 5·10⁻¹⁰ Pa" as the bottom of a range would be the most confident
    # number on the chart.
    if facts.pressure.qualifier == "upper_limit":
        logger.info(
            "%s: its %s pressure is an upper limit, so its lowest layer ships "
            "with an open base",
            object_id,
            facts.pressure.level,
        )
        return None
    return facts.pressure.pascals


def _structure_source_keys(structure: BodyStructure) -> list[str]:
    """Every work behind the cross-section — height, pressure and temperature
    on a boundary can each come from a different one."""
    keys: list[str] = []
    for layer in structure.layers:
        keys.append(layer.source)
        if layer.altitude_source is not None:
            keys.append(layer.altitude_source)
        if layer.pressure_source is not None:
            keys.append(layer.pressure_source)
        keys.extend(s.source for s in layer.composition)
    if structure.datum_temperature_source is not None:
        keys.append(structure.datum_temperature_source)
    if structure.homopause_source is not None:
        keys.append(structure.homopause_source)
    if structure.scale_height_source is not None:
        keys.append(structure.scale_height_source)
    return keys


def _validate_structure(object_id: str, structure: BodyStructure) -> None:
    """Enum and citation check, matching `_validate` on the flat facts."""
    if structure.datum not in DATUMS:
        raise ValueError(f"{object_id}: unknown datum {structure.datum}")
    if structure.note is not None and structure.note not in STRUCTURE_NOTES:
        raise ValueError(f"{object_id}: unknown note {structure.note}")
    for layer in structure.layers:
        if layer.role not in STRUCTURE_LAYER_ROLES:
            raise ValueError(f"{object_id}: unknown layer role {layer.role}")
        if layer.note is not None and layer.note not in STRUCTURE_NOTES:
            raise ValueError(f"{object_id}: unknown note {layer.note}")
        if layer.top_temperature_k is not None and layer.top_temperature_from:
            raise ValueError(
                f"{object_id}: {layer.role} states a top temperature and reads "
                "one; the second copy is the drift this field exists to stop"
            )
        layer_temperature(object_id, layer)
    for key in _structure_source_keys(structure):
        if key not in ATMOSPHERE_FACT_SOURCES:
            raise ValueError(f"{object_id}: no such source {key}")


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
