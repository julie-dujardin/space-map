"""Category groups: the top-level browse tree behind /g/cat-<slug>.

Wikidata-backed nodes whose members are child groups (zones, families, sat
classes) or bodies (planets). Names are set here, not from the singular
lower-case Wikidata label ("planet").
"""

from dataclasses import dataclass

from space_map_data.models.object.sbdb import OrbitClass

CATEGORY_SLUG_PREFIX = "cat-"

# Derived from the SBDB display names so the set can't drift from the enum;
# every other member (Centaurs and TNOs included) counts as an asteroid in
# the browse tree.
COMET_ORBIT_CLASSES: frozenset[OrbitClass] = frozenset(
    c for c in OrbitClass if "Comet" in c.value
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
RING_SYSTEMS_SLUG = f"{CATEGORY_SLUG_PREFIX}ring-systems"
ASTEROIDS_SLUG = f"{CATEGORY_SLUG_PREFIX}asteroids"
COMETS_SLUG = f"{CATEGORY_SLUG_PREFIX}comets"
SATELLITES_SLUG = f"{CATEGORY_SLUG_PREFIX}satellites"
DEBRIS_SLUG = f"{CATEGORY_SLUG_PREFIX}debris"
PROBES_SLUG = f"{CATEGORY_SLUG_PREFIX}probes"
SURFACE_FEATURES_SLUG = f"{CATEGORY_SLUG_PREFIX}surface-features"

CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec(SOLAR_SYSTEM_SLUG, "Solar System", "Q544"),
    CategorySpec(PLANETS_SLUG, "Planets", "Q634"),
    CategorySpec(DWARF_PLANETS_SLUG, "Dwarf Planets", "Q2199"),  # "dwarf planet"
    CategorySpec(MOONS_SLUG, "Moons", "Q2537"),  # "natural satellite"
    # "planetary ring" rather than "ring system" (Q28951811): the concept is the
    # same but only the former has an article in all twelve locales, and the
    # latter's Korean sitelink is about a single exoplanet candidate.
    CategorySpec(RING_SYSTEMS_SLUG, "Ring Systems", "Q179792"),
    CategorySpec(ASTEROIDS_SLUG, "Asteroids", "Q3863"),
    CategorySpec(COMETS_SLUG, "Comets", "Q3559"),
    CategorySpec(SATELLITES_SLUG, "Satellites", "Q26540"),
    # Sibling of Satellites: the spent stages and breakup fragments SATCAT
    # tracks alongside working payloads.
    CategorySpec(DEBRIS_SLUG, "Space Debris", "Q275450"),
    CategorySpec(PROBES_SLUG, "Probes", "Q26529"),  # "space probe"
    # Parent of the ft- feature-type pages; the QID the IAU descriptor terms
    # hang off (`?item wdt:P361 wd:Q1463003`).
    CategorySpec(SURFACE_FEATURES_SLUG, "Surface Features", "Q1463003"),
)

CATEGORY_BY_SLUG: dict[str, CategorySpec] = {c.slug: c for c in CATEGORIES}
