"""Category groups: the top-level browse tree behind /g/cat-<slug>.

Wikidata-backed nodes whose members are child groups (zones, families, sat
classes) or bodies (planets). Names are set here, not from the singular
lower-case Wikidata label ("planet").
"""

from dataclasses import dataclass

from space_map_data.models.object.sbdb import OrbitClass

CATEGORY_SLUG_PREFIX = "cat-"

# Comet orbit classes; every other OrbitClass member is an asteroid.
COMET_ORBIT_CLASSES: frozenset[OrbitClass] = frozenset(
    {
        OrbitClass.ETc,
        OrbitClass.JFc,
        OrbitClass.JFC,
        OrbitClass.CTc,
        OrbitClass.HTC,
        OrbitClass.PAR,
        OrbitClass.HYP,
        OrbitClass.COM,
    }
)


@dataclass(frozen=True)
class CategorySpec:
    slug: str  # cat-<name>
    name: str  # display name (English; not the singular Wikidata label)
    wikidata_qid: str


SOLAR_SYSTEM_SLUG = f"{CATEGORY_SLUG_PREFIX}solar-system"
PLANETS_SLUG = f"{CATEGORY_SLUG_PREFIX}planets"
DWARF_PLANETS_SLUG = f"{CATEGORY_SLUG_PREFIX}dwarf-planets"
MOONS_SLUG = f"{CATEGORY_SLUG_PREFIX}moons"
ASTEROIDS_SLUG = f"{CATEGORY_SLUG_PREFIX}asteroids"
COMETS_SLUG = f"{CATEGORY_SLUG_PREFIX}comets"
SATELLITES_SLUG = f"{CATEGORY_SLUG_PREFIX}satellites"
PROBES_SLUG = f"{CATEGORY_SLUG_PREFIX}probes"

CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec(SOLAR_SYSTEM_SLUG, "Solar System", "Q544"),
    CategorySpec(PLANETS_SLUG, "Planets", "Q634"),
    CategorySpec(DWARF_PLANETS_SLUG, "Dwarf Planets", "Q2199"),  # "dwarf planet"
    CategorySpec(MOONS_SLUG, "Moons", "Q2537"),  # "natural satellite"
    CategorySpec(ASTEROIDS_SLUG, "Asteroids", "Q3863"),
    CategorySpec(COMETS_SLUG, "Comets", "Q3559"),
    CategorySpec(SATELLITES_SLUG, "Satellites", "Q26540"),
    CategorySpec(PROBES_SLUG, "Probes", "Q26529"),  # "space probe"
)

CATEGORY_BY_SLUG: dict[str, CategorySpec] = {c.slug: c for c in CATEGORIES}
