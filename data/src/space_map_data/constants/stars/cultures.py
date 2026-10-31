"""Sky-tradition and cultural-group QIDs, without dataset matching.

Separate tables preserve the distinction between astronomy and its practitioners.
See docs/stellar-qids.md for lookup scope and unresolved names.
"""

SKY_TRADITION_PAGES: dict[str, tuple[str, ...]] = {
    "ancient-greek-astronomy": ("Q2390452",),
    "australian-aboriginal-astronomy": ("Q2059906",),
    "babylonian-astronomy": ("Q787929",),
    "chinese-astronomy": ("Q1268276",),
    "chinese-constellations": ("Q1074076",),
    "egyptian-astronomy": ("Q751843",),
    "iau-constellations": ("Q9241",),
    "indian-astronomy": ("Q1292962",),
    "inuit-astronomy": ("Q6059243",),
    "journey-to-the-west": ("Q70784",),
    "maya-astronomy": ("Q18358287",),
    "medieval-islamic-astronomy": ("Q1255366",),
    "nakshatra": ("Q1125935",),
    "polynesian-navigation": ("Q826781",),
    "tibetan-astronomy": ("Q1570770",),
}

SKY_CULTURE_PEOPLE_PAGES: dict[str, tuple[str, ...]] = {
    "ahtna": ("Q46826",),
    "arab": ("Q35323",),
    "aztec": ("Q20107272",),
    "babylonian": ("Q797930",),
    "balinese": ("Q1266626",),
    "banjara": ("Q252885",),
    "belarusian": ("Q483569",),
    "blackfoot": ("Q388264",),
    "bororo": ("Q894069",),
    "bugis": ("Q1002570",),
    "chinese": ("Q6501380",),
    "gamilaraay": ("Q175823",),
    "gond": ("Q1268437",),
    "greek": ("Q539051",),
    "guarani": ("Q46429",),
    "gwichin": ("Q1144501",),
    "hawaiian": ("Q1283606",),
    "huave": ("Q611921",),
    "inuit": ("Q189975",),
    "iroquois": ("Q68518",),
    "japanese": ("Q161652",),
    "javanese": ("Q49209",),
    "kalina": ("Q2486742",),
    "khoikhoi": ("Q219252",),
    "kiche": ("Q1137419",),
    "kolam": ("Q17060030",),
    "korean": ("Q484464",),
    "korku": ("Q3595693",),
    "koyukon": ("Q1389123",),
    "lokono": ("Q3258734",),
    "macedonian": ("Q2436423",),
    "madurese": ("Q1258905",),
    "malay": ("Q142702",),
    "manchu": ("Q145665",),
    "mandar": ("Q1570945",),
    "maori": ("Q6122670",),
    "maricopa": ("Q1750007",),
    "maya": ("Q45914",),
    "mikmaq": ("Q495751",),
    "mocovi": ("Q3099764",),
    "mongol": ("Q41975",),
    "navajo": ("Q108266",),
    "nicobarese": ("Q207750",),
    "norse": ("Q1211290",),
    "northern-tutchone": ("Q1255107",),
    "pardhi": ("Q7180937",),
    "pawnee": ("Q750947",),
    "potawatomi": ("Q1065583",),
    "qom": ("Q1542227",),
    "romanian": ("Q485150",),
    "russian": ("Q49542",),
    "sahtu": ("Q1151288",),
    "sami": ("Q48199",),
    "samoan": ("Q1135531",),
    "san": ("Q172365",),
    "sardinian": ("Q2140968",),
    "seri": ("Q1263088",),
    "southern-tutchone": ("Q1255761",),
    "tahitian": ("Q1282763",),
    "tanana-athabaskan": ("Q4895596",),
    "tewa": ("Q1974818",),
    "thai": ("Q472834",),
    "tibetan": ("Q187985",),
    "tikuna": ("Q5363631",),
    "tongan": ("Q26085464",),
    "tukano": ("Q2520180",),
    "tupi": ("Q120684",),
    "tzotzil": ("Q387073",),
    "wergaia": ("Q62098205",),
    "wichi": ("Q1284276",),
    "xhosa": ("Q207996",),
    "yellowknives": ("Q1092654",),
    "yuwaalaraay": ("Q39088282",),
    "zulu": ("Q129962",),
    "zuni": ("Q231317",),
}

SKY_CULTURE_SLUG_PREFIX = "culture-"
# The culture of the `sky-` pages.
IAU_SKY_CULTURE = "modern_iau"

# The cultures whose page reads a Wikipedia article, as a slug of
# `SKY_TRADITION_PAGES`. A people's article is about the people, not their sky.
# Another culture reads its own text: an article on Greek astronomy says nothing
# of the Almagest's figures.
SKY_CULTURE_ARTICLES: dict[str, str] = {
    "chinese": "chinese-constellations",
    "egyptian": "egyptian-astronomy",
    "indian": "indian-astronomy",
    "indian_nakshatras": "nakshatra",
    "inuit": "inuit-astronomy",
    "maya": "maya-astronomy",
    "modern_iau": "iau-constellations",
    "tibetan": "tibetan-astronomy",
}

# The cultures whose own text the export leaves out.
SKY_CULTURE_TEXTS_LEFT_OUT: dict[str, str] = {
    "khoi-san": "a list of stories, no introduction",
    "potawatomi": "Traditional Knowledge labels, one of them seasonal",
    "sami": "points to a reference list that the page does not have",
    "tibetan": "the author calls it unfinished",
}

# Western near-copies of `modern_iau`. The export keeps them; the picker does not.
UNPICKED_SKY_CULTURES = frozenset(
    {"modern_st", "modern", "modern_hlad", "modern_sternenkarten", "modern_rey"}
)

# Each region group of the culture picker, in its order, with its cultures. The
# two datasets name regions differently, so this table is by hand. A value is
# the page that names the culture in the reader's language where Stellarium has
# no translation (a slug of a table above), then its edition as published. An
# empty value is no good match: the culture keeps its English name. A people's
# name labels only that culture here: it does not say that the item is the
# culture's astronomy.
SKY_CULTURE_REGIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "modern": {
        "modern_iau": (),
        "modern_chinese": (),
        "modern_journey_to_the_west": ("journey-to-the-west",),
    },
    "northern-africa": {
        "egyptian": ("egyptian-astronomy",),
        "egyptian_dendera": ("egyptian-astronomy", "Dendera"),
        "greek_almagest": ("greek", "Almagest"),
    },
    "southern-africa": {
        "khoi-san": (),
        "xhosa": ("xhosa",),
        "zulu": ("zulu",),
    },
    "northern-america": {
        "ahtna": ("ahtna",),
        "blackfoot": ("blackfoot",),
        "gwichin": ("gwichin",),
        "inuit": ("inuit",),
        "iroquois": ("iroquois",),
        "koyukon": ("koyukon",),
        "lower_tanana": (),
        "maricopa": ("maricopa",),
        "mikmaq": ("mikmaq",),
        "navajo": ("navajo",),
        "pawnee": ("pawnee",),
        "potawatomi": ("potawatomi",),
        "sahtuotine": ("sahtu",),
        "tewa": ("tewa",),
        "tutchone": (),
        "yellowknives": ("yellowknives",),
        "zuni": ("zuni",),
    },
    "central-america": {
        "aztec": ("aztec",),
        "huave": ("huave",),
        "kiche": ("kiche",),
        "maya": ("maya",),
        "seri": ("seri",),
        "tzotzil": ("tzotzil",),
    },
    "south-america": {
        "ava_guarani": (),
        "bororo": ("bororo",),
        "kalina": ("kalina",),
        "lokono": ("lokono",),
        "mocovi": ("mocovi",),
        "northern_andes": (),
        "tikuna": ("tikuna",),
        "toba": ("qom",),
        "tukano": ("tukano",),
        "tupi": ("tupi",),
        "wichi": ("wichi",),
    },
    "eastern-asia": {
        "chinese": ("chinese",),
        "chinese_chenzhuo": ("chinese", "Chenzhuo"),
        "chinese_manchu": ("manchu",),
        "chinese_song_dynasty": ("chinese", "Song"),
        "chinese_xianglin": ("chinese", "Xianglin"),
        "chinese_yuan_dynasty": ("chinese", "Yuan"),
        "japanese": ("japanese", "Yasui"),
        "korean": ("korean",),
        "mongolian": ("mongol",),
        "tibetan": ("tibetan",),
    },
    "northern-asia": {
        "russian_siberian": ("russian", "Siberian"),
    },
    "south-eastern-asia": {
        "balinese": ("balinese",),
        "bugis": ("bugis",),
        "java": ("javanese",),
        "madura": ("madurese",),
        "malay": ("malay",),
        "mandar": ("mandar",),
        "thai": ("thai",),
    },
    "southern-asia": {
        "banjara": ("banjara",),
        "gond": ("gond",),
        "indian": ("indian-astronomy", "Vedic"),
        "indian_nakshatras": ("indian-astronomy", "Nakshatras"),
        "kolam": ("kolam",),
        "korku": ("korku",),
        "nicobars": ("nicobarese",),
        "pardhi": ("pardhi",),
    },
    "western-asia": {
        "arabic_al-sufi": ("arab", "Al-Sufi"),
        "arabic_arabian_peninsula": ("arab", "Arabian Peninsula"),
        "arabic_indigenous": ("arab", "Indigenous"),
        "babylonian_mulapin": ("babylonian", "MUL.APIN"),
        "babylonian_seleucid": ("babylonian", "Seleucid"),
    },
    "eastern-europe": {
        "belarusian": ("belarusian",),
        "romanian": ("romanian",),
    },
    "northern-europe": {
        "norse": ("norse",),
        "norse_edda": ("norse", "Edda"),
        "sami": ("sami",),
    },
    "southern-europe": {
        "armintxe": (),
        "greek_dante": ("greek", "Dante"),
        "greek_farnese": ("greek", "Farnese + Almagest"),
        "macedonian": ("macedonian",),
        "sardinian": ("sardinian",),
    },
    "western-europe": {
        "dien": (),
        "greek_leidenAratea": ("greek", "Leiden Aratea + Almagest"),
        "ruelle": (),
    },
    "australasia": {
        "boorong": (),
        "kamilaroi": (),
        "maori": ("maori",),
    },
    "melanesia": {
        "anutan": (),
        "vanuatu_netwar": (),
    },
    "polynesia": {
        "hawaiian_starlines": ("hawaiian", "Starlines"),
        "ruanui_sky_tahiti_and_society_islands": (),
        "samoan": ("samoan",),
        "tongan": ("tongan",),
    },
}

# The novel is the name of `modern_journey_to_the_west`, after this word.
SKY_CULTURE_LABEL_PREFIXES: dict[str, dict[str, str]] = {
    "modern_journey_to_the_west": {
        "fr": "Moderne",
        "ja": "現代",
        "ar": "الحديث",
        "pt": "Moderna",
        "it": "Moderna",
        "he": "מודרנית",
        "pl": "Współczesna",
    },
}

# The names where Stellarium has none, as no item names these.
SKY_CULTURE_LABELS: dict[str, dict[str, str]] = {
    "indian_nakshatras": {
        "fr": "Indienne (nakshatras)",
        "ja": "インド (ナクシャトラ)",
        "ar": "الهندي (النكشترات)",
        "pt": "Indiana (Nakshatras)",
        "it": "Indiana (Nakshatra)",
        "he": "הודית (נקשטרות)",
        "pl": "Indyjska (Nakszatry)",
    },
    "modern_iau": {
        "pt": "Moderna (UAI)",
        "it": "Moderna (IAU)",
        "he": "מודרנית (IAU)",
        "pl": "Współczesna (IAU)",
    },
    "modern_chinese": {
        "pt": "Moderna (chinesa)",
        "it": "Moderna (cinese)",
        "he": "מודרנית (סינית)",
        "pl": "Współczesna (chińska)",
    },
}

# Where these beat Stellarium's value: a typo, a Brazilian spelling, a wrong
# word (ar "Semitic" for Sami, he "Roman" for Romanian), a name its people
# reject, or a title long beside its neighbours in the picker.
SKY_CULTURE_NAME_FIXES: dict[str, dict[str, str]] = {
    "arabic_al-sufi": {"fr": "Arabe (Al-Sufi)"},
    "aztec": {"pt": "Astecas", "it": "Aztechi", "es": "Aztecas"},
    "babylonian_mulapin": {"pl": "Babilończycy (MUL.APIN)"},
    "inuit": {"ru": "Инуиты", "pl": "Inuici"},
    "modern_iau": {"zh": "现代 (IAU)", "ar": "الحديث (IAU)"},
    "mongolian": {"pt": "Mongóis"},
    "norse": {"fr": "Norrois", "ar": "نورديون"},
    "romanian": {"pt": "Romenos", "he": "רומנים"},
    "sami": {"ar": "شعب سامي"},
}
# Stellarium's value is no name of the culture: the language reads Wikidata's or
# English.
SKY_CULTURE_NAMES_LEFT_OUT: dict[str, frozenset[str]] = {
    # "Aborigines", and a genitive.
    "boorong": frozenset({"it", "ru"}),
}

# Wikidata labels that do not work as a culture's name, where Stellarium has none:
# article titles, a word for "people", a typo, a wrong item, or a name its people
# reject.
SKY_PAGE_LABEL_FIXES: dict[str, dict[str, str]] = {
    "aztec": {
        "fr": "Aztèques",
        "zh": "阿兹特克人",
        "ar": "الأزتك",
        "ru": "Ацтеки",
        "pt": "Astecas",
        "it": "Aztechi",
        "es": "Aztecas",
        "he": "אצטקים",
        "pl": "Aztekowie",
    },
    "babylonian": {"zh": "巴比伦人", "pt": "Babilónios", "pl": "Babilończycy"},
    "balinese": {"es": "Balineses"},
    "belarusian": {"ar": "بيلاروسيون"},
    "blackfoot": {
        "fr": "Pieds-Noirs",
        "zh": "黑脚人",
        "it": "Piedi Neri",
    },
    "bugis": {"pt": "Bugis", "es": "Bugis", "pl": "Bugisi"},
    "chinese": {"fr": "Chinois", "pt": "Chineses"},
    "egyptian-astronomy": {
        "fr": "Astronomie égyptienne",
        "de": "Ägyptische Astronomie",
    },
    "gond": {"pt": "Gond"},
    "hawaiian": {
        "fr": "Hawaïens",
        "ja": "ハワイ人",
        "ar": "هاوائيون",
        "pt": "Havaianos",
        "de": "Hawaiier",
        "it": "Hawaiani",
        "es": "Hawaianos",
        "he": "הוואים",
    },
    "huave": {"es": "Ikoots"},
    "iroquois": {"ja": "イロコイ族", "zh": "易洛魁人"},
    "japanese": {"ar": "يابانيون"},
    "javanese": {"es": "Javaneses"},
    "kalina": {"es": "Kali'na", "he": "קאלינה"},
    "korku": {"ru": "Корку"},
    "macedonian": {"ja": "マケドニア人"},
    "madurese": {"es": "Madureses"},
    "maya": {"pt": "Maias", "es": "Mayas"},
    "navajo": {"ja": "ナバホ族"},
    "nicobarese": {"fr": "Nicobarais"},
    "norse": {
        "fr": "Norrois",
        "ar": "نورديون",
        "pt": "Nórdicos",
        "de": "Nordgermanen",
    },
    "qom": {"es": "Tobas"},
    "sami": {"ar": "شعب سامي", "pt": "Sámi", "es": "Samis", "he": "סאמים"},
    "seri": {"fr": "Seris", "es": "Seris"},
    "thai": {"ja": "タイ人", "pt": "Tailandeses"},
    "tongan": {"es": "Tonganos"},
    "tupi": {"es": "Tupíes"},
    "tzotzil": {"pt": "Tzotzis", "es": "Tsotsiles"},
}


def sky_culture_page(slug: str) -> str:
    """The QID of a slug of `SKY_TRADITION_PAGES` or `SKY_CULTURE_PEOPLE_PAGES`."""
    pages = SKY_TRADITION_PAGES | SKY_CULTURE_PEOPLE_PAGES
    return pages[slug][0]


def sky_culture_name_qids() -> set[str]:
    """The items that name a culture of the picker, or give it an article."""
    return {
        sky_culture_page(name[0])
        for cultures in SKY_CULTURE_REGIONS.values()
        for name in cultures.values()
        if name
    } | {sky_culture_page(slug) for slug in SKY_CULTURE_ARTICLES.values()}
