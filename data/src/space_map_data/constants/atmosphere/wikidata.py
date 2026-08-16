"""Wikidata topic pages behind the atmosphere panel.

Keyed by body id, a superset of ``ATMOSPHERE_BODIES`` — some bodies have an
article but no atmosphere data yet. Coverage is worse than it looks: English
folds most moon atmospheres into the body article, while French and Italian
split them out.

Values are tuples because one topic sometimes splits across two Wikidata
items with disjoint sitelinks. Nothing falls back to English when a locale is
missing — a reader gets the article in their language or no link at all, so
the per-row coverage comment is the whole story.

Locale codes follow ``constants.providers.LANGUAGES``; "all 12" means every
one. Coverage was read off Wikidata and drifts as articles change — treat
the comments as of 2026-07-31.
"""

# One entry per body that has a dedicated article somewhere. Absent bodies —
# Enceladus, Rhea, Dione, Ceres and the TNOs — redirect to the body article on
# every wiki, and Titania's atmosphere (Q140185862) is a Wikidata item with no
# article behind it in any of our languages.
ATMOSPHERE_PAGES: dict[str, tuple[str, ...]] = {
    "naif-10": ("Q170754",),  # solar corona — all 12
    "naif-199": ("Q245809",),  # atmosphere of Mercury — en fr ja zh ar es
    "naif-299": ("Q1941",),  # atmosphere of Venus — en fr ja zh ar ru pt it es pl
    "naif-301": ("Q115507",),  # atmosphere of the Moon — en fr ja zh ar ru pt es
    "naif-399": ("Q3230",),  # atmosphere of Earth — all 12
    "naif-499": ("Q218860",),  # atmosphere of Mars — en fr ja zh ar ru pt de it es pl
    "naif-501": ("Q2869536",),  # atmosphere of Io — en fr ar it
    "naif-502": ("Q7885366",),  # atmosphere of Europa — fr it
    "naif-503": ("Q2869535",),  # atmosphere of Ganymede — fr it
    "naif-504": ("Q16529658",),  # atmosphere of Callisto — it
    "naif-599": ("Q3045",),  # atmosphere of Jupiter — en fr ja zh ar ru pt it es
    "naif-606": ("Q1143812",),  # atmosphere of Titan — en fr ja zh ar ru pt it
    "naif-699": ("Q303397",),  # atmosphere of Saturn — fr it
    "naif-799": ("Q1708494",),  # atmosphere of Uranus — en fr ja zh ar ru pt it es
    "naif-801": ("Q1018119",),  # atmosphere of Triton — en fr ja zh ar ru pt it es
    "naif-899": ("Q2869537",),  # atmosphere of Neptune — fr ru it
    "naif-999": ("Q3628984",),  # atmosphere of Pluto — en fr zh ar ru pt it es pl
}

# The Sun's row above is the corona because "atmosphere of the Sun"
# (Q89285197) has no article anywhere; these are the shells around it.
ATMOSPHERE_LAYER_PAGES: dict[str, tuple[str, ...]] = {
    # Solar atmosphere, innermost out. The Sun's entry above is the corona;
    # these are the rest of the shells the temperature panel reads against.
    "photosphere": ("Q6372",),  # photosphere — all 12
    "chromosphere": ("Q190003",),  # chromosphere — all 12
    # solar transition region — en fr ja zh ar ru pt it pl
    "transition_region": ("Q128118",),
    "solar_wind": ("Q79833",),  # solar wind — all 12
    "sunspot": ("Q6582994",),  # sunspot — all 12
    # Terrestrial shells, ground up.
    "troposphere": ("Q40631",),  # troposphere — all 12
    "tropopause": ("Q186433",),  # tropopause — all 12
    "stratosphere": ("Q108376",),  # stratosphere — all 12
    "mesosphere": ("Q162167",),  # mesosphere — all 12
    "thermosphere": ("Q178043",),  # thermosphere — all 12
    "exosphere": ("Q170332",),  # exosphere — all 12
    "ionosphere": ("Q162219",),  # ionosphere — all 12
    "homosphere": ("Q3359129",),  # homosphere — en es pl
    "heterosphere": ("Q1035915",),  # heterosphere — en es pl
}

ATMOSPHERE_CONCEPT_PAGES: dict[str, tuple[str, ...]] = {
    # stellar atmosphere — en fr ja zh ar ru pt de it es pl
    "stellar_atmosphere": ("Q6311",),
    "atmospheric_pressure": ("Q81809",),  # atmospheric pressure — all 12
    "scale_height": ("Q548132",),  # scale height — en fr ja zh ru pt de it
    # atmospheric escape — en fr ja zh ar ru pt it es
    "atmospheric_escape": ("Q2568436",),
    "greenhouse_effect": ("Q41560",),  # greenhouse effect — all 12
    # runaway greenhouse effect — en ja zh ar ru pt de it es pl
    "runaway_greenhouse": ("Q4357041",),
    "cloud": ("Q8074",),  # cloud — all 12
    "haze": ("Q643546",),  # haze — all 12
    "tholin": ("Q73017",),  # tholin — en fr ja zh ar ru pt de it es pl
}

# Named storms and standing features, for bodies whose panel calls them out.
ATMOSPHERE_FEATURE_PAGES: dict[str, tuple[str, ...]] = {
    "great_red_spot": ("Q194256",),  # Great Red Spot — all 12
    # Great Dark Spot — en fr ja zh ar ru pt it es he pl
    "great_dark_spot": ("Q3115080",),
    "great_white_spot": ("Q1155220",),  # Great White Spot — en fr zh ar ru it es pl
    "saturn_hexagon": ("Q210790",),  # Saturn's hexagon — all 12
}

# Keyed by the symbols ``constants.atmosphere.gases`` uses in the composition
# bar. Element pages, not "X in the atmosphere of Y" — those do not exist.
GAS_PAGES: dict[str, tuple[str, ...]] = {
    "Ar": ("Q696",),  # argon — all 12
    "CH4": ("Q37129",),  # methane — all 12
    "CO": ("Q2025",),  # carbon monoxide — all 12
    "CO2": ("Q1997",),  # carbon dioxide — all 12
    "H2": ("Q556",),  # hydrogen — all 12
    "H2O": ("Q190120",),  # water vapor — all 12
    "H2S": ("Q170591",),  # hydrogen sulfide — all 12
    "He": ("Q560",),  # helium — all 12
    "K": ("Q703",),  # potassium — all 12
    "N2": ("Q627",),  # nitrogen — all 12
    "Na": ("Q658",),  # sodium — all 12
    "NH3": ("Q4087",),  # ammonia — all 12
    "Ne": ("Q654",),  # neon — all 12
    "O2": ("Q629",),  # oxygen — all 12
    "O3": ("Q36933",),  # ozone — all 12
    "SO2": ("Q5282",),  # sulfur dioxide — all 12
    "C2H6": ("Q52858",),  # ethane — all 12
    "H2SO4": ("Q4118",),  # sulfuric acid — all 12
}
