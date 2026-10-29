"""Planet families: their Wikidata topics, their tree and the thresholds of
the rules that tag a planet.

Only a planet of the IAU class `planet` gets a family. A family is published
when the values its rule reads are measured, and estimated when the rule
needs an estimate. Every family is below one root family, exoplanet.

The rules use Earth masses (M⊕), Earth radii (R⊕), days, AU and g/cm³. A
range (lo, hi) holds lo <= x < hi. `_above(x)` as a bound includes x at the
top of a range and excludes it at the bottom.

See docs/planet-qids.md for the QID research.
"""

import math

# Page on the first QID. Mini-Neptune and sub-Neptune are one size class; the
# mini-Neptune item has more articles.
PLANET_FAMILY_PAGES: dict[str, tuple[str, ...]] = {
    "classification": ("Q44559",),
    "terrestrial-planet": ("Q128207",),
    "sub-earth": ("Q15129745",),
    "mega-earth": ("Q17325117",),
    "super-earth": ("Q327757",),
    "mini-neptune": ("Q691537", "Q97359320"),
    "super-puff": ("Q83148567",),
    "giant-planet": ("Q21857994",),
    "super-neptune": ("Q28453859",),
    "hot-neptune": ("Q420490",),
    "gas-giant": ("Q121750",),
    "super-jupiter": ("Q4021955",),
    "hot-jupiter": ("Q382979",),
    "warm-jupiter": ("Q19952590",),
    "cold-jupiter": ("Q2663361",),
    "jupiter-analogue": ("Q15121300",),
    "eccentric-jupiter": ("Q1196165",),
    "puffy-planet": ("Q911454",),
    "ultra-short-period-planet": ("Q1079825",),
    "circumbinary-planet": ("Q205901",),
    "pulsar-planet": ("Q1142835",),
    "goldilocks-planet": ("Q3391592",),
}

# The order in which a planet record lists its families.
FAMILIES: tuple[str, ...] = tuple(PLANET_FAMILY_PAGES)

# The /g/ page of a family is /g/planet-<family>.
FAMILY_SLUG_PREFIX = "planet-"
# The root of the family tree: a planet with a family is in it. Its page is on
# exoplanet, because Wikidata has no item for a planet classification.
ROOT_FAMILY = "classification"

# Each family adds these. The closure is transitive. A family without a parent
# here gets the root.
PARENTS: dict[str, tuple[str, ...]] = {
    **dict.fromkeys(("sub-earth", "mega-earth"), ("terrestrial-planet",)),
    **dict.fromkeys(("super-neptune", "hot-neptune", "gas-giant"), ("giant-planet",)),
    **dict.fromkeys(
        (
            "super-jupiter",
            "hot-jupiter",
            "warm-jupiter",
            "cold-jupiter",
            "eccentric-jupiter",
            "puffy-planet",
        ),
        ("gas-giant",),
    ),
    "jupiter-analogue": ("cold-jupiter",),
}
PARENTS |= {
    family: (ROOT_FAMILY,)
    for family in FAMILIES
    if family not in PARENTS and family != ROOT_FAMILY
}


INF = math.inf


def _above(x: float) -> float:
    return math.nextafter(x, INF)


# The planet records give masses and radii in Jupiter units: IAU 2015
# nominal values (Prša et al. 2016), equatorial radii.
EARTH_MASSES_PER_JUPITER = 317.828
EARTH_RADII_PER_JUPITER = 11.209
JUPITER_MASS_G = 1.89813e30
JUPITER_RADIUS_CM = 7.1492e9
# R⊕, equatorial.
NEPTUNE_RADIUS = 3.88
EARTH_DENSITY = 5.51
SATURN_DENSITY = 0.687

# Terrestrial planet: rocky cores up to 1.5 R⊕ (Fulton et al. 2017). When the
# radius does not decide, under 2 M⊕, the Terran-Neptunian transition (Chen &
# Kipping 2017).
TERRESTRIAL_RADIUS = (0.0, _above(1.5))
TERRESTRIAL_MASS = (0.0, 2.0)
# Sub-Earth: less massive and smaller than Earth (Sinukoff et al. 2013).
SUB_EARTH_MASS = (0.0, 1.0)
SUB_EARTH_RADIUS = (0.0, 1.0)
# Mega-Earth: 10 M⊕ or more (Seager et al. 2007), 2.1-5 R⊕ and denser than
# Earth (Kroft et al. 2026, arXiv:2603.24682).
MEGA_EARTH_MASS = (10.0, INF)
MEGA_EARTH_RADIUS = (2.1, _above(5.0))
MEGA_EARTH_DENSITY = (_above(EARTH_DENSITY), INF)
# Super-Earth: 1-10 M⊕ (Valencia et al. 2007), from Earth's radius to the
# radius gap at 2 R⊕ (Borucki et al. 2011).
SUPER_EARTH_MASS = (1.0, _above(10.0))
SUPER_EARTH_RADIUS = (1.0, 2.0)
# Mini-Neptune: from the radius gap to Neptune's radius (Fulton et al. 2017).
MINI_NEPTUNE_RADIUS = (2.0, NEPTUNE_RADIUS)
# Super-puff: a few Earth masses in more than Neptune's radius (Libby-Roberts
# et al. 2020).
SUPER_PUFF_MASS = (0.0, 10.0)
SUPER_PUFF_RADIUS = (_above(NEPTUNE_RADIUS), INF)
# Giant planet: above the super-Earth masses (Valencia et al. 2007), at least
# Neptune's radius.
GIANT_MASS = (10.0, INF)
GIANT_RADIUS = (NEPTUNE_RADIUS, INF)
# Super-Neptune: 20-100 M⊕ and 4-8 R⊕ (Wikipedia, "Super-Neptune").
SUPER_NEPTUNE_MASS = (20.0, _above(100.0))
SUPER_NEPTUNE_RADIUS = (4.0, _above(8.0))
# Gas giant: at least 0.25 MJ (Dawson & Johnson 2018), larger than a
# super-Neptune.
GAS_GIANT_MASS = (0.25 * EARTH_MASSES_PER_JUPITER, INF)
GAS_GIANT_RADIUS = (8.0, INF)
# Hot Neptune: a Neptune-size planet under the gas-giant mass, on a hot orbit.
HOT_NEPTUNE_MASS = (10.0, GAS_GIANT_MASS[0])
HOT_NEPTUNE_RADIUS = (NEPTUNE_RADIUS, 8.0)
# Hot orbit: under 10 d (Wang et al. 2015; Dawson & Johnson 2018).
HOT_PERIOD = (0.0, 10.0)
# Super-Jupiter: more massive than Jupiter.
SUPER_JUPITER_MASS = (_above(EARTH_MASSES_PER_JUPITER), INF)
# Warm Jupiter: 10-200 d (Huang, Wu & Triaud 2016; Dawson & Johnson 2018).
WARM_PERIOD = (10.0, _above(200.0))
# Cold Jupiter: beyond 1 AU.
COLD_SEMI_MAJOR_AXIS = (_above(1.0), INF)
# Jupiter analogue: at least 0.3 MJ at 3-12 AU (Gratton et al. 2023).
JUPITER_ANALOGUE_MASS = (0.3 * EARTH_MASSES_PER_JUPITER, INF)
JUPITER_ANALOGUE_SEMI_MAJOR_AXIS = (3.0, _above(12.0))
# Eccentric Jupiter: an eccentricity of 0.1 or more (Raymond et al. 2004).
ECCENTRIC = (0.1, INF)
# Puffy planet: no denser than Saturn.
PUFFY_DENSITY = (0.0, _above(SATURN_DENSITY))
# Ultra-short-period planet: under 1 d (Winn, Sanchis-Ojeda & Rappaport 2018).
ULTRA_SHORT_PERIOD = (0.0, 1.0)

# Goldilocks planet: an insolation in the conservative habitable zone of
# Kopparapu et al. 2014, Table 1, for 1 M⊕: S_eff = S + aT + bT² + cT³ + dT⁴,
# T = Teff - 5780 K, for Teff 2600-7200 K.
HABITABLE_TEFF = (2600.0, _above(7200.0))
HABITABLE_TEFF_ZERO = 5780.0
# The inner edge, runaway greenhouse.
HABITABLE_INNER = (1.107, 1.332e-4, 1.580e-8, -8.308e-12, -1.931e-15)
# The outer edge, maximum greenhouse.
HABITABLE_OUTER = (0.356, 6.171e-5, 1.698e-9, -3.198e-12, -5.575e-16)
# K, IAU 2015 nominal, for an insolation from the star's radius and Teff.
SUN_TEFF = 5772.0
