"""Satellite operators (companies, agencies, intergovernmental orgs).

Linked to the fleet through one of two paths:

- ``source``: a SATCAT ``OWNER`` code (see ``sources.py``) — when CelesTrak
  assigns the operator its own code (Intelsat, Eutelsat, ...).
- ``constellations``: constellation slugs — when the operator isn't a SATCAT
  source but owns one or more constellations (SpaceX/Starlink, Amazon/Kuiper).

``slug`` is the URL-friendly identifier; the merged organization group page
prefixes it with ``org-`` (see ``organizations.py``).
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
    slug: str  # URL slug, unique within OPERATORS; org registry prefixes with "org-"
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
    OperatorSpec(
        "Arabsat", "arabsat", "Q624426", source="AB", constellations=("arabsat",)
    ),
    OperatorSpec(
        "Asia Broadcast Satellite",
        "abs",
        "Q18238088",
        source="ABS",
        constellations=("abs",),
    ),
    OperatorSpec(
        "AsiaSat", "asiasat", "Q726812", source="AC", constellations=("asiasat",)
    ),
    OperatorSpec(
        "ESA - European Space Agency",
        "esa",
        "Q42262",
        source="ESA",
        constellations=("iride", "iss", "sentinel"),
    ),
    OperatorSpec(
        "JAXA",
        "jaxa",
        "Q179103",
        constellations=(
            "iss",
            "h-2",
            "h-1",
            "h3",
            "n-1-japan",
            "n-2-japan",
            "epsilon",
            "mu-rocket",
            "hitomi-debris",
        ),
    ),
    OperatorSpec("CSA", "csa", "Q212227", constellations=("iss",)),
    OperatorSpec(
        "Italian Space Agency",
        "asi",
        "Q392953",
        constellations=("iride", "cosmo-skymed"),
    ),
    OperatorSpec(
        "European Space Research Organization", "esro", "Q473105", source="ESRO"
    ),
    OperatorSpec(
        "ArianeGroup", "arianegroup", "Q19951610", constellations=("ariane", "vega")
    ),
    OperatorSpec(
        "EUMETSAT",
        "eumetsat",
        "Q692163",
        source="EUME",
        constellations=("metop", "meteosat"),
    ),
    OperatorSpec(
        "Eutelsat",
        "eutelsat",
        "Q848336",
        source="EUTE",
        constellations=("oneweb", "eutelsat"),
    ),
    OperatorSpec(
        "Globalstar",
        "globalstar",
        "Q1202533",
        source="GLOB",
        constellations=("globalstar",),
    ),
    OperatorSpec(
        "Inmarsat",
        "inmarsat",
        "Q827927",
        source="IM",
        constellations=("marecs", "marisat", "inmarsat"),
    ),
    OperatorSpec(
        "Iridium",
        "iridium",
        "Q3154356",
        source="IRID",
        constellations=("iridium", "iridium-33-debris"),
    ),
    OperatorSpec(
        "Indian Space Research Organisation",
        "isro",
        "Q229058",
        source="ISRO",
        constellations=(
            "pslv",
            "gslv",
            "slv-3",
            "aslv",
            "lvm3",
            "sslv",
            "irnss-navic",
            "cartosat",
            "risat",
            "resourcesat-irs",
        ),
    ),
    OperatorSpec(
        "Intelsat",
        "intelsat",
        "Q778126",
        source="ITSO",
        constellations=("intelsat", "galaxy", "horizons"),
    ),
    OperatorSpec("North Atlantic Treaty Organization", "nato", "Q7184", source="NATO"),
    OperatorSpec(
        "ICO Global Communications",
        "ico",
        "Q3792482",
        source="NICO",
        constellations=("new-ico",),
    ),
    OperatorSpec(
        "Orbcomm", "orbcomm", "Q16960684", source="ORB", constellations=("orbcomm",)
    ),
    OperatorSpec(
        "RascomStar-QAF",
        "rascomstar-qaf",
        "Q3415056",
        source="RASC",
        constellations=("rascomstar",),
    ),
    OperatorSpec(
        "SES",
        "ses",
        "Q333025",
        source="SES",
        constellations=("ses", "o3b-gen1", "o3b-mpower", "amc", "astra", "nss"),
    ),
    # Linked only via constellation
    OperatorSpec(
        "SpaceX",
        "spacex",
        "Q193701",
        constellations=("starlink", "crew-dragon", "falcon", "dragon"),
    ),
    OperatorSpec(
        "ULA - United Launch Alliance",
        "ula",
        "Q1236833",
        constellations=("atlas", "delta", "vulcan"),
    ),
    OperatorSpec(
        "Boeing",
        "boeing",
        "Q66",
        constellations=("ius",),
    ),
    OperatorSpec("Rocket Lab", "rocket-lab", "Q116319", constellations=("electron",)),
    OperatorSpec("Amazon", "amazon", "Q3884", constellations=("kuiper",)),
    OperatorSpec(
        "MEASAT Satellite Systems",
        "measat",
        "Q1881326",
        constellations=("measat", "africasat"),
    ),
    OperatorSpec("Thaicom", "thaicom", "Q6903407", constellations=("thaicom",)),
    OperatorSpec(
        "Planet Labs",
        "planet-labs",
        "Q17085620",
        constellations=("planet-flock", "planet-skysat", "planet-pelican"),
    ),
    OperatorSpec("Spire Global", "spire", "Q19877982", constellations=("spire",)),
    OperatorSpec("Telesat", "telesat", "Q2401935", constellations=("telesat", "anik")),
    OperatorSpec("Space Norway", "space-norway", "Q19389792", constellations=("thor",)),
    OperatorSpec("SBS", "sbs", "Q7426030", prefix=("SBS ", "SBS-")),
    OperatorSpec(
        "JSAT Corporation",
        "jsat",
        "Q4355616",
        constellations=("jsat", "superbird", "dsn", "horizons"),
    ),
    OperatorSpec(
        "B-SAT - Broadcasting Satellite System Corporation",
        "b-sat",
        "Q922482",
        prefix=("BSAT", "BS-3N"),
    ),
    OperatorSpec(
        "Telkom Indonesia",
        "telkom",
        "Q2305438",
        prefix=("TELKOM",),
    ),
    OperatorSpec(
        "VNPT - Vietnam Posts and Telecommunications Group",
        "vnpt",
        "Q7928543",
        prefix=("VINASAT-",),
    ),
    OperatorSpec(
        "Swarm Technologies", "swarm", "Q103484515", constellations=("spacebee",)
    ),
    OperatorSpec(
        "United States Space Force",
        "us-space-force",
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
            "nts-satellites",  # NTS-3 (NTS-1/2 were US Navy)
            "idscs",
            "dscs",
            "milstar",
        ),
    ),
    OperatorSpec(
        # The Molniya fleet was flown by the bureau in its OKB-1 days.
        "S.P. Korolev Rocket and Space Corporation Energia",
        "energia",
        "Q763402",
        constellations=("molniya",),
    ),
    OperatorSpec(
        "Soviet space program",
        "soviet-space-program",
        "Q849730",
        constellations=(
            "elektron",
            "proton",
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
            "vostok",
            "voskhod",
            "luna",
            "zond",
            "gorizont",
            "ekran",
        ),
        active_until=1991,
    ),
    OperatorSpec(
        "Roscosmos",
        "roscosmos",
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
            "resurs-o1-debris",
            "resurs-p1-debris",
        ),
        active_from=1992,
    ),
    OperatorSpec(
        "Soviet Armed Forces",
        "soviet-armed-forces",
        "Q7915590",
        constellations=("cosmos", "cis-classified", "resurs-f", "raduga"),
        active_until=1991,
    ),
    OperatorSpec(
        "Russian Aerospace Forces",
        "russian-aerospace-forces",
        "Q21042210",
        constellations=(
            "cosmos",
            "blagovest",
            "cis-classified",
            "resurs-f",  # flights continued to 1999
            "cosmos-1408-debris",  # 2021 Nudol ASAT test
            "cosmos-2251-debris",  # Strela-2M military comsat (2009 collision)
            "raduga",
        ),
        active_from=1992,
    ),
    OperatorSpec(
        "European Union Agency for the Space Programme",
        "euspa",
        "Q55610347",
        constellations=("galileo",),
    ),
    OperatorSpec(
        "Japan Self-Defense Forces", "jsdf", "Q275488", constellations=("dsn",)
    ),
    OperatorSpec(
        "NASA",
        "nasa",
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
            "mercury-crewed",
            "gemini",
            "skylab",
            "crres-debris",
            "cobe-debris",
            "seasat-debris",
            "uars-debris",
            "echo-debris",
        ),
    ),
    OperatorSpec(
        "US Navy",
        "us-navy",
        "Q11220",
        constellations=(
            "transit",
            "vanguard",
            "nts-satellites",
            "fltsatcom",
            "noss-intruder",
        ),
    ),
    OperatorSpec(
        "US Air Force",
        "us-air-force",
        "Q11223",
        constellations=(
            "us-ops-classified",
            "leasat",
            "titan-rocket",
            "orbiting-vehicle-1",
            "orbiting-vehicle-2",
            "orbiting-vehicle-3",
            "orbiting-vehicle-4",
            "orbiting-vehicle-5",
            "westford-needles",
            "solwind-debris",  # 1985 ASM-135 ASAT test
            "crres-debris",
        ),
    ),
    OperatorSpec(
        "US DOD - Department of Defense",
        "us-dod",
        "Q11209",
        constellations=("leasat",),
    ),  # Shared infra, couldn't find a more specific operator
    OperatorSpec(
        "CIA - Central Intelligence Agency",
        "cia",
        "Q37230",
        constellations=("corona",),
    ),
    OperatorSpec("Soviet Navy", "soviet-navy", "Q796754", constellations=("us-a",)),
    OperatorSpec(
        "China Meteorological Administration",
        "cma",
        "Q1063933",
        constellations=("fengyun",),
    ),
    OperatorSpec(
        "China National Space Administration",
        "cnsa",
        "Q320644",
        constellations=(
            "beidou",
            "gaofen",
            "tianlian",
            "chinese-space-station",
            "shenzhou",
            "tianzhou",
            "change",
            "tianwen",
        ),
    ),
    OperatorSpec(
        "Shanghai Spacecom Satellite Technology",
        "shanghai-spacecom",
        "Q128693569",
        constellations=("qianfan",),
    ),
    OperatorSpec(
        "CNES", "cnes", "Q48756", constellations=("argos", "jason", "diamant")
    ),
    OperatorSpec("Geespace", "geespace", "Q125167295", constellations=("geesat",)),
    OperatorSpec(
        "ICS-Holding", "ics-holding", "Q86669053", constellations=("rassvet",)
    ),
    OperatorSpec(
        "Gazprom Space Systems",
        "gazprom-space-systems",
        "Q4131791",
        constellations=("yamal",),
    ),
    OperatorSpec(
        "Northrop Grumman",
        "northrop-grumman",
        "Q86894155",
        constellations=("cygnus", "minotaur", "antares", "taurus-minotaur-c"),
    ),
    OperatorSpec(
        "Outpost Space",
        "outpost-space",
        url="https://www.outpost.space/",
        prefix=("OUTPOST MISSION",),
        category=SatelliteCategory.UNMANNED_CARGO,
    ),
    OperatorSpec(
        "D-Orbit", "d-orbit", wikidata_qid="Q116214401", constellations=("d-orbit-ion",)
    ),
    OperatorSpec(
        "Chang Guang Satellite Technology",
        "chang-guang",
        "Q30259654",
        constellations=("jilin", "yunyao"),
    ),
    OperatorSpec(
        "Zhuhai Orbita Aerospace",
        "zhuhai-orbita",
        None,
        constellations=("zhuhai",),
        url="https://www.obtdata.com/en/index.html",
    ),
    OperatorSpec(
        "Guodian Gaokeji",
        "guodian-gaokeji",
        None,
        constellations=("tianqi",),
        url="https://www.guodiangaoke.com/web/dist/index.html#/",
    ),
    OperatorSpec(
        "Beijing Future Navigation Technology",
        "beijing-future-navigation",
        None,
        constellations=("centispace",),
    ),
    OperatorSpec(
        "China Satcom",
        "china-satcom",
        "Q18243665",
        constellations=("tiantong", "zhongxing", "chinasat"),
    ),
    OperatorSpec(
        "People's Liberation Army",
        "pla",
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
            "fengyun-1c-asat-debris",  # 2007 SC-19 ASAT test
        ),
    ),
    OperatorSpec(
        "China Aerospace Science and Industry Corporation / CASIC",
        "casic",
        "Q10874081",
        constellations=(
            "tianmu",
            "guowang",
            "kuaizhou",
        ),
    ),
    OperatorSpec(
        "Camsat - chinese amateur radio",
        "camsat",
        None,
        constellations=(
            "xw",
            "cas",
        ),
    ),
    OperatorSpec(
        "China Aerospace Science and Technology Corporation / CASC",
        "casc",
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
        "cas-academy",
        "Q530471",
        constellations=("lijian",),
    ),
    # US military
    OperatorSpec(
        "Space Development Agency",
        "sda",
        "Q75746123",
        constellations=("sda", "sda-praetorian"),
    ),  # LEO missile tracking
    OperatorSpec("DARPA", "darpa", "Q207361", constellations=("blackjack",)),
    OperatorSpec(
        "National Reconnaissance Office",
        "nro",
        "Q427818",
        constellations=("usa-classified", "nemesis", "noss-intruder"),
        url="https://en.wikipedia.org/wiki/File:Nrol-39.jpg",
    ),
    # US civilian / weather
    OperatorSpec("NOAA", "noaa", "Q214700", constellations=("goes", "noaa", "jason")),
    OperatorSpec("USGS", "usgs", "Q193755", constellations=("landsat",)),
    # US commercial
    OperatorSpec(
        "HawkEye 360", "hawkeye-360", "Q104845338", constellations=("hawkeye360",)
    ),
    OperatorSpec(
        "Capella Space", "capella-space", "Q43401532", constellations=("capella",)
    ),
    OperatorSpec(
        "Tomorrow.io", "tomorrow-io", "Q30668374", constellations=("tomorrow-io",)
    ),
    OperatorSpec("EchoStar", "echostar", "Q1280748", constellations=("echostar",)),
    OperatorSpec("Viasat", "viasat", "Q7924358", constellations=("viasat",)),
    OperatorSpec("Lynk Global", "lynk-global", "Q107675681", constellations=("lynk",)),
    OperatorSpec("ICEYE", "iceye", "Q31086161", constellations=("iceye",)),
    # Umbra: US commercial SAR startup constellation.
    OperatorSpec(
        "Umbra",
        "umbra",
        "Q121644709",
        constellations=("umbra-sar",),
        url="https://umbra.space/",
    ),
    OperatorSpec(
        "AST SpaceMobile",
        "ast-spacemobile",
        "Q112659289",
        constellations=("ast-spacemobile",),
    ),
    # Space radio
    OperatorSpec(
        "SiriusXM",
        "siriusxm",
        "Q3277465",
        prefix=("FM-", "SXM"),
        category=SatelliteCategory.COMMUNICATIONS,
    ),
    OperatorSpec("SpaceQuest", "spacequest", "Q7572201", constellations=("aprizesat",)),
    OperatorSpec(
        "The Aerospace Corporation",
        "aerospace-corporation",
        "Q7712741",
        constellations=("aerocube",),
    ),
    OperatorSpec(
        "Vantor", "vantor", "Q136461484", constellations=("worldView-legion",)
    ),  # PE spinoff of a maxar division
    # Foreign military / classified
    OperatorSpec(
        "Agency for Defense Development",
        "add",
        "Q626610",
        constellations=("skor-classified",),
    ),  # South Korean defense R&D agency
    OperatorSpec(
        "IRGC Aerospace Force",
        "irgc-aerospace-force",
        "Q4410582",
        constellations=("iran-classified", "qased", "qaem-100"),
    ),
    OperatorSpec(
        "Iranian Space Agency",
        "isa",
        "Q572596",
        constellations=("safir", "simorgh", "zuljanah"),
    ),
    OperatorSpec(
        "IAI - Israel Aerospace Industries",
        "iai",
        "Q876017",
        constellations=("shavit",),
    ),
    OperatorSpec(
        "Firefly Aerospace",
        "firefly-aerospace",
        "Q17492679",
        constellations=("firefly",),
    ),
    OperatorSpec(
        "DRDO - Defence Research and Development Organisation",
        "drdo",
        "Q1154393",
        constellations=("microsat-r-debris",),
    ),  # India, Mission Shakti 2019 ASAT test
    # Satellite-IoT / data-relay & EO commercial operators
    OperatorSpec("Kinéis", "kineis", "Q60849749", constellations=("kineis",)),
    OperatorSpec("Astrocast", "astrocast", "Q107563951", constellations=("astrocast",)),
    OperatorSpec(
        "Kepler Communications",
        "kepler-communications",
        "Q28163140",
        constellations=("kepler-communications",),
    ),
    OperatorSpec(
        "Synspective",
        "synspective",
        "Q110017262",
        constellations=("strix-synspective",),
    ),
    OperatorSpec(
        "Satellogic", "satellogic", "Q22669551", constellations=("nusat-satellogic",)
    ),
    OperatorSpec(
        "Axelspace", "axelspace", "Q24876408", constellations=("grus-axelspace",)
    ),
    OperatorSpec("iQPS", "iqps", "Q124040109", constellations=("qps-sar",)),
    OperatorSpec("BlackSky", "blacksky", "Q56314218", constellations=("blacksky",)),
    # Russian Satellite Communications Company — civil GEO comms since 1992.
    OperatorSpec(
        "Russian Satellite Communications Company",
        "rscc",
        "Q4355209",
        constellations=("gorizont", "ekran", "ekspress"),
        active_from=1992,
    ),
    OperatorSpec(
        "Japan Meteorological Agency", "jma", "Q860935", constellations=("himawari",)
    ),
    OperatorSpec(
        "UK Ministry of Defence", "uk-mod", "Q1143261", constellations=("skynet",)
    ),
    OperatorSpec(
        "Cabinet Office (Japan)",
        "cabinet-office-japan",
        "Q6005",
        constellations=("qzss",),
    ),  # operates QZSS / Michibiki
    OperatorSpec(
        "Ministry of Defense (Israel)",
        "israel-mod",
        "Q1862884",
        constellations=("ofeq",),
    ),
    OperatorSpec(
        "Bundeswehr", "bundeswehr", "Q56010", constellations=("sar-lupe", "sarah")
    ),
    OperatorSpec(
        "Galactic Energy",
        "galactic-energy",
        "Q104635667",
        constellations=("ceres-1", "pallas-1"),
    ),
    OperatorSpec("LandSpace", "landspace", "Q48772158", constellations=("zhuque-2",)),
    OperatorSpec(
        "Orienspace", "orienspace", "Q110921195", constellations=("gravity-1",)
    ),
    OperatorSpec(
        "Virgin Orbit", "virgin-orbit", "Q28939648", constellations=("launcherone",)
    ),
    OperatorSpec(
        "Relativity Space",
        "relativity-space",
        "Q54263821",
        constellations=("terran-1",),
    ),
    OperatorSpec(
        "Korea Aerospace Research Institute",
        "kari",
        "Q494948",
        constellations=("naro", "nuri"),
    ),
    OperatorSpec(
        "National Aerospace Development Administration",
        "nada",
        "Q17124852",
        constellations=("unha", "chollima-1"),
    ),
    # Operators GCAT's Owner column names that no CelesTrak owner code does;
    # see gcat_orgs.py for the code → slug table.
    OperatorSpec("Eutelsat OneWeb", "oneweb", "Q24039799"),
    OperatorSpec("China Satellite Network Group", "china-satnet", "Q109051243"),
    OperatorSpec("China Manned Space Agency", "cmsa", "Q5099768"),
    OperatorSpec(
        "People's Liberation Army General Armaments Department",
        "pla-gad",
        "Q6148033",
    ),
    OperatorSpec("Ministry of Aerospace Industry", "mai-china", "Q6866598"),
    OperatorSpec("Soviet Air Defence Forces", "pvo", "Q631009"),
    OperatorSpec("Sitronics", "sitronics", "Q1022148"),
    OperatorSpec("National Space Development Agency of Japan", "nasda", "Q2704796"),
    OperatorSpec("Environmental Science Services Administration", "essa", "Q3055447"),
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

OPERATOR_BY_SLUG: dict[str, OperatorSpec] = {o.slug: o for o in OPERATORS}

assert len(OPERATOR_BY_SLUG) == len(OPERATORS), "Duplicate operator slug"
