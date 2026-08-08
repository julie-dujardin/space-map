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
STRUCTURE_ACTIVITY_SLUG = f"{CATEGORY_SLUG_PREFIX}structure-activity"
ATMOSPHERES_SLUG = f"{CATEGORY_SLUG_PREFIX}atmospheres"
OCEANS_SLUG = f"{CATEGORY_SLUG_PREFIX}oceans"
VOLCANISM_SLUG = f"{CATEGORY_SLUG_PREFIX}volcanism"
TECTONICS_SLUG = f"{CATEGORY_SLUG_PREFIX}tectonics"
MAGNETIC_FIELDS_SLUG = f"{CATEGORY_SLUG_PREFIX}magnetic-fields"
TIDAL_HEATING_SLUG = f"{CATEGORY_SLUG_PREFIX}tidal-heating"

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
    # The third axis of the browse tree. Planets/Moons/Comets say what a body
    # is and Surface Features what it has; these say what it is made of and
    # what it is still doing. Members are bodies carrying a property rather
    # than bodies of a kind, so a moon appears under both.
    CategorySpec(STRUCTURE_ACTIVITY_SLUG, "Structure & Activity", "Q104499"),
    # "atmosphere" rather than "extraterrestrial atmosphere" (Q5422261): the
    # precise term has articles in five of the twelve locales, the generic one
    # in all twelve, and this page is not about Earth's.
    CategorySpec(ATMOSPHERES_SLUG, "Atmospheres", "Q8104"),
    # "Extraterrestrial liquid water" — a topic article in six of the twelve
    # locales, and the only candidate whose subject is the water itself. The two
    # obvious alternatives both put wrong prose in the header, which takes the
    # Wikidata description ahead of any Wikipedia lede: "ocean world"
    # (Q1045138) covers 11 locales but 9 of them open on a hypothetical
    # water-covered exoplanet, and "List of ocean worlds in the Solar System"
    # (Q139377044) is a Wikimedia list item, so every locale reads "Wikimedia
    # list article" over Europa and Enceladus.
    CategorySpec(OCEANS_SLUG, "Oceans", "Q1319471"),
    # One page per mechanism, because the two are not the same size: volcanism
    # is on fifteen bodies with five fields, tectonics on ten with two. Sharing
    # a page made tectonics a suffix on volcanism's rows.
    CategorySpec(VOLCANISM_SLUG, "Volcanism", "Q505748"),
    # "Tectonics" (Q193343) has articles in only four of the twelve locales, and
    # is still the right item: its lede is the one that says "the field of
    # planetary tectonics extends the concept to other planets and moons". The
    # better-covered "tectonics" (Q78125729, ten locales) is a trap — its
    # English sitelink is *Plate tectonics theory*, and Earth is the only body
    # on this page with plate tectonics.
    CategorySpec(TECTONICS_SLUG, "Tectonics", "Q193343"),
    # "magnetosphere" over "planetary magnetic field" (Q4274059): the precise
    # term has articles in French and Russian only, this one in all twelve, and
    # what the page lists is bodies whose field is detectable from outside.
    CategorySpec(MAGNETIC_FIELDS_SLUG, "Magnetic Fields", "Q6915"),
    CategorySpec(TIDAL_HEATING_SLUG, "Tidal Heating", "Q7800788"),
)

CATEGORY_BY_SLUG: dict[str, CategorySpec] = {c.slug: c for c in CATEGORIES}
