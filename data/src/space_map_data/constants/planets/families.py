"""Planet families: their Wikidata topics and their tree.

The thresholds of the rules that tag a planet go in this file too. Every
family is below one root family, exoplanet.

See docs/planet-qids.md for the QID research.
"""

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

# Bit n of a family mask is family n.
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
