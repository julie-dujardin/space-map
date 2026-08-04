"""Types and vocabularies for the solid-body interior facts.

Two levels live in one structure. Every layer carries a **material** split —
the coarse vocabulary below, comparable across a metal core and a comet-like
ice shell — because that is what rolls up into a single whole-body bar. A
layer may *also* carry a detailed oxide or mineral composition where the
literature gives one; nothing consumes it yet, but it is the same curation
pass, so it is collected now.

The roll-up is deliberately a mass balance over layers rather than an
elemental one: a reader reads "two-thirds rock, one-third water", and water
bound in a phyllosilicate is water, not oxygen shared out among the rocks.
"""

from typing import NamedTuple


# `Component.material` values. Coarse on purpose — this is the axis that has
# to mean the same thing on Mercury and on Enceladus.
METAL = "metal"  # Fe-Ni metal
SULFIDE = "sulfide"  # troilite and friends, the core's light-element carrier
SILICATE = "silicate"  # anhydrous rock
WATER = "water"  # ice, liquid, or structurally bound in phyllosilicates
VOLATILE_ICE = "volatile_ice"  # CO₂, CH₄, N₂, NH₃, CO
ORGANIC = "organic"  # carbonaceous matter
HYDROGEN = "hydrogen"
HELIUM = "helium"
# Everything above helium, where nothing separates it further. This is the
# astronomer's Z, and it is a statement about the evidence rather than the
# rock: an ice giant's heavy elements weigh 0.76 of the planet if you model
# them as rock and 0.89 if you model them as ice, and no measurement chooses.
# Use SILICATE/WATER instead wherever a source does resolve the split.
HEAVY_ELEMENTS = "heavy_elements"

MATERIALS = frozenset(
    {
        METAL,
        SULFIDE,
        SILICATE,
        WATER,
        VOLATILE_ICE,
        ORGANIC,
        HYDROGEN,
        HELIUM,
        HEAVY_ELEMENTS,
    }
)

# `Layer.role` values, outermost first. `bulk` is the whole body in one piece:
# either it never differentiated, or the only published constraint is a bulk
# rock/ice split.
LAYER_ROLES = frozenset(
    {
        "crust",
        "ice_shell",
        "ocean",
        "mantle",
        "ice_mantle",  # high-pressure ice below an ocean
        # Molten silicate resting on the core. Mars's is the only one anyone
        # has evidence for, and it is rock rather than the ice-world `ocean`.
        "magma",
        "envelope",  # H/He, molecular
        "metallic_hydrogen",
        # Stellar. Zones of how energy travels rather than of what the gas is
        # made of, which is why they carry compositions that differ without
        # any boundary between materials.
        "radiative_zone",
        "convective_zone",
        "core",
        "outer_core",
        "inner_core",
        "bulk",
    }
)

# `BodyInterior.structure` values — how much the body has separated out.
STRUCTURES = frozenset(
    {
        "differentiated",
        "partially_differentiated",
        "undifferentiated",
        "rubble_pile",
        "fluid",  # no solid surface at all; the giants
    }
)

# `BodyInterior.note` / `Layer.note` values. Shipped as keys the frontend is
# free to ignore: today it renders a sentence for the ocean note and a layer
# name for `continental_crust_only`; the rest travel as provenance metadata.
NOTES = frozenset(
    {
        "subsurface_ocean",
        "from_moment_of_inertia",
        "from_bulk_density",
        "core_size_disputed",
        "hydrated_rock",
        # The boundary is a thermal model's, not a measurement's: ice and
        # liquid water differ by too little in density for gravity to place
        # the base of an ice shell.
        "shell_thickness_modelled",
        # Earth's crust as its continental crust: the thickness, mass and
        # chemistry of the continents, with the thinner oceanic crust left out
        # rather than averaged in.
        "continental_crust_only",
    }
)

# `Layer.state` values. What phase the layer is in, which is the other half
# of what a reader wants under a layer's name: "liquid iron alloy" says more
# than "core". Left unset wherever a source stops short of it — Venus's core
# is the case in point, where the tides allow a solid one and nobody knows.
STATES = frozenset(
    {
        "solid",
        "liquid",
        "partial_melt",  # solid with melt through it, not a magma ocean
        "fluid",  # no phase boundary to cross; the giants' envelopes
        "plasma",
    }
)

# `Detail.unit` values — what the detailed composition is expressed in.
OXIDE_WEIGHT = "oxide_weight"  # wt% of oxides, the usual geochemistry table
ELEMENT_WEIGHT = "element_weight"
MINERAL_VOLUME = "mineral_volume"

DETAIL_UNITS = frozenset({OXIDE_WEIGHT, ELEMENT_WEIGHT, MINERAL_VOLUME})


class Component(NamedTuple):
    """One material's share of a layer, by mass."""

    material: str
    fraction: float
    source: str
    # The published width, where the source gives one. `fraction` stays the
    # value to draw; this is what the panel shows as the honest spread around
    # it, so a modelled number never reads as a measured one.
    fraction_range: tuple[float, float] | None = None


class Detail(NamedTuple):
    """A finer composition for one layer, in whatever the source reports.

    Banked for the per-layer view; the whole-body bar never reads these.
    """

    unit: str
    entries: tuple[tuple[str, float], ...]  # (species, fraction)
    source: str


class Layer(NamedTuple):
    role: str
    # Of the whole body, by mass. None where a source constrains the layer's
    # geometry but not its mass — the roll-up then skips the body rather than
    # inventing a number.
    mass_fraction: float | None
    composition: tuple[Component, ...]
    source: str  # backs mass_fraction and the layer's existence
    outer_radius_km: float | None = None
    detail: Detail | None = None
    # One of STATES. `state_source` is for the case where the phase is a
    # different work's result from the geometry — Io, whose layers are
    # Galileo's gravity and whose mantle is known not to be a magma ocean
    # because Juno measured the tidal response twenty-four years later.
    state: str | None = None
    state_source: str | None = None
    note: str | None = None
    # True where the mass fraction is arithmetic on the source's radii and
    # densities rather than a number the source quotes. Ships through to the
    # panel so a modelled split never reads as a measured one.
    derived: bool = False
    # The published width, where the source gives one — Jupiter's core is
    # anywhere from 7 to 25 Earth masses and there is no honest midpoint. The
    # roll-up keeps using `mass_fraction`; this is what gets drawn around it.
    mass_fraction_range: tuple[float, float] | None = None
    # True where the layer has no boundary to draw: Jupiter's core is heavy
    # elements smeared through the envelope, not a ball with a surface, and
    # `outer_radius_km` is then where it fades out rather than where it ends.
    diffuse: bool = False


class BodyInterior(NamedTuple):
    structure: str
    layers: tuple[Layer, ...]
    structure_source: str | None = None
    note: str | None = None


class ClassComposition(NamedTuple):
    """What a taxonomic class is made of, via its meteorite analogue.

    Applied to every asteroid carrying that class, so it ships flagged as an
    estimate from the spectrum rather than a measurement of the body.
    """

    analogue: str  # message key for the meteorite group, e.g. "ordinary_chondrite"
    composition: tuple[Component, ...]
    source: str
    note: str | None = None
