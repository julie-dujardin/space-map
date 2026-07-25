"""IAU 2-letter feature type codes → display names, descriptions + Wikidata QIDs.

The ``type`` field in the IAU KML ships as ``"singular, plural"`` (e.g.
``"Crater, craters"``) for most codes, but a handful have no plural form
(``"Albedo Feature"``, ``"Satellite Feature"``, ``"Statio"``, ...) — for those,
``plural`` mirrors ``singular``.

``description`` mirrors the ``edomvd`` text in each KMZ's
``metadata_nomenclature_points_*.xml``. Six codes (CL, FT, LO, LU, SA, ST) don't
appear in any KMZ metadata file (the KMZs were built before those types were
defined); their descriptions come from the same canonical source the metadata
cites: https://planetarynames.wr.usgs.gov/DescriptorTerms

``qid`` is the Wikidata QID used to localize the nomenclature popover (label +
description) in the frontend. Sourced via SPARQL ``?item wdt:P361 wd:Q1463003``
(planetary nomenclature). Four codes (CL, LF, LO, ST) have no matching Wikidata
entry — those keep their English-only constants in the frontend.
"""

import re
from typing import NamedTuple


class FeatureType(NamedTuple):
    singular: str
    plural: str  # == singular when the IAU listing has no plural form
    description: str
    qid: str | None  # Wikidata QID, or None when no encyclopedic entry exists


FEATURE_TYPES: dict[str, FeatureType] = {
    "AA": FeatureType("Crater", "craters", "A circular depression", "Q55818"),
    "AL": FeatureType(
        "Albedo Feature",
        "Albedo Feature",
        "Geographic area distinguished by amount of reflected light",
        "Q1051581",
    ),
    "AR": FeatureType("Arcus", "arcūs", "Arc-shaped feature", "Q20743937"),
    "CA": FeatureType("Catena", "catenae", "Chain of craters", "Q498794"),
    "CB": FeatureType(
        "Cavus",
        "cavi",
        "Hollows, irregular steep-sided depressions usually in arrays or clusters",
        "Q358877",
    ),
    "CH": FeatureType(
        "Chaos", "chaoses", "Distinctive area of broken terrain", "Q2419662"
    ),
    "CL": FeatureType(
        "Collum",
        "colli",
        '"Neck"; the region connecting two lobes of a bilobed asteroid',
        None,
    ),
    "CM": FeatureType(
        "Chasma", "chasmata", "A deep, elongated, steep-sided depression", "Q1068071"
    ),
    "CO": FeatureType("Collis", "colles", "Small hills or knobs", "Q2983016"),
    "CR": FeatureType("Corona", "coronae", "Ovoid-shaped feature", "Q1134503"),
    "DO": FeatureType("Dorsum", "dorsa", "Ridge", "Q667575"),
    "ER": FeatureType(
        "Eruptive center",
        "Eruptive center",
        "Active volcanic centers on Io",
        "Q20743938",
    ),
    "FA": FeatureType("Facula", "faculae", "Bright spot", "Q128952"),
    "FE": FeatureType(
        "Flexus",
        "flexūs",
        "A very low curvilinear ridge with a scalloped pattern",
        "Q3746596",
    ),
    "FL": FeatureType("Fluctus", "fluctūs", "Flow terrain", "Q1058792"),
    "FM": FeatureType(
        "Flumen", "flumina", "Channel on Titan that might carry liquid", "Q3074486"
    ),
    "FO": FeatureType("Fossa", "fossae", "Long, narrow depression", "Q1439394"),
    "FR": FeatureType(
        "Farrum",
        "farra",
        "Pancake-like structure, or a row of such structures",
        "Q526644",
    ),
    "FT": FeatureType(
        "Fretum",
        "freta",
        "Strait, a narrow passage of liquid connecting two larger areas of liquid",
        "Q20743940",
    ),
    "IN": FeatureType(
        "Insula",
        "insulae",
        "Island (islands), an isolated land area (or group of such areas) surrounded "
        "by, or nearly surrounded by, a liquid area (sea or lake).",
        "Q2402047",
    ),
    "LA": FeatureType("Labes", "labēs", "Landslide", "Q3214330"),
    "LB": FeatureType(
        "Labyrinthus",
        "labyrinthi",
        "Complex of intersecting valleys or ridges.",
        "Q3214576",
    ),
    "LC": FeatureType(
        "Lacus",
        "lacūs",
        '"Lake" or small plain; on Titan, a "lake" or small, dark plain with '
        "discrete, sharp boundaries",
        "Q3215913",
    ),
    "LF": FeatureType(
        "Astronaut-named features",
        "Astronaut-named features",
        "Lunar features at or near Apollo landing sites",
        None,
    ),
    "LG": FeatureType(
        "Large ringed feature",
        "Large ringed feature",
        "Cryptic ringed features",
        "Q3077423",
    ),
    "LI": FeatureType(
        "Linea",
        "lineae",
        "A dark or bright elongate marking, may be curved or straight",
        "Q3832650",
    ),
    "LN": FeatureType(
        "Lingula",
        "lingulae",
        "Extension of plateau having rounded lobate or tongue-like boundaries",
        "Q512573",
    ),
    "LO": FeatureType(
        "Lobus", "lobi", "One of two lobes of a contact binary asteroid", None
    ),
    "LU": FeatureType(
        "Lacuna",
        "lacunae",
        "Irregularly shaped depression on Titan having the appearance of a dry lake bed",
        "Q20743942",
    ),
    "MA": FeatureType("Macula", "maculae", "Dark spot, may be irregular", "Q1413444"),
    "ME": FeatureType(
        "Mare",
        "maria",
        '"Sea"; large circular plain; on Titan, large expanses of dark materials '
        "thought to be liquid hydrocarbons",
        "Q3290341",  # generic; Q180874 is Moon-only
    ),
    "MN": FeatureType(
        "Mensa", "mensae", "A flat-topped prominence with cliff-like edges", "Q3306046"
    ),
    "MO": FeatureType("Mons", "montes", "Mountain", "Q429088"),
    "OC": FeatureType(
        "Oceanus", "oceani", "A very large dark area on the moon", "Q3880745"
    ),
    "PA": FeatureType("Palus", "paludes", '"Swamp"; small plain', "Q948516"),
    "PE": FeatureType(
        "Patera",
        "paterae",
        "An irregular crater, or a complex one with scalloped edges",
        "Q5259261",
    ),
    "PL": FeatureType("Planitia", "planitiae", "Low plain", "Q3391469"),
    "PM": FeatureType("Planum", "plana", "Plateau or high plain", "Q7708397"),
    "PR": FeatureType(
        "Promontorium", "promontoria", '"Cape"; headland promontoria', "Q3922925"
    ),
    "PU": FeatureType(
        "Plume", "plumes", "Cryo-volcanic features on Triton", "Q3906785"
    ),
    "RE": FeatureType(
        "Regio",
        "regiones",
        "A large area marked by reflectivity or color distinctions from adjacent "
        "areas, or a broad geographic region",
        "Q3423535",
    ),
    "RI": FeatureType("Rima", "rimae", "Fissure", "Q1432092"),
    "RU": FeatureType("Rupes", "rupēs", "Scarp", "Q2066176"),
    "SA": FeatureType("Saxum", "saxa", "Boulder or rock", "Q64744256"),
    "SC": FeatureType("Scopulus", "scopuli", "Lobate or irregular scarp", "Q3476035"),
    "SE": FeatureType(
        "Serpens",
        "serpentes",
        "Sinuous feature with segments of positive and negative relief along its length",
        "Q20743944",
    ),
    "SF": FeatureType(
        "Satellite Feature",
        "Satellite Feature",
        "A feature that shares the name of an associated feature. For example, on "
        'the Moon the craters referred to as "Lettered Craters" are classified in '
        'the gazetteer as "Satellite Features."',
        "Q20743939",
    ),
    "SI": FeatureType("Sinus", "sinūs", '"Bay"; small plain', "Q3961951"),
    "ST": FeatureType("Statio", "Statio", "Spacecraft landing site", None),
    "SU": FeatureType("Sulcus", "sulci", "Subparallel furrows and ridges", "Q96406679"),
    "TA": FeatureType("Terra", "terrae", "Extensive land mass", "Q3518514"),
    "TE": FeatureType(
        "Tessera", "tesserae", "Tile-like, polygonal terrain", "Q3519009"
    ),
    "TH": FeatureType("Tholus", "tholi", "Small domical mountain or hill", "Q956300"),
    "UN": FeatureType("Unda", "undae", "Dunes", "Q20743921"),
    "VA": FeatureType("Vallis", "valles", "Valley", "Q2249285"),
    "VI": FeatureType("Virga", "virgae", "A streak or stripe of color", "Q20743945"),
    "VS": FeatureType("Vastitas", "vastitates", "Extensive plain", "Q3555010"),
}


FEATURE_TYPE_SLUG_PREFIX = "ft-"


def _slugify(singular: str) -> str:
    """Kebab-case a singular type name ("Albedo Feature" → "albedo-feature")."""
    return re.sub(r"[^a-z0-9]+", "-", singular.lower()).strip("-")


# Readable over code-based ("ft-crater", not "ft-AA") — these slugs are URLs.
FEATURE_TYPE_SLUGS: dict[str, str] = {
    code: f"{FEATURE_TYPE_SLUG_PREFIX}{_slugify(ft.singular)}"
    for code, ft in FEATURE_TYPES.items()
}
FEATURE_TYPE_CODE_BY_SLUG: dict[str, str] = {
    slug: code for code, slug in FEATURE_TYPE_SLUGS.items()
}

assert len(FEATURE_TYPE_CODE_BY_SLUG) == len(FEATURE_TYPE_SLUGS), (
    "Duplicate feature-type slug"
)
