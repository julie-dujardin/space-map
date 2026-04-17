"""Satellite operators (companies, agencies, intergovernmental orgs).

An operator is a real-world entity that owns/operates satellites. It is linked
to the fleet through one of two paths:

- ``source``: a SATCAT ``OWNER`` code (see ``sources.py``) — used when
  CelesTrak assigns the operator its own code (Intelsat, Eutelsat, ...).
- ``constellations``: a tuple of constellation slugs — used when the operator
  isn't a SATCAT source but owns one or more constellations (SpaceX operates
  Starlink, Amazon operates Kuiper, EUMETSAT operates MetOp/Meteosat, ...).

The per-source ``operator`` free-text field on ``SourceSpec`` was removed in
favor of this structured form.
"""

from dataclasses import dataclass

from space_map_data.constants.earth_sats.constellations import SatelliteCategory


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    wikidata_qid: str | None = None
    source: str | None = None  # SATCAT SOURCE/OWNER code, when one exists
    constellations: tuple[str, ...] = ()  # constellation slugs operated by this entity
    url: str | None = None  # Alternate ref if no wikipedia
    prefix: tuple[str, ...] = ()  # Companies with no constellations - direct to company
    category: SatelliteCategory | None = None  # Apply category to satelites


OPERATORS: tuple[OperatorSpec, ...] = (
    # Linked via a dedicated SATCAT SOURCE code
    OperatorSpec("Arabsat", "Q65277396", source="AB", constellations=("arabsat",)),
    OperatorSpec(
        "Asia Broadcast Satellite", "Q18238088", source="ABS", constellations=("abs",)
    ),
    OperatorSpec("AsiaSat", "Q726812", source="AC", constellations=("asiasat",)),
    OperatorSpec(
        "ESA - European Space Agency",
        "Q42262",
        source="ESA",
        constellations=("iride", "iss", "sentinel"),
    ),
    OperatorSpec("JAXA", "Q179103", constellations=("iss",)),
    OperatorSpec("CSA", "Q212227", constellations=("iss",)),
    OperatorSpec("Italian Space Agency", "Q392953", constellations=("iride",)),
    OperatorSpec("European Space Research Organization", "Q473105", source="ESRO"),
    OperatorSpec(
        "EUMETSAT", "Q692163", source="EUME", constellations=("metop", "meteosat")
    ),
    OperatorSpec(
        "Eutelsat", "Q848336", source="EUTE", constellations=("oneweb", "eutelsat")
    ),
    OperatorSpec(
        "Globalstar", "Q1202533", source="GLOB", constellations=("globalstar",)
    ),
    OperatorSpec(
        "Inmarsat",
        "Q827927",
        source="IM",
        constellations=("marecs", "marisat", "inmarsat"),
    ),
    OperatorSpec("Iridium", "Q3154356", source="IRID", constellations=("iridium",)),
    OperatorSpec("Indian Space Research Organisation", "Q229058", source="ISRO"),
    OperatorSpec(
        "Intelsat", "Q778126", source="ITSO", constellations=("intelsat", "galaxy")
    ),
    OperatorSpec("North Atlantic Treaty Organization", "Q7184", source="NATO"),
    OperatorSpec(
        "ICO Global Communications",
        "Q3792482",
        source="NICO",
        constellations=("new-ico",),
    ),
    OperatorSpec("Orbcomm", "Q16960684", source="ORB", constellations=("orbcomm",)),
    OperatorSpec(
        "RascomStar-QAF", "Q3415056", source="RASC", constellations=("rascomstar",)
    ),
    OperatorSpec("SES", "Q333025", source="SES", constellations=("ses", "o3b")),
    # Linked only via constellation
    OperatorSpec(
        "SpaceX", "Q193701", constellations=("starlink", "crew-dragon", "falcon")
    ),
    OperatorSpec(
        "ULA - United Launch Alliance", "Q1236833", constellations=("atlas", "delta")
    ),
    OperatorSpec("Rocket Lab", "Q116319", constellations=("electron",)),
    OperatorSpec("Amazon", "Q3884", constellations=("kuiper",)),
    OperatorSpec(
        "MEASAT Satellite Systems", "Q1881326", constellations=("measat", "africasat")
    ),
    OperatorSpec("Thaicom", "Q6903407", constellations=("thaicom",)),
    OperatorSpec(
        "Planet Labs",
        "Q17085620",
        constellations=("planet-flock", "planet-skysat", "planet-pelican"),
    ),
    OperatorSpec("Spire Global", "Q19877982", constellations=("spire",)),
    OperatorSpec("Telesat", "Q2401935", constellations=("telesat",)),
    OperatorSpec("Swarm Technologies", "Q103484515", constellations=("spacebee",)),
    OperatorSpec(
        "United States Space Force",
        "Q55088961",
        constellations=("gps", "wgs", "aehf", "sbirs", "dmsp", "checkmate", "muos"),
    ),
    OperatorSpec(
        "S.P. Korolev Rocket and Space Corporation Energia - OKB-1",
        "Q763402",
        constellations=("molniya",),
    ),
    OperatorSpec(
        "Roscosmos",
        "Q190795",
        constellations=(
            "soyuz",
            "mir",
            "fregat",
            "proton-m",
            "glonass",
            "gonets",
            "iss",
        ),
    ),
    OperatorSpec(
        "European Union Agency for the Space Programme",
        "Q55610347",
        constellations=("galileo",),
    ),
    OperatorSpec(
        "NASA",
        "Q23548",
        constellations=(
            "explorer",
            "themis",
            "tdrss",
            "iss",
            "goes",
            "landsat",
            "jason",
            "Television-Infrared-Observation-Satellite",
        ),
    ),
    OperatorSpec("US Navy", "Q11220", constellations=("transit", "vanguard")),
    OperatorSpec(
        "US Air Force", "Q11223", constellations=("us-ops-classified", "titan-rocket")
    ),
    OperatorSpec("Soviet Navy", "Q796754", constellations=("us-a",)),
    OperatorSpec(
        "China Meteorological Administration", "Q1063933", constellations=("fengyun",)
    ),
    OperatorSpec(
        "China National Space Administration",
        "Q320644",
        constellations=("beidou", "gaofen", "tianlian", "chinese-space-station"),
    ),
    OperatorSpec(
        "Shanghai Spacecom Satellite Technology",
        "Q128693569",
        constellations=("qianfan",),
    ),
    OperatorSpec("CNES", "Q48756", constellations=("argos", "jason")),
    OperatorSpec("Geespace", "Q125167295", constellations=("geesat",)),
    OperatorSpec("ICS-Holding", "Q86669053", constellations=("rassvet",)),
    OperatorSpec("Gazprom Space Systems", "Q4131791", constellations=("Yamal",)),
    OperatorSpec("Northrop Grumman", "Q86894155", constellations=("cygnus",)),
    OperatorSpec(
        "Outpost Space",
        url="https://www.outpost.space/",
        prefix=("OUTPOST MISSION",),
        category=SatelliteCategory.UNMANNED_CARGO,
    ),
    OperatorSpec("D-Orbit", wikidata_qid="Q116214401", constellations=("d-orbit-ion",)),
    OperatorSpec(
        "Chang Guang Satellite Technology",
        "Q30259654",
        constellations=("jilin", "yunyao"),
    ),
    OperatorSpec(
        "Zhuhai Orbita Aerospace",
        None,
        constellations=("zhuhai",),
        url="https://www.obtdata.com/en/index.html",
    ),
    OperatorSpec(
        "Guodian Gaokeji",
        None,
        constellations=("tianqi",),
        url="https://www.guodiangaoke.com/web/dist/index.html#/",
    ),
    OperatorSpec(
        "Beijing Future Navigation Technology", None, constellations=("centispace",)
    ),
    OperatorSpec(
        "China Satcom",
        "Q18243665",
        constellations=("tiantong", "zhongxing", "chinasat"),
    ),
    OperatorSpec(
        "People's Liberation Army",
        "Q200106",
        constellations=(
            "yaogan",
            "tongxin-jishu-shiyan",
            "tianyan",
            "tianhui",
            "yunhai-1",
            "yunhai-2",
            "yunhai-3",
        ),
    ),
    OperatorSpec(
        "China Aerospace Science and Industry Corporation / CASIC",
        "Q10874081",
        constellations=(
            "tianmu",
            "guowang",
        ),
    ),
    OperatorSpec(
        "Camsat - chinese amateur radio",
        None,
        constellations=(
            "xw",
            "cas",
        ),
    ),
    OperatorSpec(
        "China Aerospace Science and Technology Corporation / CASC",
        "Q2777589",
        constellations=(
            "shijian",
            "chuangxin",
            "shiyan",
            "superview-china-siwei",
            "haiyang",
            "long-march",
        ),
    ),
    # US military
    OperatorSpec(
        "Space Development Agency",
        "Q75746123",
        constellations=("sda", "sda-praetorian"),
    ),  # LEO missile tracking
    OperatorSpec("DARPA", "Q207361", constellations=("blackjack",)),
    OperatorSpec(
        "National Reconnaissance Office",
        "Q427818",
        constellations=("usa-classified",),
        url="https://en.wikipedia.org/wiki/File:Nrol-39.jpg",
    ),
    # US civilian / weather
    OperatorSpec("NOAA", "Q214700", constellations=("goes", "noaa", "jason")),
    OperatorSpec("USGS", "Q193755", constellations=("landsat",)),
    # US commercial
    OperatorSpec("HawkEye 360", "Q104845338", constellations=("hawkeye360",)),
    OperatorSpec("Capella Space", "Q43401532", constellations=("capella",)),
    OperatorSpec("Tomorrow.io", "Q30668374", constellations=("tomorrow-io",)),
    OperatorSpec("EchoStar", "Q1280748", constellations=("echostar",)),
    OperatorSpec("Viasat", "Q7924358", constellations=("viasat",)),
    OperatorSpec("Lynk Global", "Q107675681", constellations=("lynk",)),
    OperatorSpec("ICEYE", "Q31086161", constellations=("iceye",)),
    # Umbra: US commercial SAR startup constellation.
    OperatorSpec(
        "Umbra",
        None,
        prefix=("UMBRA",),
        category=SatelliteCategory.OBSERVATION,
        url="https://umbra.space/",
    ),
    OperatorSpec("AST SpaceMobile", "Q112659289", constellations=("ast-spacemobile",)),
    # Space radio
    OperatorSpec(
        "SiriusXM",
        "Q3277465",
        prefix=("FM-", "SXM"),
        category=SatelliteCategory.COMMUNICATIONS,
    ),
    OperatorSpec("SpaceQuest", "Q7572201", constellations=("aprizesat",)),
    OperatorSpec("The Aerospace Corporation", "Q7712741", constellations=("aerocube",)),
    OperatorSpec(
        "Vantor", "Q136461484", constellations=("worldView-legion",)
    ),  # PE spinoff of a maxar division
)


OPERATOR_BY_SOURCE: dict[str, OperatorSpec] = {
    o.source: o for o in OPERATORS if o.source is not None
}
OPERATOR_BY_CONSTELLATION: dict[str, OperatorSpec] = {
    slug: o for o in OPERATORS for slug in o.constellations
}
