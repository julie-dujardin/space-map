"""Landform families: the eight buckets the 57 IAU descriptor codes group into.

Curated, not an IAU grouping — assigned from each term's definition in
:mod:`space_map_data.constants.nomenclature.feature_types`. A family is a
*naming* bucket for browsing 57 chips, not a geological claim; the axes mix
(process for impact/volcanic/tectonic/erosional, referent for
liquid/relief/albedo, origin for human).

Judgement calls worth knowing:

- ``erosional`` vs ``liquid``: the boundary is the term's referent, not
  whether liquid is present — ``erosional`` is what carved or piled up the
  land, ``liquid`` names a standing body. Flumen (a channel) vs Lacuna (a dry
  lake bed).
- ``MO`` Mons is defined as plain "Mountain"; most named montes are volcanic
  edifices (Olympus, Maat), but lunar Montes are impact-basin rims.
- ``RE`` Regio is defined twice over — "reflectivity or color distinctions" *or*
  "a broad geographic region". Venus regiones are highlands, Pluto's are albedo;
  it sits under relief because most named ones are terrain.
- ``LI`` Linea reads as an albedo term ("elongate marking"), but Europa's lineae
  — nearly all of them — are tectonic bands.
- ``LC``/``ME``/``SI``/``PA``/``OC`` are lunar basalt plains named as water
  bodies; they sit in ``liquid`` by that naming conceit, alongside Titan's actual
  hydrocarbon seas.
"""

from space_map_data.constants.nomenclature.feature_types import FEATURE_TYPES

# Ordered by formation narrative, not size — display keeps this order across
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
    "erosional": ("VA", "CB", "UN", "FM", "LA"),
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
