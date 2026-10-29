"""The planets of the Solar System as planet records.

The planet family rules read the planet records of the extrasolar export.
Each Solar System planet gets a record of the same shape, so that the same
rules give its families: the mass from the SPICE GM, the equatorial radius
from the PCK, the Horizons mean elements, the insolation from the semi-major
axis, and the heavy-element fraction from the interior models. All of these
values are measured. As a served record, it has `families` and
`families_estimated`.
"""

from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.interior.schema import HELIUM, HYDROGEN
from space_map_data.constants.planets import families as rules
from space_map_data.export.extrasolar.planet_families import families_of
from space_map_data.extrasolar.exoplanets.catalogues import TRUE_MASS
from space_map_data.extrasolar.exoplanets.iau import PLANET
from space_map_data.extrasolar.families import most_specific
from space_map_data.ingest.providers.objects.sbdb import mass_kg_from_gm

# The eight planets of the IAU, Mercury to Neptune.
PLANET_NAIF_IDS: tuple[int, ...] = tuple(n * 100 + 99 for n in range(1, 9))

# The host record of the Sun: R☉ and the IAU 2015 nominal Teff.
SUN = {"class": "star", "teff": rules.SUN_TEFF, "radius": 1.0}


def object_id(naif_id: int) -> str:
    return f"naif-{naif_id}"


def heavy_element_fraction(body: str) -> float | None:
    """The mass fraction of everything but hydrogen and helium, from the
    interior model of `body`. None without a model or with a layer of unknown
    mass."""
    facts = INTERIOR_FACTS.get(body)
    if facts is None:
        return None
    total = 0.0
    for layer in facts.layers:
        if layer.mass_fraction is None:
            return None
        total += layer.mass_fraction * sum(
            component.fraction
            for component in layer.composition
            if component.material not in (HYDROGEN, HELIUM)
        )
    return total


def solar_planet_records(
    radii: dict[int, dict],
    gms: dict[int, float],
    elements: dict[int, dict],
) -> dict[str, dict]:
    """The planet record of each Solar System planet, by object id, in
    heliocentric order, with its families around the Sun. A value without a
    source is absent."""
    out = {}
    for naif_id in PLANET_NAIF_IDS:
        body = object_id(naif_id)
        values: dict = {}
        if (kg := mass_kg_from_gm(gms.get(naif_id))) is not None:
            # Jupiter masses: kg × 1000 / g.
            values["mass"] = kg * 1000 / rules.JUPITER_MASS_G
            values["mass_kind"] = TRUE_MASS
        if (axes := radii.get(naif_id)) is not None:
            values["radius"] = axes["a"] * 1e5 / rules.JUPITER_RADIUS_CM
        if (orbit := elements.get(naif_id)) is not None:
            values["semi_major_axis"] = orbit["a"]
            values["eccentricity"] = orbit["e"]
            values["period"] = orbit["period"]
            values["insolation"] = 1 / orbit["a"] ** 2
        if (fraction := heavy_element_fraction(body)) is not None:
            values["heavy_element_fraction"] = fraction
        record = {
            "class": PLANET,
            "values": values,
            "assumed": [],
            "estimated": [],
            "limits": [],
        }
        record["families"], record["families_estimated"] = families_of(record, SUN)
        out[body] = record
    return out


def page_families(records: dict[str, dict]) -> dict[str, list[str]]:
    """The most specific published families of each record, for the tiles of
    the planet's page."""
    return {
        body: most_specific(record["families"], rules.FAMILIES, rules.PARENTS)
        for body, record in records.items()
    }
