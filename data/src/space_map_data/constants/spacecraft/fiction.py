"""Ships that do not exist, described the same way as the ones that do.

They earn their place by breaking the solver in interesting directions. A
torch drive has no Δv budget worth stating — it has an acceleration it holds
until it arrives, which is a brachistochrone rather than a transfer orbit, and
the panel can only say so if the catalogue admits the field exists.

Citations are the works themselves. What a novel states about its own ship is
the primary source for that ship, and the alternative is a number from nowhere.
Where a work never states a figure, the entry does not invent one: the
Millennium Falcon below is famous for a hyperdrive rating and has no sublight
acceleration anyone wrote down, so it carries neither.
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
    Spacecraft(
        id="rocinante",
        qid="Q107297632",
        kind="fictional",
        propulsion="fictional",
        status="fictional",
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
        power="fictional",
        accel_m_s2=Measured(_G, "reynolds_2000_revelation_space"),
        crew=Measured(160000, "reynolds_2000_revelation_space"),
    ),
    # Nuclear, and slow enough to be recognisable: Discovery's Jupiter
    # transfer is months rather than days, and three of its five crew sleep
    # through it. The novel gives no acceleration, so it has none here.
    Spacecraft(
        id="discovery-one",
        qid="Q3030246",
        kind="fictional",
        propulsion="nuclear",
        status="fictional",
        power="nuclear",
        crew=Measured(5, "clarke_1968_2001"),
    ),
    # Present for the same reason a map has a compass rose. Lucasfilm's
    # databank publishes the ship's length and nothing else, and no film gives
    # a sublight acceleration or a mass, so the panel will say it cannot judge
    # the trip. Eight is the ship's complement rather than its flight crew:
    # two fly it and six ride, which is the split every reference gives and
    # roughly what leaves Tatooine in the first film.
    Spacecraft(
        id="millennium-falcon",
        qid="Q19901",
        kind="fictional",
        propulsion="fictional",
        status="fictional",
        power="fictional",
        crew=Measured(8, "lucas_1977_star_wars"),
    ),
)
