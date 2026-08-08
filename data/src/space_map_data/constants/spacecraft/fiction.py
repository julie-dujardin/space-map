"""Ships that do not exist, described the same way as the ones that do.

Two kinds. Ships out of novels, which earn their place by breaking the solver
in interesting directions — a torch drive has no Δv budget worth stating, it
has an acceleration it holds until it arrives, which is a brachistochrone
rather than a transfer orbit, and the panel can only say so if the catalogue
admits the field exists. And archetypes: a propulsion type sized into a
plausible vehicle, so a trip can be costed against what a *kind* of ship could
do rather than against the eleven that happen to have flown. They come from no
work at all and say so.

Departures are read off the work the same way. Most of these are assembled in
orbit and never touch a surface — a lighthugger's landings are done by the
lighters it carries, and the ship itself has no more business in an atmosphere
than a shipyard does. The ones that fly off a surface under their own power say
so, and are the exception rather than the default.

Citations are the works themselves. What a novel states about its own ship is
the primary source for that ship, and the alternative is a number from nowhere.

Where a work describes a drive but gives it no numbers, the entry may carry
figures fitted to that description — cited to `space_map_fitted`, never to the
author — so the ship can be judged on the same yardstick as everything else.
They come out enormous, which is the honest answer and the interesting one.
Two limits on that. A ship the work says nothing useful about gets nothing:
the Millennium Falcon is famous for a hyperdrive rating and has no sublight
acceleration anyone wrote down, so it carries neither. And faster-than-light
is out of scope entirely — a jump is not a trajectory, and no amount of Δv
describes one.
"""

from space_map_data.constants.spacecraft.specs import Measured, Spacecraft

# One gravity, the unit every constant-acceleration drive in fiction is quoted
# in. Kept separate from specs.G0_M_S2, which is the rocket equation's
# constant rather than a comfortable floor to stand on.
_G = 9.80665

FICTIONAL: tuple[Spacecraft, ...] = (
    # The Expanse's economy runs on this: a drive efficient enough that a
    # crew's limit is their own blood pressure rather than their propellant.
    # A third of a gravity is the cruise the Rocinante's crew fly at when
    # nobody is shooting; the ship's ceiling is where the drugs stop working.
    # A frigate on landing struts: it makes planetfall and lifts off again on
    # the same drive, which is why it departs from both.
    Spacecraft(
        id="rocinante",
        qid="Q107297632",
        kind="fictional",
        propulsion="fictional",
        status="fictional",
        departs_from=frozenset({"surface", "orbit"}),
        power="fictional",
        accel_m_s2=Measured(_G / 3.0, "corey_2011_leviathan_wakes"),
        crew=Measured(18, "corey_2011_leviathan_wakes"),
    ),
    # A drive that eats its own fuel's mass at something close to unit
    # efficiency, which is how a ship this size crosses twelve light years.
    # Wikidata has no item for the ship, so the name is hand-authored.
    Spacecraft(
        id="hail-mary",
        name="Hail Mary",
        kind="fictional",
        propulsion="fictional",
        status="fictional",
        departs_from=frozenset({"orbit"}),
        power="fictional",
        accel_m_s2=Measured(1.5 * _G, "weir_2021_project_hail_mary"),
        crew=Measured(3, "weir_2021_project_hail_mary"),
    ),
    # The other end of the same idea: an ion drive that never stops, at an
    # acceleration you could not feel, which still beats every chemical
    # transfer to Mars because it is spending thrust the entire way.
    Spacecraft(
        id="hermes",
        name="Hermes",
        kind="fictional",
        propulsion="fictional",
        status="fictional",
        departs_from=frozenset({"orbit"}),
        power="nuclear",
        accel_m_s2=Measured(0.002, "weir_2011_the_martian"),
        crew=Measured(6, "weir_2011_the_martian"),
    ),
    # A lighthugger holds one gravity until it is close enough to light speed
    # that the crew's clocks and everyone else's stop agreeing. The
    # brachistochrone here is interstellar, and the interesting number is not
    # the trip time but which of the two trip times you mean.
    Spacecraft(
        id="nostalgia-for-infinity",
        qid="Q98098048",
        kind="fictional",
        propulsion="fictional",
        status="fictional",
        departs_from=frozenset({"orbit"}),
        power="fictional",
        accel_m_s2=Measured(_G, "reynolds_2000_revelation_space"),
        crew=Measured(160000, "reynolds_2000_revelation_space"),
    ),
    # Nuclear, and slow enough to be recognisable: Discovery's Jupiter transfer
    # is months rather than days, and three of its five crew sleep through it.
    # The novel gives no numbers, so the three below are chosen rather than
    # quoted, and chosen to stay inside the physics the novel does commit to.
    #
    # "Plasma drive" running on liquid hydrogen puts it in gas-core territory,
    # a few thousand seconds — an order above the solid-core reactors anyone
    # has built and three orders below a torch. Three quarters of a 1,200 t
    # ship as propellant is the ratio a vehicle assembled in orbit can carry.
    # That is 41 km/s, or eighteen Cassinis, and it is what makes a months-long
    # Jupiter transfer rather than a years-long one.
    Spacecraft(
        id="discovery-one",
        qid="Q3030246",
        kind="fictional",
        propulsion="nuclear",
        status="fictional",
        departs_from=frozenset({"orbit"}),
        power="nuclear",
        dry_mass_kg=Measured(300000, "space_map_fitted"),
        propellant_mass_kg=Measured(900000, "space_map_fitted"),
        isp_s=Measured(3000.0, "space_map_fitted"),
        # 0.04 g, so the departure burn is a day rather than a season. Below
        # this the impulsive arc the solver draws stops describing the trip.
        thrust_n=Measured(500000.0, "space_map_fitted"),
        crew=Measured(5, "clarke_1968_2001"),
    ),
    # Present for the same reason a map has a compass rose. Lucasfilm's
    # databank publishes the ship's length and nothing else, and no film gives
    # a sublight acceleration or a mass, so the panel will say it cannot judge
    # the trip. Eight is the ship's complement rather than its flight crew:
    # two fly it and six ride, which is the split every reference gives and
    # roughly what leaves Tatooine in the first film — off a landing pad,
    # under its own power, which is the one performance claim the films do
    # make about it.
    Spacecraft(
        id="millennium-falcon",
        qid="Q19901",
        kind="fictional",
        propulsion="fictional",
        status="fictional",
        departs_from=frozenset({"surface", "orbit"}),
        power="fictional",
        crew=Measured(8, "lucas_1977_star_wars"),
    ),
    # --- archetypes --------------------------------------------------------
    # Not ships from anywhere: a propulsion type sized into a vehicle, so the
    # panel can answer "what would it take" and not only "who has been". Every
    # figure is chosen, but chosen off flown hardware rather than out of the
    # air, and none of them is a stretch of what has already been built.
    #
    # `status` is `concept` rather than `fictional`: nothing here has flown,
    # and nothing here is impossible either.
    #
    # All three depart from orbit alone. A stage with a thrust-to-weight under
    # one is not a thing that leaves a pad, whatever else it can do.
    #
    # Fifty kilowatts of Hall thrusters on eight and a half tonnes: the tug is
    # Psyche's propulsion scaled to something that moves cargo rather than
    # instruments. Thirty-six kilometres a second, and four hundredths of a
    # millinewton per kilogram to spend it with — nearly three years of
    # continuous thrust, which is the whole character of the thing.
    Spacecraft(
        id="ion-tug",
        name="Ion tug",
        kind="fictional",
        propulsion="electric",
        status="concept",
        departs_from=frozenset({"orbit"}),
        power="solar",
        dry_mass_kg=Measured(2500, "space_map_fitted"),
        propellant_mass_kg=Measured(6000, "space_map_fitted"),
        isp_s=Measured(3000.0, "space_map_fitted"),
        thrust_n=Measured(3.5, "space_map_fitted"),
    ),
    # The one entry with no propellant at all, which is the point: a sail's Δv
    # budget is not large, it does not exist. What it has instead is 0.2 mm/s²
    # at Earth's distance — four times what any sail has actually flown, and
    # falling off as the inverse square on the way out, so the constant
    # acceleration below is an honest number in exactly one place.
    Spacecraft(
        id="solar-sail",
        name="Solar sail",
        kind="fictional",
        propulsion="solar_sail",
        status="concept",
        departs_from=frozenset({"orbit"}),
        power="solar",
        accel_m_s2=Measured(0.0002, "space_map_fitted"),
    ),
    # The middle the catalogue otherwise skips: hydrogen through a reactor at
    # twice the specific impulse of anything chemical and a thrust-to-weight
    # that still lets it burn like a rocket rather than a season. 900 s is
    # about what NERVA measured on a test stand in 1968; the 55 t stage around
    # it is sized to a launcher that exists.
    Spacecraft(
        id="nuclear-thermal-stage",
        name="Nuclear thermal stage",
        kind="fictional",
        propulsion="nuclear",
        status="concept",
        departs_from=frozenset({"orbit"}),
        power="nuclear",
        dry_mass_kg=Measured(15000, "space_map_fitted"),
        propellant_mass_kg=Measured(40000, "space_map_fitted"),
        isp_s=Measured(900.0, "space_map_fitted"),
        thrust_n=Measured(250000.0, "space_map_fitted"),
    ),
)
