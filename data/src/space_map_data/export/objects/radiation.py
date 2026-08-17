"""Per-object radiation block — how much ionizing dose a place delivers.

Three kinds of entry, and a reader has to be able to tell them apart because
they differ by fourteen orders of magnitude and by how much anyone knows.

A handful of bodies carry a *published* dose: four measured by an instrument
sat on them, two computed for a body-sized target by someone whose model this
is not. Those ship as they are.

Most bodies carry no dose at all, and for the ones that are simply rock in
sunlight that is a gap worth filling rather than a finding: the cosmic ray
field is exact geometry away from an atmosphere, and it predicts the two
measured airless surfaces to within 7%. So a `modelled_surface_dose` is
computed for them here.

The bodies that get neither are the ones inside a magnetosphere. A cosmic ray
figure there is a floor and not an estimate — Europa's measured dose is six
orders of magnitude above what this field returns for it — and a floor
presented next to real numbers reads as a ranking. So a moon of a belted
planet gets its `kind` and its note and no figure, which is what
`environments.py` already decided for the four Galileans and is applied here
to every moon of Jupiter, Saturn, Uranus, Neptune and Earth.
"""

from typing import NamedTuple

from space_map_data.constants.activity.magnetism import MAGNETIC_FIELDS
from space_map_data.constants.activity.schema import Measurement
from space_map_data.constants.atmosphere.bodies import ATMOSPHERE_BODIES
from space_map_data.constants.atmosphere.facts import ATMOSPHERE_FACTS
from space_map_data.constants.radiation.belts import TRAPPED_BELTS, TRAPPED_SYSTEMS
from space_map_data.constants.radiation.environments import RADIATION_ENVIRONMENTS
from space_map_data.constants.radiation.field import (
    FIELD_SOURCES,
    SOLAR_CYCLE_RATIO,
    SOLAR_CYCLE_YEARS,
    SOLAR_MINIMUM_EPOCH,
    NearBody,
    column_depth_g_cm2,
    gcr_dose_rate,
)
from space_map_data.constants.radiation.references import (
    RADIATION_SOURCES,
    RadiationReference,
)
from space_map_data.constants.radiation.schema import TRAPPED, DoseRate, TrappedBelt
from space_map_data.export.objects.sources import source_row

# The cycle-mean epoch: `solar_cycle_factor` is 1 a quarter-cycle off minimum,
# so evaluating there gives the average over a cycle without the export having
# to pick a date it would then go stale against.
_CYCLE_MEAN_EPOCH = SOLAR_MINIMUM_EPOCH + SOLAR_CYCLE_YEARS / 4.0

# Half the cycle's swing either way about that mean, which is the dominant
# uncertainty on any modelled figure and dwarfs everything else in the model.
_CYCLE_HALF_SWING = SOLAR_CYCLE_RATIO**0.5

# How far out the radial gradient was fitted. Roussos had Cassini between 1 and
# 9.5 au and nothing beyond it, so Pluto's figure rests on a straight line
# continued four times past its evidence. Flagged rather than withheld: the
# gradient is genuinely near-linear out to the termination shock, and a Kuiper
# belt object with no number at all would be a worse answer than one that says
# where the fit stopped.
_FITTED_GRADIENT_LIMIT_AU = 9.5


def radiation_block(
    object_id: str,
    *,
    parent_id: str | None,
    distance_au: float | None,
) -> dict | None:
    """Build the `radiation` block for `object_id`, or None if there is none."""
    environment = RADIATION_ENVIRONMENTS.get(object_id)
    belt = TRAPPED_BELTS.get(object_id)

    block: dict = {}
    keys: list[str] = []

    if environment is not None:
        block["kind"] = environment.kind
        keys.extend(environment.kind_sources)
        if environment.note is not None:
            block["note"] = environment.note
        if environment.surface_dose is not None:
            block["surface_dose"] = _dose(environment.surface_dose)
            keys.append(environment.surface_dose.sv_per_day.source)
        if environment.orbit_dose is not None:
            block["orbit_dose"] = _dose(environment.orbit_dose)
            keys.append(environment.orbit_dose.sv_per_day.source)

    if belt is not None:
        block["belt"], belt_keys = _belt(belt)
        keys.extend(belt_keys)

    if "surface_dose" not in block:
        modelled = _modelled_surface_dose(
            object_id, parent_id=parent_id, distance_au=distance_au
        )
        if modelled is not None:
            block["modelled_surface_dose"] = modelled
            keys.extend(FIELD_SOURCES)

    if not block:
        return None
    block["sources"] = _sources(keys)
    return block


class Place(NamedTuple):
    """Where a collection member sits, which is all its dose depends on."""

    parent_id: str | None
    distance_au: float | None


def collection_row(object_id: str, place: Place) -> dict | None:
    """The same block, trimmed to a figure and which chart it belongs on.

    Built by calling `radiation_block` rather than by rebuilding it, so the
    figure on the Radiation page and the figure in the body's own panel cannot
    come apart. None where there is no figure, which is what keeps a body off
    the page: everything else the block carries — the works, the belt's extents,
    the note naming what dominates — is prose or geometry a row has no room for,
    and the body's own panel is one click away.
    """
    block = radiation_block(
        object_id, parent_id=place.parent_id, distance_au=place.distance_au
    )
    if block is None:
        return None
    row = {k: v for k, v in block.items() if k in _ROW_KEYS}
    return row if len(row) > 1 else None


# `kind` decides which of the two charts a row draws on, and which reading hangs
# off its figure; the other two are the figure, only ever one of them.
_ROW_KEYS = frozenset({"kind", "surface_dose", "modelled_surface_dose"})


def collection_sources(places: dict[str, Place]) -> list[dict]:
    """Every work behind a collection page's doses, deduped, first use first.

    The page's own bibliography. Unlike the other Structure & Activity pages,
    whose figures come from catalogues their members' bundles already credit,
    every number here is read off a paper.
    """
    out: dict[str, dict] = {}
    for object_id, place in places.items():
        block = radiation_block(
            object_id, parent_id=place.parent_id, distance_au=place.distance_au
        )
        if block is None:
            continue
        for source in block["sources"]:
            out.setdefault(source["url"], source)
    return list(out.values())


def _in_a_magnetosphere(object_id: str, parent_id: str | None) -> bool:
    """Whether trapped particles, not cosmic rays, decide this body's dose.

    The body's own `kind` answers for itself, rather than whether `belts.py`
    has an entry: Mercury has a belt and is still `cosmic`, because the thing
    comes and goes with the solar wind and peaks at 93 keV, which is a finding
    about magnetospheres and not a hazard.

    For a moon the parent's belt is the test — the parent being a system
    barycentre rather than the planet, which is why the set tested against
    carries both — and distance from it is not consulted. Titan and Iapetus
    really do orbit outside Saturn's belts and
    would be fair game, but the boundary is only known for the four planets
    `belts.py` covers, and getting it wrong costs six orders of magnitude in
    the direction that flatters a moon. The cheap rule is the safe one, and
    the moons it wrongly excludes lose a number nobody has asked for rather
    than gaining a wrong one. Titan is excluded twice over anyway — see the
    Titan entry in `field.MODELLED_CHECKS`.
    """
    environment = RADIATION_ENVIRONMENTS.get(object_id)
    if environment is not None and environment.kind == TRAPPED:
        return True
    # A planet is parented on its own system barycentre, so without this it
    # would read as sitting inside its own belt. Whether it does is what its
    # `kind` above already answered.
    if object_id in TRAPPED_BELTS:
        return False
    return parent_id is not None and parent_id in TRAPPED_SYSTEMS


def _modelled_surface_dose(
    object_id: str,
    *,
    parent_id: str | None,
    distance_au: float | None,
) -> dict | None:
    """Cosmic ray dose on the ground, where the field model is answerable.

    Averaged over a solar cycle, with the range being the cycle's own swing:
    a factor of 2.4 between a quiet Sun and an active one, which is larger
    than any other uncertainty here and is the reason this is a band rather
    than a number.

    The body's size does not appear because it cannot: standing on a surface
    leaves exactly half the sky open whatever the body's radius, so the
    geometry term is 1:1 by definition and Ceres and Jupiter would differ only
    by where they are, not how big they are.
    """
    if distance_au is None or _in_a_magnetosphere(object_id, parent_id):
        return None

    near = NearBody(
        radius_km=1.0,
        distance_km=1.0,
        column_g_cm2=_column_g_cm2(object_id),
        dipole_moment_a_m2=_dipole_moment_a_m2(object_id),
    )
    mean = gcr_dose_rate(_CYCLE_MEAN_EPOCH, distance_au, near)
    if mean <= 0.0:
        return None
    out = {
        "sv_per_day": mean,
        "range": [mean / _CYCLE_HALF_SWING, mean * _CYCLE_HALF_SWING],
        "modelled": True,
    }
    if distance_au > _FITTED_GRADIENT_LIMIT_AU:
        out["extrapolated"] = True
    return out


def _column_g_cm2(object_id: str) -> float:
    """Atmosphere overhead, for the handful of surfaces that have one."""
    facts = ATMOSPHERE_FACTS.get(object_id)
    body = ATMOSPHERE_BODIES.get(object_id)
    if facts is None or facts.pressure is None or body is None:
        return 0.0
    return column_depth_g_cm2(facts.pressure.pascals, body.gravity_m_s2)


def _dipole_moment_a_m2(object_id: str) -> float:
    """A field of the body's own, which shuts out the softer cosmic rays."""
    field = MAGNETIC_FIELDS.get(object_id)
    if field is None or field.dipole_moment_a_m2 is None:
        return 0.0
    if field.dipole_moment_a_m2.upper_limit:
        return 0.0
    return field.dipole_moment_a_m2.value


def _dose(dose: DoseRate) -> dict:
    """A published rate and what was between it and the sky.

    The shielding is part of the number rather than context for it: against
    cosmic rays a hull barely matters, against trapped particles it is the
    whole difference, and a figure quoted without it makes those look alike.
    """
    out: dict = {"sv_per_day": _measurement(dose.sv_per_day)}
    if dose.shielding_g_cm2 is not None:
        out["shielding_g_cm2"] = dose.shielding_g_cm2
    return out


def _belt(belt: TrappedBelt) -> tuple[dict, list[str]]:
    """Extents in planetary radii, which is how this literature reports them."""
    out: dict = {}
    keys = list(belt.sources)
    for name in ("inner_radii", "peak_radii", "outer_radii", "crossing_dose_sv"):
        measurement = getattr(belt, name)
        if measurement is not None:
            out[name] = _measurement(measurement)
            keys.append(measurement.source)
    if belt.note is not None:
        out["note"] = belt.note
    return out, keys


def _measurement(measurement: Measurement) -> dict:
    """One published number with what its source said about how sure it is.

    `source` stays out: works are credited once in `sources`, as in the
    activity, interior and atmosphere blocks.
    """
    out: dict = {"value": measurement.value}
    if measurement.range is not None:
        out["range"] = list(measurement.range)
    if measurement.upper_limit:
        out["upper_limit"] = True
    if measurement.modelled:
        out["modelled"] = True
    return out


def _sources(keys: list[str]) -> list[dict]:
    """Dedupe, first occurrence wins — the `kind` source leads, matching the
    panel's opening line."""
    out = []
    for key in dict.fromkeys(keys):
        ref: RadiationReference | None = RADIATION_SOURCES.get(key)
        if ref is None:
            raise ValueError(f"no such radiation source {key}")
        out.append(source_row(ref))
    return out
