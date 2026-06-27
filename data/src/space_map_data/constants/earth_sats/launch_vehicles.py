"""Launch-vehicle group entities (``/g/lv-<slug>``).

Each launch vehicle merges two views of itself: spent stages tracked in orbit
(via the ROCKET ``ConstellationSpec`` of the same slug) and its launch history
(GCAT launchlog rows whose ``lv_type`` matches ``lv_prefixes``). Most slugs
reuse a constellation for orbital membership + QID; launch-only families with
no catalogued debris (Space Shuttle, deep-space expendables, recent commercial
flights) declare their own QID inline.

``lv_type`` matching is longest-prefix-wins so nested names resolve correctly:
"Thor Delta" → ``delta`` beats "Thor " → ``thor-rocket``; "GSLV Mk III" →
``lvm3`` beats "GSLV" → ``gslv``.
"""

from dataclasses import dataclass

from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_BY_SLUG,
    SatelliteCategory,
)

LAUNCH_VEHICLE_SLUG_PREFIX = "lv-"


@dataclass(frozen=True)
class LaunchVehicleSpec:
    """A launch-vehicle group page.

    ``constellation_slug`` links a ROCKET constellation supplying orbital
    rocket-body members and (when ``wikidata_qid`` is unset) the QID + display
    name. Launch-only families leave it ``None`` and set ``wikidata_qid`` /
    ``name`` directly.
    """

    slug: str
    lv_prefixes: tuple[str, ...] = ()
    constellation_slug: str | None = None
    wikidata_qid: str | None = None
    name: str | None = None

    @property
    def qid(self) -> str | None:
        """Own QID, else the backing constellation's."""
        if self.wikidata_qid is not None:
            return self.wikidata_qid
        if self.constellation_slug is not None:
            spec = CONSTELLATION_BY_SLUG.get(self.constellation_slug)
            if spec is not None:
                return spec.wikidata_qid
        return None


LAUNCH_VEHICLES: tuple[LaunchVehicleSpec, ...] = (
    # Constellation-backed: orbital rocket-body members + launchlog launches.
    # `constellation_slug` reuses the ROCKET ConstellationSpec's QID + matching.
    LaunchVehicleSpec(
        "long-march", ("Chang Zheng", "Feng Bao"), constellation_slug="long-march"
    ),
    LaunchVehicleSpec(
        "titan-rocket", ("Titan", "Commercial Titan"), constellation_slug="titan-rocket"
    ),
    LaunchVehicleSpec(
        "falcon", ("Falcon 9", "Falcon Heavy", "Falcon 1"), constellation_slug="falcon"
    ),
    LaunchVehicleSpec("atlas", ("Atlas",), constellation_slug="atlas"),
    LaunchVehicleSpec("delta", ("Delta", "Thor Delta"), constellation_slug="delta"),
    LaunchVehicleSpec("electron", ("Electron",), constellation_slug="electron"),
    LaunchVehicleSpec(
        "thor-rocket", ("Thor ", "Thorad", "Thor-"), constellation_slug="thor-rocket"
    ),
    LaunchVehicleSpec("pslv", ("PSLV",), constellation_slug="pslv"),
    LaunchVehicleSpec("pegasus", ("Pegasus",), constellation_slug="pegasus"),
    LaunchVehicleSpec(
        "saturn", ("Saturn", "Uprated Saturn"), constellation_slug="saturn"
    ),
    LaunchVehicleSpec("scout", ("Scout", "Blue Scout"), constellation_slug="scout"),
    LaunchVehicleSpec("diamant", ("Diamant",), constellation_slug="diamant"),
    LaunchVehicleSpec(
        "black-arrow", ("Black Arrow",), constellation_slug="black-arrow"
    ),
    LaunchVehicleSpec("h-1", ("H-1",), constellation_slug="h-1"),
    LaunchVehicleSpec("h-2", ("H-II",), constellation_slug="h-2"),
    LaunchVehicleSpec("n-1-japan", ("N-1",), constellation_slug="n-1-japan"),
    LaunchVehicleSpec("n-2-japan", ("N-2",), constellation_slug="n-2-japan"),
    LaunchVehicleSpec("h3", ("H3",), constellation_slug="h3"),
    LaunchVehicleSpec("gslv", ("GSLV",), constellation_slug="gslv"),
    LaunchVehicleSpec(
        "minotaur",
        ("Minotaur I", "Minotaur IV", "Minotaur V"),
        constellation_slug="minotaur",
    ),
    LaunchVehicleSpec("antares", ("Antares",), constellation_slug="antares"),
    LaunchVehicleSpec("shavit", ("Shavit",), constellation_slug="shavit"),
    LaunchVehicleSpec("epsilon", ("Epsilon",), constellation_slug="epsilon"),
    LaunchVehicleSpec("vulcan", ("Vulcan",), constellation_slug="vulcan"),
    LaunchVehicleSpec("firefly", ("Firefly",), constellation_slug="firefly"),
    LaunchVehicleSpec("kuaizhou", ("Kuaizhou",), constellation_slug="kuaizhou"),
    LaunchVehicleSpec("lijian", ("Lijian",), constellation_slug="lijian"),
    LaunchVehicleSpec("jielong", ("Jielong",), constellation_slug="jielong"),
    LaunchVehicleSpec(
        "mu-rocket", ("Mu-", "M-V", "M-3", "M-4"), constellation_slug="mu-rocket"
    ),
    LaunchVehicleSpec("vega", ("Vega",), constellation_slug="vega"),
    LaunchVehicleSpec("athena", ("Athena", "LMLV", "LLV"), constellation_slug="athena"),
    LaunchVehicleSpec(
        "taurus-minotaur-c",
        ("Taurus", "Minotaur-C", "ARPA Taurus"),
        constellation_slug="taurus-minotaur-c",
    ),
    LaunchVehicleSpec("conestoga", ("Conestoga",), constellation_slug="conestoga"),
    LaunchVehicleSpec(
        "juno-ii", ("Juno II", "Jupiter C", "Juno I"), constellation_slug="juno-ii"
    ),
    LaunchVehicleSpec(
        "vanguard-rocket", ("Vanguard",), constellation_slug="vanguard-rocket"
    ),
    LaunchVehicleSpec(
        "launcherone", ("LauncherOne",), constellation_slug="launcherone"
    ),
    LaunchVehicleSpec("terran-1", ("Terran 1",), constellation_slug="terran-1"),
    LaunchVehicleSpec("ceres-1", ("Gushenxing",), constellation_slug="ceres-1"),
    LaunchVehicleSpec("zhuque-2", ("Zhuque-2",), constellation_slug="zhuque-2"),
    LaunchVehicleSpec(
        "hyperbola-1", ("Shuang Quxian", "SQX"), constellation_slug="hyperbola-1"
    ),
    LaunchVehicleSpec("gravity-1", ("Yinli",), constellation_slug="gravity-1"),
    LaunchVehicleSpec("kaituozhe", ("KT-1", "KT-2"), constellation_slug="kaituozhe"),
    LaunchVehicleSpec("pallas-1", (), constellation_slug="pallas-1"),
    LaunchVehicleSpec("slv-3", ("SLV-3",), constellation_slug="slv-3"),
    LaunchVehicleSpec("aslv", ("ASLV",), constellation_slug="aslv"),
    LaunchVehicleSpec("lvm3", ("LVM3", "GSLV Mk III"), constellation_slug="lvm3"),
    LaunchVehicleSpec("sslv", ("SSLV",), constellation_slug="sslv"),
    LaunchVehicleSpec("naro", ("Naro",), constellation_slug="naro"),
    LaunchVehicleSpec("nuri", ("Nuri",), constellation_slug="nuri"),
    LaunchVehicleSpec(
        "unha", ("Unha", "Paektusan", "Kwangmyongsong"), constellation_slug="unha"
    ),
    LaunchVehicleSpec("chollima-1", ("Cheonlima",), constellation_slug="chollima-1"),
    LaunchVehicleSpec("safir", ("Safir",), constellation_slug="safir"),
    LaunchVehicleSpec("simorgh", ("Simorgh",), constellation_slug="simorgh"),
    LaunchVehicleSpec("qased", ("Qased",), constellation_slug="qased"),
    LaunchVehicleSpec("qaem-100", ("Qaem-100",), constellation_slug="qaem-100"),
    LaunchVehicleSpec(
        "zuljanah", ("Zoljanah", "Zuljanah"), constellation_slug="zuljanah"
    ),
    LaunchVehicleSpec("ariane", ("Ariane",), constellation_slug="ariane"),
    LaunchVehicleSpec("soyuz-rocket", ("Soyuz",), constellation_slug="soyuz-rocket"),
    LaunchVehicleSpec(
        "sputnik-rocket", ("Sputnik",), constellation_slug="sputnik-rocket"
    ),
    LaunchVehicleSpec("vostok-rocket", ("Vostok",), constellation_slug="vostok-rocket"),
    LaunchVehicleSpec("polyot", ("Polyot",), constellation_slug="polyot"),
    LaunchVehicleSpec(
        "molniya-rocket", ("Molniya",), constellation_slug="molniya-rocket"
    ),
    LaunchVehicleSpec(
        "kosmos-2i", ("Kosmos 11K63", "Kosmos 63S1"), constellation_slug="kosmos-2i"
    ),
    LaunchVehicleSpec(
        "kosmos-3m",
        ("Kosmos 11K65", "Kosmos 65S3", "K65M-RB"),
        constellation_slug="kosmos-3m",
    ),
    LaunchVehicleSpec(
        "proton-rocket",
        ("Proton-K", "Proton ", "UR-500"),
        constellation_slug="proton-rocket",
    ),
    LaunchVehicleSpec("tsyklon-2", ("Tsiklon-2",), constellation_slug="tsyklon-2"),
    LaunchVehicleSpec("tsyklon-3", ("Tsiklon-3",), constellation_slug="tsyklon-3"),
    LaunchVehicleSpec("zenit", ("Zenit",), constellation_slug="zenit"),
    LaunchVehicleSpec("start-1", ("Start-1", "Start"), constellation_slug="start-1"),
    LaunchVehicleSpec("rokot", ("Rokot",), constellation_slug="rokot"),
    LaunchVehicleSpec("shtil", ("Shtil'", "Shtil"), constellation_slug="shtil"),
    LaunchVehicleSpec("dnepr", ("Dnepr",), constellation_slug="dnepr"),
    LaunchVehicleSpec("energia", ("Energiya", "Energia"), constellation_slug="energia"),
    LaunchVehicleSpec("fregat", (), constellation_slug="fregat"),
    LaunchVehicleSpec("proton-m", ("Proton-M",), constellation_slug="proton-m"),
    # Launch-only families (no catalogued debris); QID declared inline, None
    # where Wikidata had no confident match (page falls back to `name`).
    LaunchVehicleSpec(
        "starship", ("Starship",), wikidata_qid="Q62833385", name="Starship"
    ),
    LaunchVehicleSpec(
        "space-shuttle", ("Space Shuttle",), wikidata_qid="Q48806", name="Space Shuttle"
    ),
    LaunchVehicleSpec(
        "sls", ("SLS",), wikidata_qid="Q64127", name="Space Launch System"
    ),
    LaunchVehicleSpec("voskhod", ("Voskhod",), wikidata_qid="Q1526424", name="Voskhod"),
    LaunchVehicleSpec("angara", ("Angara",), wikidata_qid="Q530600", name="Angara"),
    LaunchVehicleSpec(
        "new-glenn", ("New Glenn",), wikidata_qid="Q26869616", name="New Glenn"
    ),
    LaunchVehicleSpec("vls-1", ("VLS-1",), wikidata_qid="Q60593", name="VLS-1"),
    LaunchVehicleSpec("lambda", ("Lambda",), wikidata_qid="Q5241097", name="Lambda"),
    LaunchVehicleSpec("strela", ("Strela",), wikidata_qid="Q248564", name="Strela"),
    LaunchVehicleSpec("europa", ("Europa",), wikidata_qid=None, name="Europa"),
    LaunchVehicleSpec(
        "super-strypi", ("Super Strypi",), wikidata_qid="Q2654744", name="Super Strypi"
    ),
    LaunchVehicleSpec(
        "astra-rocket-3",
        ("Astra Rocket",),
        wikidata_qid="Q56294729",
        name="Astra Rocket 3",
    ),
    LaunchVehicleSpec(
        "zhuque-3", ("Zhuque-3",), wikidata_qid="Q124807399", name="Zhuque-3"
    ),
    LaunchVehicleSpec(
        "tianlong-2", ("Tianlong-2",), wikidata_qid="Q116829551", name="Tianlong-2"
    ),
    LaunchVehicleSpec(
        "tianlong-3", ("Tianlong-3",), wikidata_qid="Q124715398", name="Tianlong-3"
    ),
    LaunchVehicleSpec(
        "hanbit", ("HANBIT",), wikidata_qid="Q132130760", name="HANBIT-Nano"
    ),
    LaunchVehicleSpec("kairos", ("Kairos",), wikidata_qid=None, name="Kairos"),
    LaunchVehicleSpec("rs1", ("RS1",), wikidata_qid=None, name="RS1"),
    LaunchVehicleSpec("spectrum", ("Spectrum",), wikidata_qid=None, name="Spectrum"),
    LaunchVehicleSpec("eris", ("Eris",), wikidata_qid=None, name="Eris"),
    LaunchVehicleSpec("os-m", ("OS-M",), wikidata_qid=None, name="OS-M"),
    LaunchVehicleSpec("volna", ("Volna",), wikidata_qid=None, name="Volna"),
)

LAUNCH_VEHICLE_BY_SLUG: dict[str, LaunchVehicleSpec] = {
    lv.slug: lv for lv in LAUNCH_VEHICLES
}
# Family QID → vehicle, for pointing a P375 crossref at its lv- page. Specific
# configurations are caught by LAUNCH_VEHICLE_VARIANT_QID instead.
LAUNCH_VEHICLE_BY_QID: dict[str, LaunchVehicleSpec] = {
    qid: lv for lv in LAUNCH_VEHICLES if (qid := lv.qid) is not None
}
# Specific P375 configurations ("Atlas V 401") → family slug, so the crossref
# reaches the family lv- page; the variant stays the displayed name. Ambiguous
# or non-LV values are intentionally absent (plain Wikipedia ref).
LAUNCH_VEHICLE_VARIANT_QID: dict[str, str] = {
    "Q112063526": "angara",  # Angara-1.2
    "Q18694511": "angara",  # Angara-A5
    "Q16351692": "ariane",  # Ariane 5 ECA
    "Q9159563": "ariane",  # Ariane 44L
    "Q9159564": "ariane",  # Ariane 44LP
    "Q16351696": "ariane",  # Ariane 5G
    "Q9159561": "ariane",  # Ariane 40
    "Q18381": "ariane",  # Ariane 3
    "Q9159559": "ariane",  # Ariane 42P
    "Q10417856": "ariane",  # Ariane 5ES
    "Q16530018": "ariane",  # Ariane 44P
    "Q16530012": "ariane",  # Ariane 42L
    "Q18375": "ariane",  # Ariane 1
    "Q135885158": "ariane",  # Ariane 62
    "Q16351704": "ariane",  # Ariane 5GS
    "Q124077105": "ariane",  # Ariane 5 ECA+
    "Q16351700": "ariane",  # Ariane 5G+
    "Q18379": "ariane",  # Ariane 2
    "Q135885159": "ariane",  # Ariane 64
    "Q15720682": "ariane",  # Ariane 6
    "Q18532": "ariane",  # Ariane 5
    "Q22786": "athena",  # Athena I
    "Q22791": "athena",  # Athena II
    "Q20803939": "atlas",  # Atlas V 401
    "Q9161682": "atlas",  # Atlas SLV-3 Agena-D
    "Q12403688": "atlas",  # Atlas E/F
    "Q23600": "atlas",  # Atlas II
    "Q862321": "atlas",  # Atlas-Centaur
    "Q9161678": "atlas",  # Atlas-Agena B
    "Q2895380": "atlas",  # SM-65D Atlas
    "Q16351993": "atlas",  # Atlas V 501
    "Q16352007": "atlas",  # Atlas V 551
    "Q9161679": "atlas",  # Atlas-Agena D
    "Q16351985": "atlas",  # Atlas V 421
    "Q16352003": "atlas",  # Atlas V 541
    "Q115629811": "atlas",  # Atlas SLV-3C Centaur-D
    "Q116027214": "atlas",  # Atlas IIAS
    "Q16351980": "atlas",  # Atlas V 411
    "Q22978": "atlas",  # Atlas I
    "Q129554072": "atlas",  # Atlas SLV-3D Centaur-D1AR
    "Q16351997": "atlas",  # Atlas V 531
    "Q99672315": "atlas",  # Atlas LV-3 Agena-D
    "Q7391028": "atlas",  # SM-65E Atlas
    "Q862610": "atlas",  # Atlas G
    "Q109659498": "atlas",  # Atlas Centaur-D
    "Q116027213": "atlas",  # Atlas IIA
    "Q127204964": "atlas",  # Atlas IIIB
    "Q16351989": "atlas",  # Atlas V 431
    "Q97684935": "atlas",  # Atlas V N22
    "Q113633647": "atlas",  # Atlas V 511
    "Q127204961": "atlas",  # Atlas IIIA
    "Q20803912": "atlas",  # Atlas V 521
    "Q9161676": "atlas",  # Atlas-Agena A
    "Q1129316": "atlas",  # SM-65B Atlas
    "Q123499372": "atlas",  # Atlas SLV-3D Centaur-D1A
    "Q4816837": "atlas",  # Atlas SLV-3
    "Q99672564": "atlas",  # Atlas LV-3 Agena-B
    "Q99672608": "atlas",  # Atlas SLV-3B Agena-D
    "Q99672663": "atlas",  # Atlas SLV-3 Agena-B
    "Q99672687": "atlas",  # Atlas SLV-3A Agena-D
    "Q99672841": "atlas",  # Atlas-F Agena-D
    "Q49538": "delta",  # Delta II
    "Q49516": "delta",  # Delta 2000
    "Q49520": "delta",  # Delta 3000
    "Q767119": "delta",  # Thor-Delta
    "Q20574406": "delta",  # Delta IV Medium+(4,2)
    "Q249492": "delta",  # Delta IV Heavy
    "Q49533": "delta",  # Delta E
    "Q49530": "delta",  # Delta C
    "Q49553": "delta",  # Delta M
    "Q49514": "delta",  # Delta 1000
    "Q49528": "delta",  # Delta B
    "Q49555": "delta",  # Delta N
    "Q16354315": "delta",  # Delta IV Medium+(5,4)
    "Q49510": "delta",  # Delta 0100
    "Q16354312": "delta",  # Delta IV Medium+(5,2)
    "Q16354305": "delta",  # Delta IV Medium
    "Q49523": "delta",  # Delta 4000
    "Q49527": "delta",  # Delta A
    "Q49532": "delta",  # Delta D
    "Q49537": "delta",  # Delta G
    "Q49525": "delta",  # Delta 5000
    "Q49541": "delta",  # Delta III
    "Q49545": "delta",  # Delta J
    "Q49551": "delta",  # Delta L
    "Q28450215": "falcon",  # Falcon 9 Block 5
    "Q22808999": "falcon",  # Falcon 9 Full Thrust
    "Q1093627": "falcon",  # Falcon Heavy
    "Q15215794": "falcon",  # Falcon 9 v1.1
    "Q16837944": "falcon",  # Falcon 9 v1.0
    "Q58924629": "falcon",  # Falcon 9 Block 4
    "Q648606": "falcon",  # Falcon 1
    "Q65560832": "gslv",  # Geosynchronous Satellite Launch Vehicle Mark II
    "Q65560833": "gslv",  # Geosynchronous Satellite Launch Vehicle Mark I
    "Q60599": "h-2",  # H-IIA
    "Q60580": "h-2",  # H-IIB
    "Q1192304": "juno-ii",  # Juno I
    "Q5957520": "kaituozhe",  # Kaituozhe-2
    "Q4235067": "kosmos-2i",  # Kosmos-2I
    "Q11744067": "kosmos-2i",  # Kosmos 63S1
    "Q6119291": "kosmos-2i",  # Kosmos-1
    "Q5952587": "kosmos-3m",  # Kosmos-3
    "Q111212242": "lijian",  # Lijian-1
    "Q54164": "long-march",  # Long March 3B
    "Q54186": "long-march",  # Long March 4B
    "Q53702": "long-march",  # Long March 2C
    "Q53704": "long-march",  # Long March 2D
    "Q54190": "long-march",  # Long March 4C
    "Q53710": "long-march",  # Long March 2F
    "Q1090965": "long-march",  # Long March 6
    "Q54162": "long-march",  # Long March 3A
    "Q54167": "long-march",  # Long March 3C
    "Q53734": "long-march",  # Long March 3
    "Q3544124": "long-march",  # Long March 7
    "Q53708": "long-march",  # Long March 2E
    "Q6672962": "long-march",  # Long March 11
    "Q999788": "long-march",  # Feng Bao 1
    "Q787531": "long-march",  # Long March 5
    "Q28418605": "long-march",  # Long March 5 (basic configuration)
    "Q93359357": "long-march",  # Long March 5B
    "Q53698": "long-march",  # Long March 1
    "Q22099169": "long-march",  # Long March 8
    "Q31888873": "long-march",  # Long March 2F/G
    "Q3271279": "minotaur",  # Minotaur I
    "Q907608": "minotaur",  # Minotaur IV
    "Q3270785": "minotaur",  # Minotaur V
    "Q2155073": "molniya-rocket",  # Molniya-M
    "Q11230713": "mu-rocket",  # M-3S2
    "Q1332896": "mu-rocket",  # M-V
    "Q11230714": "mu-rocket",  # M-3S
    "Q11230709": "mu-rocket",  # M-3C
    "Q11230712": "mu-rocket",  # M-3H
    "Q11230715": "mu-rocket",  # M-4S
    "Q1756428": "proton-rocket",  # Proton-K
    "Q10853123": "proton-rocket",  # UR-500
    "Q65559631": "pslv",  # Polar Satellite Launch Vehicle-XL
    "Q65559628": "pslv",  # Polar Satellite Launch Vehicle-CA
    "Q65559632": "pslv",  # Polar Satellite Launch Vehicle-G
    "Q65559629": "pslv",  # Polar Satellite Launch Vehicle-QL
    "Q65559630": "pslv",  # Polar Satellite Launch Vehicle-DL
    "Q21652063": "safir",  # Sapphire-2
    "Q54363": "saturn",  # Saturn V
    "Q719315": "saturn",  # Saturn IB
    "Q521076": "saturn",  # Saturn I
    "Q10368958": "scout",  # Scout B
    "Q10368961": "scout",  # Scout D-1
    "Q9334624": "scout",  # Scout X-4
    "Q10368959": "scout",  # Scout A
    "Q10368964": "scout",  # Scout G-1
    "Q10368966": "scout",  # Scout X-3
    "Q604839": "scout",  # Scout X-1
    "Q10368962": "scout",  # Scout F
    "Q10368963": "scout",  # Scout E-1
    "Q31282992": "scout",  # Scout B1
    "Q7438333": "scout",  # Scout X-2M
    "Q117330182": "shavit",  # Shavit
    "Q9335951": "shavit",  # Shavit-1
    "Q1460216": "shtil",  # Shtil'
    "Q109943270": "sls",  # Space Launch System Block 1
    "Q65515921": "slv-3",  # Satellite Launch Vehicle 3
    "Q660345": "soyuz-rocket",  # Soyuz-U
    "Q13220030": "soyuz-rocket",  # Soyuz-2.1a
    "Q12780081": "soyuz-rocket",  # Soyuz-2.1b
    "Q2415633": "soyuz-rocket",  # Soyuz-FG
    "Q5957052": "soyuz-rocket",  # Soyuz-U2
    "Q23902660": "soyuz-rocket",  # Soyuz
    "Q3071792": "soyuz-rocket",  # Soyuz-2.1v
    "Q7572046": "soyuz-rocket",  # Soyuz-M
    "Q2107170": "soyuz-rocket",  # Soyuz-L
    "Q1705346": "soyuz-rocket",  # Soyuz/Vostok
    "Q9358558": "thor-rocket",  # Thor-Agena D
    "Q9358556": "thor-rocket",  # Thor-Agena B
    "Q1093848": "thor-rocket",  # Thor-Ablestar
    "Q2918347": "thor-rocket",  # Thor-Burner
    "Q9358555": "thor-rocket",  # Thor-Agena A
    "Q582838": "thor-rocket",  # Thorad-Agena D
    "Q7796057": "thor-rocket",  # Thor DSV-2U
    "Q9358550": "thor-rocket",  # Thor Able I
    "Q9358551": "thor-rocket",  # Thor Able II
    "Q9358552": "thor-rocket",  # Thor Able III
    "Q9358553": "thor-rocket",  # Thor Able IV
    "Q1187865": "titan-rocket",  # Titan IIIC
    "Q74369": "titan-rocket",  # Titan IV
    "Q1187238": "titan-rocket",  # Titan II GLV
    "Q1187262": "titan-rocket",  # Titan IIIE
    "Q5918827": "titan-rocket",  # Titan 23G
    "Q1187235": "titan-rocket",  # Titan IIID
    "Q5152536": "titan-rocket",  # Commercial Titan III
    "Q1187342": "titan-rocket",  # Titan 34D
    "Q1187387": "titan-rocket",  # Titan IIIB
    "Q1187393": "titan-rocket",  # Titan IIIA
    "Q4390622": "unha",  # Unha-3
    "Q56010145": "vega",  # Vega C
    "Q1656530": "vostok-rocket",  # Vostok-2M
    "Q582517": "vostok-rocket",  # Vostok-2
    "Q3303767": "vostok-rocket",  # Vostok-K
    "Q1442051": "vostok-rocket",  # Vostok-L
    "Q6501191": "zenit",  # Zenit-2
    "Q8727455": "zenit",  # Zenit-3SL
    "Q1756479": "zenit",  # Zenit-3SLB
    "Q1756732": "zenit",  # Zenit-3F
    "Q1756577": "zenit",  # Zenit-2M
}
# Constellation slug → launch vehicle, for relabeling ROCKET constellation
# membership onto the lv- group at export time.
LAUNCH_VEHICLE_BY_CONSTELLATION: dict[str, LaunchVehicleSpec] = {
    lv.constellation_slug: lv
    for lv in LAUNCH_VEHICLES
    if lv.constellation_slug is not None
}

# (lowercased prefix, slug) sorted longest-first so the first startswith hit is
# the most specific.
_PREFIX_INDEX: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((p.lower(), lv.slug) for lv in LAUNCH_VEHICLES for p in lv.lv_prefixes),
        key=lambda x: len(x[0]),
        reverse=True,
    )
)


def match_launch_vehicle_slug(lv_type: str | None) -> str | None:
    """Map a launchlog ``lv_type`` to a launch-vehicle slug (longest prefix wins)."""
    if not lv_type:
        return None
    low = lv_type.lower()
    for prefix, slug in _PREFIX_INDEX:
        if low.startswith(prefix):
            return slug
    return None


def launch_vehicle_slug_for_qid(qid: str) -> str | None:
    """Map a P375 QID (family or specific configuration) to its family slug."""
    lv = LAUNCH_VEHICLE_BY_QID.get(qid)
    if lv is not None:
        return lv.slug
    return LAUNCH_VEHICLE_VARIANT_QID.get(qid)


assert len(LAUNCH_VEHICLE_BY_SLUG) == len(LAUNCH_VEHICLES), "Duplicate lv slug"
for _vq, _vslug in LAUNCH_VEHICLE_VARIANT_QID.items():
    assert _vslug in LAUNCH_VEHICLE_BY_SLUG, f"variant {_vq}: unknown slug {_vslug}"
    assert _vq not in LAUNCH_VEHICLE_BY_QID, f"variant {_vq} is also a family QID"
for _lv in LAUNCH_VEHICLES:
    if _lv.constellation_slug is not None:
        _c = CONSTELLATION_BY_SLUG.get(_lv.constellation_slug)
        assert _c is not None, (
            f"{_lv.slug}: unknown constellation {_lv.constellation_slug}"
        )
        assert SatelliteCategory.ROCKET in _c.category, (
            f"{_lv.slug}: constellation {_lv.constellation_slug} is not ROCKET"
        )
