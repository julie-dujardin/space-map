"""IAU 2-letter feature type codes → display names.

The KML ``type`` field ships as ``"singular, plural"`` (e.g. ``"Crater, craters"``)
for most codes, but a handful of types have no plural form (``"Albedo Feature"``,
``"Satellite Feature"``, ``"Statio"``, ...) — for those, plural mirrors singular.

Source: https://planetarynames.wr.usgs.gov/DescriptorTerms
"""

from typing import NamedTuple


class FeatureType(NamedTuple):
    singular: str
    plural: str  # == singular when the IAU listing has no plural form


FEATURE_TYPES: dict[str, FeatureType] = {
    "AA": FeatureType("Crater", "craters"),
    "AL": FeatureType("Albedo Feature", "Albedo Feature"),
    "AR": FeatureType("Arcus", "arcūs"),
    "CA": FeatureType("Catena", "catenae"),
    "CB": FeatureType("Cavus", "cavi"),
    "CH": FeatureType("Chaos", "chaoses"),
    "CL": FeatureType("Collum", "colli"),
    "CM": FeatureType("Chasma", "chasmata"),
    "CO": FeatureType("Collis", "colles"),
    "CR": FeatureType("Corona", "coronae"),
    "DO": FeatureType("Dorsum", "dorsa"),
    "ER": FeatureType("Eruptive center", "Eruptive center"),
    "FA": FeatureType("Facula", "faculae"),
    "FE": FeatureType("Flexus", "flexūs"),
    "FL": FeatureType("Fluctus", "fluctūs"),
    "FM": FeatureType("Flumen", "flumina"),
    "FO": FeatureType("Fossa", "fossae"),
    "FR": FeatureType("Farrum", "farra"),
    "FT": FeatureType("Fretum", "freta"),
    "IN": FeatureType("Insula", "insulae"),
    "LA": FeatureType("Labes", "labēs"),
    "LB": FeatureType("Labyrinthus", "labyrinthi"),
    "LC": FeatureType("Lacus", "lacūs"),
    "LF": FeatureType("Astronaut-named features", "Astronaut-named features"),
    "LG": FeatureType("Large ringed feature", "Large ringed feature"),
    "LI": FeatureType("Linea", "lineae"),
    "LN": FeatureType("Lingula", "lingulae"),
    "LO": FeatureType("Lobus", "lobi"),
    "LU": FeatureType("Lacuna", "lacunae"),
    "MA": FeatureType("Macula", "maculae"),
    "ME": FeatureType("Mare", "maria"),
    "MN": FeatureType("Mensa", "mensae"),
    "MO": FeatureType("Mons", "montes"),
    "OC": FeatureType("Oceanus", "oceani"),
    "PA": FeatureType("Palus", "paludes"),
    "PE": FeatureType("Patera", "paterae"),
    "PL": FeatureType("Planitia", "planitiae"),
    "PM": FeatureType("Planum", "plana"),
    "PR": FeatureType("Promontorium", "promontoria"),
    "PU": FeatureType("Plume", "plumes"),
    "RE": FeatureType("Regio", "regiones"),
    "RI": FeatureType("Rima", "rimae"),
    "RU": FeatureType("Rupes", "rupēs"),
    "SA": FeatureType("Saxum", "saxa"),
    "SC": FeatureType("Scopulus", "scopuli"),
    "SE": FeatureType("Serpens", "serpentes"),
    "SF": FeatureType("Satellite Feature", "Satellite Feature"),
    "SI": FeatureType("Sinus", "sinūs"),
    "ST": FeatureType("Statio", "Statio"),
    "SU": FeatureType("Sulcus", "sulci"),
    "TA": FeatureType("Terra", "terrae"),
    "TE": FeatureType("Tessera", "tesserae"),
    "TH": FeatureType("Tholus", "tholi"),
    "UN": FeatureType("Unda", "undae"),
    "VA": FeatureType("Vallis", "valles"),
    "VI": FeatureType("Virga", "virgae"),
    "VS": FeatureType("Vastitas", "vastitates"),
}
