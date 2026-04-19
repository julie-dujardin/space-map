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

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from space_map_data.constants.earth_sats.constellations import SatelliteCategory

# Year-only or exact date for operator active periods.
ActiveDate = int | date


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    wikidata_qid: str | None = None
    source: str | None = None  # SATCAT SOURCE/OWNER code, when one exists
    constellations: tuple[str, ...] = ()  # constellation slugs operated by this entity
    url: str | None = None  # Alternate ref if no wikipedia
    prefix: tuple[str, ...] = ()  # Companies with no constellations - direct to company
    category: SatelliteCategory | None = None  # Apply category to satelites
    active_from: ActiveDate | None = None
    active_until: ActiveDate | None = None


def _to_date(d: str) -> date:
    """Parse a SATCAT date string (YYYY-MM-DD) to a date."""
    return date.fromisoformat(d[:10])


def _active_as_date_lower(ad: ActiveDate) -> date:
    """Earliest possible date: 1992 → 1992-01-01."""
    return date(ad, 1, 1) if isinstance(ad, int) else ad


def _active_as_date_upper(ad: ActiveDate) -> date:
    """Latest possible date: 1991 → 1991-12-31."""
    return date(ad, 12, 31) if isinstance(ad, int) else ad


def operator_overlaps(
    op: OperatorSpec,
    launch_date: str | None,
    decay_date: str | None,
) -> bool:
    """Check whether a satellite's lifetime overlaps the operator's active period."""
    if op.active_until is not None and launch_date is not None:
        if _to_date(launch_date) > _active_as_date_upper(op.active_until):
            return False
    if op.active_from is not None and decay_date is not None:
        if _to_date(decay_date) < _active_as_date_lower(op.active_from):
            return False
    return True


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
    OperatorSpec(
        "JAXA", "Q179103", constellations=("iss", "h-2", "h-1", "epsilon", "mu-rocket")
    ),
    OperatorSpec("CSA", "Q212227", constellations=("iss",)),
    OperatorSpec("Italian Space Agency", "Q392953", constellations=("iride",)),
    OperatorSpec("European Space Research Organization", "Q473105", source="ESRO"),
    OperatorSpec("ArianeGroup", "Q19951610", constellations=("ariane", "vega")),
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
    OperatorSpec(
        "Indian Space Research Organisation",
        "Q229058",
        source="ISRO",
        constellations=("pslv", "gslv"),
    ),
    OperatorSpec(
        "Intelsat",
        "Q778126",
        source="ITSO",
        constellations=("intelsat", "galaxy", "horizons"),
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
    OperatorSpec(
        "SES", "Q333025", source="SES", constellations=("ses", "o3b-gen1", "o3b-mpower")
    ),
    # Linked only via constellation
    OperatorSpec(
        "SpaceX",
        "Q193701",
        constellations=("starlink", "crew-dragon", "falcon", "dragon"),
    ),
    OperatorSpec(
        "ULA - United Launch Alliance",
        "Q1236833",
        constellations=("atlas", "delta", "vulcan"),
    ),
    OperatorSpec(
        "Boeing",
        "Q66",
        constellations=("ius",),
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
    OperatorSpec("Telesat", "Q2401935", constellations=("telesat", "anik")),
    OperatorSpec("Space Norway", "Q19389792", constellations=("thor",)),
    OperatorSpec("SBS", "Q7426030", prefix=("SBS ", "SBS-")),
    OperatorSpec(
        "JSAT Corporation",
        "Q4355616",
        constellations=("jsat", "superbird", "dsn", "horizons"),
    ),
    OperatorSpec("Swarm Technologies", "Q103484515", constellations=("spacebee",)),
    OperatorSpec(
        "United States Space Force",
        "Q55088961",
        constellations=(
            "gps",
            "wgs",
            "aehf",
            "sbirs",
            "dmsp",
            "checkmate",
            "muos",
            "dsp",
            "uhf-follow-on",
        ),
    ),
    OperatorSpec(
        "S.P. Korolev Rocket and Space Corporation Energia - OKB-1",
        "Q763402",
        constellations=("molniya",),
    ),
    OperatorSpec(
        "Soviet space program",
        "Q849730",
        constellations=(
            "soyuz",
            "soyuz-rocket",
            "progress",
            "mir",
            "fregat",
            "proton-m",
            "glonass",
            "gonets",
            "sputnik",
            "salyut",
            "venera",
            "meteor",
            "block-dm",
        ),
        active_until=1991,
    ),
    OperatorSpec(
        "Roscosmos",
        "Q190795",
        constellations=(
            "soyuz",
            "soyuz-rocket",
            "progress",
            "mir",
            "fregat",
            "proton-m",
            "glonass",
            "gonets",
            "iss",
            "meteor",
            "block-dm",
        ),
        active_from=1992,
    ),
    OperatorSpec(
        "Soviet Armed Forces",
        "Q7915590",
        constellations=("cosmos", "cis-classified", "resurs-"),
        active_until=1991,
    ),
    OperatorSpec(
        "Russian Aerospace Forces",
        "Q21042210",
        constellations=("cosmos", "blagovest", "cis-classified", "resurs-"),
        active_from=1992,
    ),
    OperatorSpec(
        "European Union Agency for the Space Programme",
        "Q55610347",
        constellations=("galileo",),
    ),
    OperatorSpec("Japan Self-Defense Forces", "Q275488", constellations=("dsn",)),
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
            "apollo",
            "saturn",
            "scout",
            "pegasus",
            "thor",
            "pageos",
            "sts",
            "nimbus",
            "syncom",
        ),
    ),
    OperatorSpec("US Navy", "Q11220", constellations=("transit", "vanguard")),
    OperatorSpec(
        "US Air Force",
        "Q11223",
        constellations=("us-ops-classified", "leasat", "titan-rocket"),
    ),
    OperatorSpec(
        "US DOD - Department of Defense",
        "Q11209",
        constellations=("leasat",),
    ),  # Shared infra, couldn't find a more specific operator
    OperatorSpec(
        "CIA - Central Intelligence Agency",
        "Q37230",
        constellations=("corona",),
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
    OperatorSpec("CNES", "Q48756", constellations=("argos", "jason", "diamant")),
    OperatorSpec("Geespace", "Q125167295", constellations=("geesat",)),
    OperatorSpec("ICS-Holding", "Q86669053", constellations=("rassvet",)),
    OperatorSpec("Gazprom Space Systems", "Q4131791", constellations=("yamal",)),
    OperatorSpec(
        "Northrop Grumman",
        "Q86894155",
        constellations=("cygnus", "minotaur", "antares"),
    ),
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
            "prc-classified",
        ),
    ),
    OperatorSpec(
        "China Aerospace Science and Industry Corporation / CASIC",
        "Q10874081",
        constellations=(
            "tianmu",
            "guowang",
            "kuaizhou",
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
            "yuanzheng",
            "jielong",
        ),
    ),
    OperatorSpec(
        "Chinese Academy of Sciences / CAS",
        "Q530471",
        constellations=("lijian",),
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
    # Foreign military / classified
    OperatorSpec(
        "Agency for Defense Development",
        "Q626610",
        constellations=("skor-classified",),
    ),  # South Korean defense R&D agency
    OperatorSpec(
        "IRGC Aerospace Force",
        "Q4410582",
        constellations=("iran-classified",),
    ),
    OperatorSpec(
        "Iranian Space Agency",
        "Q572596",
        constellations=("safir",),
    ),
    OperatorSpec(
        "IAI - Israel Aerospace Industries",
        "Q876017",
        constellations=("shavit",),
    ),
    OperatorSpec(
        "Firefly Aerospace",
        "Q17492679",
        constellations=("firefly",),
    ),
)


OPERATOR_BY_SOURCE: dict[str, OperatorSpec] = {
    o.source: o for o in OPERATORS if o.source is not None
}

_by_constellation: dict[str, list[OperatorSpec]] = defaultdict(list)
for _op in OPERATORS:
    for _slug in _op.constellations:
        _by_constellation[_slug].append(_op)
OPERATOR_BY_CONSTELLATION: dict[str, list[OperatorSpec]] = dict(_by_constellation)

OPERATOR_BY_QID: dict[str, OperatorSpec] = {
    o.wikidata_qid: o for o in OPERATORS if o.wikidata_qid is not None
}
