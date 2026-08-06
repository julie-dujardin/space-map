"""Types and vocabularies for what a body is still *doing*.

Three tables share this schema because they are three views of one question —
is there heat left inside, and does it reach the surface. Tidal heating is the
supply on the small worlds, volcanism and tectonics are what the supply builds,
and a dynamo is the same heat leaving a core by convection. Io has all three
entries for one reason; Callisto has almost none for the same reason.

Every number is a `Measurement` rather than a bare float, because in this
subject the qualifier usually *is* the finding: Titan's magnetic moment is an
upper limit, Venus's eruption rate is an extrapolation from Earth, and Io's
hot-spot count is whatever the last survey resolved. A value that ships without
its width or its date would read as a measurement when it is a bound.
"""

from typing import NamedTuple


# `Volcanism.kind` values. `both` is for the bodies whose record holds silicate
# volcanism in the past and cryovolcanism now — Ceres is the case, its domes
# built of brine over a mantle that once melted.
SILICATE = "silicate"
CRYO = "cryo"
BOTH = "both"
NO_VOLCANISM = "none"

VOLCANISM_KINDS = frozenset({SILICATE, CRYO, BOTH, NO_VOLCANISM})

# `Volcanism.status` / `Tectonics.status` values, certain to absent. The middle
# three are the whole reason this vocabulary is not a boolean: most of the
# interesting bodies sit in them, and collapsing them would turn Venus's
# argument into Earth's fact.
STATUSES = frozenset(
    {
        # Caught in the act: an eruption, a plume, or a thermal source observed.
        "active",
        # Better than circumstantial but never witnessed — a surface change
        # between two passes, a deposit dated to within human timescales.
        "probable",
        # Circumstantial only: a young-looking landform, a transient gas.
        "suspected",
        # No activity observed, but the body is still warm enough to resume.
        "dormant",
        # The heat is gone. Cratering or dating puts the last event a
        # geological age ago.
        "extinct",
        # Never had any, as far as anything shows.
        "none",
    }
)

# `Tectonics.style` values. Not a ladder — an ice shell cracking over an ocean
# and a rock planet shrinking onto its core are different machines, and the
# only one of them that recycles a surface is Earth's.
TECTONIC_STYLES = frozenset(
    {
        "plate_tectonics",  # rigid plates, spreading and subduction; Earth alone
        "stagnant_lid",  # one unbroken lithosphere over a convecting mantle
        # A stagnant lid in compression: the whole planet shrinking as its core
        # cools, taken up by thrust faults. Mercury, and the Moon at smaller
        # amplitude.
        "contractional_lid",
        # Whole-lithosphere overturn without plates: Venus's rifts, coronae and
        # the possibility that its lid moves in blocks without subducting.
        "mobile_lid",
        "ice_shell_tectonics",  # ridges, bands and chaos in a floating ice shell
        "impact_dominated",  # nothing since the bombardment; the surface is craters
        "none",
    }
)

# `MagneticField.kind` values.
DYNAMO = "dynamo"  # generated now, in a convecting conductive interior
# No field of its own: eddy currents in a conductive shell — a salty ocean,
# an ionosphere — answering the varying field it sits in. The signal is
# evidence about the shell rather than about a core.
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
    # The published width. Where a source brackets a value without preferring
    # one — Mimas's ocean is 2 to 25 Myr old — `value` holds the midpoint and
    # this holds the claim.
    range: tuple[float, float] | None = None
    # A non-detection's bound rather than a measurement. Venus's and Titan's
    # dipole moments are only ever this.
    upper_limit: bool = False
    # The number is a scaling, an extrapolation or a model rather than an
    # observation of this body — Venus's eruption rate is Earth's record
    # multiplied by a mass ratio.
    modelled: bool = False
    # For counts that are a snapshot of a growing catalogue: the database
    # version or survey cut-off the count belongs to. Without it "343 hot
    # spots" reads as a property of Io rather than of the last flyby.
    as_of: str | None = None


class Volcanism(NamedTuple):
    kind: str
    status: str
    # Plural because a status is often the sum of independent detections and
    # crediting one of them misattributes the rest: Venus is `probable` because
    # of a vent that changed shape *and* flows that appeared elsewhere, Europa
    # is `suspected` on four separate techniques that mostly disagree.
    status_sources: tuple[str, ...]
    # Vents, edifices or thermal sources currently erupting or emitting. What
    # counts as one differs by body and is the survey's definition, not ours.
    active_centres: Measurement | None = None
    # The catalogue behind the count above: everything mapped that could erupt.
    known_centres: Measurement | None = None
    eruptions_per_year: Measurement | None = None
    erupted_volume_km3_per_year: Measurement | None = None
    # Observed jets or plumes, and what they carry away. The two go together on
    # the icy bodies, where the plume is the only thing that can be counted.
    plumes: Measurement | None = None
    plume_mass_kg_per_s: Measurement | None = None
    # Total heat leaving the body from inside, and the same divided by area.
    # Both are quoted because the ratio between two bodies is the story: Io
    # against Earth is a factor of two in power and thirty in flux.
    endogenic_power_w: Measurement | None = None
    heat_flux_w_per_m2: Measurement | None = None
    # Age of the youngest activity anyone has dated, in years before present.
    # This is what separates "extinct" from "dormant" and it is the number the
    # argument is usually about.
    youngest_activity_years: Measurement | None = None
    # Mean crater-retention age of the surface, in years — how long ago the
    # last resurfacing was, where volcanism did the resurfacing.
    surface_age_years: Measurement | None = None
    note: str | None = None


class Tectonics(NamedTuple):
    style: str
    status: str
    sources: tuple[str, ...]
    plates: Measurement | None = None
    # Area of new lithosphere made per year, which on Earth equals the area
    # destroyed. The one quantity that says a surface is being recycled rather
    # than merely deformed.
    crust_production_km2_per_year: Measurement | None = None
    # How much the planet's radius has shrunk as its core cooled, in km. The
    # measure of a contractional lid, read off the shortening in its faults.
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
    # The gravitational tidal Love number: how much the body deforms. Large
    # means soft, which usually means molten somewhere.
    k2: Measurement | None = None
    # Tidal quality factor — the inverse of how lossy the deformation is. Small
    # Q dissipates hard; Io's ~11 is the smallest measured anywhere.
    q: Measurement | None = None
    # What keeps the eccentricity from damping to zero, without which the tide
    # would switch itself off. Body ids of the resonance partners.
    resonance_with: tuple[str, ...] = ()
    resonance_source: str | None = None
    note: str | None = None


class MagneticField(NamedTuple):
    kind: str
    kind_sources: tuple[str, ...]
    # Of the equivalent centred dipole, in A m². The one figure that compares
    # across bodies, which is why it is here even where a source publishes only
    # a surface field and this is arithmetic on it.
    dipole_moment_a_m2: Measurement | None = None
    # Field at the surface on the magnetic equator, in tesla. `range` carries
    # the spread over the real surface where the field is far from a dipole —
    # Uranus runs from 0.1 to 1.1 G depending where you stand.
    surface_field_t: Measurement | None = None
    # Angle between the dipole and rotation axes. The number that separates
    # Saturn from Uranus and is the hardest thing for dynamo models to make.
    dipole_tilt_deg: Measurement | None = None
    # Displacement of the equivalent dipole from the body's centre, in body
    # radii. Mercury's 0.2 north and Neptune's 0.48 are both large enough to
    # dominate what the magnetosphere looks like.
    dipole_offset_radii: Measurement | None = None
    # Distance to the sub-solar magnetopause, in body radii — how far the field
    # holds the solar wind off.
    magnetopause_radii: Measurement | None = None
    # When the dynamo stopped, in years before present, for the bodies that
    # carry only remanence now.
    dynamo_ended_years: Measurement | None = None
    note: str | None = None
