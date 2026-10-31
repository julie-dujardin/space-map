"""Constellation topic QIDs grouped by sky culture.

See docs/stellar-qids.md for lookup scope and sources.
"""

SKY_CONSTELLATION_SLUG_PREFIX = "sky-"

MODERN_IAU_CONSTELLATIONS: dict[str, tuple[str, ...]] = {
    "andromeda": ("Q9256",),
    "antlia": ("Q10481",),
    "apus": ("Q10506",),
    "aquarius": ("Q10576",),
    "aquila": ("Q10586",),
    "ara": ("Q9253",),
    "aries": ("Q10584",),
    "auriga": ("Q10476",),
    "bootes": ("Q8667",),
    "caelum": ("Q10488",),
    "camelopardalis": ("Q8832",),
    "cancer": ("Q8849",),
    "canes-venatici": ("Q10452",),
    "canis-major": ("Q10538",),
    "canis-minor": ("Q9305",),
    "capricornus": ("Q10535",),
    "carina": ("Q10470",),
    "cassiopeia": ("Q10464",),
    "centaurus": ("Q8844",),
    "cepheus": ("Q10468",),
    "cetus": ("Q8839",),
    "chamaeleon": ("Q10457",),
    "circinus": ("Q10508",),
    "columba": ("Q10425",),
    "coma-berenices": ("Q9285",),
    "corona-australis": ("Q10413",),
    "corona-borealis": ("Q10406",),
    "corvus": ("Q10517",),
    "crater": ("Q9282",),
    "crux": ("Q10542",),
    "cygnus": ("Q8921",),
    "delphinus": ("Q9302",),
    "dorado": ("Q8837",),
    "draco": ("Q8675",),
    "equuleus": ("Q10438",),
    "eridanus": ("Q10433",),
    "fornax": ("Q8913",),
    "gemini": ("Q8923",),
    "grus": ("Q10563",),
    "hercules": ("Q10448",),
    "horologium": ("Q10574",),
    "hydra": ("Q10578",),
    "hydrus": ("Q10416",),
    "indus": ("Q10450",),
    "lacerta": ("Q10430",),
    "leo": ("Q8853",),
    "leo-minor": ("Q10403",),
    "lepus": ("Q10446",),
    "libra": ("Q10580",),
    "lupus": ("Q10571",),
    "lynx": ("Q10443",),
    "lyra": ("Q10484",),
    "mensa": ("Q9289",),
    "microscopium": ("Q10492",),
    "monoceros": ("Q10428",),
    "musca": ("Q10435",),
    "norma": ("Q10582",),
    "octans": ("Q10503",),
    "ophiuchus": ("Q8906",),
    "orion": ("Q8860",),
    "pavo": ("Q10515",),
    "pegasus": ("Q8864",),
    "perseus": ("Q10511",),
    "phoenix": ("Q10441",),
    "pictor": ("Q10486",),
    "pisces": ("Q8679",),
    "piscis-austrinus": ("Q10409",),
    "puppis": ("Q9251",),
    "pyxis": ("Q10473",),
    "reticulum": ("Q10498",),
    "sagitta": ("Q10513",),
    "sagittarius": ("Q8866",),
    "scorpius": ("Q8865",),
    "sculptor": ("Q9286",),
    "scutum": ("Q10529",),
    "serpens": ("Q8910",),
    "sextans": ("Q10525",),
    "taurus": ("Q10570",),
    "telescopium": ("Q10546",),
    "triangulum": ("Q10565",),
    "triangulum-australe": ("Q10422",),
    "tucana": ("Q10567",),
    "ursa-major": ("Q8918",),
    "ursa-minor": ("Q10478",),
    "vela": ("Q10521",),
    "virgo": ("Q8842",),
    "volans": ("Q10437",),
    "vulpecula": ("Q10519",),
}

# Wikidata's Polish labels are article titles ("Gwiazdozbiór Oriona").
POLISH_CONSTELLATION_NAMES: dict[str, str] = {
    "andromeda": "Andromeda",
    "antlia": "Pompa",
    "apus": "Ptak Rajski",
    "aquarius": "Wodnik",
    "aquila": "Orzeł",
    "ara": "Ołtarz",
    "aries": "Baran",
    "auriga": "Woźnica",
    "bootes": "Wolarz",
    "caelum": "Rylec",
    "camelopardalis": "Żyrafa",
    "cancer": "Rak",
    "canes-venatici": "Psy Gończe",
    "canis-major": "Wielki Pies",
    "canis-minor": "Mały Pies",
    "capricornus": "Koziorożec",
    "carina": "Kil",
    "cassiopeia": "Kasjopeja",
    "centaurus": "Centaur",
    "cepheus": "Cefeusz",
    "cetus": "Wieloryb",
    "chamaeleon": "Kameleon",
    "circinus": "Cyrkiel",
    "columba": "Gołąb",
    "coma-berenices": "Warkocz Bereniki",
    "corona-australis": "Korona Południowa",
    "corona-borealis": "Korona Północna",
    "corvus": "Kruk",
    "crater": "Puchar",
    "crux": "Krzyż Południa",
    "cygnus": "Łabędź",
    "delphinus": "Delfin",
    "dorado": "Złota Ryba",
    "draco": "Smok",
    "equuleus": "Źrebię",
    "eridanus": "Erydan",
    "fornax": "Piec",
    "gemini": "Bliźnięta",
    "grus": "Żuraw",
    "hercules": "Herkules",
    "horologium": "Zegar",
    "hydra": "Hydra",
    "hydrus": "Wąż Wodny",
    "indus": "Indianin",
    "lacerta": "Jaszczurka",
    "leo": "Lew",
    "leo-minor": "Mały Lew",
    "lepus": "Zając",
    "libra": "Waga",
    "lupus": "Wilk",
    "lynx": "Ryś",
    "lyra": "Lutnia",
    "mensa": "Góra Stołowa",
    "microscopium": "Mikroskop",
    "monoceros": "Jednorożec",
    "musca": "Mucha",
    "norma": "Węgielnica",
    "octans": "Oktant",
    "ophiuchus": "Wężownik",
    "orion": "Orion",
    "pavo": "Paw",
    "pegasus": "Pegaz",
    "perseus": "Perseusz",
    "phoenix": "Feniks",
    "pictor": "Malarz",
    "pisces": "Ryby",
    "piscis-austrinus": "Ryba Południowa",
    "puppis": "Rufa",
    "pyxis": "Kompas",
    "reticulum": "Sieć",
    "sagitta": "Strzała",
    "sagittarius": "Strzelec",
    "scorpius": "Skorpion",
    "sculptor": "Rzeźbiarz",
    "scutum": "Tarcza",
    "serpens": "Wąż",
    "sextans": "Sekstant",
    "taurus": "Byk",
    "telescopium": "Luneta",
    "triangulum": "Trójkąt",
    "triangulum-australe": "Trójkąt Południowy",
    "tucana": "Tukan",
    "ursa-major": "Wielka Niedźwiedzica",
    "ursa-minor": "Mała Niedźwiedzica",
    "vela": "Żagiel",
    "virgo": "Panna",
    "volans": "Ryba Latająca",
    "vulpecula": "Lis",
}

WESTERN_HISTORICAL_CONSTELLATIONS: dict[str, tuple[str, ...]] = {
    "antinous": ("Q579051",),
    "argo-navis": ("Q9258",),
    "cerberus": ("Q2321626",),
    "musca-borealis": ("Q1939728",),
    "quadrans-muralis": ("Q10495",),
}

CHINESE_CONSTELLATIONS: dict[str, tuple[str, ...]] = {
    "azure-dragon": ("Q515882",),
    "black-tortoise": ("Q125696",),
    "bond": ("Q1145504",),
    "chariot": ("Q1145810",),
    "dipper": ("Q1146722",),
    "emptiness": ("Q1145921",),
    "encampment": ("Q1145451",),
    "extended-net": ("Q1145915",),
    "ghost": ("Q1145465",),
    "girl": ("Q1145803",),
    "hairy-head": ("Q1141299",),
    "heart": ("Q1145909",),
    "horn": ("Q1192463",),
    "legs": ("Q1193839",),
    "neck": ("Q1145927",),
    "net": ("Q1192490",),
    "ox": ("Q1143106",),
    "roof": ("Q1145896",),
    "room": ("Q1145870",),
    "root": ("Q1145795",),
    "star": ("Q1193154",),
    "stomach": ("Q210912",),
    "tail": ("Q1145842",),
    "three-stars": ("Q1192788",),
    "turtle-beak": ("Q1145890",),
    "wall": ("Q1145933",),
    "well": ("Q1145878",),
    "white-tiger": ("Q1072455",),
    "willow": ("Q1145830",),
    "wings": ("Q1145474",),
    "winnowing-basket": ("Q1145781",),
    "zhuque": ("Q1059392",),
}

INDIAN_NAKSHATRA_CONSTELLATIONS: dict[str, tuple[str, ...]] = {
    "anuradha": ("Q2606414",),
    "ardra": ("Q3241450",),
    "ashlesha": ("Q3243419",),
    "ashvini": ("Q3352459",),
    "bharani": ("Q3506449",),
    "chitra": ("Q12426514",),
    "dhanishta": ("Q3502768",),
    "hasta": ("Q3631388",),
    "jyeshtha": ("Q672611",),
    "krittika": ("Q3241440",),
    "magha": ("Q3237861",),
    "mrigashirsha": ("Q3241444",),
    "mula": ("Q3506604",),
    "punarvasu": ("Q3238296",),
    "purva-ashadha": ("Q3631660",),
    "purva-bhadrapada": ("Q3502790",),
    "purva-phalguni": ("Q3237942",),
    "pushya": ("Q3243444",),
    "revati": ("Q3502799",),
    "rohini": ("Q3238710",),
    "shatabhisha": ("Q3502820",),
    "shravana": ("Q3502756",),
    "svati": ("Q3502809",),
    "uttara-ashadha": ("Q3631795",),
    "uttara-bhadrapada": ("Q3502777",),
    "uttara-phalguni": ("Q3237932",),
    "vishakha": ("Q3631799",),
}

CONSTELLATION_PAGES: dict[str, dict[str, tuple[str, ...]]] = {
    "chinese": CHINESE_CONSTELLATIONS,
    "indian-nakshatras": INDIAN_NAKSHATRA_CONSTELLATIONS,
    "modern-iau": MODERN_IAU_CONSTELLATIONS,
    "western-historical": WESTERN_HISTORICAL_CONSTELLATIONS,
}

# Each mansion: its number, and its figure number in `CHINESE_NUMBERED`.
CHINESE_MANSIONS: dict[str, tuple[int, int]] = {
    "horn": (1, 9),
    "neck": (2, 11),
    "root": (3, 4),
    "room": (4, 6),
    "heart": (5, 26),
    "tail": (6, 24),
    "winnowing-basket": (7, 8),
    "dipper": (8, 5),
    "ox": (9, 16),
    "girl": (10, 17),
    "emptiness": (11, 28),
    "roof": (12, 23),
    "encampment": (13, 18),
    "wall": (14, 2),
    "legs": (15, 12),
    "bond": (16, 14),
    "stomach": (17, 25),
    "hairy-head": (18, 15),
    "net": (19, 1),
    "turtle-beak": (20, 34),
    "three-stars": (21, 3),
    "well": (22, 10),
    "ghost": (23, 7),
    "willow": (24, 13),
    "star": (25, 27),
    "extended-net": (26, 30),
    "wings": (27, 29),
    "chariot": (28, 31),
}
# Figure IDs "CON <key> 001", "AST <key> 001".
CHINESE_NUMBERED = {
    "chinese": "CON",
    "chinese_manchu": "AST",
    "modern_chinese": "AST",
}
# Figure ID "CON <key> 01A": the mansion's number. An edition can name it its
# own way (Southern Dipper for Dipper), so the number decides, not the name.
CHINESE_CHART_EDITIONS = (
    "chinese_chenzhuo",
    "chinese_song_dynasty",
    "chinese_xianglin",
    "chinese_yuan_dynasty",
    "japanese",
    "korean",
)

# Each nakshatra: its figure ID in `indian`, and its number in `indian_nakshatras`.
NAKSHATRA_FIGURES: dict[str, tuple[str, int]] = {
    "ashvini": ("Aśv", 1),
    "bharani": ("Bhar", 2),
    "krittika": ("Kṛt", 3),
    "rohini": ("Roh", 4),
    "mrigashirsha": ("Mṛg", 5),
    "ardra": ("Ārd", 6),
    "punarvasu": ("PVas", 7),
    "pushya": ("Puṣ", 8),
    "ashlesha": ("Aśl", 9),
    "magha": ("Magh", 10),
    "purva-phalguni": ("PPhā", 11),
    "uttara-phalguni": ("UPhā", 12),
    "hasta": ("Hasta", 13),
    "chitra": ("Chitr", 14),
    "svati": ("Svā", 15),
    "vishakha": ("Viś", 16),
    "anuradha": ("Anur", 17),
    "jyeshtha": ("Jyeṣ", 18),
    "mula": ("Mūl", 19),
    "purva-ashadha": ("PAṣ", 20),
    "uttara-ashadha": ("UAṣ", 21),
    "shravana": ("Śra", 22),
    "dhanishta": ("Dhani", 23),
    "shatabhisha": ("Śata", 24),
    "purva-bhadrapada": ("PBhā", 25),
    "uttara-bhadrapada": ("UBhā", 26),
    "revati": ("Rev", 27),
}

WESTERN_HISTORICAL_FIGURES: dict[str, dict[str, tuple[str, ...]]] = {
    "antinous": {"dien": ("CON Dien Aql2",), "ruelle": ("CON Ruelle Aql2",)},
    "argo-navis": {
        "arabic_al-sufi": ("CON arabic_al-sufi Arg",),
        "dien": ("CON Dien CarPupVel",),
        "greek_almagest": ("CON greek_almagest Arg",),
        "greek_farnese": ("CON greek_farnese Arg",),
        "greek_leidenAratea": ("CON greek_leidenAratea Arg",),
        "ruelle": ("CON Ruelle CarPupVel",),
    },
    "cerberus": {
        "dien": ("CON Dien Cer", "CON Dien Cer_eq"),
        "ruelle": ("CON Ruelle Cer",),
    },
    "musca-borealis": {"dien": ("CON Dien MuB",), "ruelle": ("CON Ruelle MuB",)},
    "quadrans-muralis": {"modern": ("AST modern QuM",)},
}

# Stellarium gives two figures of `japanese` this ID: the name tells them apart.
MISNUMBERED_FIGURES = {("japanese", "Tail"): "tail"}

# Their figures with the Latin name of an IAU constellation are that
# constellation, in one chart or the other ("Aquarius (eq)").
IAU_NAMED_CULTURES = frozenset({"dien", "ruelle"})
EQUATORIAL_CHART = " (eq)"

# Wikidata labels that do not work as a page's name; an empty value drops one.
SKY_PAGE_NAME_FIXES: dict[str, dict[str, str]] = {
    "mula": {"zh": ""},
    "musca-borealis": {"fr": "Mouche boréale"},
    "quadrans-muralis": {"fr": "Quadrant mural"},
}

# What a nakshatra's article shows of its astrological symbol: not of the sky.
SKY_PAGE_PICTURES_LEFT_OUT = frozenset(
    {
        "AEW_diamond_solo_white.gif",
        "Ankus_(elephand_goad).svg",
        "Chariot_(PSF).jpg",
        "CobraWoodcut.jpg",
        "Cogotas-II_(empuñadura_de_espada)-Segunda_Edad_del_Hierro.jpg",
        "Coral3.JPG",
        "Gray904.png",
        "Hun_bow.jpg",
        "JKRUK_20070725_El-kolo_garncarskie.jpg",
        "Male_red_deer_(Cervus_elaphus),_Munich,_Germany_-_20060530.jpg",
        "Nelumno_nucifera_open_flower_-_botanic_garden_adelaide.jpg",
        "NikkoCaparisonedHorse5423.jpg",
        "Picture_of_a_ram,_1569_by_Jost_Amman.jpg",
        "PolynesianRatNZ.jpg",
        "Polymixia_nobilis.jpg",
        "Smellie_twins.jpg",
        "Vaca_N&B.jpg",
        "Z_Camelopardalis_GALEX.jpg",
    }
)

# The culture each page sits under. The IAU pages are not here.
SKY_PAGE_CULTURES: dict[str, str] = {
    **dict.fromkeys(CHINESE_MANSIONS, "chinese"),
    **dict.fromkeys(NAKSHATRA_FIGURES, "indian_nakshatras"),
    "antinous": "ruelle",
    "argo-navis": "greek_almagest",
    "cerberus": "ruelle",
    "musca-borealis": "ruelle",
    "quadrans-muralis": "modern",
}
# `modern` has no page of its own: a page drawn on it sits under this culture.
UNPAGED_CULTURE_PARENTS = {"modern": "modern_iau"}


def sky_page_culture(slug: str) -> str | None:
    """The culture of a group slug of another culture than the IAU's."""
    return SKY_PAGE_CULTURES.get(slug.removeprefix(SKY_CONSTELLATION_SLUG_PREFIX))


def sky_constellation_pages() -> dict[str, str]:
    """The QID of each constellation page, by slug. A QID with no figure has none."""
    tables = (
        CHINESE_CONSTELLATIONS,
        INDIAN_NAKSHATRA_CONSTELLATIONS,
        WESTERN_HISTORICAL_CONSTELLATIONS,
    )
    pages = {slug: qids[0] for slug, qids in MODERN_IAU_CONSTELLATIONS.items()}
    for table in tables:
        pages |= {
            slug: qids[0] for slug, qids in table.items() if slug in SKY_PAGE_CULTURES
        }
    return pages


def sky_figure_pages() -> dict[str, dict[str, str]]:
    """The page of each figure that the tables match, by culture and figure ID."""
    pages: dict[str, dict[str, str]] = {}
    for slug, (mansion, number) in CHINESE_MANSIONS.items():
        for key, kind in CHINESE_NUMBERED.items():
            pages.setdefault(key, {})[f"{kind} {key} {number:03d}"] = slug
        for key in CHINESE_CHART_EDITIONS:
            pages.setdefault(key, {})[f"CON {key} {mansion:02d}A"] = slug
    for slug, (figure, number) in NAKSHATRA_FIGURES.items():
        indian = pages.setdefault("indian", {})
        indian[f"CON indian {figure}"] = indian[f"AST indian {figure}"] = slug
        pages.setdefault("indian_nakshatras", {})[
            f"CON indian_nakshatras Naks{number:02d}"
        ] = slug
    for slug, figures in WESTERN_HISTORICAL_FIGURES.items():
        for key, ids in figures.items():
            pages.setdefault(key, {}).update(dict.fromkeys(ids, slug))
    return pages
