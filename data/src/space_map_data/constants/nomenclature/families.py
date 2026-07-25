"""Landform families: the eight formation origins the 57 IAU descriptor codes group into.

The IAU gazetteer has no such grouping — descriptor terms are a flat list — so
this is curated, assigned from each term's own definition in
:mod:`space_map_data.constants.nomenclature.feature_types`. It exists to make 57
chips browsable; a family is a *naming* bucket, not a geological claim about any
individual feature.

Judgement calls worth knowing:

- ``MO`` Mons is defined as plain "Mountain"; most named montes are volcanic
  edifices (Olympus, Maat), but lunar Montes are impact-basin rims.
- ``RE`` Regio is defined twice over — "reflectivity or color distinctions" *or*
  "a broad geographic region". Venus regiones are highlands, Pluto's are albedo;
  it sits under relief because most named ones are terrain.
- ``LI`` Linea reads as an albedo term ("elongate marking"), but Europa's lineae
  — nearly all of them — are tectonic bands.
- ``LC``/``ME``/``SI``/``PA``/``OC`` are lunar basalt plains named as water
  bodies; they group by that naming conceit, alongside Titan's actual lakes.
"""

from space_map_data.constants.nomenclature.feature_types import FEATURE_TYPES

# Ordered by formation narrative (impact → volcanic → tectonic → erosional →
# …), not by size: the display keeps this order so the list reads the same on
# every body's gazetteer.
FEATURE_FAMILY_CODES: dict[str, tuple[str, ...]] = {
    "impact": ("AA", "SF", "CA", "LG"),
    "volcanic": ("MO", "CR", "PE", "TH", "FL", "ER", "PU", "FR"),
    "tectonic": (
        "DO",
        "RU",
        "FO",
        "CM",
        "RI",
        "SU",
        "LI",
        "TE",
        "LB",
        "SC",
        "SE",
        "FE",
        "AR",
    ),
    "fluvial": ("VA", "CB", "UN", "FM", "LA"),
    "liquid": ("LC", "SI", "ME", "LU", "IN", "PA", "FT", "OC"),
    "relief": (
        "PL",
        "RE",
        "PM",
        "MN",
        "CO",
        "CH",
        "SA",
        "TA",
        "PR",
        "LN",
        "LO",
        "CL",
        "VS",
    ),
    "albedo": ("AL", "FA", "MA", "VI"),
    "human": ("LF", "ST"),
}

FAMILY_BY_CODE: dict[str, str] = {
    code: family for family, codes in FEATURE_FAMILY_CODES.items() for code in codes
}

assert len(FAMILY_BY_CODE) == len(FEATURE_TYPES), "A code is in two families"
assert set(FAMILY_BY_CODE) == set(FEATURE_TYPES), (
    f"Family coverage mismatch: {set(FEATURE_TYPES) ^ set(FAMILY_BY_CODE)}"
)
