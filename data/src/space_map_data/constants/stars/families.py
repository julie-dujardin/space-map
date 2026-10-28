"""Stellar families: their Wikidata topics and the rules that tag a star.

A star is in every family that its data supports. A published family comes
from a catalogued classification only: an MK spectral type, a SIMBAD object
type or the Metadata class. An estimated family uses at least one Gaia DR3
estimate: the spectral type tag of ESP-ELS, the FLAME evolutionary stage, the
DSC white-dwarf probability or the ESP-ELS emission-line class.

A family states the spectral letter of a star, its stage, both or neither. A
published family or MK value stops the Gaia estimate of what it states.

Every family is below one root family, stellar classification.

See docs/stellar-qids.md for the QID research.
"""

STAR_FAMILY_PAGES: dict[str, tuple[str, ...]] = {
    "a-type-main-sequence": ("Q471805",),
    "asymptotic-giant-branch": ("Q50089",),
    "b-type-main-sequence": ("Q767432",),
    "barium-star": ("Q808220",),
    "blue-giant": ("Q5855",),
    "blue-straggler": ("Q5848",),
    "blue-supergiant": ("Q1048372",),
    "bright-giant": ("Q5881",),
    "brown-dwarf": ("Q101600",),
    "carbon-star": ("Q130019",),
    "cepheid-variable": ("Q188593",),
    "classification": ("Q25377588",),
    "dwarf": ("Q244393",),
    "f-type-main-sequence": ("Q1353952",),
    "flare-star": ("Q285400",),
    "g-type-main-sequence": ("Q5864",),
    "giant": ("Q5875",),
    "herbig-ae-be": ("Q1044693",),
    "horizontal-branch": ("Q50076",),
    "hypergiant": ("Q231982",),
    "k-type-main-sequence": ("Q863936",),
    "l-dwarf": ("Q11878917",),
    "luminous-blue-variable": ("Q742741",),
    "magnetar": ("Q190426",),
    "main-sequence": ("Q3450",),
    "mira-variable": ("Q744691",),
    "neutron-star": ("Q4202",),
    "o-type-main-sequence": ("Q911809",),
    "pre-main-sequence": ("Q1062509",),
    "protostar": ("Q204903",),
    "pulsar": ("Q4360",),
    "red-dwarf": ("Q5893",),
    "red-giant": ("Q50081",),
    "red-supergiant": ("Q5898",),
    "rr-lyrae-variable": ("Q726242",),
    "s-type-star": ("Q1153392",),
    "subdwarf": ("Q6220",),
    "subdwarf-b": ("Q1207898",),
    "subdwarf-o": ("Q7631112",),
    "subgiant": ("Q6227",),
    "supergiant": ("Q193599",),
    "t-dwarf": ("Q11702990",),
    "t-tauri": ("Q6232",),
    "variable-star": ("Q6243",),
    "white-dwarf": ("Q5871",),
    "wolf-rayet": ("Q6251",),
    "y-dwarf": ("Q9283175",),
    "yellow-hypergiant": ("Q1196680",),
    "yellow-supergiant": ("Q1142197",),
}

# Bit n of a family mask is family n.
FAMILIES: tuple[str, ...] = tuple(STAR_FAMILY_PAGES)

# The /g/ page of a family is /g/star-<family>.
FAMILY_SLUG_PREFIX = "star-"
# The Sun is in none of the catalogues that the rules read.
SUN_SPECTRAL_TYPE = "G2V"
# The root of the family tree, stellar classification: a star with a family
# is in it.
ROOT_FAMILY = "classification"

LETTER, STAGE = 1, 2
# What a family states about a star. A family that is not here states neither.
STATES: dict[str, int] = {
    **dict.fromkeys(
        (
            "o-type-main-sequence",
            "b-type-main-sequence",
            "a-type-main-sequence",
            "f-type-main-sequence",
            "g-type-main-sequence",
            "k-type-main-sequence",
            "red-dwarf",
            "blue-giant",
            "red-giant",
            "blue-supergiant",
            "yellow-supergiant",
            "red-supergiant",
            "yellow-hypergiant",
            "white-dwarf",
            "brown-dwarf",
            "l-dwarf",
            "t-dwarf",
            "y-dwarf",
            "neutron-star",
            "pulsar",
            "magnetar",
            "wolf-rayet",
            "subdwarf-b",
            "subdwarf-o",
        ),
        LETTER | STAGE,
    ),
    **dict.fromkeys(("carbon-star", "s-type-star"), LETTER),
    **dict.fromkeys(
        (
            "main-sequence",
            "subgiant",
            "giant",
            "bright-giant",
            "supergiant",
            "hypergiant",
            "subdwarf",
            "dwarf",
            "horizontal-branch",
            "asymptotic-giant-branch",
            "blue-straggler",
            "pre-main-sequence",
            "protostar",
            "t-tauri",
            "herbig-ae-be",
            "cepheid-variable",
            "rr-lyrae-variable",
            "mira-variable",
            "luminous-blue-variable",
        ),
        STAGE,
    ),
}

# The families of each MK luminosity class, as the parser names it. The FLAME
# stages use the same names.
LUMINOSITY_CLASSES: dict[str, str] = {
    "0": "hypergiant",
    "Ia+": "hypergiant",
    "Ia0": "hypergiant",
    "Iab": "supergiant",
    "Ia": "supergiant",
    "Ib": "supergiant",
    "I": "supergiant",
    "II": "bright-giant",
    "III": "giant",
    "IV": "subgiant",
    "V": "main-sequence",
    "VI": "subdwarf",
    "VII": "white-dwarf",
}
# Old prefixes of the class: Mount Wilson's d, g and c, and the subdwarfs. The
# subdwarf prefix wins over a luminosity class: hot subdwarfs use VII and
# VIII for another scale.
PREFIX_STAGES: dict[str, str] = {
    "d": "main-sequence",
    "g": "giant",
    "c": "supergiant",
    "sd": "subdwarf",
    "esd": "subdwarf",
    "usd": "subdwarf",
}

# The families of a spectral letter with a stage.
LETTER_STAGE_FAMILIES: dict[tuple[str, str], tuple[str, ...]] = {
    ("O", "main-sequence"): ("o-type-main-sequence",),
    ("B", "main-sequence"): ("b-type-main-sequence",),
    ("A", "main-sequence"): ("a-type-main-sequence",),
    ("F", "main-sequence"): ("f-type-main-sequence",),
    ("G", "main-sequence"): ("g-type-main-sequence",),
    ("K", "main-sequence"): ("k-type-main-sequence",),
    ("M", "main-sequence"): ("red-dwarf",),
    ("O", "giant"): ("blue-giant",),
    ("B", "giant"): ("blue-giant",),
    ("O", "bright-giant"): ("blue-giant",),
    ("B", "bright-giant"): ("blue-giant",),
    ("K", "giant"): ("red-giant",),
    ("M", "giant"): ("red-giant",),
    ("K", "bright-giant"): ("red-giant",),
    ("M", "bright-giant"): ("red-giant",),
    ("O", "supergiant"): ("blue-supergiant",),
    ("B", "supergiant"): ("blue-supergiant",),
    ("F", "supergiant"): ("yellow-supergiant",),
    ("G", "supergiant"): ("yellow-supergiant",),
    ("K", "supergiant"): ("red-supergiant",),
    ("M", "supergiant"): ("red-supergiant",),
    ("F", "hypergiant"): ("yellow-hypergiant",),
    ("G", "hypergiant"): ("yellow-hypergiant",),
    ("O", "subdwarf"): ("subdwarf-o",),
    ("B", "subdwarf"): ("subdwarf-b",),
}
# The families of a spectral class without a stage. C, R and N are carbon
# stars; MS and SC lie between M, S and C.
LETTER_FAMILIES: dict[str, tuple[str, ...]] = {
    "D": ("white-dwarf",),
    "W": ("wolf-rayet",),
    "C": ("carbon-star",),
    "R": ("carbon-star",),
    "N": ("carbon-star",),
    "S": ("s-type-star",),
    "MS": ("s-type-star",),
    "SC": ("s-type-star",),
    "L": ("l-dwarf",),
    "T": ("t-dwarf",),
    "Y": ("y-dwarf",),
}

# Spectral types that are a word, by their start.
SPECTRAL_TYPE_WORDS: dict[str, tuple[str, ...]] = {
    "PSR": ("pulsar",),
    "Pulsar": ("pulsar",),
    "LBV": ("luminous-blue-variable",),
    "WD": ("white-dwarf",),
    "PG1159": ("white-dwarf",),
}
# Letters whose "Ba" index marks a barium star. In an Am star or a carbon
# star the index has another meaning.
BARIUM_LETTERS = frozenset("FGKM")

# SIMBAD object types (otypedef). SIMBAD's type tree does not follow these
# families, so each code is listed. Candidate types (`?`) give no family.
OTYPE_FAMILIES: dict[str, tuple[str, ...]] = {
    **dict.fromkeys(
        (
            "V*",
            "Ir*",
            "Er*",
            "Pu*",
            "Ro*",
            "LP*",
            "RV*",
            "RC*",
            "dS*",
            "bC*",
            "gD*",
            "a2*",
            "EB*",
            "El*",
            "BY*",
            "RS*",
            "CV*",
            "No*",
        ),
        ("variable-star",),
    ),
    "SX*": ("blue-straggler", "variable-star"),
    "RR*": ("rr-lyrae-variable",),
    "Ce*": ("cepheid-variable",),
    "cC*": ("cepheid-variable",),
    "WV*": ("cepheid-variable",),
    "Mi*": ("mira-variable",),
    "TT*": ("t-tauri", "variable-star"),
    "Or*": ("pre-main-sequence", "variable-star"),
    "Ae*": ("herbig-ae-be",),
    "Y*O": ("pre-main-sequence",),
    "MS*": ("main-sequence",),
    "BS*": ("blue-straggler",),
    "RG*": ("red-giant",),
    "HB*": ("horizontal-branch",),
    "AB*": ("asymptotic-giant-branch",),
    "C*": ("carbon-star",),
    "S*": ("s-type-star",),
    "WD*": ("white-dwarf",),
    "BD*": ("brown-dwarf",),
    "HS*": ("subdwarf",),
    "N*": ("neutron-star",),
    "Psr": ("pulsar",),
    "sg*": ("supergiant",),
    "s*r": ("red-supergiant",),
    "s*b": ("blue-supergiant",),
    "s*y": ("yellow-supergiant",),
    "WR*": ("wolf-rayet",),
}

# Metadata classes other than `star`.
CLASS_FAMILIES: dict[str, tuple[str, ...]] = {
    "white dwarf": ("white-dwarf",),
    "brown dwarf": ("brown-dwarf",),
    "pulsar": ("pulsar",),
}

# ESP-ELS emission-line classes. Be stars and planetary nebulae have no family.
ELS_FAMILIES: dict[str, tuple[str, ...]] = {
    "TTauri": ("t-tauri",),
    "HerbigStar": ("herbig-ae-be",),
    "RedDwarfEmStar": ("red-dwarf",),
    "wC": ("wolf-rayet",),
    "wN": ("wolf-rayet",),
}
SUBDWARF_PREFIXES = frozenset({"sd", "esd", "usd"})
# DSC-Combmod probability above which a star is an estimated white dwarf.
MIN_WHITE_DWARF_PROBABILITY = 0.5
# ESP-ELS spectral type tags, with the tag qualities (second digit of
# flags_esphs, 1 best to 5) that each needs. Against catalogued MK letters,
# quality 1 agrees for 72-96% of the stars and quality 5 for 33-53%; an O or
# B tag above quality 1 is often a white dwarf. 0 marks the carbon stars that
# the validation confirmed. O, B and A also need the OBA golden sample.
ESP_LETTERS: dict[str, tuple[str, frozenset[str]]] = {
    **{letter: (letter, frozenset("1")) for letter in "OB"},
    **{letter: (letter, frozenset("1234")) for letter in "AFGKM"},
    "CSTAR": ("C", frozenset("0")),
}
GOLDEN_LETTERS = frozenset("OBA")
# FLAME phase index on the BaSTI tracks: main sequence up to the end of the
# turn-off, then subgiant, then giant (Creevey et al. 2023, Sect. 4.4).
FLAME_STAGES: tuple[tuple[int, str], ...] = (
    (420, "main-sequence"),
    (490, "subgiant"),
    (10_000, "giant"),
)
FLAME_MIN_STAGE = 100
# Gaia trusts the mass of a FLAME giant only in this range (solar masses).
FLAME_GIANT_MASS = (1.0, 2.0)
# FLAME fits a star at the temperature of its run, so its stage holds for a
# star of these letters only from that temperature up (K). GSP-Phot often
# fits a hot star far too cool: a median of 8,700 K for the O-tagged stars.
FLAME_MIN_TEFF: dict[str, float] = {"O": 30_000, "B": 10_000}

# Each family adds these. The closure is transitive. A family without a parent
# here gets the root.
PARENTS: dict[str, tuple[str, ...]] = {
    **dict.fromkeys(
        (
            "o-type-main-sequence",
            "b-type-main-sequence",
            "a-type-main-sequence",
            "f-type-main-sequence",
            "g-type-main-sequence",
            "k-type-main-sequence",
            "red-dwarf",
        ),
        ("main-sequence",),
    ),
    **dict.fromkeys(
        ("main-sequence", "white-dwarf", "brown-dwarf", "subdwarf"), ("dwarf",)
    ),
    **dict.fromkeys(("red-giant", "blue-giant", "bright-giant"), ("giant",)),
    "subdwarf-b": ("subdwarf",),
    "subdwarf-o": ("subdwarf",),
    "t-dwarf": ("brown-dwarf",),
    "y-dwarf": ("brown-dwarf",),
    "red-supergiant": ("supergiant",),
    "blue-supergiant": ("supergiant",),
    "yellow-supergiant": ("supergiant",),
    "yellow-hypergiant": ("hypergiant",),
    "pulsar": ("neutron-star",),
    "magnetar": ("neutron-star",),
    "t-tauri": ("pre-main-sequence",),
    "herbig-ae-be": ("pre-main-sequence",),
    "rr-lyrae-variable": ("horizontal-branch", "variable-star"),
    "mira-variable": ("asymptotic-giant-branch", "variable-star"),
    "cepheid-variable": ("variable-star",),
    "flare-star": ("variable-star",),
    "luminous-blue-variable": ("variable-star",),
}
PARENTS |= {
    family: (ROOT_FAMILY,)
    for family in FAMILIES
    if family not in PARENTS and family != ROOT_FAMILY
}
