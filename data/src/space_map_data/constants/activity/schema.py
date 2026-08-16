"""Types and vocabularies for what a body is still *doing*.

Three tables share this schema as three views of one question — is there heat
left inside, and does it reach the surface. Tidal heating is the supply on
small worlds, volcanism/tectonics is what it builds, a dynamo is the same heat
leaving a core by convection. Io has all three for one reason; Callisto has
almost none for the same reason.

Every number is a `Measurement`, not a bare float: the qualifier usually *is*
the finding — Titan's moment is an upper limit, Venus's eruption rate an
extrapolation, Io's hot-spot count whatever the last survey resolved. Shipped
without its width or date, a bound would read as a measurement.
"""

from typing import NamedTuple


# `Volcanism.kind` values. `both` is for bodies with silicate volcanism in the
# past and cryovolcanism now — Ceres, whose domes are brine over a mantle
# that once melted.
SILICATE = "silicate"
CRYO = "cryo"
BOTH = "both"
NO_VOLCANISM = "none"

VOLCANISM_KINDS = frozenset({SILICATE, CRYO, BOTH, NO_VOLCANISM})

# `Volcanism.status` / `Tectonics.status` values, certain to absent. The
# middle three exist because most interesting bodies sit there, and a boolean
# would turn Venus's argument into Earth's fact.
STATUSES = frozenset(
    {
        "active",  # caught in the act: an eruption, plume, or thermal source
        # Better than circumstantial but never witnessed — a surface change
        # between two passes, a deposit dated to human timescales.
        "probable",
        "suspected",  # circumstantial only: a young-looking landform, a transient gas
        "dormant",  # no activity observed, but still warm enough to resume
        "extinct",  # heat is gone; cratering/dating puts the last event ages ago
        "none",  # never had any, as far as anything shows
    }
)

# `Tectonics.style` values. Not a ladder — an ice shell cracking over an ocean
# and a rock planet shrinking onto its core are different machines, and only
# Earth's recycles a surface.
TECTONIC_STYLES = frozenset(
    {
        "plate_tectonics",  # rigid plates, spreading and subduction; Earth alone
        "stagnant_lid",  # one unbroken lithosphere over a convecting mantle
        # Stagnant lid in compression: the planet shrinking as its core cools,
        # taken up by thrust faults. Mercury, and the Moon at smaller amplitude.
        "contractional_lid",
        # Whole-lithosphere overturn without plates: Venus's rifts, coronae,
        # a lid that may move in blocks without subducting.
        "mobile_lid",
        "ice_shell_tectonics",  # ridges, bands and chaos in a floating ice shell
        "impact_dominated",  # nothing since the bombardment; the surface is craters
        "none",
    }
)

# `MagneticField.kind` values.
DYNAMO = "dynamo"  # generated now, in a convecting conductive interior
# No field of its own: eddy currents in a conductive shell — salty ocean,
# ionosphere — answering the field it sits in. Evidence about the shell, not
# a core.
INDUCED = "induced"
REMANENT = "remanent"  # frozen into the crust by a dynamo that has since stopped
NO_FIELD = "none"

FIELD_KINDS = frozenset({DYNAMO, INDUCED, REMANENT, NO_FIELD})

# `TidalHeating.role` values — how much of the body's heat budget the tide is.
TIDAL_ROLES = frozenset(
    {
        "dominant",  # the tide is why the body is warm at all
        "significant",  # comparable to radiogenic heating
        "minor",
        "negligible",
        "past",  # the orbit has since circularised, or the resonance broke
    }
)


class Measurement(NamedTuple):
    """One published number, with what the source said about how sure it is.

    `value` is always the number to draw. Everything else says what it means.
    """

    value: float
    source: str
    # The published width. Where a source only brackets a value — Mimas's
    # ocean is 2 to 25 Myr old — `value` holds the midpoint, this the claim.
    range: tuple[float, float] | None = None
    # A non-detection's bound, not a measurement. Venus's and Titan's dipole
    # moments are only ever this.
    upper_limit: bool = False
    # A scaling, extrapolation or model rather than an observation of this
    # body — Venus's eruption rate is Earth's record times a mass ratio.
    modelled: bool = False
    # Database version or survey cut-off, for counts that snapshot a growing
    # catalogue. Without it "343 hot spots" reads as Io's property, not the
    # last flyby's.
    as_of: str | None = None


class Volcanism(NamedTuple):
    kind: str
    status: str
    # Plural because status is often the sum of independent detections and
    # crediting one misattributes the rest: Venus is `probable` on a vent
    # that changed shape *and* flows elsewhere; Europa is `suspected` on four
    # disagreeing techniques.
    status_sources: tuple[str, ...]
    # Vents, edifices or thermal sources mapped. What counts as one differs
    # by body — the survey's definition, not ours.
    known_centres: Measurement | None = None
    eruptions_per_year: Measurement | None = None
    erupted_volume_km3_per_year: Measurement | None = None
    # Observed jets/plumes and what they carry away. Go together on icy
    # bodies, where the plume is the only thing that can be counted.
    plumes: Measurement | None = None
    plume_mass_kg_per_s: Measurement | None = None
    # Total heat leaving the body, and the same divided by area. Both quoted
    # because the ratio between bodies is the story: Io vs Earth is a factor
    # of two in power, thirty in flux.
    endogenic_power_w: Measurement | None = None
    heat_flux_w_per_m2: Measurement | None = None
    # Age of the youngest dated activity, years before present — separates
    # "extinct" from "dormant", usually the number the argument is about.
    youngest_activity_years: Measurement | None = None
    # Mean crater-retention age of the surface, years — how long since the
    # last volcanic resurfacing.
    surface_age_years: Measurement | None = None
    note: str | None = None


class Tectonics(NamedTuple):
    style: str
    status: str
    sources: tuple[str, ...]
    # Radius shrinkage as the core cooled, km — the measure of a
    # contractional lid, read off the shortening in its faults.
    radial_contraction_km: Measurement | None = None
    note: str | None = None


class BodyActivity(NamedTuple):
    volcanism: Volcanism
    tectonics: Tectonics | None = None


class TidalHeating(NamedTuple):
    """The tide raised on this body by the object it orbits."""

    # Body id of what raises the tide, so the panel can name it.
    raised_by: str
    role: str
    role_sources: tuple[str, ...]
    power_w: Measurement | None = None
    flux_w_per_m2: Measurement | None = None
    # Tidal Love number: how much the body deforms. Large means soft, usually
    # molten somewhere.
    k2: Measurement | None = None
    # Tidal quality factor, inverse of how lossy the deformation is. Small Q
    # dissipates hard; Io's ~11 is the smallest measured anywhere.
    q: Measurement | None = None
    # Body ids of the resonance partners keeping eccentricity from damping to
    # zero, without which the tide would switch itself off.
    resonance_with: tuple[str, ...] = ()
    resonance_source: str | None = None
    note: str | None = None


class MagneticField(NamedTuple):
    kind: str
    kind_sources: tuple[str, ...]
    # Equivalent centred dipole, A m². The one figure that compares across
    # bodies, present even where the source publishes only a surface field
    # and this is arithmetic on it.
    dipole_moment_a_m2: Measurement | None = None
    # Field at the surface on the magnetic equator, tesla. `range` carries the
    # spread where the real field is far from a dipole — Uranus runs 0.1 to
    # 1.1 G depending where you stand.
    surface_field_t: Measurement | None = None
    # Angle between dipole and rotation axes — separates Saturn from Uranus,
    # the hardest thing for dynamo models to reproduce.
    dipole_tilt_deg: Measurement | None = None
    # Displacement of the equivalent dipole from the body's centre, body
    # radii. Mercury's 0.2 north and Neptune's 0.48 both dominate what the
    # magnetosphere looks like.
    dipole_offset_radii: Measurement | None = None
    # When the dynamo stopped, years before present, for bodies that carry
    # only remanence now.
    dynamo_ended_years: Measurement | None = None
    note: str | None = None
