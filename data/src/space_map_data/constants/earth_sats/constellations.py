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
    category: tuple[SatelliteCategory, ...]
    prefix: str | tuple[str, ...] | None = None  # TLE OBJECT_NAME startswith
    contains: tuple[str, ...] | None = None  # like prefix but anywhere in the name
    group: str | None = None  # CelesTrak gp.php GROUP slug
    source: str | None = None  # SATCAT SOURCE/OWNER code
    url: str | None = None  # When no wikipedia link
    satellites: list[str] | None = None  # List of member names
    object_id_prefix: str | tuple[str, ...] | None = None  # COSPAR launch-ID core


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
        "starlink", "Q19867977", (SatelliteCategory.COMMUNICATIONS,), prefix="STARLINK"
    ),
    ConstellationSpec(
        "oneweb", "Q17184117", (SatelliteCategory.COMMUNICATIONS,), prefix="ONEWEB"
    ),
    ConstellationSpec(
        "iridium", "Q3154356", (SatelliteCategory.COMMUNICATIONS,), prefix="IRIDIUM"
    ),
    ConstellationSpec(
        "kuiper", "Q62812537", (SatelliteCategory.COMMUNICATIONS,), prefix="KUIPER"
    ),
    ConstellationSpec(
        "qianfan", "Q124981442", (SatelliteCategory.COMMUNICATIONS,), prefix="QIANFAN"
    ),
    ConstellationSpec(
        "guowang",
        "Q123581514",
        (SatelliteCategory.COMMUNICATIONS,),
        prefix="HULIANWANG",
    ),  # HULIANWANG JISHU, HULIANWAN GAOGUI, HULIANWANG DIGUI (that's the big one, first 2 are experimental?)
    ConstellationSpec(
        "globalstar",
        "Q1202533",
        (SatelliteCategory.COMMUNICATIONS,),
        prefix="GLOBALSTAR",
    ),
    ConstellationSpec(
        "planet-flock", "Q97380305", (SatelliteCategory.OBSERVATION,), prefix="FLOCK"
    ),
    ConstellationSpec(
        "planet-skysat", "Q27031816", (SatelliteCategory.OBSERVATION,), prefix="SKYSAT"
    ),
    ConstellationSpec(
        "spacebee", "Q105334563", (SatelliteCategory.COMMUNICATIONS,), prefix="SPACEBEE"
    ),
    ConstellationSpec(
        "sitro-ais", None, (SatelliteCategory.COMMUNICATIONS,), prefix="SITRO-AIS"
    ),
    ConstellationSpec(
        "geesat", "Q125167295", (SatelliteCategory.COMMUNICATIONS,), prefix="GEESAT"
    ),
    ConstellationSpec(
        "gonets", "Q2041033", (SatelliteCategory.COMMUNICATIONS,), prefix="GONETS"
    ),
    ConstellationSpec(
        "tianqi",
        None,
        (SatelliteCategory.COMMUNICATIONS,),
        prefix="TIANQI-",
        url="https://www.guodiangaoke.com/web/dist/index.html#/tianqixingzuo",
    ),  # Hyphen-anchored; bare "TIANQI" would catch TIANQIN 1 (gravity-wave demo).
    ConstellationSpec(
        "connecta-iot",
        None,
        (SatelliteCategory.COMMUNICATIONS,),
        prefix="CONNECTA IOT",
        url="https://www.connectasat.com/technology/satellite-iot/",
    ),
    ConstellationSpec(
        "tianmu", "Q124168307", (SatelliteCategory.WEATHER,), prefix="TIANMU-1"
    ),
    ConstellationSpec(
        "spire", "Q19877982", (SatelliteCategory.OBSERVATION,), prefix="LEMUR"
    ),
    ConstellationSpec(
        "marecs", "Q1881172", (SatelliteCategory.COMMUNICATIONS,), prefix="MARECS"
    ),
    ConstellationSpec(
        "marisat", "Q6765591", (SatelliteCategory.COMMUNICATIONS,), prefix="MARISAT"
    ),
    ConstellationSpec(
        "inmarsat", "Q827927", (SatelliteCategory.COMMUNICATIONS,), prefix="INMARSAT"
    ),
    ConstellationSpec("metop", "Q819651", (SatelliteCategory.WEATHER,), prefix="METOP"),
    ConstellationSpec(
        "meteosat", "Q1429889", (SatelliteCategory.WEATHER,), prefix="METEOSAT"
    ),
    ConstellationSpec(
        "measat",
        None,
        (SatelliteCategory.COMMUNICATIONS,),
        prefix="MEASAT",
        url="https://www.measat.com/our-coverage/measat-fleet/",
    ),
    ConstellationSpec(
        "africasat",
        "Q20052527",
        (SatelliteCategory.COMMUNICATIONS,),
        prefix="AFRICASAT",
    ),
    ConstellationSpec(
        "thaicom", None, (SatelliteCategory.COMMUNICATIONS,), prefix="THAICOM"
    ),
    ConstellationSpec(
        "fengyun", "Q1404722", (SatelliteCategory.WEATHER,), prefix="FENGYUN"
    ),
    ConstellationSpec(
        "galaxy", "Q832041", (SatelliteCategory.COMMUNICATIONS,), prefix="GALAXY"
    ),
    # TODO:
    # SCS-* - https://www.scs-space.com?
    # -------------------------------------------------------------------------
    # Chinese EO / mapping constellations (PRC owner)
    # -------------------------------------------------------------------------
    # XW, camsat: chinese amateur radio
    ConstellationSpec("xw", None, (SatelliteCategory.COMMUNICATIONS,), prefix="XW"),
    ConstellationSpec("cas", None, (SatelliteCategory.COMMUNICATIONS,), prefix="CAS-"),
    # Jilin-1: largest Chinese commercial EO constellation (CGST / Chang Guang).
    ConstellationSpec(
        "jilin", "Q123139897", (SatelliteCategory.OBSERVATION,), prefix="JILIN"
    ),
    # Gaofen: CNSA civil high-resolution EO programme (government/dual-use)
    ConstellationSpec(
        "gaofen", "Q18669407", (SatelliteCategory.OBSERVATION,), prefix="GAOFEN"
    ),
    # SuperView / Gaojing: commercial VHR EO (Beijing Space View / SI Imaging)
    ConstellationSpec(
        "superview-china-siwei",
        "Q135765238",
        (SatelliteCategory.OBSERVATION,),
        prefix="SUPERVIEW",
    ),
    # Zhuhai: hyperspectral/SAR constellation (Orbita Aerospace)
    ConstellationSpec(
        "zhuhai",
        None,
        (SatelliteCategory.OBSERVATION,),
        prefix="ZHUHAI-",
        url="https://www.obtdata.com/en/zhuhai1.html",
    ),
    # Yunyao-1: commercial weather
    ConstellationSpec(
        "yunyao", "Q124256662", (SatelliteCategory.WEATHER,), prefix="YUNYAO-1"
    ),
    # Haiyang: CNSA ocean color and dynamics satellites
    ConstellationSpec(
        "haiyang", "Q2362851", (SatelliteCategory.OBSERVATION,), prefix="HAIYANG"
    ),
    # TODO: check
    # - NINGXIA-1: https://www.newspace.im/constellations/ningxia
    # - DONGPO: ????
    # Centispace-1: Chinese nav-augmentation LEO constellation (Beijing Future Navigation Technology)?
    ConstellationSpec(
        "centispace", None, (SatelliteCategory.NAVIGATION,), prefix="CENTISPACE-"
    ),
    # Tianlian I / II: Chinese TDRSS equivalent (relay / tracking, CNSA)
    ConstellationSpec(
        "tianlian", "Q7800236", (SatelliteCategory.COMMUNICATIONS,), prefix="TIANLIAN"
    ),  # Also Q67931551 but that has very low coverage
    # Tiantong-1: Chinese mobile satellite comms (CASC / China Satcom)
    ConstellationSpec(
        "tiantong",
        "Q105274818",
        (SatelliteCategory.COMMUNICATIONS,),
        prefix="TIANTONG-",
    ),
    # Zhongxing / Chinasat: Chinese military and civil GEO comms (CASC / CASIC).
    # SATCAT uses "ZHONGXING-N" and "CHINASAT N" interchangeably.
    ConstellationSpec(
        "zhongxing", None, (SatelliteCategory.COMMUNICATIONS,), prefix="ZHONGXING"
    ),
    ConstellationSpec(
        "chinasat", None, (SatelliteCategory.COMMUNICATIONS,), prefix="CHINASAT"
    ),
    # Chinese Space Station (CSS): core module TIANHE + labs WENTIAN / MENGTIAN.
    ConstellationSpec(
        "chinese-space-station", "Q5100935", (SatelliteCategory.STATION,), prefix="CSS "
    ),
    # International Space Station: TLE names start with "ISS".
    ConstellationSpec("iss", "Q25271", (SatelliteCategory.STATION,), prefix="ISS"),
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
        "shijian", "Q11452851", (SatelliteCategory.SCIENCE,), prefix=("SHIJIAN", "SJ")
    ),  # "Practice"
    ConstellationSpec(
        "chuangxin", None, (SatelliteCategory.SCIENCE,), prefix=("CHUANGXIN")
    ),  # "Innovation"
    ConstellationSpec(
        "shiyan", "Q2279595", (SatelliteCategory.SCIENCE,), prefix=("SHIYAN")
    ),  # "Experiment"
    # Long march boosters
    ConstellationSpec(
        "long-march",
        "Q53665",
        (SatelliteCategory.ROCKET,),
        prefix="CZ-",
    ),
    # -------------------------------------------------------------------------
    # US military constellations
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "vanguard",
        "Q179527",
        (SatelliteCategory.MILITARY,),
        prefix="VANGUARD",
    ),
    ConstellationSpec(
        "uhf-follow-on",
        "Q941216",
        (SatelliteCategory.MILITARY,),
        prefix="UFO ",
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
        "sda-praetorian",
        "Q75746123",
        (SatelliteCategory.MILITARY,),
        prefix="PRAETORIAN",
    ),
    ConstellationSpec("sda", "Q75746123", (SatelliteCategory.MILITARY,), prefix="SDA_"),
    # Blackjack: DARPA LEO military demonstration programme.
    ConstellationSpec(
        "blackjack", "Q96373675", (SatelliteCategory.MILITARY,), prefix="BLACKJACK"
    ),
    # Checkmate: classified LEO military programme.
    ConstellationSpec(
        "checkmate", None, (SatelliteCategory.MILITARY,), prefix="CHECKMATE"
    ),
    # USA: classified US national-security payloads (NRO, AFSPC, etc.)
    # Kept as last-resort for sats that match nothing more specific.
    ConstellationSpec(
        "usa-classified", None, (SatelliteCategory.MILITARY,), contains=("USA ",)
    ),
    # OPS: US military, classified into US air force due to https://en.wikipedia.org/wiki/SNAP-10A and launch times (pre-1980s)
    ConstellationSpec(
        "us-ops-classified", None, (SatelliteCategory.MILITARY,), prefix="OPS "
    ),
    # Titan rocket boosters, mostly military, ICBM-derived
    ConstellationSpec(
        "titan-rocket",
        "Q1136670",
        (SatelliteCategory.ROCKET, SatelliteCategory.MILITARY),
        prefix="TITAN",
    ),
    # OVx: US Air Force Orbiting Vehicle series (1960s-1970s), mostly military.
    ConstellationSpec(
        "orbiting-vehicle-1",
        "Q7100108",
        (SatelliteCategory.SCIENCE, SatelliteCategory.MILITARY),
        contains=("OV1",),
    ),
    ConstellationSpec(
        "orbiting-vehicle-2",
        "Q7100108",
        (SatelliteCategory.SCIENCE, SatelliteCategory.MILITARY),
        contains=("OV2",),
    ),
    ConstellationSpec(
        "orbiting-vehicle-3",
        "Q7100108",
        (SatelliteCategory.SCIENCE, SatelliteCategory.MILITARY),
        contains=("OV3",),
    ),
    ConstellationSpec(
        "orbiting-vehicle-4",
        "Q7100108",
        (SatelliteCategory.SCIENCE, SatelliteCategory.MILITARY),
        contains=("OV4",),
    ),
    ConstellationSpec(
        "orbiting-vehicle-5",
        "Q7100108",
        (SatelliteCategory.SCIENCE, SatelliteCategory.MILITARY),
        contains=("OV5",),
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
    ConstellationSpec("goes", "Q976688", (SatelliteCategory.WEATHER,), prefix="GOES"),
    ConstellationSpec("noaa", None, (SatelliteCategory.WEATHER,), prefix="NOAA"),
    ConstellationSpec(
        "jason",
        None,
        (SatelliteCategory.OBSERVATION, SatelliteCategory.SCIENCE),
        prefix="JASON",
    ),
    # Landsat: USGS/NASA land-surface imaging series.
    ConstellationSpec(
        "landsat", "Q849791", (SatelliteCategory.OBSERVATION,), prefix="LANDSAT"
    ),
    ConstellationSpec(
        "explorer",
        "Q603526",
        (SatelliteCategory.SCIENCE,),
        prefix="EXPLORER",
    ),
    ConstellationSpec(
        "themis",
        "Q837500",
        (SatelliteCategory.SCIENCE,),
        contains=("THEMIS",),
    ),
    # PE spinoff of a maxar division
    ConstellationSpec(
        "worldView-legion",
        "Q122398742",
        (SatelliteCategory.OBSERVATION,),
        prefix=("GEOEYE", "WORLDVIEW", "LEGION"),
    ),
    # -------------------------------------------------------------------------
    # Rockets/upper stages
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "falcon",
        "Q249091",
        (SatelliteCategory.ROCKET,),
        prefix=("FALCON 1", "FALCON 9", "FALCON HEAVY"),
    ),  # Includes one falcon 1 stage. Bare "FALCON " would catch UAE FALCON EYE.
    ConstellationSpec("atlas", "Q22949", (SatelliteCategory.ROCKET,), prefix="ATLAS"),
    ConstellationSpec("delta", "Q49506", (SatelliteCategory.ROCKET,), prefix="DELTA"),
    ConstellationSpec(
        "electron", "Q18471030", (SatelliteCategory.ROCKET,), prefix="ELECTRON"
    ),
    ConstellationSpec(
        "thor-rocket",
        "Q249534",
        (SatelliteCategory.ROCKET,),
        # Thor/Thorad booster stacks. AGENA/BURNER stages get their own
        # cross-family entries below; "THOR 5/6/7" are Telenor comsats (thor).
        prefix=("THOR ABLE", "THOR ALTAIR", "THOR DELTA", "THORAD DELTA"),
    ),
    ConstellationSpec("pslv", "Q221654", (SatelliteCategory.ROCKET,), prefix="PSLV"),
    ConstellationSpec(
        "pegasus", "Q478603", (SatelliteCategory.ROCKET,), prefix="PEGASUS"
    ),
    ConstellationSpec(
        "saturn", "Q1285723", (SatelliteCategory.ROCKET,), prefix="SATURN"
    ),
    ConstellationSpec("scout", "Q605072", (SatelliteCategory.ROCKET,), prefix="SCOUT"),
    ConstellationSpec(
        "diamant", "Q49568", (SatelliteCategory.ROCKET,), prefix="DIAMANT"
    ),
    ConstellationSpec(
        "black-arrow", "Q35307", (SatelliteCategory.ROCKET,), prefix="BLACK ARROW"
    ),
    ConstellationSpec("h-1", "Q1279552", (SatelliteCategory.ROCKET,), prefix="H-1"),
    ConstellationSpec("h-2", "Q548376", (SatelliteCategory.ROCKET,), prefix="H-2"),
    ConstellationSpec(
        "n-1-japan", "Q618897", (SatelliteCategory.ROCKET,), prefix="N-1"
    ),  # NASDA N-I (licensed Thor-Delta); catalogued "N-1 R/B".
    ConstellationSpec(
        "n-2-japan", "Q3130574", (SatelliteCategory.ROCKET,), prefix="N-2"
    ),
    ConstellationSpec("h3", "Q11222053", (SatelliteCategory.ROCKET,), prefix="H-3"),
    ConstellationSpec("gslv", "Q249238", (SatelliteCategory.ROCKET,), prefix="GSLV"),
    ConstellationSpec(
        "minotaur", "Q1727072", (SatelliteCategory.ROCKET,), prefix="MINOTAUR"
    ),
    ConstellationSpec(
        "antares", "Q128683", (SatelliteCategory.ROCKET,), prefix="ANTARES"
    ),
    ConstellationSpec(
        "shavit", "Q876010", (SatelliteCategory.ROCKET,), prefix="SHAVIT"
    ),
    ConstellationSpec(
        "epsilon", "Q1135682", (SatelliteCategory.ROCKET,), prefix="EPSILON"
    ),
    ConstellationSpec(
        "vulcan", "Q19816744", (SatelliteCategory.ROCKET,), prefix="VULCAN"
    ),
    ConstellationSpec(
        "firefly", "Q21512704", (SatelliteCategory.ROCKET,), prefix="FIREFLY"
    ),
    ConstellationSpec(
        "kuaizhou", "Q15049837", (SatelliteCategory.ROCKET,), prefix="KZ-1"
    ),
    ConstellationSpec(
        "lijian", "Q111745426", (SatelliteCategory.ROCKET,), prefix="LIJIAN"
    ),
    ConstellationSpec(
        "jielong", "Q115555344", (SatelliteCategory.ROCKET,), prefix="JIELONG"
    ),
    ConstellationSpec(
        "mu-rocket",
        "Q218381",
        (SatelliteCategory.ROCKET,),
        prefix=("M-3S", "M-3C", "M-3H", "M-4S", "M-V"),
    ),
    # Upper stages — shared across multiple rocket families
    ConstellationSpec(
        "ius", "Q1662192", (SatelliteCategory.UPPER_STAGE,), prefix="IUS"
    ),  # Inertial Upper Stage
    ConstellationSpec(
        "block-dm", "Q219166", (SatelliteCategory.UPPER_STAGE,), prefix="BLOCK"
    ),
    ConstellationSpec(
        "yuanzheng", "Q20871633", (SatelliteCategory.UPPER_STAGE,), prefix="YZ-1"
    ),
    ConstellationSpec(
        "vega", "Q262629", (SatelliteCategory.ROCKET,), prefix="AVUM"
    ),  # AVUM is Vega's upper stage
    ConstellationSpec(
        "agena", "Q16862", (SatelliteCategory.UPPER_STAGE,), contains=("AGENA",)
    ),
    # No "centaur" entry: every Centaur in SATCAT is booster-prefixed
    # (ATLAS/TITAN/VULCAN CENTAUR) and so resolves to atlas/titan-rocket/vulcan.
    ConstellationSpec(
        "burner", "Q4356935", (SatelliteCategory.UPPER_STAGE,), contains=("BURNER",)
    ),
    ConstellationSpec(
        "pam-star",
        "Q1424161",
        (SatelliteCategory.UPPER_STAGE,),
        contains=("[PAM-", "STAR 37", "STAR 48"),
    ),  # PAM-D/A bracketed tags + Thiokol Star-37/48 apogee motors.
    ConstellationSpec(
        "iabs", "Q110419336", (SatelliteCategory.UPPER_STAGE,), prefix="IABS"
    ),
    ConstellationSpec(
        "volga", "Q12090276", (SatelliteCategory.UPPER_STAGE,), prefix="VOLGA"
    ),
    ConstellationSpec(
        "athena",
        "Q22770",
        (SatelliteCategory.ROCKET,),
        prefix=("ATHENA 1", "ATHENA 2"),
    ),  # Bare "ATHENA" would catch ATHENA-FIDUS / ATHENA EPIC payloads.
    ConstellationSpec(
        "taurus-minotaur-c",
        "Q201032",
        (SatelliteCategory.ROCKET,),
        prefix=("TAURUS ", "MINOTAUR-C"),
    ),  # "MINOTAUR-C" (longer) beats the minotaur prefix; "TAURUS " excludes TAURUS-1.
    ConstellationSpec(
        "conestoga", "Q248551", (SatelliteCategory.ROCKET,), prefix="CONESTOGA"
    ),  # Stub: sole orbital attempt (1995) failed; no catalogue residue.
    ConstellationSpec(
        "juno-ii", "Q248951", (SatelliteCategory.ROCKET,), prefix="JUNO II"
    ),
    ConstellationSpec(
        "vanguard-rocket",
        "Q333812",
        (SatelliteCategory.ROCKET,),
        satellites=["VANGUARD R/B", "VANGUARD DEB"],
    ),  # Exact list splits the rocket from the VANGUARD 1/2/3 satellites (vanguard).
    ConstellationSpec(
        "launcherone", "Q1807659", (SatelliteCategory.ROCKET,), prefix="LAUNCHERONE"
    ),
    ConstellationSpec(
        "terran-1", "Q60847337", (SatelliteCategory.ROCKET,), prefix="TERRAN 1"
    ),  # Stub: sole flight (2023) failed to orbit.
    # China
    ConstellationSpec(
        "ceres-1", "Q97172682", (SatelliteCategory.ROCKET,), prefix="CERES-1"
    ),  # Hyphen excludes the French CERES ELINT satellites ("CERES 1").
    ConstellationSpec(
        "zhuque-2",
        "Q65151444",
        (SatelliteCategory.ROCKET,),
        prefix=("ZHUQUE-2", "ZQ-2"),
    ),
    ConstellationSpec(
        "hyperbola-1", "Q56692274", (SatelliteCategory.ROCKET,), prefix="SQX-1"
    ),
    ConstellationSpec(
        "gravity-1", "Q123469921", (SatelliteCategory.ROCKET,), prefix="GRAVITY-1"
    ),
    ConstellationSpec(
        "kaituozhe",
        "Q966854",
        (SatelliteCategory.ROCKET,),
        prefix=("KT-1", "KAITUOZHE"),
    ),  # Stub: early KT-1/KT-2 flights left no catalogued objects.
    ConstellationSpec(
        "pallas-1", "Q96398258", (SatelliteCategory.ROCKET,), prefix="PALLAS"
    ),  # Stub: in development, no orbital residue yet.
    # India
    ConstellationSpec("slv-3", "Q1752243", (SatelliteCategory.ROCKET,), prefix="SLV-3"),
    ConstellationSpec("aslv", "Q15017", (SatelliteCategory.ROCKET,), prefix="ASLV"),
    ConstellationSpec(
        "lvm3", "Q1360911", (SatelliteCategory.ROCKET,), prefix="LVM3"
    ),  # LVM3 (ex-GSLV Mk III) shares no stages with GSLV; distinct entry.
    ConstellationSpec(
        "sslv", "Q56292638", (SatelliteCategory.ROCKET,), prefix=("SSLV", "VTM")
    ),  # VTM = Velocity Trimming Module, the SSLV terminal stage.
    # Korea
    ConstellationSpec("naro", "Q494204", (SatelliteCategory.ROCKET,), prefix="KSLV-1"),
    ConstellationSpec("nuri", "Q624548", (SatelliteCategory.ROCKET,), prefix="KSLV-II"),
    # North Korea
    ConstellationSpec("unha", "Q496193", (SatelliteCategory.ROCKET,), prefix="UNHA"),
    ConstellationSpec(
        "chollima-1", "Q118906406", (SatelliteCategory.ROCKET,), prefix="CHOLLIMA"
    ),
    # Iran
    ConstellationSpec("safir", "Q142596", (SatelliteCategory.ROCKET,), prefix="SAFIR"),
    ConstellationSpec(
        "simorgh", "Q2905149", (SatelliteCategory.ROCKET,), prefix="SIMORGH"
    ),  # Stub: most flights failed to orbit.
    ConstellationSpec(
        "qased", "Q91459262", (SatelliteCategory.ROCKET,), prefix="QASED"
    ),
    ConstellationSpec(
        "qaem-100", "Q115815184", (SatelliteCategory.ROCKET,), prefix="QAEM"
    ),
    ConstellationSpec(
        "zuljanah", "Q105686394", (SatelliteCategory.ROCKET,), prefix="ZULJANAH"
    ),  # Stub: no orbital residue.
    # -------------------------------------------------------------------------
    # US commercial constellations
    # -------------------------------------------------------------------------
    # HawkEye 360: RF geolocation cluster constellation.
    ConstellationSpec(
        "hawkeye360",
        None,
        (SatelliteCategory.OBSERVATION,),
        prefix=("HAWK-", "KESTREL-"),
    ),  # Bare "HAWK" would catch HAWKSAT 1 (ATK demo cubesat, unrelated).
    # Capella Space: commercial SAR imaging constellation.
    ConstellationSpec(
        "capella", None, (SatelliteCategory.OBSERVATION,), prefix="CAPELLA"
    ),
    # Wildfire: wildfire-detection EO constellation TODO: (Tomorrow.io subsidiary?)
    ConstellationSpec(
        "wildfire", None, (SatelliteCategory.OBSERVATION,), prefix="WILDFIRE"
    ),
    # EchoStar / DISH: GEO broadcast + broadband (ECHOSTAR-N, JUPITER-N).
    ConstellationSpec(
        "echostar", "Q97217972", (SatelliteCategory.COMMUNICATIONS,), prefix="ECHOSTAR"
    ),
    # ViaSat: GEO high-throughput broadband (VIASAT-1, VIASAT-3 F1/F2/F3).
    ConstellationSpec(
        "viasat", None, (SatelliteCategory.COMMUNICATIONS,), prefix="VIASAT"
    ),
    # Lynk Global: direct-to-standard-cell IoT/broadband LEO constellation.
    ConstellationSpec("lynk", None, (SatelliteCategory.COMMUNICATIONS,), prefix="LYNK"),
    # ICEYE: Finnish SAR company, sells & operates sats (so country codes varies)
    ConstellationSpec("iceye", None, (SatelliteCategory.OBSERVATION,), prefix="ICEYE"),
    # Tomorrow.io: commercial weather-monitoring microsatellite constellation.
    ConstellationSpec(
        "tomorrow-io", None, (SatelliteCategory.WEATHER,), prefix="TOMORROW"
    ),
    # Planet Labs Pelican: next-gen high-revisit EO constellation.
    ConstellationSpec(
        "planet-pelican", None, (SatelliteCategory.OBSERVATION,), prefix="PELICAN"
    ),
    # AST SpaceMobile: direct-to-cell broadband LEO constellation.
    ConstellationSpec(
        "ast-spacemobile",
        "Q131940547",
        (SatelliteCategory.COMMUNICATIONS,),
        prefix="SPACEMOBILE",
    ),
    # APrizeSat: low-cost store-and-forward IoT messaging (SpaceQuest).
    ConstellationSpec(
        "aprizesat",
        "Q17512448",
        (SatelliteCategory.COMMUNICATIONS,),
        prefix=("APRIZESAT", "LatinSat"),
    ),
    # AeroCube: Aerospace Corporation technology-demonstration cubesats.
    ConstellationSpec(
        "aerocube",
        None,
        (SatelliteCategory.SCIENCE,),
        prefix="AEROCUBE",
        url="https://aerospace.org/paper/aerospace-corporations-aerocube-program",
    ),
    # D-Orbit ION Satellite Carrier: in-space transportation / hosted payload buses.
    ConstellationSpec(
        "d-orbit-ion", "Q65084209", (SatelliteCategory.SPACE_TUG,), prefix="ION "
    ),
    # Early weather satellites
    ConstellationSpec(
        "Television-Infrared-Observation-Satellite",
        "Q2141538",
        (SatelliteCategory.WEATHER,),
        prefix="TIROS",
    ),
    # ISS crewed / cargo vehicles catalogued as separate objects by NORAD.
    ConstellationSpec(
        "cygnus", "Q127924", (SatelliteCategory.UNMANNED_CARGO,), prefix="CYGNUS"
    ),
    ConstellationSpec(
        "crew-dragon",
        "Q105095031",
        (SatelliteCategory.MANNED_CAPSULE,),
        prefix="CREW DRAGON",
    ),
    ConstellationSpec(
        "apollo", "Q46611", (SatelliteCategory.MANNED_CAPSULE,), prefix="APOLLO"
    ),
    ConstellationSpec(
        "sts", "Q1775296", (SatelliteCategory.MANNED_CAPSULE,), prefix="STS "
    ),  # Trailing space; bare "STS" would catch Korean STSAT-* and US-DoD STSS *.
    ConstellationSpec(
        "dragon", "Q236448", (SatelliteCategory.UNMANNED_CARGO,), prefix="DRAGON "
    ),  # Trailing space; bare "DRAGON" would catch DRAGONFLY, DRAGONSAT.
    # Science / geodetic
    ConstellationSpec(
        "pageos", "Q2043671", (SatelliteCategory.SCIENCE,), prefix="PAGEOS"
    ),
    ConstellationSpec(
        "venera", "Q192144", (SatelliteCategory.SCIENCE,), prefix="VENERA"
    ),
    ConstellationSpec(
        "nimbus", "Q609455", (SatelliteCategory.SCIENCE,), prefix="NIMBUS"
    ),
    # US sigint/comint
    ConstellationSpec(
        "nemesis",  # Are we the baddies?
        "Q56301465",
        (SatelliteCategory.MILITARY, SatelliteCategory.OBSERVATION),
        contains=("USA 207", "USA 257"),
    ),
    # US reconnaissance
    ConstellationSpec(
        "corona",
        "Q256812",
        (SatelliteCategory.MILITARY, SatelliteCategory.OBSERVATION),
        prefix="DISCOVERER",
    ),
    # Russian/Soviet weather
    ConstellationSpec(
        "meteor", "Q1925316", (SatelliteCategory.WEATHER,), prefix="METEOR"
    ),
    # -------------------------------------------------------------------------
    # European constellations
    # -------------------------------------------------------------------------
    # IRIDE: Italian national Earth observation constellation (ESA/ASI mandate,
    # prime contractor Thales Alenia Space Italia).
    ConstellationSpec(
        "iride", "Q137485492", (SatelliteCategory.OBSERVATION,), prefix="IRIDE"
    ),
    ConstellationSpec(
        "sentinel", "Q4303731", (SatelliteCategory.OBSERVATION,), prefix="SENTINEL"
    ),
    ConstellationSpec(
        "ariane", "Q131535", (SatelliteCategory.ROCKET,), prefix="ARIANE"
    ),
    # -------------------------------------------------------------------------
    # Russian/Soviet (CIS) constellations
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "resurs-f",
        "Q4393667",
        (SatelliteCategory.MILITARY, SatelliteCategory.OBSERVATION),
        prefix="RESURS F-",
    ),
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
    # EKS / Tundra / Kupol: Russian early-warning constellation in Molniya orbits
    ConstellationSpec(
        "eks",
        "Q5323248",
        (SatelliteCategory.MILITARY, SatelliteCategory.COMMUNICATIONS),
        satellites=[
            "COSMOS 2510",
            "COSMOS 2518",
            "COSMOS 2541",
            "COSMOS 2546",
            "COSMOS 2552",
            "COSMOS 2563",
        ],
    ),
    # Soviet sats, monitored van allen belts
    ConstellationSpec(
        "elektron",
        "Q1313442",
        (SatelliteCategory.SCIENCE,),
        prefix="ELEKTRON",
    ),
    ConstellationSpec(
        "proton",
        "Q1406559",
        (SatelliteCategory.SCIENCE,),
        prefix="PROTON",
    ),
    # Communication sats with high eccentricity orbits, for good polar coverage
    ConstellationSpec(
        "molniya",
        "Q593283",
        (SatelliteCategory.MILITARY, SatelliteCategory.COMMUNICATIONS),
        prefix="MOLNIYA",
    ),
    # COSMOS: generic classified satellites, TODO: not all are military
    ConstellationSpec(
        "cosmos", "Q147802", (SatelliteCategory.MILITARY,), prefix="COSMOS"
    ),
    # Rassvet- Russian commercial broadband LEO (X holding).
    ConstellationSpec(
        "rassvet", "Q124753962", (SatelliteCategory.COMMUNICATIONS,), prefix="RASSVET"
    ),
    # Yamal: Russian geostationary communications (Gazprom Space Systems).
    ConstellationSpec(
        "yamal", "Q3656794", (SatelliteCategory.COMMUNICATIONS,), prefix="YAMAL"
    ),
    ConstellationSpec(
        "sputnik", "Q170413", (SatelliteCategory.SCIENCE,), prefix="SPUTNIK"
    ),
    ConstellationSpec(
        "soyuz", "Q579421", (SatelliteCategory.MANNED_CAPSULE,), prefix="SOYUZ"
    ),
    ConstellationSpec(
        "progress", "Q309363", (SatelliteCategory.UNMANNED_CARGO,), prefix="PROGRESS"
    ),
    ConstellationSpec(
        "salyut", "Q207933", (SatelliteCategory.STATION,), prefix="SALYUT"
    ),  # some were military, documented in individual pages (good coverage)
    ConstellationSpec(
        "mir",
        "Q48604",
        (SatelliteCategory.STATION,),
        prefix="MIR ",
        satellites=["MIR"],
    ),  # Bare "MIR" prefix would catch MIRANDA, MIRATA, MIR-SAT 1 (all unrelated).
    # Sheldon "SL-N" designators split by launch-vehicle family.
    ConstellationSpec(
        "soyuz-rocket",
        "Q1299641",
        (SatelliteCategory.ROCKET,),
        prefix=("SL-4", "SL-26"),
    ),  # Soyuz/Voskhod/Soyuz-2 spent stages & debris
    ConstellationSpec(
        "sputnik-rocket", "Q1393751", (SatelliteCategory.ROCKET,), prefix="SL-1"
    ),
    ConstellationSpec(
        "vostok-rocket", "Q841262", (SatelliteCategory.ROCKET,), prefix="SL-3"
    ),
    ConstellationSpec("polyot", "Q1392495", (SatelliteCategory.ROCKET,), prefix="SL-5"),
    ConstellationSpec(
        "molniya-rocket", "Q847798", (SatelliteCategory.ROCKET,), prefix="SL-6"
    ),
    ConstellationSpec(
        "kosmos-2i", "Q1540897", (SatelliteCategory.ROCKET,), prefix="SL-7"
    ),  # Kosmos-2I (11K63); no distinct Wikidata item, family QID used.
    ConstellationSpec(
        "kosmos-3m", "Q4235084", (SatelliteCategory.ROCKET,), prefix="SL-8"
    ),
    ConstellationSpec(
        "proton-rocket",
        "Q249231",
        (SatelliteCategory.ROCKET,),
        prefix=("SL-9", "SL-12", "SL-13", "SL-25"),
    ),  # UR-500/Proton-K/Proton-M stages. The "proton" SCIENCE entry is the payload series.
    ConstellationSpec(
        "tsyklon-2", "Q367286", (SatelliteCategory.ROCKET,), prefix="SL-11"
    ),
    ConstellationSpec(
        "tsyklon-3", "Q334236", (SatelliteCategory.ROCKET,), prefix="SL-14"
    ),
    ConstellationSpec(
        "zenit", "Q1748964", (SatelliteCategory.ROCKET,), prefix=("SL-16", "SL-23")
    ),  # SL-16 Zenit-2 (LEO) + SL-23 Zenit-3SLB/SLBF (GEO, Baikonur).
    ConstellationSpec(
        "start-1",
        "Q60524",
        (SatelliteCategory.ROCKET,),
        prefix=("SL-18", "START-1", "START 1"),
    ),
    ConstellationSpec(
        "rokot", "Q682764", (SatelliteCategory.ROCKET,), prefix="SL-19"
    ),  # SL-19 also covers the sibling Strela (both UR-100N conversions).
    ConstellationSpec(
        "shtil", None, (SatelliteCategory.ROCKET,), prefix="SL-21"
    ),  # Submarine-launched R-29RM conversion; Wikidata has only a disambig page.
    ConstellationSpec(
        "dnepr", "Q49674", (SatelliteCategory.ROCKET,), prefix=("SL-24", "DNEPR")
    ),
    ConstellationSpec(
        "energia", "Q731859", (SatelliteCategory.ROCKET,), prefix="ENERGIA"
    ),  # Stub: 1987-88 flights left no catalogued objects under this name.
    ConstellationSpec(
        "fregat", "Q1453740", (SatelliteCategory.ROCKET,), prefix="FREGAT"
    ),  # Upper stages (mostly Soyuz)
    ConstellationSpec(
        "proton-m", "Q1756423", (SatelliteCategory.ROCKET,), prefix="BREEZE"
    ),  # Briz-M/KM upper stage (flies on Proton-M and Rokot)
    # -------------------------------------------------------------------------
    # Derived from CelesTrak group membership
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "orbcomm", "Q16960684", (SatelliteCategory.COMMUNICATIONS,), group="orbcomm"
    ),  # all are named "ORBCOMM-..." except VESSELSAT, which are part of the constellation
    ConstellationSpec(
        "intelsat", "Q778126", (SatelliteCategory.COMMUNICATIONS,), group="intelsat"
    ),
    ConstellationSpec(
        "ses", "Q333025", (SatelliteCategory.COMMUNICATIONS,), group="ses"
    ),
    ConstellationSpec(
        "amc", "Q7389874", (SatelliteCategory.COMMUNICATIONS,), prefix="AMC-"
    ),  # SES Americom, AMC fleet, acquired by SES
    ConstellationSpec(
        "astra", "Q15711023", (SatelliteCategory.COMMUNICATIONS,), prefix="ASTRA "
    ),
    ConstellationSpec(
        "nss", "Q2205870", (SatelliteCategory.COMMUNICATIONS,), prefix="NSS"
    ),
    ConstellationSpec(
        "eutelsat", "Q848336", (SatelliteCategory.COMMUNICATIONS,), prefix="EUTELSAT"
    ),  # include Ekspress-AT
    ConstellationSpec(
        "telesat", "Q2401935", (SatelliteCategory.COMMUNICATIONS,), group="telesat"
    ),
    ConstellationSpec(
        "anik", "Q546687", (SatelliteCategory.COMMUNICATIONS,), contains=("ANIK",)
    ),
    ConstellationSpec(
        "jsat", "Q11225562", (SatelliteCategory.COMMUNICATIONS,), contains=("JCSAT",)
    ),
    ConstellationSpec(
        "superbird",
        "Q11245057",
        (SatelliteCategory.COMMUNICATIONS,),
        contains=("SUPERBIRD",),
    ),
    ConstellationSpec(
        "o3b-gen1", "Q7072273", (SatelliteCategory.COMMUNICATIONS,), prefix=("O3B FM",)
    ),
    ConstellationSpec(
        "o3b-mpower",
        "Q104845067",
        (SatelliteCategory.COMMUNICATIONS,),
        prefix=("O3B MPOWER",),
    ),
    ConstellationSpec(
        "horizons",
        "Q5903528",
        (SatelliteCategory.COMMUNICATIONS,),
        contains=("HORIZONS-",),
    ),  # Joint venture
    ConstellationSpec(
        "dsn",
        "Q18465737",
        (SatelliteCategory.COMMUNICATIONS, SatelliteCategory.MILITARY),
        contains=(
            "DSN-",
            "Superbird-B3",
        ),
    ),  # Japanese military GEO comm sats, joint venture
    ConstellationSpec(
        "thor",
        "Q73877",
        (SatelliteCategory.COMMUNICATIONS,),
        contains=("THOR ", "MARCOPOLO", "INTELSAT 10-02"),
    ),
    ConstellationSpec(
        "gps",
        "Q18822",
        (SatelliteCategory.NAVIGATION,),
        group="gps-ops",
        prefix=("NAVSTAR",),
    ),
    ConstellationSpec(
        "nts-satellites",
        "Q135670517",
        (SatelliteCategory.NAVIGATION, SatelliteCategory.MILITARY),
        satellites=["OPS 7518 (NTS 1)", "NTS 2", "NTS-3"],
    ),
    ConstellationSpec(
        "glonass", "Q486250", (SatelliteCategory.NAVIGATION,), group="glo-ops"
    ),
    ConstellationSpec(
        "galileo", "Q193902", (SatelliteCategory.NAVIGATION,), group="galileo"
    ),
    ConstellationSpec(
        "beidou", "Q857141", (SatelliteCategory.NAVIGATION,), group="beidou"
    ),
    ConstellationSpec(
        "transit", "Q651136", (SatelliteCategory.NAVIGATION,), group="nnss"
    ),  # Navy Navigation Satellite System
    ConstellationSpec(
        "sbas", "Q2165162", (SatelliteCategory.NAVIGATION,), group="sbas"
    ),  # generic "constellation"
    ConstellationSpec(
        "tdrss", "Q3522774", (SatelliteCategory.COMMUNICATIONS,), group="tdrss"
    ),
    ConstellationSpec(
        "argos", "Q649489", (SatelliteCategory.OBSERVATION,), group="argos"
    ),
    # Deliberate debris events: ASAT tests / intentional dispersals
    ConstellationSpec(
        "fengyun-1c-asat-debris",
        "Q182183",
        (SatelliteCategory.DEBRIS,),
        group="fengyun-1c-debris",
    ),
    ConstellationSpec(
        "westford-needles",
        "Q621882",
        (SatelliteCategory.DEBRIS,),
        object_id_prefix="1963-014",
        prefix=("WESTFORD NEEDLES",),
    ),
    ConstellationSpec(
        "solwind-debris",
        "Q54370",
        (SatelliteCategory.DEBRIS,),
        object_id_prefix="1979-017",
        prefix=("SOLWIND DEB",),
    ),
    ConstellationSpec(
        "microsat-r-debris",
        "Q60990709",
        (SatelliteCategory.DEBRIS,),
        object_id_prefix="2019-006",
        prefix=("MICROSAT-R DEB",),
    ),
    ConstellationSpec(
        "crres-debris",
        "Q5013937",
        (SatelliteCategory.DEBRIS,),
        object_id_prefix="1990-065",
        prefix=("CRRES DEB",),
    ),
    ConstellationSpec(
        "cosmos-1408-debris",
        "Q12907386",
        (SatelliteCategory.DEBRIS,),
        object_id_prefix="1982-092",
        prefix=("COSMOS 1408 DEB",),
    ),
    # Accidental breakup debris
    ConstellationSpec(
        "iridium-33-debris",
        "Q843912",
        (SatelliteCategory.DEBRIS,),
        group="iridium-33-debris",
    ),
    ConstellationSpec(
        "cosmos-2251-debris",
        "Q843912",
        (SatelliteCategory.DEBRIS,),
        group="cosmos-2251-debris",
    ),
    ConstellationSpec(
        "hitomi-debris",
        "Q298048",
        (SatelliteCategory.DEBRIS,),
        object_id_prefix="2016-012",
        prefix=("ASTRO-H (HITOMI) DEB", "ASTRO-H DEB"),
    ),
    ConstellationSpec(
        "cobe-debris",
        "Q49445",
        (SatelliteCategory.DEBRIS,),
        object_id_prefix="1989-089",
        prefix=("COBE DEB",),
    ),
    ConstellationSpec(
        "seasat-debris",
        "Q257020",
        (SatelliteCategory.DEBRIS,),
        object_id_prefix="1978-064",
        prefix=("SEASAT 1 DEB",),
    ),
    ConstellationSpec(
        "uars-debris",
        "Q534401",
        (SatelliteCategory.DEBRIS,),
        object_id_prefix="1991-063",
        prefix=("UARS DEB",),
    ),  #
    ConstellationSpec(
        "resurs-o1-debris",
        "Q12816951",
        (SatelliteCategory.DEBRIS,),
        object_id_prefix="1994-074",
        prefix=("RESURS O1 DEB",),
    ),
    ConstellationSpec(
        "resurs-p1-debris",
        "Q4393669",
        (SatelliteCategory.DEBRIS,),
        object_id_prefix="2013-030",
        prefix=("RESURS-P 1 DEB",),
    ),
    ConstellationSpec(
        "echo-debris",
        "Q620661",
        (SatelliteCategory.DEBRIS,),
        prefix=("ECHO 1 DEB", "ECHO 2 DEB"),
    ),
    # -------------------------------------------------------------------------
    # Derived from SATCAT SOURCE/OWNER code
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "arabsat", "Q65277396", (SatelliteCategory.COMMUNICATIONS,), source="AB"
    ),
    ConstellationSpec(
        "abs", "Q18238088", (SatelliteCategory.COMMUNICATIONS,), source="ABS"
    ),
    ConstellationSpec(
        "asiasat", "Q726812", (SatelliteCategory.COMMUNICATIONS,), source="AC"
    ),
    ConstellationSpec(
        "new-ico", "Q3792482", (SatelliteCategory.COMMUNICATIONS,), source="NICO"
    ),
    ConstellationSpec(
        "rascomstar", "Q3415056", (SatelliteCategory.COMMUNICATIONS,), source="RASC"
    ),
    # -------------------------------------------------------------------------
    # Soviet / Russian GEO communications
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "gorizont", "Q2622945", (SatelliteCategory.COMMUNICATIONS,), prefix="GORIZONT"
    ),
    # RADUGA-1 / RADUGA-1M units share the RADUGA prefix; no GLOBUS names in SATCAT.
    ConstellationSpec(
        "raduga",
        "Q15915658",
        (SatelliteCategory.COMMUNICATIONS, SatelliteCategory.MILITARY),
        prefix="RADUGA",
    ),
    ConstellationSpec(
        "ekran", "Q877664", (SatelliteCategory.COMMUNICATIONS,), prefix="EKRAN"
    ),
    # All catalogued "EXPRESS"/"EXPRESS-A/AM/AT"; every match is CIS-owned.
    ConstellationSpec(
        "ekspress",
        "Q73605",
        (SatelliteCategory.COMMUNICATIONS,),
        prefix=("EXPRESS", "EKSPRESS"),
    ),
    # -------------------------------------------------------------------------
    # Western military communications
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "skynet",
        "Q1751266",
        (SatelliteCategory.COMMUNICATIONS, SatelliteCategory.MILITARY),
        prefix="SKYNET",
    ),
    # IDSCS / DSCS catalogued as "OPS NNNN (...)" or bare; exact lists needed to
    # win over us-ops-classified (prefix "OPS " resolves first otherwise).
    # IDSCS (Initial DSCS, phase I) is a distinct program from DSCS-II/III.
    ConstellationSpec(
        "idscs",
        "Q106946774",
        (SatelliteCategory.COMMUNICATIONS, SatelliteCategory.MILITARY),
        satellites=[
            "OPS 9311 (IDSCS 1)",
            "OPS 9312 (IDSCS 2)",
            "OPS 9313 (IDSCS 3)",
            "OPS 9314 (IDSCS 4)",
            "OPS 9315 (IDSCS 5)",
            "OPS 9316 (IDSCS 6)",
            "OPS 9317 (IDSCS 7)",
            "OPS 9321 (IDSCS 8)",
            "OPS 9322 (IDSCS 9)",
            "OPS 9323 (IDSCS 10)",
            "OPS 9324 (IDSCS 11)",
            "OPS 9325 (IDSCS 12)",
            "OPS 9326 (IDSCS 13)",
            "OPS 9327 (IDSCS 14)",
            "OPS 9328 (IDSCS 15)",
            "OPS 9331 (IDSCS 16)",
            "OPS 9332 (IDSCS 17)",
            "OPS 9333 (IDSCS 18)",
            "OPS 9334 (IDSCS 19)",
            "OPS 9341 (IDSCS 20)",
            "OPS 9342 (IDSCS 21)",
            "OPS 9343 (IDSCS 22)",
            "OPS 9344 (IDSCS 23)",
            "OPS 9345 (IDSCS 24)",
            "OPS 9346 (IDSCS 25)",
            "OPS 9347 (IDSCS 26)",
            "OPS 9348 (IDSCS 27)",
        ],
    ),
    ConstellationSpec(
        "dscs",
        "Q821834",
        (SatelliteCategory.COMMUNICATIONS, SatelliteCategory.MILITARY),
        satellites=[
            "OPS 9431 (DSCS 2-1)",
            "OPS 9432 (DSCS 2-2)",
            "OPS 9433 (DSCS 2-3)",
            "OPS 9434 (DSCS 2-4)",
            "OPS 9435 (DSCS 2-5)",
            "OPS 9436 (DSCS 2-6)",
            "OPS 9437 (DSCS 2-7)",
            "OPS 9438 (DSCS 2-8)",
            "OPS 9441 (DSCS 2-11)",
            "OPS 9442 (DSCS 2-12)",
            "OPS 9443 (DSCS 2-13)",
            "OPS 9444 (DSCS 2-14)",
            "DSCS 2-15",
            "DSCS 3-1",
        ],
    ),
    # Catalogued as "USA NNN (MILSTAR-...)"; exact list beats usa-classified.
    ConstellationSpec(
        "milstar",
        "Q1759462",
        (SatelliteCategory.COMMUNICATIONS, SatelliteCategory.MILITARY),
        satellites=[
            "USA 99 (MILSTAR-1 1)",
            "USA 115 (MILSTAR-1 2)",
            "USA 143 (MILSTAR-2 1)",
            "USA 157 (MILSTAR-2 2)",
            "USA 164 (MILSTAR-2 3)",
            "USA 169 (MILSTAR-2 4)",
        ],
    ),
    # Mix of "OPS NNNN (FLTSATCOM N)", bare, and "FLTSATCOM N (USA NN)".
    ConstellationSpec(
        "fltsatcom",
        "Q378548",
        (SatelliteCategory.COMMUNICATIONS, SatelliteCategory.MILITARY),
        satellites=[
            "OPS 6391 (FLTSATCOM 1)",
            "OPS 6392 (FLTSATCOM 2)",
            "OPS 6393 (FLTSATCOM 3)",
            "OPS 6394 (FLTSATCOM 4)",
            "FLTSATCOM 5",
            "FLTSATCOM 7 (USA 20)",
            "FLTSATCOM 8 (USA 46)",
        ],
    ),
    # -------------------------------------------------------------------------
    # Satellite-IoT / data-relay constellations
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "kineis", "Q60849749", (SatelliteCategory.COMMUNICATIONS,), prefix="KINEIS"
    ),
    ConstellationSpec(
        "astrocast",
        "Q107563951",
        (SatelliteCategory.COMMUNICATIONS,),
        prefix="ASTROCAST",
    ),
    # Trailing hyphen isolates from the NASA Kepler telescope ("KEPLER", no hyphen).
    ConstellationSpec(
        "kepler-communications",
        "Q28163140",
        (SatelliteCategory.COMMUNICATIONS,),
        prefix="KEPLER-",
    ),
    # AMSAT amateur radio. No leading prefix: OSCAR designators ride as
    # parenthetical "(xO-NN)" tags. Open-paren anchor avoids RS-/IRS- collisions.
    ConstellationSpec(
        "oscar",
        "Q2008094",
        (SatelliteCategory.COMMUNICATIONS,),
        prefix="OSCAR ",
        contains=(
            "(AO-",
            "(FO-",
            "(SO-",
            "(UO-",
            "(DO-",
            "(NO-",
            "(LO-",
            "(IO-",
            "(WO-",
            "(VO-",
            "(HO-",
            "(PO-",
            "(RS-",
        ),
    ),
    # -------------------------------------------------------------------------
    # Regional navigation
    # -------------------------------------------------------------------------
    # NavIC: IRNSS-1x + 2nd-gen NVS-0x; scoped so it doesn't catch ISRO comms GSAT.
    ConstellationSpec(
        "irnss-navic",
        "Q94915",
        (SatelliteCategory.NAVIGATION,),
        prefix=("IRNSS", "NVS"),
    ),
    # QZS-N (MICHIBIKI-N); all units carry the QZS- prefix.
    ConstellationSpec(
        "qzss", "Q862327", (SatelliteCategory.NAVIGATION,), prefix="QZS-"
    ),
    # -------------------------------------------------------------------------
    # Commercial / military Earth observation & SAR
    # -------------------------------------------------------------------------
    # Satellogic (ARGN). Hyphen anchor excludes the 1985 US "NUSAT 1" and the
    # unrelated US "NEWSAT-1 (PALAPA B2R)"; SATCAT spells the Ñ as "NUSAT".
    ConstellationSpec(
        "nusat-satellogic",
        "Q28803027",
        (SatelliteCategory.OBSERVATION,),
        prefix="NUSAT-",
    ),
    ConstellationSpec(
        "grus-axelspace", None, (SatelliteCategory.OBSERVATION,), prefix="GRUS"
    ),
    ConstellationSpec(
        "qps-sar", None, (SatelliteCategory.OBSERVATION,), prefix="QPS-SAR"
    ),
    ConstellationSpec(
        "umbra-sar", None, (SatelliteCategory.OBSERVATION,), prefix="UMBRA"
    ),
    # Trailing hyphen scopes to the SAR fleet, not the owl genus "STRIX".
    ConstellationSpec(
        "strix-synspective", None, (SatelliteCategory.OBSERVATION,), prefix="STRIX-"
    ),
    # BlackSky Global EO; SATCAT name is bare "GLOBAL-N". Hyphen avoids Globalstar.
    ConstellationSpec(
        "blacksky", None, (SatelliteCategory.OBSERVATION,), prefix="GLOBAL-"
    ),
    ConstellationSpec(
        "cartosat", "Q11383970", (SatelliteCategory.OBSERVATION,), prefix="CARTOSAT"
    ),
    ConstellationSpec(
        "risat",
        "Q3631031",
        (SatelliteCategory.OBSERVATION, SatelliteCategory.MILITARY),
        prefix="RISAT",
    ),
    # IRS- (hyphen) keeps it off unrelated short tokens; RESOURCESAT-2/2A too.
    ConstellationSpec(
        "resourcesat-irs",
        "Q1661266",
        (SatelliteCategory.OBSERVATION,),
        prefix=("RESOURCESAT", "IRS-"),
    ),
    # First-gen "COSMO-SKYMED N" + second-gen "CSG-N".
    ConstellationSpec(
        "cosmo-skymed",
        "Q591968",
        (SatelliteCategory.OBSERVATION, SatelliteCategory.MILITARY),
        prefix=("COSMO-SKYMED", "CSG"),
    ),
    ConstellationSpec(
        "sar-lupe",
        "Q698351",
        (SatelliteCategory.OBSERVATION, SatelliteCategory.MILITARY),
        prefix="SAR-LUPE",
    ),
    ConstellationSpec(
        "sarah",
        "Q19308236",
        (SatelliteCategory.OBSERVATION, SatelliteCategory.MILITARY),
        prefix="SARAH",
    ),
    # Israeli recon: optical OFEQ + SAR TECSAR (catalogued as standalone "TECSAR").
    ConstellationSpec(
        "ofeq",
        "Q1130496",
        (SatelliteCategory.OBSERVATION, SatelliteCategory.MILITARY),
        prefix=("OFEQ", "TECSAR"),
    ),
    # Naval Ocean Surveillance System (White Cloud/PARCAE → Ranger → Intruder).
    # SIGINT clusters/pairs catalogued under classified USA/OPS names + obscure
    # first-gen subsat tags; exact list beats usa-classified / us-ops-classified.
    # Rideshare cubesats on the NROL-36/-55 launches are deliberately excluded.
    ConstellationSpec(
        "noss-intruder",
        "Q3074873",
        (SatelliteCategory.MILITARY, SatelliteCategory.OBSERVATION),
        satellites=[
            "OPS 6431",
            "SSU 1",
            "SSU 2",
            "SSU 3",
            "OPS 8781",
            "SS 1",
            "SS 2",
            "SS 3",
            "OPS 7245",
            "EP 1",
            "EP 2",
            "EP 3",
            "OPS 0252",
            "SSD",
            "SSA",
            "SSB",
            "SSC",
            "OPS 6432",
            "GB 1",
            "GB 2",
            "GB 3",
            "OPS 8737",
            "JD 1",
            "JD 2",
            "JD 3",
            "USA 15",
            "USA 16",
            "USA 17",
            "USA 18",
            "USA 22",
            "USA 23",
            "USA 24",
            "USA 25",
            "USA 59",
            "USA 60",
            "USA 61",
            "USA 62",
            "USA 72",
            "USA 74",
            "USA 76",
            "USA 77",
            "USA 119",
            "USA 120",
            "USA 121",
            "USA 122",
            "USA 123",
            "USA 124",
            "USA 160",
            "USA 173",
            "USA 181",
            "USA 194",
            "USA 229",
            "USA 238",
            "USA 264",
            "USA 274",
            "USA 327",
            "USA 498",
        ],
    ),
    # -------------------------------------------------------------------------
    # Japanese geostationary weather
    # -------------------------------------------------------------------------
    # All units "HIMAWARI-N (GMS-N)"; no bare GMS names (one unrelated German GMS-T).
    ConstellationSpec(
        "himawari", "Q3103808", (SatelliteCategory.WEATHER,), prefix="HIMAWARI"
    ),
    # -------------------------------------------------------------------------
    # Crewed spacecraft, cargo & stations
    # -------------------------------------------------------------------------
    ConstellationSpec(
        "shenzhou",
        "Q1138653",
        (SatelliteCategory.MANNED_CAPSULE,),
        prefix=("SHENZHOU", "SZ-"),
    ),
    ConstellationSpec(
        "tianzhou", "Q15905312", (SatelliteCategory.UNMANNED_CARGO,), prefix="TIANZHOU"
    ),
    # Orbital Mercury-Atlas flights (MA-4..9). Trailing space drops "MERCURY ONE".
    ConstellationSpec(
        "mercury-crewed",
        "Q52162",
        (SatelliteCategory.MANNED_CAPSULE,),
        prefix="MERCURY ATLAS ",
    ),
    # Trailing space drops the unrelated "GEMINI-POLLUX".
    ConstellationSpec(
        "gemini", "Q214996", (SatelliteCategory.MANNED_CAPSULE,), prefix="GEMINI "
    ),
    ConstellationSpec(
        "skylab", "Q190776", (SatelliteCategory.STATION,), prefix="SKYLAB"
    ),
    ConstellationSpec(
        "vostok", "Q623873", (SatelliteCategory.MANNED_CAPSULE,), prefix="VOSTOK"
    ),
    ConstellationSpec(
        "voskhod", "Q8860000", (SatelliteCategory.MANNED_CAPSULE,), prefix="VOSKHOD"
    ),
    # -------------------------------------------------------------------------
    # Lunar / planetary science
    # -------------------------------------------------------------------------
    # Trailing space: bare "LUNA" catches unrelated US/Turkish cubesats.
    ConstellationSpec("luna", "Q192372", (SatelliteCategory.SCIENCE,), prefix="LUNA "),
    ConstellationSpec("zond", "Q219857", (SatelliteCategory.SCIENCE,), prefix="ZOND"),
    # SATCAT spells it "CHANG'E-N"; CHANGE kept for apostrophe-free catalogs.
    ConstellationSpec(
        "change", "Q860037", (SatelliteCategory.SCIENCE,), prefix=("CHANG'E", "CHANGE")
    ),
    ConstellationSpec(
        "tianwen", "Q97300910", (SatelliteCategory.SCIENCE,), prefix="TIANWEN"
    ),
    # -------------------------------------------------------------------------
    # Classified payloads — fallback for "OBJECT X" names, keyed by SATCAT owner
    # -------------------------------------------------------------------------
    ConstellationSpec("prc-classified", None, (SatelliteCategory.MILITARY,)),
    ConstellationSpec("cis-classified", None, (SatelliteCategory.MILITARY,)),
    ConstellationSpec("skor-classified", None, (SatelliteCategory.MILITARY,)),
    ConstellationSpec("iran-classified", None, (SatelliteCategory.MILITARY,)),
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

EXACT_NAME_TO_SLUG: dict[str, str] = {
    n: c.slug for c in CONSTELLATIONS if c.satellites is not None for n in c.satellites
}

CONTAINS_TO_SLUG: dict[str, str] = {
    k: c.slug for c in CONSTELLATIONS if c.contains is not None for k in c.contains
}

# COSPAR launch-ID core (e.g. "1979-017") → slug. Catches breakup debris whose
# OBJECT_NAME lacks the expected prefix but whose OBJECT_ID shares the launch.
# Longest prefix first so a more specific launch wins.
OBJECT_ID_PREFIX_TO_SLUG: dict[str, str] = dict(
    sorted(
        (
            (p, c.slug)
            for c in CONSTELLATIONS
            if c.object_id_prefix is not None
            for p in (
                c.object_id_prefix
                if isinstance(c.object_id_prefix, tuple)
                else (c.object_id_prefix,)
            )
        ),
        key=lambda kv: -len(kv[0]),
    )
)

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
        "thor",  # thor rocket is more specific, few entries that don't match its prefixes are thor sats
        "sbas",  # type of sat
        "argos",
        "us-ops-classified",
        "cosmos",
        "ses",
        "telesat",
        "intelsat",
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
    exact = EXACT_NAME_TO_SLUG.get(name)
    if exact is not None:
        return exact
    for prefix, slug in PREFIX_TO_SLUG.items():
        if name.startswith(prefix):
            return slug
    for keyword, slug in CONTAINS_TO_SLUG.items():
        if keyword in name:
            return slug
    return None


def slug_from_cospar(cospar: str | None) -> str | None:
    """Match a COSPAR/OBJECT_ID by launch-ID prefix (e.g. '1979-017A' → solwind-debris)."""
    if not cospar:
        return None
    for prefix, slug in OBJECT_ID_PREFIX_TO_SLUG.items():
        if cospar.startswith(prefix):
            return slug
    return None
