"""The Wikidata items of the rocket model bundles, by bundle slug.

A rocket is no Object, so nothing else ties its bundle to an item. Rockets
missing here have no item that names that vehicle, so they are not ranked.
"""

ROCKET_QIDS: dict[str, str] = {
    "angara-a5": "Q18694511",
    "ariane-1": "Q18375",
    "ariane-4": "Q18387",
    "ariane-5": "Q18532",
    "ariane-6": "Q15720682",
    "atlas-v": "Q23625",
    "black-arrow": "Q35307",
    "delta-ii": "Q49538",
    "delta-iv-heavy": "Q249492",
    "delta-iv-medium": "Q16354305",
    "epsilon": "Q1135682",
    "falcon-1": "Q648606",
    "falcon-9-block-5": "Q249091",
    "falcon-heavy": "Q1093627",
    "h-iia": "Q60599",
    "long-march-5": "Q787531",
    "lvm3": "Q1360911",
    "m-v": "Q1332896",
    "mercury-redstone": "Q2915676",
    "n1": "Q622762",
    "new-glenn": "Q26869616",
    "proton-m": "Q1756423",
    "pslv": "Q221654",
    "saturn-i": "Q521076",
    "saturn-ib": "Q719315",
    "saturn-v": "Q54363",
    "sls-block-1": "Q109943270",
    "soyuz-fg": "Q2415633",
    "space-shuttle": "Q48806",
    "starship": "Q62833385",
    "vega-c": "Q56010145",
    "vulcan-centaur": "Q19816744",
}
