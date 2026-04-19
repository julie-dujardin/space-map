"""Satellite constellation catalog.

Each constellation has a ``slug`` (primary key), an optional ``wikidata_qid``
(display names are sourced from Wikipedia/Wikidata), a ``category`` (one of
CelesTrak's top-level groupings), and one of three membership selectors: an
object-name ``prefix`` (detected from the TLE ``OBJECT_NAME``), a CelesTrak
``group`` slug (fetched via ``gp.php?GROUP=``), or a SATCAT ``source`` code
(matched against the ``OWNER`` field, i.e. the CelesTrak source/operator code).

Prefix-based membership is preferred since it avoids fetching 10k+ rows just to
tag a single constellation (Starlink alone is most of that). Group fetches are
reserved for constellations whose members don't share an obvious name prefix.
Source-based membership is used for commercial operators whose fleet is
identified in SATCAT but whose satellites don't share a name prefix.

Categories mirror the top-level sections of https://celestrak.org/NORAD/elements/
"""

from dataclasses import dataclass
from enum import StrEnum


class SatelliteCategory(StrEnum):
    """Top-level grouping from https://celestrak.org/NORAD/elements/"""

    DISASTER = "disaster-sar"
    WEATHER = "weather"
    OBSERVATION = "observation"
    COMMUNICATIONS = "communications"
    NAVIGATION = "navigation"
    SCIENCE = "science"
    MILITARY = "military"
    DEBRIS = "debris"
    STATION = "station"
    MANNED_CAPSULE = "manned_capsule"
    UNMANNED_CARGO = "unmanned_cargo"
    SPACE_TUG = "space_tug"
    ROCKET = "rocket"  # spent stages, debris
    UPPER_STAGE = "upper_stage"  # shared across multiple rocket families
    MISCELLANEOUS = "miscellaneous"


@dataclass(frozen=True)
class ConstellationSpec:
    slug: str
    wikidata_qid: str | None
    category: SatelliteCategory | tuple[SatelliteCategory, ...]
    prefix: str | tuple[str, ...] | None = None  # TLE OBJECT_NAME startswith
    contains: tuple[str, ...] | None = None  # like prefix but anywhere in the name
    group: str | None = None  # CelesTrak gp.php GROUP slug
    source: str | None = None  # SATCAT SOURCE/OWNER code
    url: str | None = None  # When no wikipedia link
    satellites: list[str] | None = None  # List of member names


"""
Science programs with members but no pattern and (certainly) lacking wikidata backlinks
- https://en.wikipedia.org/wiki/Explorers_Program (later ones)
- https://en.wikipedia.org/wiki/Cosmic_Vision
- https://en.wikipedia.org/wiki/Discovery_Program
- https://en.wikipedia.org/wiki/New_Frontiers_program
"""


CONSTELLATIONS: tuple[ConstellationSpec, ...] = (
    # -------------------------------------------------------------------------
    # Major commercial / government constellations — identified by name prefix
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "starlink", "Q19867977", SatelliteCategory.COMMUNICATIONS, prefix="STARLINK"
    ),
    ConstellationSpec(
        "oneweb", "Q17184117", SatelliteCategory.COMMUNICATIONS, prefix="ONEWEB"
    ),
    ConstellationSpec(
        "iridium", "Q3154356", SatelliteCategory.COMMUNICATIONS, prefix="IRIDIUM"
    ),
    ConstellationSpec(
        "kuiper", "Q62812537", SatelliteCategory.COMMUNICATIONS, prefix="KUIPER"
    ),
    ConstellationSpec(
        "qianfan", "Q124981442", SatelliteCategory.COMMUNICATIONS, prefix="QIANFAN"
    ),
    ConstellationSpec(
        "guowang",
        "Q123581514",
        SatelliteCategory.COMMUNICATIONS,
        prefix="HULIANWANG",
    ),  # HULIANWANG JISHU, HULIANWAN GAOGUI, HULIANWANG DIGUI (that's the big one, first 2 are experimental?)
    ConstellationSpec(
        "globalstar", "Q1202533", SatelliteCategory.COMMUNICATIONS, prefix="GLOBALSTAR"
    ),
    ConstellationSpec(
        "planet-flock", "Q97380305", SatelliteCategory.OBSERVATION, prefix="FLOCK"
    ),
    ConstellationSpec(
        "planet-skysat", "Q27031816", SatelliteCategory.OBSERVATION, prefix="SKYSAT"
    ),
    ConstellationSpec(
        "spacebee", "Q105334563", SatelliteCategory.COMMUNICATIONS, prefix="SPACEBEE"
    ),
    ConstellationSpec(
        "sitro-ais", None, SatelliteCategory.COMMUNICATIONS, prefix="SITRO-AIS"
    ),
    ConstellationSpec(
        "geesat", "Q125167295", SatelliteCategory.COMMUNICATIONS, prefix="GEESAT"
    ),
    ConstellationSpec(
        "gonets", "Q2041033", SatelliteCategory.COMMUNICATIONS, prefix="GONETS"
    ),
    ConstellationSpec(
        "tianqi",
        None,
        SatelliteCategory.COMMUNICATIONS,
        prefix="TIANQI",
        url="https://www.guodiangaoke.com/web/dist/index.html#/tianqixingzuo",
    ),
    ConstellationSpec(
        "connecta-iot",
        None,
        SatelliteCategory.COMMUNICATIONS,
        prefix="CONNECTA IOT",
        url="https://www.connectasat.com/technology/satellite-iot/",
    ),
    ConstellationSpec(
        "tianmu", "Q124168307", SatelliteCategory.WEATHER, prefix="TIANMU-1"
    ),
    ConstellationSpec(
        "spire", "Q19877982", SatelliteCategory.OBSERVATION, prefix="LEMUR"
    ),
    ConstellationSpec(
        "marecs", "Q1881172", SatelliteCategory.COMMUNICATIONS, prefix="MARECS"
    ),
    ConstellationSpec(
        "marisat", "Q6765591", SatelliteCategory.COMMUNICATIONS, prefix="MARISAT"
    ),
    ConstellationSpec(
        "inmarsat", "Q827927", SatelliteCategory.COMMUNICATIONS, prefix="INMARSAT"
    ),
    ConstellationSpec("metop", "Q819651", SatelliteCategory.WEATHER, prefix="METOP"),
    ConstellationSpec(
        "meteosat", "Q1429889", SatelliteCategory.WEATHER, prefix="METEOSAT"
    ),
    ConstellationSpec(
        "measat",
        None,
        SatelliteCategory.COMMUNICATIONS,
        prefix="MEASAT",
        url="https://www.measat.com/our-coverage/measat-fleet/",
    ),
    ConstellationSpec(
        "africasat", "Q20052527", SatelliteCategory.COMMUNICATIONS, prefix="AFRICASAT"
    ),
    ConstellationSpec(
        "thaicom", None, SatelliteCategory.COMMUNICATIONS, prefix="THAICOM"
    ),
    ConstellationSpec(
        "fengyun", "Q1404722", SatelliteCategory.WEATHER, prefix="FENGYUN"
    ),
    ConstellationSpec(
        "galaxy", "Q832041", SatelliteCategory.COMMUNICATIONS, prefix="GALAXY"
    ),
    # TODO:
    # SCS-* - https://www.scs-space.com?
    # -------------------------------------------------------------------------
    # Chinese EO / mapping constellations (PRC owner)
    # -------------------------------------------------------------------------
    # XW, camsat: chinese amateur radio
    ConstellationSpec("xw", None, SatelliteCategory.COMMUNICATIONS, prefix="XW"),
    ConstellationSpec("cas", None, SatelliteCategory.COMMUNICATIONS, prefix="CAS-"),
    # Jilin-1: largest Chinese commercial EO constellation (CGST / Chang Guang).
    ConstellationSpec(
        "jilin", "Q123139897", SatelliteCategory.OBSERVATION, prefix="JILIN"
    ),
    # Gaofen: CNSA civil high-resolution EO programme (government/dual-use)
    ConstellationSpec(
        "gaofen", "Q18669407", SatelliteCategory.OBSERVATION, prefix="GAOFEN"
    ),
    # SuperView / Gaojing: commercial VHR EO (Beijing Space View / SI Imaging)
    ConstellationSpec(
        "superview-china-siwei",
        "Q135765238",
        SatelliteCategory.OBSERVATION,
        prefix="SUPERVIEW",
    ),
    # Zhuhai: hyperspectral/SAR constellation (Orbita Aerospace)
    ConstellationSpec(
        "zhuhai",
        None,
        SatelliteCategory.OBSERVATION,
        prefix="ZHUHAI-",
        url="https://www.obtdata.com/en/zhuhai1.html",
    ),
    # Yunyao-1: commercial weather
    ConstellationSpec(
        "yunyao", "Q124256662", SatelliteCategory.WEATHER, prefix="YUNYAO-1"
    ),
    # Haiyang: CNSA ocean color and dynamics satellites
    ConstellationSpec(
        "haiyang", "Q2362851", SatelliteCategory.OBSERVATION, prefix="HAIYANG"
    ),
    # TODO: check
    # - NINGXIA-1: https://www.newspace.im/constellations/ningxia
    # - DONGPO: ????
    # Centispace-1: Chinese nav-augmentation LEO constellation (Beijing Future Navigation Technology)?
    ConstellationSpec(
        "centispace", None, SatelliteCategory.NAVIGATION, prefix="CENTISPACE-"
    ),
    # Tianlian I / II: Chinese TDRSS equivalent (relay / tracking, CNSA)
    ConstellationSpec(
        "tianlian", "Q7800236", SatelliteCategory.COMMUNICATIONS, prefix="TIANLIAN"
    ),  # Also Q67931551 but that has very low coverage
    # Tiantong-1: Chinese mobile satellite comms (CASC / China Satcom)
    ConstellationSpec(
        "tiantong", "Q105274818", SatelliteCategory.COMMUNICATIONS, prefix="TIANTONG-"
    ),
    # Zhongxing / Chinasat: Chinese military and civil GEO comms (CASC / CASIC).
    # SATCAT uses "ZHONGXING-N" and "CHINASAT N" interchangeably.
    ConstellationSpec(
        "zhongxing", None, SatelliteCategory.COMMUNICATIONS, prefix="ZHONGXING"
    ),
    ConstellationSpec(
        "chinasat", None, SatelliteCategory.COMMUNICATIONS, prefix="CHINASAT"
    ),
    # Chinese Space Station (CSS): core module TIANHE + labs WENTIAN / MENGTIAN.
    ConstellationSpec(
        "chinese-space-station", "Q5100935", SatelliteCategory.STATION, prefix="CSS "
    ),
    # International Space Station: TLE names start with "ISS".
    ConstellationSpec("iss", "Q25271", SatelliteCategory.STATION, prefix="ISS"),
    # Yaogan: Chinese military reconnaissance constellation (PLA/CNSA).
    # Covers SAR triplets, EO, and SIGINT pairs across many sub-series.
    ConstellationSpec(
        "yaogan",
        "Q589786",
        (SatelliteCategory.MILITARY, SatelliteCategory.OBSERVATION),
        prefix="YAOGAN",
    ),
    ConstellationSpec(
        "tongxin-jishu-shiyan",
        "Q60994560",
        (SatelliteCategory.MILITARY, SatelliteCategory.OBSERVATION),
        prefix="TJS",
    ),
    ConstellationSpec(
        "tianyan",
        "Q123807910",
        (SatelliteCategory.MILITARY, SatelliteCategory.OBSERVATION),
        prefix="TIANYAN",
    ),
    # Yunhai: chinese weather for military
    ConstellationSpec(
        "yunhai-1",
        "Q86726049",
        (SatelliteCategory.WEATHER, SatelliteCategory.MILITARY),
        prefix="YUNHAI-1",
    ),
    ConstellationSpec(
        "yunhai-2",
        "Q125398771",
        (SatelliteCategory.WEATHER, SatelliteCategory.MILITARY),
        prefix="YUNHAI-2",
    ),
    ConstellationSpec(
        "yunhai-3",
        "Q125447848",
        (SatelliteCategory.WEATHER, SatelliteCategory.MILITARY),
        prefix="YUNHAI-3",
    ),
    # Tianhui: Chinese military imaging
    ConstellationSpec(
        "tianhui",
        "Q111496708",
        (SatelliteCategory.OBSERVATION, SatelliteCategory.MILITARY),
        prefix="TIANHUI",
    ),
    # Shijian, chuangxin, shiyan: Chinese technology-experiment / R&D series (CASC/CASIC).
    # Extremely broad — covers dozens of unrelated missions.
    # Classified, possibly military
    ConstellationSpec(
        "shijian", "Q11452851", SatelliteCategory.SCIENCE, prefix=("SHIJIAN", "SJ")
    ),  # "Practice"
    ConstellationSpec(
        "chuangxin", None, SatelliteCategory.SCIENCE, prefix=("CHUANGXIN")
    ),  # "Innovation"
    ConstellationSpec(
        "shiyan", "Q2279595", SatelliteCategory.SCIENCE, prefix=("SHIYAN")
    ),  # "Experiment"
    # Long march boosters
    ConstellationSpec(
        "long-march",
        "Q53665",
        (SatelliteCategory.ROCKET),
        prefix="CZ-",
    ),
    # -------------------------------------------------------------------------
    # US military constellations
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "vanguard",
        "Q179527",
        (SatelliteCategory.MILITARY),
        prefix="VANGUARD",
    ),
    # WGS: Wideband Global SATCOM — US DoD high-bandwidth GEO comms.
    ConstellationSpec(
        "wgs",
        "Q2567808",
        (SatelliteCategory.MILITARY, SatelliteCategory.COMMUNICATIONS),
        prefix="WGS",
    ),
    # Syncom IV / leasat.
    ConstellationSpec(
        "leasat",
        "Q545738",
        (SatelliteCategory.MILITARY, SatelliteCategory.COMMUNICATIONS),
        prefix="LEASAT",
    ),
    # AEHF: Advanced Extremely High Frequency — comms.
    ConstellationSpec(
        "aehf",
        "Q379544",
        (SatelliteCategory.MILITARY, SatelliteCategory.COMMUNICATIONS),
        prefix="AEHF",
    ),
    # MUOS: Mobile User Objective System — US Navy UHF narrowband satcom.
    ConstellationSpec(
        "muos",
        "Q1810552",
        (SatelliteCategory.MILITARY, SatelliteCategory.COMMUNICATIONS),
        prefix="MUOS",
    ),
    # SBIRS: Space-Based Infrared System — US missile warning (GEO + HEO).
    ConstellationSpec(
        "sbirs",
        "Q905215",
        (SatelliteCategory.MILITARY, SatelliteCategory.OBSERVATION),
        prefix="SBIRS",
    ),
    # DMSP: Defense Meteorological Satellite Program.
    ConstellationSpec(
        "dmsp",
        "Q1182618",
        (SatelliteCategory.MILITARY, SatelliteCategory.WEATHER),
        contains=("DMSP",),
    ),
    # DMP: Defense Support Program, early warning system (launches & nuke explosions)
    ConstellationSpec(
        "dsp",
        "Q1182623",
        (SatelliteCategory.MILITARY, SatelliteCategory.OBSERVATION),
        contains=("DSP ",),
    ),
    # SDA
    ConstellationSpec(
        "sda-praetorian", "Q75746123", SatelliteCategory.MILITARY, prefix="PRAETORIAN"
    ),
    ConstellationSpec("sda", "Q75746123", SatelliteCategory.MILITARY, prefix="SDA_"),
    # Blackjack: DARPA LEO military demonstration programme.
    ConstellationSpec(
        "blackjack", "Q96373675", SatelliteCategory.MILITARY, prefix="BLACKJACK"
    ),
    # Checkmate: classified LEO military programme.
    ConstellationSpec(
        "checkmate", None, SatelliteCategory.MILITARY, prefix="CHECKMATE"
    ),
    # USA: classified US national-security payloads (NRO, AFSPC, etc.)
    # Kept as last-resort for sats that match nothing more specific.
    ConstellationSpec("usa-classified", None, SatelliteCategory.MILITARY, prefix="USA"),
    # OPS: US military, classified into US air force due to https://en.wikipedia.org/wiki/SNAP-10A and launch times (pre-1980s)
    ConstellationSpec(
        "us-ops-classified", None, SatelliteCategory.MILITARY, prefix="OPS "
    ),
    # Titan rocket boosters, mostly military, ICBM-derived
    ConstellationSpec(
        "titan-rocket",
        "Q1136670",
        (SatelliteCategory.ROCKET, SatelliteCategory.MILITARY),
        prefix="TITAN",
    ),
    # -------------------------------------------------------------------------
    # US civilian / weather satellites
    # -------------------------------------------------------------------------
    # Syncom 1-3, early GEO com
    ConstellationSpec(
        "syncom",
        "Q545738",
        (SatelliteCategory.SCIENCE, SatelliteCategory.COMMUNICATIONS),
        prefix="SYNCOM ",
    ),
    # GOES: NOAA Geostationary Operational Environmental Satellites.
    ConstellationSpec("goes", "Q976688", SatelliteCategory.WEATHER, prefix="GOES"),
    ConstellationSpec("noaa", None, SatelliteCategory.WEATHER, prefix="NOAA"),
    ConstellationSpec(
        "jason",
        None,
        (SatelliteCategory.OBSERVATION, SatelliteCategory.SCIENCE),
        prefix="JASON",
    ),
    # Landsat: USGS/NASA land-surface imaging series.
    ConstellationSpec(
        "landsat", "Q849791", SatelliteCategory.OBSERVATION, prefix="LANDSAT"
    ),
    ConstellationSpec(
        "explorer",
        "Q603526",
        (SatelliteCategory.SCIENCE),
        prefix="EXPLORER",
    ),
    ConstellationSpec(
        "themis",
        "Q837500",
        (SatelliteCategory.SCIENCE),
        contains=("THEMIS",),
    ),
    # PE spinoff of a maxar division
    ConstellationSpec(
        "worldView-legion",
        "Q122398742",
        SatelliteCategory.OBSERVATION,
        prefix=("GEOEYE", "WORLDVIEW", "LEGION"),
    ),
    # Rocket stages
    ConstellationSpec(
        "falcon", "Q249091", SatelliteCategory.ROCKET, prefix="FALCON "
    ),  # Includes one falcon 1 stage
    ConstellationSpec("atlas", "Q22949", SatelliteCategory.ROCKET, prefix="ATLAS"),
    ConstellationSpec("delta", "Q49506", SatelliteCategory.ROCKET, prefix="DELTA"),
    ConstellationSpec(
        "electron", "Q18471030", SatelliteCategory.ROCKET, prefix="ELECTRON"
    ),
    ConstellationSpec(
        "thor", "Q249534", SatelliteCategory.ROCKET, prefix=("THORAD", "THOR ABLESTAR")
    ),
    ConstellationSpec("pslv", "Q221654", SatelliteCategory.ROCKET, prefix="PSLV"),
    ConstellationSpec("pegasus", "Q478603", SatelliteCategory.ROCKET, prefix="PEGASUS"),
    ConstellationSpec("saturn", "Q1285723", SatelliteCategory.ROCKET, prefix="SATURN"),
    ConstellationSpec("scout", "Q605072", SatelliteCategory.ROCKET, prefix="SCOUT"),
    ConstellationSpec("diamant", "Q49568", SatelliteCategory.ROCKET, prefix="DIAMANT"),
    ConstellationSpec("h-1", "Q1279552", SatelliteCategory.ROCKET, prefix="H-1"),
    ConstellationSpec("h-2", "Q548376", SatelliteCategory.ROCKET, prefix="H-2"),
    ConstellationSpec("gslv", "Q249238", SatelliteCategory.ROCKET, prefix="GSLV"),
    ConstellationSpec(
        "minotaur", "Q1727072", SatelliteCategory.ROCKET, prefix="MINOTAUR"
    ),
    ConstellationSpec("antares", "Q128683", SatelliteCategory.ROCKET, prefix="ANTARES"),
    ConstellationSpec("shavit", "Q876010", SatelliteCategory.ROCKET, prefix="SHAVIT"),
    ConstellationSpec(
        "epsilon", "Q1135682", SatelliteCategory.ROCKET, prefix="EPSILON"
    ),
    ConstellationSpec("vulcan", "Q19816744", SatelliteCategory.ROCKET, prefix="VULCAN"),
    ConstellationSpec(
        "firefly", "Q21512704", SatelliteCategory.ROCKET, prefix="FIREFLY"
    ),
    ConstellationSpec("safir", "Q142596", SatelliteCategory.ROCKET, prefix="SAFIR"),
    ConstellationSpec("kuaizhou", "Q15049837", SatelliteCategory.ROCKET, prefix="KZ-1"),
    ConstellationSpec(
        "lijian", "Q111745426", SatelliteCategory.ROCKET, prefix="LIJIAN"
    ),
    ConstellationSpec(
        "jielong", "Q115555344", SatelliteCategory.ROCKET, prefix="JIELONG"
    ),
    ConstellationSpec(
        "mu-rocket",
        "Q218381",
        SatelliteCategory.ROCKET,
        prefix=("M-3S", "M-3C", "M-3H", "M-4S", "M-V"),
    ),
    # Upper stages — shared across multiple rocket families
    ConstellationSpec(
        "ius", "Q1662192", SatelliteCategory.UPPER_STAGE, prefix="IUS"
    ),  # Inertial Upper Stage
    ConstellationSpec(
        "block-dm", "Q219166", SatelliteCategory.UPPER_STAGE, prefix="BLOCK"
    ),
    ConstellationSpec(
        "yuanzheng", "Q20871633", SatelliteCategory.UPPER_STAGE, prefix="YZ-1"
    ),
    ConstellationSpec(
        "vega", None, SatelliteCategory.ROCKET, prefix="AVUM"
    ),  # avum is vega's upper stage
    # -------------------------------------------------------------------------
    # US commercial constellations
    # -------------------------------------------------------------------------
    # HawkEye 360: RF geolocation cluster constellation.
    ConstellationSpec(
        "hawkeye360", None, SatelliteCategory.OBSERVATION, prefix=("HAWK", "KESTREL-")
    ),
    # Capella Space: commercial SAR imaging constellation.
    ConstellationSpec("capella", None, SatelliteCategory.OBSERVATION, prefix="CAPELLA"),
    # Wildfire: wildfire-detection EO constellation TODO: (Tomorrow.io subsidiary?)
    ConstellationSpec(
        "wildfire", None, SatelliteCategory.OBSERVATION, prefix="WILDFIRE"
    ),
    # EchoStar / DISH: GEO broadcast + broadband (ECHOSTAR-N, JUPITER-N).
    ConstellationSpec(
        "echostar", "Q97217972", SatelliteCategory.COMMUNICATIONS, prefix="ECHOSTAR"
    ),
    # ViaSat: GEO high-throughput broadband (VIASAT-1, VIASAT-3 F1/F2/F3).
    ConstellationSpec(
        "viasat", None, SatelliteCategory.COMMUNICATIONS, prefix="VIASAT"
    ),
    # Lynk Global: direct-to-standard-cell IoT/broadband LEO constellation.
    ConstellationSpec("lynk", None, SatelliteCategory.COMMUNICATIONS, prefix="LYNK"),
    # ICEYE: Finnish SAR company, sells & operates sats (so country codes varies)
    ConstellationSpec("iceye", None, SatelliteCategory.OBSERVATION, prefix="ICEYE"),
    # Tomorrow.io: commercial weather-monitoring microsatellite constellation.
    ConstellationSpec(
        "tomorrow-io", None, SatelliteCategory.WEATHER, prefix="TOMORROW"
    ),
    # Planet Labs Pelican: next-gen high-revisit EO constellation.
    ConstellationSpec(
        "planet-pelican", None, SatelliteCategory.OBSERVATION, prefix="PELICAN"
    ),
    # AST SpaceMobile: direct-to-cell broadband LEO constellation.
    ConstellationSpec(
        "ast-spacemobile",
        "Q131940547",
        SatelliteCategory.COMMUNICATIONS,
        prefix="SPACEMOBILE",
    ),
    # APrizeSat: low-cost store-and-forward IoT messaging (SpaceQuest).
    ConstellationSpec(
        "aprizesat",
        "Q17512448",
        SatelliteCategory.COMMUNICATIONS,
        prefix=("APRIZESAT", "LatinSat"),
    ),
    # AeroCube: Aerospace Corporation technology-demonstration cubesats.
    ConstellationSpec(
        "aerocube",
        None,
        SatelliteCategory.SCIENCE,
        prefix="AEROCUBE",
        url="https://aerospace.org/paper/aerospace-corporations-aerocube-program",
    ),
    # D-Orbit ION Satellite Carrier: in-space transportation / hosted payload buses.
    ConstellationSpec(
        "d-orbit-ion", "Q65084209", SatelliteCategory.SPACE_TUG, prefix="ION "
    ),
    # Early weather satellites
    ConstellationSpec(
        "Television-Infrared-Observation-Satellite",
        "Q2141538",
        SatelliteCategory.WEATHER,
        prefix="TIROS",
    ),
    # ISS crewed / cargo vehicles catalogued as separate objects by NORAD.
    ConstellationSpec(
        "cygnus", "Q127924", SatelliteCategory.UNMANNED_CARGO, prefix="CYGNUS"
    ),
    ConstellationSpec(
        "crew-dragon",
        "Q105095031",
        SatelliteCategory.MANNED_CAPSULE,
        prefix="CREW DRAGON",
    ),
    ConstellationSpec(
        "apollo", "Q46611", SatelliteCategory.MANNED_CAPSULE, prefix="APOLLO"
    ),
    ConstellationSpec(
        "sts", "Q1775296", SatelliteCategory.MANNED_CAPSULE, prefix="STS"
    ),
    ConstellationSpec(
        "dragon", "Q236448", SatelliteCategory.UNMANNED_CARGO, prefix="DRAGON"
    ),
    # Science / geodetic
    ConstellationSpec("pageos", "Q2043671", SatelliteCategory.SCIENCE, prefix="PAGEOS"),
    ConstellationSpec("venera", "Q192144", SatelliteCategory.SCIENCE, prefix="VENERA"),
    ConstellationSpec("nimbus", "Q609455", SatelliteCategory.SCIENCE, prefix="NIMBUS"),
    # US reconnaissance
    ConstellationSpec(
        "corona",
        "Q256812",
        (SatelliteCategory.MILITARY, SatelliteCategory.OBSERVATION),
        prefix="DISCOVERER",
    ),
    # Russian/Soviet weather
    ConstellationSpec("meteor", "Q1925316", SatelliteCategory.WEATHER, prefix="METEOR"),
    # -------------------------------------------------------------------------
    # European constellations
    # -------------------------------------------------------------------------
    # IRIDE: Italian national Earth observation constellation (ESA/ASI mandate,
    # prime contractor Thales Alenia Space Italia).
    ConstellationSpec(
        "iride", "Q137485492", SatelliteCategory.OBSERVATION, prefix="IRIDE"
    ),
    ConstellationSpec(
        "sentinel", "Q4303731", SatelliteCategory.OBSERVATION, prefix="SENTINEL"
    ),
    ConstellationSpec("ariane", "Q131535", SatelliteCategory.ROCKET, prefix="ARIANE"),
    # -------------------------------------------------------------------------
    # Russian/Soviet (CIS) constellations
    # -------------------------------------------------------------------------
    # US-A: soviet nuclear-powered radar satellites
    ConstellationSpec(
        "us-a",
        "Q1542629",
        (SatelliteCategory.MILITARY, SatelliteCategory.OBSERVATION),
        satellites=[
            "COSMOS 209",
            "COSMOS 367",
            "COSMOS 402",
            "COSMOS 469",
            "COSMOS 516",
            "COSMOS 626",
            "COSMOS 651",
            "COSMOS 654",
            "COSMOS 723",
            "COSMOS 724",
            "COSMOS 785",
            "COSMOS 860",
            "COSMOS 861",
            "COSMOS 952",
            "COSMOS 954",
            "COSMOS 1176",
            "COSMOS 1266",
            "COSMOS 1299",
            "COSMOS 1249",
            "COSMOS 1402",
            "COSMOS 1372",
            "COSMOS 1365",
            "COSMOS 1412",
            "COSMOS 1579",
            "COSMOS 1607",
            "COSMOS 1670",
            "COSMOS 1677",
            "COSMOS 1771",
            "COSMOS 1736",
            "COSMOS 1818",
            "COSMOS 1860",
            "COSMOS 1867",
            "COSMOS 1900",
            "COSMOS 1932",
        ],
    ),
    # Geostationary, high bandwidth, Ekspress-2000
    ConstellationSpec(
        "blagovest",
        "Q39074459",
        (SatelliteCategory.MILITARY, SatelliteCategory.COMMUNICATIONS),
        satellites=[
            "COSMOS 2520",
            "COSMOS 2526",
            "COSMOS 2533",
            "COSMOS 2539",
        ],
    ),
    # Communication sats with high eccentricity orbits, for good polar coverage
    ConstellationSpec(
        "molniya",
        "Q593283",
        (SatelliteCategory.MILITARY, SatelliteCategory.COMMUNICATIONS),
        prefix="MOLNIYA",
    ),
    # COSMOS: generic classified satellites, TODO: not all are military
    ConstellationSpec("cosmos", "Q147802", SatelliteCategory.MILITARY, prefix="COSMOS"),
    # Rassvet- Russian commercial broadband LEO (X holding).
    ConstellationSpec(
        "rassvet", "Q124753962", SatelliteCategory.COMMUNICATIONS, prefix="RASSVET"
    ),
    # Yamal: Russian geostationary communications (Gazprom Space Systems).
    ConstellationSpec(
        "yamal", "Q3656794", SatelliteCategory.COMMUNICATIONS, prefix="YAMAL"
    ),
    ConstellationSpec(
        "sputnik", "Q170413", SatelliteCategory.SCIENCE, prefix="SPUTNIK"
    ),
    ConstellationSpec(
        "soyuz", "Q579421", SatelliteCategory.MANNED_CAPSULE, prefix="SOYUZ"
    ),
    ConstellationSpec(
        "progress", "Q309363", SatelliteCategory.UNMANNED_CARGO, prefix="PROGRESS"
    ),
    ConstellationSpec(
        "salyut", "Q207933", SatelliteCategory.STATION, prefix="SALYUT"
    ),  # some were military, documented in individual pages (good coverage)
    ConstellationSpec("mir", "Q48604", SatelliteCategory.STATION, prefix="MIR"),
    ConstellationSpec(
        "soyuz-rocket", "Q579421", SatelliteCategory.ROCKET, prefix="SL-"
    ),  # Soyuz rocket spent stages & debris
    ConstellationSpec(
        "fregat", "Q1453740", SatelliteCategory.ROCKET, prefix="FREGAT"
    ),  # Upper stages (mostly Soyuz)
    ConstellationSpec(
        "proton-m", "Q1756423", SatelliteCategory.ROCKET, prefix="BREEZE"
    ),  # Proton-M rocket spent stages & debris
    # -------------------------------------------------------------------------
    # Derived from CelesTrak group membership
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "orbcomm", "Q16960684", SatelliteCategory.COMMUNICATIONS, group="orbcomm"
    ),  # all are named "ORBCOMM-..." except VESSELSAT, which are part of the constellation
    ConstellationSpec(
        "intelsat", "Q778126", SatelliteCategory.COMMUNICATIONS, group="intelsat"
    ),
    ConstellationSpec("ses", "Q333025", SatelliteCategory.COMMUNICATIONS, group="ses"),
    ConstellationSpec(
        "eutelsat", "Q848336", SatelliteCategory.COMMUNICATIONS, prefix="EUTELSAT"
    ),  # include Ekspress-AT
    ConstellationSpec(
        "telesat", "Q2401935", SatelliteCategory.COMMUNICATIONS, group="telesat"
    ),
    ConstellationSpec(
        "anik", "Q546687", SatelliteCategory.COMMUNICATIONS, contains=("ANIK",)
    ),
    ConstellationSpec(
        "jsat", "Q11225562", SatelliteCategory.COMMUNICATIONS, contains=("JCSAT",)
    ),
    ConstellationSpec(
        "superbird",
        "Q11245057",
        SatelliteCategory.COMMUNICATIONS,
        contains=("SUPERBIRD",),
    ),
    ConstellationSpec(
        "horizons",
        "Q5903528",
        SatelliteCategory.COMMUNICATIONS,
        contains=("HORIZONS-",),
    ),  # Joint venture
    ConstellationSpec(
        "dsn",
        "Q11245057",
        (SatelliteCategory.COMMUNICATIONS, SatelliteCategory.MILITARY),
        contains=(
            "DSN-",
            "Superbird-B3",
        ),
    ),  # Japanese military GEO comm sats, joint venture
    ConstellationSpec(
        "thor",
        "Q73877",
        SatelliteCategory.COMMUNICATIONS,
        contains=("THOR ", "MARCOPOLO", "INTELSAT 10-02"),
    ),
    ConstellationSpec("gps", "Q18822", SatelliteCategory.NAVIGATION, group="gps-ops"),
    ConstellationSpec(
        "glonass", "Q486250", SatelliteCategory.NAVIGATION, group="glo-ops"
    ),
    ConstellationSpec(
        "galileo", "Q193902", SatelliteCategory.NAVIGATION, group="galileo"
    ),
    ConstellationSpec(
        "beidou", "Q857141", SatelliteCategory.NAVIGATION, group="beidou"
    ),
    ConstellationSpec(
        "transit", "Q651136", SatelliteCategory.NAVIGATION, group="nnss"
    ),  # Navy Navigation Satellite System
    ConstellationSpec(
        "sbas", "Q2165162", SatelliteCategory.NAVIGATION, group="sbas"
    ),  # generic "constellation"
    ConstellationSpec(
        "fengyun-1c-asat-debris",
        "Q182183",
        SatelliteCategory.DEBRIS,
        group="fengyun-1c-debris",
    ),
    ConstellationSpec(
        "iridium-33-debris",
        "Q843912",
        SatelliteCategory.DEBRIS,
        group="iridium-33-debris",
    ),
    ConstellationSpec(
        "cosmos-2251-debris",
        "Q843912",
        SatelliteCategory.DEBRIS,
        group="cosmos-2251-debris",
    ),
    ConstellationSpec(
        "tdrss", "Q3522774", SatelliteCategory.COMMUNICATIONS, group="tdrss"
    ),
    ConstellationSpec("argos", "Q649489", SatelliteCategory.OBSERVATION, group="argos"),
    # -------------------------------------------------------------------------
    # Derived from SATCAT SOURCE/OWNER code
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "arabsat", "Q65277396", SatelliteCategory.COMMUNICATIONS, source="AB"
    ),
    ConstellationSpec(
        "abs", "Q18238088", SatelliteCategory.COMMUNICATIONS, source="ABS"
    ),
    ConstellationSpec(
        "asiasat", "Q726812", SatelliteCategory.COMMUNICATIONS, source="AC"
    ),
    ConstellationSpec(
        "new-ico", "Q3792482", SatelliteCategory.COMMUNICATIONS, source="NICO"
    ),
    ConstellationSpec(
        "o3b", "Q3347484", SatelliteCategory.COMMUNICATIONS, source="O3B"
    ),
    ConstellationSpec(
        "rascomstar", "Q3415056", SatelliteCategory.COMMUNICATIONS, source="RASC"
    ),
    # -------------------------------------------------------------------------
    # Classified payloads — fallback for "OBJECT X" names, keyed by SATCAT owner
    # -------------------------------------------------------------------------
    ConstellationSpec("prc-classified", None, SatelliteCategory.MILITARY),
    ConstellationSpec("cis-classified", None, SatelliteCategory.MILITARY),
    ConstellationSpec("skor-classified", None, SatelliteCategory.MILITARY),
    ConstellationSpec("iran-classified", None, SatelliteCategory.MILITARY),
)


CONSTELLATION_BY_SLUG: dict[str, ConstellationSpec] = {
    c.slug: c for c in CONSTELLATIONS
}

PREFIX_TO_SLUG: dict[str, str] = dict(
    sorted(
        (
            (p, c.slug)
            for c in CONSTELLATIONS
            if c.prefix is not None
            for p in (c.prefix if isinstance(c.prefix, tuple) else (c.prefix,))
        ),
        key=lambda kv: -len(kv[0]),
    )
)

CONTAINS_TO_SLUG: dict[str, str] = {
    k: c.slug for c in CONSTELLATIONS if c.contains is not None for k in c.contains
}

GROUP_TO_SLUG: dict[str, str] = {
    c.group: c.slug for c in CONSTELLATIONS if c.group is not None
}

SOURCE_TO_SLUG: dict[str, str] = {
    c.source: c.slug for c in CONSTELLATIONS if c.source is not None
}

# SATCAT owner code → classified constellation for "OBJECT X" payloads.
# US is already handled by usa-classified (prefix "USA") and us-ops-classified.
CLASSIFIED_BY_OWNER: dict[str, str] = {
    "PRC": "prc-classified",
    "CIS": "cis-classified",
    "SKOR": "skor-classified",
    "IRAN": "iran-classified",
    "US": "usa-classified",
}

# When several rules match the same sat (name-prefix vs group vs source),
# slugs listed here win — in order. Used to resolve conflicts like a debris
# fragment of Iridium-33 that would otherwise also match the "iridium" prefix.
PREFERRED_SLUGS: tuple[str, ...] = (
    "fengyun-1c-asat-debris",
    "iridium-33-debris",
    "cosmos-2251-debris",
    "o3b",  # more specific than SES (its parent operator)
)

# Opposite of PREFERRED_SLUGS: in case of conflict, any other candidate is preferred over these.
UNPREFERRED_SLUGS: frozenset[str] = frozenset(
    {
        "thor"  # thor rocket is more specific, few entries that don't match its prefixes are thor sats
        "sbas",  # type of sat
        "argos",
        "usa-classified",
        "us-ops-classified",
        "cosmos",
        "tdrss",  # secondary use of some sats (iss)
        "intelsat",  # Multiple constellations
        *CLASSIFIED_BY_OWNER.values(),
    }
)

# CelesTrak groups that tag sats with a category directly, without belonging to
# a named constellation. See https://celestrak.org/NORAD/elements/.
GROUP_TO_CATEGORY: dict[str, SatelliteCategory] = {
    "military": SatelliteCategory.MILITARY,
    "radar": SatelliteCategory.MISCELLANEOUS,
    "other-comm": SatelliteCategory.COMMUNICATIONS,
    "analyst": SatelliteCategory.DEBRIS,
    "stations": SatelliteCategory.STATION,
    "dmc": SatelliteCategory.DISASTER,
    "sarsat": SatelliteCategory.DISASTER,
    "science": SatelliteCategory.SCIENCE,
    "engineering": SatelliteCategory.SCIENCE,
    "education": SatelliteCategory.SCIENCE,
    "geodetic": SatelliteCategory.SCIENCE,
}


def slug_from_name(name: str | None) -> str | None:
    if not name:
        return None
    for prefix, slug in PREFIX_TO_SLUG.items():
        if name.startswith(prefix):
            return slug
    for keyword, slug in CONTAINS_TO_SLUG.items():
        if keyword in name:
            return slug
    return None
