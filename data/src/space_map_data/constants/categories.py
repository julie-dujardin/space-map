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
    # "planetary ring" over "ring system" (Q28951811): the former has an
    # article in all twelve locales; the latter's Korean sitelink is about a
    # single exoplanet candidate.
    CategorySpec(RING_SYSTEMS_SLUG, "Ring Systems", "Q179792"),
    CategorySpec(ASTEROIDS_SLUG, "Asteroids", "Q3863"),
    CategorySpec(COMETS_SLUG, "Comets", "Q3559"),
    CategorySpec(SATELLITES_SLUG, "Satellites", "Q26540"),
    # Sibling of Satellites: spent stages and breakup fragments SATCAT tracks
    # alongside working payloads.
    CategorySpec(DEBRIS_SLUG, "Space Debris", "Q275450"),
    CategorySpec(PROBES_SLUG, "Probes", "Q26529"),  # "space probe"
    # Parent of the ft- feature-type pages; the QID the IAU descriptor terms
    # hang off (`?item wdt:P361 wd:Q1463003`).
    CategorySpec(SURFACE_FEATURES_SLUG, "Surface Features", "Q1463003"),
    # Third axis of the browse tree: what a body is made of and still doing,
    # vs. what it is (Planets/Moons/Comets) or has (Surface Features).
    # Members carry a property rather than belong to a kind, so a moon can
    # appear under both.
    CategorySpec(STRUCTURE_ACTIVITY_SLUG, "Structure & Activity", "Q104499"),
    # "atmosphere" over "extraterrestrial atmosphere" (Q5422261): the precise
    # term covers five of twelve locales, the generic one all twelve, and
    # this page isn't about Earth's.
    CategorySpec(ATMOSPHERES_SLUG, "Atmospheres", "Q8104"),
    # "Extraterrestrial liquid water" — the only candidate whose subject is
    # the water itself, in six of twelve locales. Alternatives are worse:
    # "ocean world" (Q1045138, 11 locales) mostly opens on a hypothetical
    # exoplanet; "List of ocean worlds..." (Q139377044) is a Wikimedia list
    # item, so every locale would read "Wikimedia list article".
    CategorySpec(OCEANS_SLUG, "Oceans", "Q1319471"),
    # One page per mechanism — volcanism (fifteen bodies, five fields) and
    # tectonics (ten bodies, two) aren't the same size; sharing a page made
    # tectonics a suffix on volcanism's rows.
    CategorySpec(VOLCANISM_SLUG, "Volcanism", "Q505748"),
    # "Tectonics" (Q193343, four locales) is still right: its lede says "the
    # field of planetary tectonics extends the concept to other planets and
    # moons". The better-covered "tectonics" (Q78125729, ten locales) is a
    # trap — its English sitelink is *Plate tectonics theory*, and Earth is
    # the only body here with plate tectonics.
    CategorySpec(TECTONICS_SLUG, "Tectonics", "Q193343"),
    # "magnetosphere" over "planetary magnetic field" (Q4274059): the precise
    # term covers French and Russian only, this one all twelve, and the page
    # lists bodies whose field is detectable from outside.
    CategorySpec(MAGNETIC_FIELDS_SLUG, "Magnetic Fields", "Q6915"),
    CategorySpec(TIDAL_HEATING_SLUG, "Tidal Heating", "Q7800788"),
)

CATEGORY_BY_SLUG: dict[str, CategorySpec] = {c.slug: c for c in CATEGORIES}
