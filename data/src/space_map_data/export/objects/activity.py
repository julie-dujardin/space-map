"""Per-object activity block — what a body is still doing, denormalized onto
its global bundle.

Four tables share one block because they are four views of one question: is
there heat left inside, and does it reach the surface. Volcanism and tectonics
are what the heat builds, tidal heating is where the heat comes from on the
small worlds, and a dynamo is the same heat leaving a core by convection.

Twenty-three bodies carry one, and the shape is deliberately lopsided: the
categorical fields are complete and the numbers are not. Every body has a
volcanic status or a field type; only Earth, Io, Mercury and Enceladus have
more than four measurements between them, and five bodies — Europa, Callisto,
Mimas, Dione, Charon — have a status, a note and nothing else. A consumer
should lead with the status and treat every number as optional.

Each number ships as an object rather than a bare float, because in this
subject the qualifier is usually the finding: Titan's magnetic moment is only
ever an upper limit, Venus's eruption rate is Earth's record scaled by mass,
and a vent count is whatever the last survey resolved rather than a property of
the body.
"""

import logging

from space_map_data.constants.activity.magnetism import MAGNETIC_FIELDS
from space_map_data.constants.activity.references import (
    ACTIVITY_SOURCES,
    ActivityReference,
)
from space_map_data.constants.activity.schema import (
    BodyActivity,
    MagneticField,
    Measurement,
    TidalHeating,
)
from space_map_data.constants.activity.tidal import TIDAL_HEATING
from space_map_data.constants.activity.volcanism import GEOLOGIC_ACTIVITY
from space_map_data.export.objects.sources import source_row

logger = logging.getLogger(__name__)

_VOLCANISM_FIELDS = (
    "known_centres",
    "eruptions_per_year",
    "erupted_volume_km3_per_year",
    "plumes",
    "plume_mass_kg_per_s",
    "endogenic_power_w",
    "heat_flux_w_per_m2",
    "youngest_activity_years",
    "surface_age_years",
)
_TECTONICS_FIELDS = ("radial_contraction_km",)
_TIDAL_FIELDS = ("power_w", "flux_w_per_m2", "k2", "q")
_MAGNETISM_FIELDS = (
    "dipole_moment_a_m2",
    "surface_field_t",
    "dipole_tilt_deg",
    "dipole_offset_radii",
    "dynamo_ended_years",
)


def activity_block(object_id: str) -> dict | None:
    """Build the `activity` block for `object_id`, or None if no table has it."""
    geology = GEOLOGIC_ACTIVITY.get(object_id)
    tidal = TIDAL_HEATING.get(object_id)
    field = MAGNETIC_FIELDS.get(object_id)
    if geology is None and tidal is None and field is None:
        return None

    block: dict = {}
    keys: list[str] = []
    if geology is not None:
        block["volcanism"], volcanism_keys = _volcanism(geology)
        keys.extend(volcanism_keys)
        if geology.tectonics is not None:
            block["tectonics"], tectonics_keys = _tectonics(geology)
            keys.extend(tectonics_keys)
    if tidal is not None:
        block["tidal"], tidal_keys = _tidal(object_id, tidal, geology)
        keys.extend(tidal_keys)
    if field is not None:
        block["magnetism"], field_keys = _magnetism(field)
        keys.extend(field_keys)

    block["sources"] = _sources(keys)
    return block


def _volcanism(geology: BodyActivity) -> tuple[dict, list[str]]:
    facts = geology.volcanism
    out: dict = {"kind": facts.kind, "status": facts.status}
    keys = list(facts.status_sources)
    for name in _VOLCANISM_FIELDS:
        measurement = getattr(facts, name)
        if measurement is not None:
            out[name] = _measurement(measurement)
            keys.append(measurement.source)
    if facts.note is not None:
        out["note"] = facts.note
    return out, keys


def _tectonics(geology: BodyActivity) -> tuple[dict, list[str]]:
    facts = geology.tectonics
    assert facts is not None
    out: dict = {"style": facts.style, "status": facts.status}
    keys = list(facts.sources)
    for name in _TECTONICS_FIELDS:
        measurement = getattr(facts, name)
        if measurement is not None:
            out[name] = _measurement(measurement)
            keys.append(measurement.source)
    if facts.note is not None:
        out["note"] = facts.note
    return out, keys


def _tidal(
    object_id: str, facts: TidalHeating, geology: BodyActivity | None
) -> tuple[dict, list[str]]:
    """The tide raised on this body, and whether it accounts for the heat.

    Io and Enceladus quote the same watts twice — the tidal power and the
    endogenic power are one measurement, because on those two the observed heat
    loss *is* taken as the production, and that identity is the finding. It is
    resolved here rather than in a panel: both numbers are in hand at this
    point, and a consumer comparing floats across two sub-blocks would be
    re-deriving it every render.
    """
    out: dict = {"raised_by": facts.raised_by, "role": facts.role}
    keys = list(facts.role_sources)
    for name in _TIDAL_FIELDS:
        measurement = getattr(facts, name)
        if measurement is not None:
            out[name] = _measurement(measurement)
            keys.append(measurement.source)
    if facts.resonance_with:
        out["resonance_with"] = list(facts.resonance_with)
        if facts.resonance_source is not None:
            keys.append(facts.resonance_source)
    if facts.note is not None:
        out["note"] = facts.note

    endogenic = geology.volcanism.endogenic_power_w if geology is not None else None
    if facts.power_w is not None and endogenic is not None:
        if facts.power_w.value == endogenic.value:
            out["explains_heat_output"] = True
        else:
            logger.info(
                "%s: %.3g W of tide against %.3g W leaving the body — showing "
                "both, the tide is a share of the budget rather than all of it",
                object_id,
                facts.power_w.value,
                endogenic.value,
            )
    return out, keys


def _magnetism(facts: MagneticField) -> tuple[dict, list[str]]:
    out: dict = {"kind": facts.kind}
    keys = list(facts.kind_sources)
    for name in _MAGNETISM_FIELDS:
        measurement = getattr(facts, name)
        if measurement is not None:
            out[name] = _measurement(measurement)
            keys.append(measurement.source)
    if facts.note is not None:
        out["note"] = facts.note
    return out, keys


def _measurement(measurement: Measurement) -> dict:
    """One published number with what its source said about how sure it is.

    `source` stays behind: the block credits its works once, in `sources`, the
    way the interior and atmosphere blocks do. Per-value keys would be a third
    of the bytes for a provenance nothing renders per row.
    """
    out: dict = {"value": measurement.value}
    if measurement.range is not None:
        out["range"] = list(measurement.range)
    if measurement.upper_limit:
        out["upper_limit"] = True
    if measurement.modelled:
        out["modelled"] = True
    if measurement.as_of is not None:
        out["as_of"] = measurement.as_of
    return out


def _sources(keys: list[str]) -> list[dict]:
    """Dedupe, first occurrence wins — the work behind the volcanic status
    leads, which is the line the panel opens with."""
    out = []
    for key in dict.fromkeys(keys):
        ref: ActivityReference | None = ACTIVITY_SOURCES.get(key)
        if ref is None:
            raise ValueError(f"no such activity source {key}")
        out.append(source_row(ref))
    return out
