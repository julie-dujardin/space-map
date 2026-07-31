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
HYDROGEN_HELIUM = "hydrogen_helium"  # giant envelopes

MATERIALS = frozenset(
    {METAL, SULFIDE, SILICATE, WATER, VOLATILE_ICE, ORGANIC, HYDROGEN_HELIUM}
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
        "envelope",  # H/He, molecular
        "metallic_hydrogen",
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

# `BodyInterior.note` / `Layer.note` values. Same trick as the atmosphere
# facts: the pipeline ships a key, the frontend ships the sentence, so the
# prose stays translatable.
NOTES = frozenset(
    {
        "subsurface_ocean",
        "magma_ocean",
        "no_seismic_data",
        "from_moment_of_inertia",
        "from_bulk_density",
        "core_size_disputed",
        "rubble_pile",
        "hydrated_rock",
        "no_solid_surface",
        "taxonomy_estimate",
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
    note: str | None = None
    # True where the mass fraction is arithmetic on the source's radii and
    # densities rather than a number the source quotes. Ships through to the
    # panel so a modelled split never reads as a measured one.
    derived: bool = False


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
