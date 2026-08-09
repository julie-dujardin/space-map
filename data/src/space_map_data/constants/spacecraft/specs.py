"""What a spacecraft is, in the terms a trajectory solver can use.

Two things are judged two different ways. A launcher is judged on whether it
can reach the departure energy at all, which is one curve: payload against
characteristic energy C3. Everything else is judged on the Δv it carries once
it is up there, and that is deliberately *not* stored as a Δv — the rocket
equation's three inputs are, so the panel can show the working and so a craft
whose propellant load is known but whose engine is not fails visibly rather
than shipping a rounded number nobody can check.

Every figure carries its own source key. A mass and a C3 curve almost never
come from the same document, and a catalogue with one citation per vehicle
would be claiming otherwise.
"""

from dataclasses import dataclass
from math import log
from typing import NamedTuple

# Standard gravity, the constant in the rocket equation. Not a property of any
# body — it is the definition Isp is quoted against.
G0_M_S2 = 9.80665


class Measured(NamedTuple):
    """One number and the work it comes from.

    Integer quantities (crew) are stored as ints; the export emits what it is
    given rather than coercing, so a crew of 3 does not ship as 3.0.
    """

    value: float
    source: str


class Cost(NamedTuple):
    """What it costs to fly, in millions of USD of `year`.

    No inflation adjustment is applied anywhere: the year is shipped so the
    frontend can say "2020 dollars" instead of implying a comparison the data
    does not support. `kind` says what was actually bought, which is the
    difference between the $117M NASA paid for a Falcon Heavy and the $1.4B
    Psyche cost to build and fly.
    """

    usd_millions: float
    year: int
    kind: str
    source: str


class C3Curve(NamedTuple):
    """Payload against departure energy: ascending `(C3 km²/s², kg)` pairs.

    Either `points`, for a curve read out of a published table, or `dataset`,
    naming a file the launch-performance downloader fetches — a hundred
    digitised points do not belong pasted into a constants module.

    `truncated` marks a curve whose published range stops before the vehicle
    does — ULA tabulates the Vulcan at two energies and says nothing about the
    third. Past the end of a complete curve the vehicle genuinely cannot fly;
    past the end of a truncated one nobody has said. Reporting those as the
    same answer would turn a gap in the documentation into a claim about the
    rocket.
    """

    source: str
    points: tuple[tuple[float, float], ...] = ()
    dataset: str | None = None
    truncated: bool = False
    # A second work the curve was checked against. Only set where someone
    # else published a point on the same curve — a digitised curve that
    # reproduces the manufacturer's own table is worth more than one that
    # nobody has ever checked, and the reader should be able to see which is
    # which.
    cross_check: str | None = None


# `Spacecraft.kind` — which feasibility path an entry takes. A launcher is
# checked against its C3 curve, everything else against Δv.
KINDS = frozenset({"launcher", "probe", "crewed", "lander", "fictional"})

# `Spacecraft.propulsion`. Sets the display, and decides whether impulsive Δv
# is the right yardstick at all: an electric craft's Δv is real but takes years
# to spend, so a Lambert arc it "can afford" is still not one it can fly.
PROPULSION = frozenset({"chemical", "electric", "nuclear", "solar_sail", "fictional"})

# `Spacecraft.status`. `concept` is the honest label for anything whose
# performance figures come from a manufacturer's slide rather than a flight.
# `cancelled` is distinct from `retired`: one stopped flying, the other never
# started, and both keep whatever performance was published for them.
STATUSES = frozenset(
    {"active", "retired", "planned", "cancelled", "concept", "fictional"}
)

# `Spacecraft.power`. A solar-only craft past the asteroid belt is a real
# constraint and a cheap one to check — Juno needed 60 m² of panel to work at
# Jupiter, and nothing solar has operated beyond it.
POWER = frozenset({"solar", "rtg", "nuclear", "battery", "fictional"})

# `Spacecraft.departs_from`. Where a trip flown with this vehicle can start.
# An SLS leaves from a pad and nowhere else; a capsule is already up there and
# has no way of getting there itself; a Starship does both. Nothing is cited
# because nothing is measured — this is what the vehicle is for, and it is the
# same statement as putting it under `launcher` or `crewed` in the first place.
DEPARTURES = frozenset({"surface", "orbit"})

# `Spacecraft.capabilities`. What the vehicle can do on arrival, which is what
# decides whether an arrival mode may even be offered.
CAPABILITIES = frozenset(
    {
        "aerocapture",  # survives a pass through an atmosphere and stays
        "aerobraking",  # trims an orbit over months of shallow passes
        "entry",  # has a heat shield rated for direct arrival
        "landing",  # reaches a surface intact and under control
        "sample_return",
        "crew_return",  # can bring people back down again
    }
)

# `Cost.kind`. Which number a figure is: the price of a ride, or everything the
# mission cost from proposal to end of operations.
COST_KINDS = frozenset(
    {
        "launch_service",  # what a customer paid for one flight
        "mission_lifecycle",  # development + build + launch + operations
        "unit",  # to build one more of the vehicle
    }
)


@dataclass(frozen=True)
class Spacecraft:
    """One vehicle, at one configuration.

    A configuration is a separate entry rather than a flag: a Falcon Heavy
    that lands its boosters and one that does not have different curves at
    every energy, and a Star-48 kick stage changes what the vehicle *is* at
    high C3 rather than scaling it.
    """

    id: str
    kind: str
    propulsion: str
    status: str
    # Wikidata supplies the display name in all twelve locales, the way bodies
    # get theirs. `name` is the fallback for the handful of fictional ships
    # with no item, and those carry a hand-authored message key instead.
    qid: str | None = None
    name: str | None = None
    # What distinguishes this entry from the others sharing its Wikidata item.
    # Three Falcon Heavy configurations are three curves and one QID, so the
    # label alone would print the same row three times. Slugs rather than
    # words, and several rather than one joined string: the frontend has to say
    # "expendable" in twelve languages and "Star 48" in none of them.
    variant: tuple[str, ...] = ()

    # Which departures this vehicle can be offered against, so the panel does
    # not suggest lifting an SLS out of low orbit. Empty is a claim rather than
    # a gap: a rover starts no trip at all, it is carried.
    departs_from: frozenset[str] = frozenset()

    # --- in-space performance: the rocket equation's inputs --------------
    dry_mass_kg: Measured | None = None
    propellant_mass_kg: Measured | None = None
    isp_s: Measured | None = None
    # Total thrust of the propulsion the Δv above is spent through. Divided by
    # wet mass this gives the acceleration, which is what decides whether an
    # impulsive burn is a fair model — a 90 mN ion thruster on a 1.2 t probe
    # takes months to do what a Lambert arc assumes happens instantly.
    thrust_n: Measured | None = None

    # --- launch performance ----------------------------------------------
    c3_curve: C3Curve | None = None

    # --- what the trip does to the crew and the hull ----------------------
    # Everyone aboard, not just whoever is flying: crew plus passengers. On
    # every spacecraft ever flown those are the same set, which is why the
    # field is named for the crew — it stops being true the moment anything
    # carries people who are not operating it, and a lighthugger's twenty-five
    # thousand sleepers are the case the name would otherwise lose.
    crew: Measured | None = None
    # How long the consumables last, which is the constraint a Δv budget never
    # shows: a 6 km/s transfer a capsule can afford may still be four times
    # its life support.
    endurance_days: Measured | None = None
    # Entry speed the heat shield is rated for, km/s. Gates arrival: Apollo's
    # 11 km/s shield is a lunar-return shield and Mars arrival is faster.
    max_entry_speed_kms: Measured | None = None
    capabilities: frozenset[str] = frozenset()
    capability_source: str | None = None
    power: str | None = None

    # --- constant-acceleration drives -------------------------------------
    # A torch drive has no Δv budget worth stating; it has an acceleration it
    # holds until it arrives. Brachistochrone, not Hohmann.
    accel_m_s2: Measured | None = None
    # Propellant is not a constraint the work imposes. Only ever true of
    # fiction, and it is a reading of the work rather than a figure out of it —
    # the ships this is set on are the ones whose stories are about where the
    # crew can go and never about whether they can afford to get there. The
    # cited work is already on the entry's other figures, so there is nothing
    # extra to cite.
    #
    # It is also what admits a ship to the constant-thrust solver: an arc flown
    # under power the whole way is spending the entire time, and offering one
    # to a craft with a real propellant load would be pricing a trip it could
    # not finish.
    unlimited_dv: bool = False

    cost: Cost | None = None

    # --- what this entry already is elsewhere in the map ------------------
    # Probe object ids (`probe-<id>`) this entry describes the hardware of.
    # Voyager is one design and two spacecraft; Apollo's CSM is one design and
    # eleven, which is why the capsules link a group page instead.
    object_ids: tuple[str, ...] = ()
    # An existing group page: `lv-<slug>` for a launcher family, `const-<slug>`
    # for a capsule class.
    group_slug: str | None = None

    def sources(self) -> frozenset[str]:
        """Every source key the entry cites, for validation and credits."""
        keys = {
            m.source
            for m in (
                self.dry_mass_kg,
                self.propellant_mass_kg,
                self.isp_s,
                self.thrust_n,
                self.crew,
                self.endurance_days,
                self.max_entry_speed_kms,
                self.accel_m_s2,
            )
            if m is not None
        }
        if self.c3_curve is not None:
            keys.add(self.c3_curve.source)
            if self.c3_curve.cross_check is not None:
                keys.add(self.c3_curve.cross_check)
        if self.cost is not None:
            keys.add(self.cost.source)
        if self.capability_source is not None:
            keys.add(self.capability_source)
        return frozenset(keys)


def delta_v_kms(craft: Spacecraft) -> float | None:
    """Ideal Δv from the rocket equation, or None if a term is missing.

    Ideal in the strict sense: no gravity losses, no finite-burn losses, and
    the whole propellant load spent through one engine at one Isp. Real
    missions split it across a bipropellant main engine and a monopropellant
    attitude system at two thirds the Isp, so this is an upper bound.
    """
    if craft.dry_mass_kg is None or craft.propellant_mass_kg is None:
        return None
    if craft.isp_s is None:
        return None
    dry = craft.dry_mass_kg.value
    wet = dry + craft.propellant_mass_kg.value
    if dry <= 0 or wet <= dry:
        return None
    return craft.isp_s.value * G0_M_S2 * log(wet / dry) / 1000.0
