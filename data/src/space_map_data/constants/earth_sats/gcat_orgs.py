"""GCAT organisation codes → the manufacturers this project names.

``satcat.tsv`` gives a Manufacturer per object as a GCAT org code, which is
finer and more honest than a per-bus prime: it says Polyot for the GLONASS
satellites Polyot actually assembled, and SECM rather than CAST for the BeiDou-3
satellites Shanghai built. What it does not give is a Wikidata entity, so this
table is the join — keyed on UCode, the code that survives GCAT's renames.

A code with no entry here contributes no manufacturer, which is the normal case
for the long tail of one-off builders; see the unmapped-code report the satcat
ingest logs.
"""

# UCode → manufacturers.py slug.
MANUFACTURER_BY_GCAT: dict[str, str] = {
    "ADST": "airbus-ds",
    "AERO": "aerospace-corporation",
    "APL": "apl",
    "ASTT": "airbus-ds",  # Astrium Toulouse
    "BALL": "ball-aerospace",
    "BLCAN": "blue-canyon",
    "BOES": "boeing",  # Boeing El Segundo, the former Hughes plant
    "CAST": "cast",
    "CGSTL": "chang-guang",
    "COSMOG": "planet-labs",  # Cosmogia, Planet's original name
    "EADSB": "airbus-ds",  # EADS Bremen
    "ERNO": "erno",
    "FAIR": "fairchild",
    "FORDA": "ford-aerospace",
    "GOMSP": "gomspace",
    "GSFC": "nasa-goddard",
    "HSES": "hughes",
    "IAI": "iai",
    "ICEYE": "iceye",
    "ISAC": "ursc",  # ISRO Satellite Centre, now U R Rao Satellite Centre
    "ISRO": "isro",
    "JPL": "jpl",
    "KOMET": "kometa",
    "KUIP": "kuiper-systems",
    "LMCSS": "lockheed-martin",
    "LMSC": "lockheed-martin",
    "MARTD": "martin-marietta",
    "MATT": "matra",  # Matra Espace, the root of the Airbus lineage in GCAT
    "MELCO": "mitsubishi-electric",
    "MHI": "mhi",
    "MOTO": "motorola",
    "NAASB": "rockwell",  # North American Aviation, Rockwell from 1967
    "NANAV": "nanoavionics",
    "NPOE": "energia",
    "NPOL": "npo-lavochkin",
    "NPOPM": "iss-reshetnev",
    "NRL": "nrl",
    "OHB": "ohb",
    "OKB1": "energia",
    "ONEWUS": "airbus-ds",  # OneWeb Satellites, the Airbus joint venture
    "OSC": "orbital-sciences",
    "PROG": "tsskb-progress",
    "RESH": "iss-reshetnev",
    "RWI": "rockwell",
    "SAST": "sast",
    "SBA": "sast",  # Shanghai Bureau 805, SAST's earlier name
    "SECM": "secm",
    "SNVL": "sierra-nevada",
    "SPA": "spectrum-astro",
    "SPIREG": "spire",
    "SPUT": "sputnix",
    "SPX": "spacex",
    "SPXS": "spacex",
    "SSTL": "sstl",
    "STL": "trw",  # Space Technology Laboratories, TRW's satellite arm
    "SUD": "aerospatiale",  # Sud Aviation, merged into Aérospatiale in 1970
    "SWARM": "swarm",
    "THALR": "thales-alenia-space",
    "TRW": "trw",
    "TSSKB": "tsskb-progress",
    "TYVAK": "tyvak",
    "URUGUS": "satellogic",
    "UTIAS": "utias-sfl",
    "VNIEM": "vniiem",
    "YUZH": "yuzhnoye",
}


# GCAT org code (or UCode) → the organisation that operated the satellite.
# Same table shape as the manufacturer map above and the same code-before-UCode
# rule; what differs is the question, since the builder and the operator are
# rarely the same body outside the constellation operators.
OPERATOR_BY_GCAT: dict[str, str] = {
    "AFWDD": "us-air-force",  # USAF Western Development Division
    "ARC": "nasa",
    "CASC": "casc",
    "CGSTL": "chang-guang",
    "CMSEO": "cmsa",
    "COSMOG": "planet-labs",  # Cosmogia, Planet's original name
    "ESA": "esa",
    "ESRO": "esa",  # European Space Research Organisation, ESA from 1975
    "ESSA": "essa",
    "EUTEL": "eutelsat",
    "GEESP": "geespace",
    # The Soviet, then Russian, military space directorate under its six
    # successive names. GCAT dates each code, so the era comes from the code
    # rather than from the launch date: TSUKOS through UNKS are Soviet, and the
    # rest track the reorganisations the branch went through after 1991.
    "GRU": "soviet-armed-forces",
    "GUKOS": "soviet-armed-forces",
    "GUKOSR": "soviet-armed-forces",
    "KVR": "russian-space-forces",
    "TSUKOS": "soviet-armed-forces",
    "UNKS": "soviet-armed-forces",
    "UNKSR": "russian-space-forces",
    "VKS": "russian-space-forces",
    "VKSR": "russian-space-forces",
    "VTS": "soviet-armed-forces",  # military topographic service
    "VVKO": "russian-aerospace-defence",
    "VVKOV": "russian-aerospace-forces",
    "GLOB": "globalstar",
    "GSFC": "nasa",
    "INTEL": "intelsat",
    "IRID": "iridium",
    "ISRO": "isro",
    "JPL": "jpl",
    "JSC": "nasa",
    "KS": "rscc",
    "KUIP": "kuiper-systems",
    "MAI": "mai-china",
    "MSFC": "nasa",
    "NANSFI": "spire",  # NanoSatisfi, Spire's original name
    "NASDA": "nasda",
    "NOAA": "noaa",
    "NPOPM": "iss-reshetnev",
    "NRO": "nro",
    "OKB1": "energia",
    "ONEWEB": "oneweb",
    "ORBC": "orbcomm",
    "PVO": "pvo",
    "RKKE": "energia",
    "SDA": "sda",
    "SITRO": "sitronics",
    "SPX": "spacex",
    "SPXS": "spacex",
    "SWARM": "swarm",
    "TSSKB": "tsskb-progress",
    "VMF": "soviet-navy",
    "YUANX": "shanghai-spacecom",
    "ZXW": "china-satnet",
    "ZZB": "pla-gad",
}
