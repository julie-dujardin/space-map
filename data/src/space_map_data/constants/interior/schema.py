"""Types and vocabularies for the solid-body interior facts.

Three levels live in one structure. Every layer carries a **material**
split — the coarse vocabulary below, comparable across a metal core and a
comet-like ice shell — because that rolls up into a single whole-body bar.
A layer may also carry a detailed oxide/mineral composition where the
literature gives one, and a **rock** name where it has agreed on one — the
level a reader already thinks in: the useful thing about the ocean floor is
that it is basalt.

The roll-up is deliberately a mass balance over layers, not an elemental
one: a reader reads "two-thirds rock, one-third water", and water bound in a
phyllosilicate is water, not oxygen shared among the rocks.

Temperature runs on the boundaries rather than the shells, since that is the
form the literature publishes — a geotherm quoted at the Moho, at 660 km, at
the core-mantle boundary. A layer's two ends are its own boundary and the
next one down's, the same contract the atmosphere layers use.
"""

from typing import NamedTuple


# `Component.material` values. Coarse on purpose — this is the axis that has
# to mean the same thing on Mercury and on Enceladus.
METAL = "metal"  # Fe-Ni metal
SULFIDE = "sulfide"  # troilite and friends, the core's light-element carrier
SILICATE = "silicate"  # anhydrous rock
WATER = "water"  # ice, liquid, or structurally bound in phyllosilicates
# CO₂, CH₄, C₂H₆, N₂, NH₃, CO. The substance, not the state — `Layer.state`
# already says whether it is frozen, and Titan's seas are the same material
# as Pluto's frosts.
VOLATILE = "volatile"
ORGANIC = "organic"  # carbonaceous matter
HYDROGEN = "hydrogen"
HELIUM = "helium"
# Everything above helium, where nothing separates it further — the
# astronomer's Z, a statement about the evidence rather than the rock: an
# ice giant's heavy elements weigh 0.76 of the planet modelled as rock,
# 0.89 as ice, and no measurement chooses. Use SILICATE/WATER instead
# wherever a source does resolve the split.
HEAVY_ELEMENTS = "heavy_elements"

MATERIALS = frozenset(
    {
        METAL,
        SULFIDE,
        SILICATE,
        WATER,
        VOLATILE,
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
        # Earth's second crust, and the reason `area_fraction` exists: basalt
        # under the sea against granite under the land, side by side rather
        # than one above the other.
        "oceanic_crust",
        "ice_shell",
        # Liquid water, whether it lies on the surface or under an ice shell.
        # Only Earth's is on top; the test that ties the `subsurface_ocean`
        # note to a layer keys on which one it is.
        "ocean",
        # Standing liquid that is not water and does not go round: Titan's
        # maria. Kept apart from `ocean` because Titan has both, 100 km of ice
        # apart, and one word for the two would be the worst place to use it.
        "sea",
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
        # Earth's `crust` layer as its continental crust: the thickness, mass
        # and chemistry of the continents, with the ocean floor carried
        # separately as `oceanic_crust` rather than averaged in.
        "continental_crust_only",
    }
)

# `Layer.state` values — the state of matter, the other half of what a
# reader wants under a layer's name: "liquid iron alloy" says more than
# "core". Left unset wherever a source stops short of it, like Venus's core,
# where the tides allow a solid one and nobody knows.
STATES = frozenset(
    {
        "solid",
        "liquid",
        "partial_melt",  # solid with melt through it, not a magma ocean
        "fluid",  # no phase boundary to cross; the giants' envelopes
        "plasma",
    }
)

# `Layer.phase` values — which crystal structure a solid layer took, where the
# pressure picks one and the source names it. "Solid water" is true of the ice
# shell and of the ice mantle 800 km below it, and the difference between them
# is the whole reason the second layer exists.
PHASES = frozenset(
    {
        "ice_i",  # ordinary ice, the only phase stable at surface pressures
        "ice_iii",
        "ice_v",
        "ice_vi",
        "ice_vii",
    }
)

# `Layer.rock` values — the name a petrologist gives the layer, where one
# exists. "Solid rock" is the same phrase on Earth's continents, its ocean
# floor, the lunar highlands and Vesta, and those four are not the same rock;
# the coarse `silicate` material can't say so, and an oxide table only says
# it to a reader who can read one.
#
# The vocabulary stays short on purpose: each entry is a name a source
# applies to a whole layer, not its most abundant rock or the part anyone
# has sampled. Two names and no verdict leaves the field unset — Mercury's
# crust has none, its lavas read as komatiites, norites and boninites by
# three sets of authors with the same MESSENGER data.
BASALT = "basalt"
ANDESITE = "andesite"
ANORTHOSITE = "anorthosite"
PERIDOTITE = "peridotite"

ROCKS = frozenset({BASALT, ANDESITE, ANORTHOSITE, PERIDOTITE})

# `Detail.unit` values — what the detailed composition is expressed in, named
# <what>_<measure>. Each layer takes the one its own source publishes: rock
# comes as oxides by weight, a core as elements by weight, a sea as the
# molecules themselves, and nothing is converted between them here.
OXIDE_WEIGHT = "oxide_weight"  # wt% of oxides, the usual geochemistry table
ELEMENT_WEIGHT = "element_weight"
MINERAL_VOLUME = "mineral_volume"
# Whole molecules by mass, for the layers where the compound is the fact and
# its elements are not: seawater is 96.5% H₂O and 3.5% salt, which "86% oxygen"
# manages to say without saying. Dissolved ions ride here too, written as the
# neutral formula — the charge is not what a reader is reading for.
COMPOUND_WEIGHT = "compound_weight"
# The same, by volume, which is how the radar sounding of a cryogenic liquid
# reports itself.
COMPOUND_VOLUME = "compound_volume"

DETAIL_UNITS = frozenset(
    {
        OXIDE_WEIGHT,
        ELEMENT_WEIGHT,
        MINERAL_VOLUME,
        COMPOUND_WEIGHT,
        COMPOUND_VOLUME,
    }
)


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
    # Share of the body's surface the layer covers, for the layers that are
    # patches rather than shells: Earth's ocean floors its 71%, its continents
    # the other 41% of the crust's own area, and the two crusts meet at a
    # coastline instead of a depth. Unset means a global shell, which is every
    # other layer on every other body.
    area_fraction: float | None = None
    # Where the layer stops. A shell needs none — the next layer's top is its
    # floor — but a patch's floor is its own: what lies under Earth's ocean is
    # the sea floor, not the continental crust that follows it in this list.
    # Required with `area_fraction`, and the two together close the arithmetic,
    # since area × thickness × 4πR² has to come back to the published volume.
    base_radius_km: float | None = None
    # Where the density that turned this layer's geometry into a mass is a
    # different work from the geometry itself — the ocean's volume is
    # bathymetry and its density an equation of state.
    density_source: str | None = None
    detail: Detail | None = None
    # One of STATES. `state_source` is for the case where the phase is a
    # different work's result from the geometry — Io, whose layers are
    # Galileo's gravity and whose mantle is known not to be a magma ocean
    # because Juno measured the tidal response twenty-four years later.
    state: str | None = None
    state_source: str | None = None
    # One of PHASES, for a solid whose polymorph the source names. Usually the
    # same model as the geometry — the phase is what fixed the density the
    # thicknesses were solved with — so `phase_source` is only for where it is
    # not: Titan, whose layers are a gravity solution that sees one hydrosphere
    # and cannot tell which ice is at the bottom of it.
    phase: str | None = None
    phase_source: str | None = None
    # One of ROCKS. `rock_source` is nearly always set, because the name is
    # petrology and the geometry is geophysics: Mars's crust is 47 km thick
    # because InSight watched a quake bounce off its base, and it is basalt
    # because a gamma-ray spectrometer and a rover agreed on the chemistry.
    rock: str | None = None
    rock_source: str | None = None
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
    # The temperature at `outer_radius_km` — the layer's own top, matching how
    # geotherms are published: a number at the Moho, at 660 km, at the
    # core-mantle boundary, not an average over a shell nobody can average.
    # A layer's span is therefore this against the *next* layer's, and the
    # innermost one's inner end is `BodyInterior.centre_temperature_k`.
    #
    # Left unset on the outermost layer: that boundary is the surface, and
    # constants/temperature already measures it. Restating it here would give
    # the same body two surface temperatures that could drift apart.
    outer_temperature_k: float | None = None
    # Most of these are a spread across models or experiments rather than an
    # error bar on one, so the range is usually the whole claim and the value
    # above stays unset — Venus's core-mantle boundary is 4000 to 5000 K and
    # nothing between is preferred. Set both only where a source does prefer a
    # number and brackets it.
    outer_temperature_range_k: tuple[float, float] | None = None
    # Plural because a bracket's two ends routinely come from two traditions —
    # the giants' low ends are classical adiabats and their high ends post-Juno
    # models — and crediting only one of them would misattribute the other.
    temperature_sources: tuple[str, ...] = ()


class BodyInterior(NamedTuple):
    structure: str
    layers: tuple[Layer, ...]
    structure_source: str | None = None
    note: str | None = None
    # The centre, which closes the innermost layer's span the way the datum
    # closes the atmosphere's lowest one. Separate from any layer because it is
    # a point rather than a boundary between two shells — and it is all a
    # diffuse core has, there being no radius at which it starts.
    centre_temperature_k: float | None = None
    centre_temperature_range_k: tuple[float, float] | None = None
    centre_temperature_sources: tuple[str, ...] = ()


class ClassComposition(NamedTuple):
    """What a taxonomic class is made of, via its meteorite analogue.

    Applied to every asteroid carrying that class, so it ships flagged as an
    estimate from the spectrum rather than a measurement of the body.
    """

    analogue: str  # message key for the meteorite group, e.g. "ordinary_chondrite"
    composition: tuple[Component, ...]
    source: str
    note: str | None = None
