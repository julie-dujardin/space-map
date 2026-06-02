"""IAU 2-letter feature type codes → display names + descriptions.

The ``type`` field in the IAU KML ships as ``"singular, plural"`` (e.g.
``"Crater, craters"``) for most codes, but a handful have no plural form
(``"Albedo Feature"``, ``"Satellite Feature"``, ``"Statio"``, ...) — for those,
``plural`` mirrors ``singular``.

``description`` mirrors the ``edomvd`` text in each KMZ's
``metadata_nomenclature_points_*.xml``. Six codes (CL, FT, LO, LU, SA, ST) don't
appear in any KMZ metadata file (the KMZs were built before those types were
defined); their descriptions come from the same canonical source the metadata
cites: https://planetarynames.wr.usgs.gov/DescriptorTerms
"""

from typing import NamedTuple


class FeatureType(NamedTuple):
    singular: str
    plural: str  # == singular when the IAU listing has no plural form
    description: str


FEATURE_TYPES: dict[str, FeatureType] = {
    "AA": FeatureType("Crater", "craters", "A circular depression"),
    "AL": FeatureType(
        "Albedo Feature",
        "Albedo Feature",
        "Geographic area distinguished by amount of reflected light",
    ),
    "AR": FeatureType("Arcus", "arcūs", "Arc-shaped feature"),
    "CA": FeatureType("Catena", "catenae", "Chain of craters"),
    "CB": FeatureType(
        "Cavus",
        "cavi",
        "Hollows, irregular steep-sided depressions usually in arrays or clusters",
    ),
    "CH": FeatureType("Chaos", "chaoses", "Distinctive area of broken terrain"),
    "CL": FeatureType(
        "Collum",
        "colli",
        '"Neck"; the region connecting two lobes of a bilobed asteroid',
    ),
    "CM": FeatureType(
        "Chasma", "chasmata", "A deep, elongated, steep-sided depression"
    ),
    "CO": FeatureType("Collis", "colles", "Small hills or knobs"),
    "CR": FeatureType("Corona", "coronae", "Ovoid-shaped feature"),
    "DO": FeatureType("Dorsum", "dorsa", "Ridge"),
    "ER": FeatureType(
        "Eruptive center", "Eruptive center", "Active volcanic centers on Io"
    ),
    "FA": FeatureType("Facula", "faculae", "Bright spot"),
    "FE": FeatureType(
        "Flexus", "flexūs", "A very low curvilinear ridge with a scalloped pattern"
    ),
    "FL": FeatureType("Fluctus", "fluctūs", "Flow terrain"),
    "FM": FeatureType("Flumen", "flumina", "Channel on Titan that might carry liquid"),
    "FO": FeatureType("Fossa", "fossae", "Long, narrow depression"),
    "FR": FeatureType(
        "Farrum", "farra", "Pancake-like structure, or a row of such structures"
    ),
    "FT": FeatureType(
        "Fretum",
        "freta",
        "Strait, a narrow passage of liquid connecting two larger areas of liquid",
    ),
    "IN": FeatureType(
        "Insula",
        "insulae",
        "Island (islands), an isolated land area (or group of such areas) surrounded "
        "by, or nearly surrounded by, a liquid area (sea or lake).",
    ),
    "LA": FeatureType("Labes", "labēs", "Landslide"),
    "LB": FeatureType(
        "Labyrinthus", "labyrinthi", "Complex of intersecting valleys or ridges."
    ),
    "LC": FeatureType(
        "Lacus",
        "lacūs",
        '"Lake" or small plain; on Titan, a "lake" or small, dark plain with '
        "discrete, sharp boundaries",
    ),
    "LF": FeatureType(
        "Astronaut-named features",
        "Astronaut-named features",
        "Lunar features at or near Apollo landing sites",
    ),
    "LG": FeatureType(
        "Large ringed feature", "Large ringed feature", "Cryptic ringed features"
    ),
    "LI": FeatureType(
        "Linea",
        "lineae",
        "A dark or bright elongate marking, may be curved or straight",
    ),
    "LN": FeatureType(
        "Lingula",
        "lingulae",
        "Extension of plateau having rounded lobate or tongue-like boundaries",
    ),
    "LO": FeatureType("Lobus", "lobi", "One of two lobes of a contact binary asteroid"),
    "LU": FeatureType(
        "Lacuna",
        "lacunae",
        "Irregularly shaped depression on Titan having the appearance of a dry lake bed",
    ),
    "MA": FeatureType("Macula", "maculae", "Dark spot, may be irregular"),
    "ME": FeatureType(
        "Mare",
        "maria",
        '"Sea"; large circular plain; on Titan, large expanses of dark materials '
        "thought to be liquid hydrocarbons",
    ),
    "MN": FeatureType(
        "Mensa", "mensae", "A flat-topped prominence with cliff-like edges"
    ),
    "MO": FeatureType("Mons", "montes", "Mountain"),
    "OC": FeatureType("Oceanus", "oceani", "A very large dark area on the moon"),
    "PA": FeatureType("Palus", "paludes", '"Swamp"; small plain'),
    "PE": FeatureType(
        "Patera",
        "paterae",
        "An irregular crater, or a complex one with scalloped edges",
    ),
    "PL": FeatureType("Planitia", "planitiae", "Low plain"),
    "PM": FeatureType("Planum", "plana", "Plateau or high plain"),
    "PR": FeatureType("Promontorium", "promontoria", '"Cape"; headland promontoria'),
    "PU": FeatureType("Plume", "plumes", "Cryo-volcanic features on Triton"),
    "RE": FeatureType(
        "Regio",
        "regiones",
        "A large area marked by reflectivity or color distinctions from adjacent "
        "areas, or a broad geographic region",
    ),
    "RI": FeatureType("Rima", "rimae", "Fissure"),
    "RU": FeatureType("Rupes", "rupēs", "Scarp"),
    "SA": FeatureType("Saxum", "saxa", "Boulder or rock"),
    "SC": FeatureType("Scopulus", "scopuli", "Lobate or irregular scarp"),
    "SE": FeatureType(
        "Serpens",
        "serpentes",
        "Sinuous feature with segments of positive and negative relief along its length",
    ),
    "SF": FeatureType(
        "Satellite Feature",
        "Satellite Feature",
        "A feature that shares the name of an associated feature. For example, on "
        'the Moon the craters referred to as "Lettered Craters" are classified in '
        'the gazetteer as "Satellite Features."',
    ),
    "SI": FeatureType("Sinus", "sinūs", '"Bay"; small plain'),
    "ST": FeatureType("Statio", "Statio", "Spacecraft landing site"),
    "SU": FeatureType("Sulcus", "sulci", "Subparallel furrows and ridges"),
    "TA": FeatureType("Terra", "terrae", "Extensive land mass"),
    "TE": FeatureType("Tessera", "tesserae", "Tile-like, polygonal terrain"),
    "TH": FeatureType("Tholus", "tholi", "Small domical mountain or hill"),
    "UN": FeatureType("Unda", "undae", "Dunes"),
    "VA": FeatureType("Vallis", "valles", "Valley"),
    "VI": FeatureType("Virga", "virgae", "A streak or stripe of color"),
    "VS": FeatureType("Vastitas", "vastitates", "Extensive plain"),
}
