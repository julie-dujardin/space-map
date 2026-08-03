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


@dataclass(frozen=True)
class LaunchVehicleVariantSpec:
    """A configuration of a family, more specific than the family's own QID.

    ``gcat_names`` are empty when the variant is only ever a spacecraft's P375
    value, never matched to a launchlog ``lv_type``.
    """

    qid: str
    family_slug: str
    gcat_names: tuple[str, ...] = ()


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
    # Slug shadows the capsule constellation; the lv-/const- page namespaces
    # keep the two apart, and only the rocket carries a Voskhod lv_type.
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
# Generated by scripts/generate_launch_vehicle_variants.py, hand-reviewed.
LAUNCH_VEHICLE_VARIANTS: tuple[LaunchVehicleVariantSpec, ...] = (
    LaunchVehicleVariantSpec("Q112063526", "angara", ("Angara-1.2",)),
    LaunchVehicleVariantSpec(
        "Q18694511", "angara", ("Angara A5", "Angara A5/Orion", "Angara A5/Persei")
    ),
    LaunchVehicleVariantSpec("Q10417856", "ariane", ("Ariane 5ES", "Ariane 5ES/ATV")),
    LaunchVehicleVariantSpec("Q124077105", "ariane"),
    LaunchVehicleVariantSpec("Q135885158", "ariane"),
    LaunchVehicleVariantSpec("Q135885159", "ariane"),
    LaunchVehicleVariantSpec("Q15720682", "ariane", ("Ariane 62", "Ariane 64")),
    LaunchVehicleVariantSpec("Q16351692", "ariane", ("Ariane 5ECA", "Ariane 5ECA+")),
    LaunchVehicleVariantSpec("Q16351696", "ariane", ("Ariane 5G", "Ariane 5G+")),
    LaunchVehicleVariantSpec("Q16351700", "ariane"),
    LaunchVehicleVariantSpec("Q16351704", "ariane", ("Ariane 5GS",)),
    LaunchVehicleVariantSpec("Q16530012", "ariane", ("Ariane 42L",)),
    LaunchVehicleVariantSpec("Q16530018", "ariane", ("Ariane 44P",)),
    LaunchVehicleVariantSpec("Q18375", "ariane", ("Ariane 1",)),
    LaunchVehicleVariantSpec("Q18379", "ariane", ("Ariane 2",)),
    LaunchVehicleVariantSpec("Q18381", "ariane", ("Ariane 3",)),
    LaunchVehicleVariantSpec("Q18532", "ariane"),
    LaunchVehicleVariantSpec("Q9159559", "ariane", ("Ariane 42P",)),
    LaunchVehicleVariantSpec("Q9159561", "ariane", ("Ariane 40",)),
    LaunchVehicleVariantSpec("Q9159563", "ariane", ("Ariane 44L",)),
    LaunchVehicleVariantSpec("Q9159564", "ariane", ("Ariane 44LP",)),
    LaunchVehicleVariantSpec("Q22786", "athena", ("Athena-1", "LLV-1", "LMLV-1")),
    LaunchVehicleVariantSpec("Q22791", "athena", ("Athena-2",)),
    LaunchVehicleVariantSpec("Q109659498", "atlas", ("Atlas Centaur D",)),
    LaunchVehicleVariantSpec("Q1129316", "atlas", ("Atlas B",)),
    LaunchVehicleVariantSpec("Q113633647", "atlas", ("Atlas V 511",)),
    LaunchVehicleVariantSpec("Q115629811", "atlas", ("Atlas SLV-3C Centaur",)),
    LaunchVehicleVariantSpec("Q116027213", "atlas", ("Atlas IIA",)),
    LaunchVehicleVariantSpec("Q116027214", "atlas", ("Atlas IIAS",)),
    LaunchVehicleVariantSpec("Q123499372", "atlas", ("Atlas SLV-3D Centaur",)),
    LaunchVehicleVariantSpec("Q12403688", "atlas"),
    LaunchVehicleVariantSpec("Q127204961", "atlas", ("Atlas 3A",)),
    LaunchVehicleVariantSpec("Q127204964", "atlas", ("Atlas 3B",)),
    LaunchVehicleVariantSpec("Q129554072", "atlas"),
    LaunchVehicleVariantSpec("Q16351980", "atlas", ("Atlas V 411",)),
    LaunchVehicleVariantSpec("Q16351985", "atlas", ("Atlas V 421",)),
    LaunchVehicleVariantSpec("Q16351989", "atlas", ("Atlas V 431",)),
    LaunchVehicleVariantSpec("Q16351993", "atlas", ("Atlas V 501",)),
    LaunchVehicleVariantSpec("Q16351997", "atlas", ("Atlas V 531",)),
    LaunchVehicleVariantSpec("Q16352003", "atlas", ("Atlas V 541",)),
    LaunchVehicleVariantSpec("Q16352007", "atlas", ("Atlas V 551",)),
    LaunchVehicleVariantSpec("Q20803912", "atlas", ("Atlas V 521",)),
    LaunchVehicleVariantSpec("Q20803939", "atlas", ("Atlas V 401",)),
    LaunchVehicleVariantSpec("Q22812", "atlas", ("Atlas Able",)),
    LaunchVehicleVariantSpec("Q22978", "atlas", ("Atlas I",)),
    LaunchVehicleVariantSpec("Q23600", "atlas", ("Atlas II",)),
    LaunchVehicleVariantSpec("Q2895380", "atlas", ("Atlas D",)),
    LaunchVehicleVariantSpec("Q4816837", "atlas", ("Atlas SLV-3",)),
    LaunchVehicleVariantSpec(
        "Q7391028",
        "atlas",
        ("Atlas E", "Atlas E/MSD", "Atlas E/OIS", "Atlas E/SGS-2", "Atlas E/SVS"),
    ),
    LaunchVehicleVariantSpec(
        "Q7391030",
        "atlas",
        ("Atlas F", "Atlas F/MSD", "Atlas F/OIS", "Atlas F/PTS", "Atlas F/SVS"),
    ),
    LaunchVehicleVariantSpec("Q862321", "atlas", ("Atlas Centaur",)),
    LaunchVehicleVariantSpec("Q862610", "atlas"),
    LaunchVehicleVariantSpec("Q9161676", "atlas", ("Atlas Agena A",)),
    LaunchVehicleVariantSpec("Q9161678", "atlas", ("Atlas Agena B",)),
    LaunchVehicleVariantSpec(
        "Q9161679", "atlas", ("Atlas Agena D", "Atlas SLV-3 Agena D")
    ),
    LaunchVehicleVariantSpec("Q9161682", "atlas"),
    LaunchVehicleVariantSpec("Q97684935", "atlas", ("Atlas V N22",)),
    LaunchVehicleVariantSpec("Q99672315", "atlas"),
    LaunchVehicleVariantSpec("Q99672564", "atlas"),
    LaunchVehicleVariantSpec("Q99672608", "atlas"),
    LaunchVehicleVariantSpec("Q99672663", "atlas", ("Atlas SLV-3 Agena B",)),
    LaunchVehicleVariantSpec("Q99672687", "atlas", ("Atlas SLV-3A Agena D",)),
    LaunchVehicleVariantSpec("Q99672841", "atlas", ("Atlas F/Agena D",)),
    LaunchVehicleVariantSpec("Q16354305", "delta", ("Delta 4M",)),
    LaunchVehicleVariantSpec("Q16354312", "delta", ("Delta 4M+(5,2)",)),
    LaunchVehicleVariantSpec("Q16354315", "delta", ("Delta 4M+(5,4)",)),
    LaunchVehicleVariantSpec("Q20574406", "delta", ("Delta 4M+(4,2)",)),
    LaunchVehicleVariantSpec("Q249492", "delta", ("Delta 4H", "Delta 4H/Star 48BV")),
    LaunchVehicleVariantSpec("Q49510", "delta", ("Delta 0300", "Delta 0900")),
    LaunchVehicleVariantSpec("Q49514", "delta"),
    LaunchVehicleVariantSpec("Q49516", "delta"),
    LaunchVehicleVariantSpec("Q49520", "delta"),
    LaunchVehicleVariantSpec("Q49523", "delta"),
    LaunchVehicleVariantSpec("Q49525", "delta"),
    LaunchVehicleVariantSpec("Q49527", "delta", ("Thor Delta A",)),
    LaunchVehicleVariantSpec("Q49528", "delta", ("Thor Delta B",)),
    LaunchVehicleVariantSpec("Q49530", "delta", ("Thor Delta C",)),
    LaunchVehicleVariantSpec("Q49532", "delta", ("Thor Delta D",)),
    LaunchVehicleVariantSpec("Q49533", "delta", ("Thor Delta E", "Thor Delta E1")),
    LaunchVehicleVariantSpec("Q49537", "delta", ("Thor Delta G",)),
    LaunchVehicleVariantSpec("Q49538", "delta"),
    LaunchVehicleVariantSpec("Q49541", "delta", ("Delta 8930",)),
    LaunchVehicleVariantSpec("Q49545", "delta", ("Thor Delta J",)),
    LaunchVehicleVariantSpec("Q49551", "delta", ("Thor Delta L",)),
    LaunchVehicleVariantSpec("Q49553", "delta", ("Thor Delta M",)),
    LaunchVehicleVariantSpec("Q49555", "delta", ("Thor Delta N",)),
    LaunchVehicleVariantSpec("Q767119", "delta", ("Thor Delta",)),
    LaunchVehicleVariantSpec("Q49570", "diamant", ("Diamant B",)),
    LaunchVehicleVariantSpec("Q50241648", "europa", ("Europa II",)),
    LaunchVehicleVariantSpec("Q50241703", "europa", ("Europa I",)),
    LaunchVehicleVariantSpec("Q1093627", "falcon", ("Falcon Heavy",)),
    LaunchVehicleVariantSpec("Q15215794", "falcon"),
    LaunchVehicleVariantSpec("Q16837944", "falcon"),
    LaunchVehicleVariantSpec("Q22808999", "falcon"),
    LaunchVehicleVariantSpec("Q28450215", "falcon"),
    LaunchVehicleVariantSpec("Q58924629", "falcon"),
    LaunchVehicleVariantSpec("Q648606", "falcon", ("Falcon 1",)),
    LaunchVehicleVariantSpec("Q65560832", "gslv", ("GSLV Mk II",)),
    LaunchVehicleVariantSpec("Q65560833", "gslv", ("GSLV Mk I",)),
    LaunchVehicleVariantSpec("Q60580", "h-2", ("H-IIB",)),
    LaunchVehicleVariantSpec("Q60599", "h-2"),
    LaunchVehicleVariantSpec("Q1192304", "juno-ii", ("Jupiter C",)),
    LaunchVehicleVariantSpec("Q124727307", "kairos", ("Kairos",)),
    LaunchVehicleVariantSpec("Q5957520", "kaituozhe"),
    LaunchVehicleVariantSpec("Q11744067", "kosmos-2i", ("Kosmos 63S1",)),
    LaunchVehicleVariantSpec("Q4235067", "kosmos-2i", ("Kosmos 11K63",)),
    LaunchVehicleVariantSpec("Q6119291", "kosmos-2i"),
    LaunchVehicleVariantSpec("Q5952587", "kosmos-3m", ("Kosmos 11K65",)),
    LaunchVehicleVariantSpec("Q22100111", "kuaizhou", ("Kuaizhou-11",)),
    LaunchVehicleVariantSpec("Q28417933", "kuaizhou", ("Kuaizhou-1A",)),
    LaunchVehicleVariantSpec("Q111212242", "lijian", ("Lijian-1",)),
    LaunchVehicleVariantSpec("Q124801063", "lijian", ("Lijian-2",)),
    LaunchVehicleVariantSpec("Q1090965", "long-march", ("Chang Zheng 6",)),
    LaunchVehicleVariantSpec("Q124675532", "long-march", ("Chang Zheng 12",)),
    LaunchVehicleVariantSpec("Q137163283", "long-march", ("Chang Zheng 12A",)),
    LaunchVehicleVariantSpec("Q137798550", "long-march", ("Chang Zheng 12B",)),
    LaunchVehicleVariantSpec("Q174706", "long-march", ("Chang Zheng 2",)),
    LaunchVehicleVariantSpec("Q22099169", "long-march", ("Chang Zheng 8",)),
    LaunchVehicleVariantSpec("Q28418605", "long-march"),
    LaunchVehicleVariantSpec("Q31888873", "long-march"),
    LaunchVehicleVariantSpec(
        "Q3544124", "long-march", ("Chang Zheng 7", "Chang Zheng 7/YZ-1A")
    ),
    LaunchVehicleVariantSpec("Q53698", "long-march", ("Chang Zheng 1",)),
    LaunchVehicleVariantSpec(
        "Q53702", "long-march", ("Chang Zheng 2C", "Chang Zheng 2C/YZ-1S")
    ),
    LaunchVehicleVariantSpec(
        "Q53704", "long-march", ("Chang Zheng 2D", "Chang Zheng 2D/YZ-3")
    ),
    LaunchVehicleVariantSpec("Q53708", "long-march", ("Chang Zheng 2E",)),
    LaunchVehicleVariantSpec("Q53710", "long-march", ("Chang Zheng 2F",)),
    LaunchVehicleVariantSpec("Q53734", "long-march", ("Chang Zheng 3",)),
    LaunchVehicleVariantSpec("Q54162", "long-march", ("Chang Zheng 3A",)),
    LaunchVehicleVariantSpec(
        "Q54164", "long-march", ("Chang Zheng 3B", "Chang Zheng 3B/YZ-1")
    ),
    LaunchVehicleVariantSpec(
        "Q54167", "long-march", ("Chang Zheng 3C", "Chang Zheng 3C/YZ-1")
    ),
    LaunchVehicleVariantSpec("Q54186", "long-march", ("Chang Zheng 4B",)),
    LaunchVehicleVariantSpec("Q54190", "long-march", ("Chang Zheng 4C",)),
    LaunchVehicleVariantSpec("Q5979791", "long-march", ("Chang Zheng 4",)),
    LaunchVehicleVariantSpec("Q60988944", "long-march", ("Chang Zheng 6A",)),
    LaunchVehicleVariantSpec("Q6672962", "long-march", ("Chang Zheng 11",)),
    LaunchVehicleVariantSpec(
        "Q787531", "long-march", ("Chang Zheng 5", "Chang Zheng 5/YZ-2")
    ),
    LaunchVehicleVariantSpec("Q85884985", "long-march", ("Chang Zheng 7A",)),
    LaunchVehicleVariantSpec(
        "Q93359357", "long-march", ("Chang Zheng 5B", "Chang Zheng 5B/YZ-2")
    ),
    LaunchVehicleVariantSpec("Q999788", "long-march", ("Feng Bao 1",)),
    LaunchVehicleVariantSpec("Q3270785", "minotaur", ("Minotaur V",)),
    LaunchVehicleVariantSpec("Q3271279", "minotaur", ("Minotaur I",)),
    LaunchVehicleVariantSpec("Q907608", "minotaur", ("Minotaur IV", "Minotaur IV+")),
    LaunchVehicleVariantSpec(
        "Q2155073", "molniya-rocket", ("Molniya 8K78M", "Molniya 8K78M-PVB")
    ),
    LaunchVehicleVariantSpec("Q11230709", "mu-rocket", ("Mu-3C",)),
    LaunchVehicleVariantSpec("Q11230712", "mu-rocket", ("Mu-3H",)),
    LaunchVehicleVariantSpec("Q11230713", "mu-rocket", ("Mu-3S-II",)),
    LaunchVehicleVariantSpec("Q11230714", "mu-rocket", ("Mu-3S",)),
    LaunchVehicleVariantSpec("Q11230715", "mu-rocket", ("Mu-4S",)),
    LaunchVehicleVariantSpec("Q1332896", "mu-rocket", ("M-V",)),
    LaunchVehicleVariantSpec("Q10853123", "proton-rocket"),
    LaunchVehicleVariantSpec("Q124098035", "proton-rocket", ("Proton-K/Briz-M",)),
    LaunchVehicleVariantSpec("Q137671265", "proton-rocket", ("UR-500",)),
    LaunchVehicleVariantSpec("Q16349696", "proton-rocket", ("Proton-K/DM",)),
    LaunchVehicleVariantSpec("Q16349701", "proton-rocket", ("Proton-K/DM-2",)),
    LaunchVehicleVariantSpec("Q16349706", "proton-rocket", ("Proton-K/DM-2M",)),
    LaunchVehicleVariantSpec(
        "Q1756428",
        "proton-rocket",
        ("Proton-K", "Proton-K/17S40", "Proton-K/D-1", "Proton-K/D-2"),
    ),
    LaunchVehicleVariantSpec(
        "Q20578252", "proton-rocket", ("Proton-K/D", "UR-500K/Blok D")
    ),
    LaunchVehicleVariantSpec("Q65559628", "pslv"),
    LaunchVehicleVariantSpec("Q65559629", "pslv", ("PSLV-QL",)),
    LaunchVehicleVariantSpec("Q65559630", "pslv", ("PSLV-DL",)),
    LaunchVehicleVariantSpec("Q65559631", "pslv", ("PSLV-XL",)),
    LaunchVehicleVariantSpec("Q65559632", "pslv"),
    LaunchVehicleVariantSpec("Q71203593", "rs1", ("RS1",)),
    LaunchVehicleVariantSpec("Q21652063", "safir"),
    LaunchVehicleVariantSpec("Q521076", "saturn", ("Saturn I",)),
    LaunchVehicleVariantSpec("Q54363", "saturn", ("Saturn V",)),
    LaunchVehicleVariantSpec("Q719315", "saturn", ("Saturn IB", "Uprated Saturn I")),
    LaunchVehicleVariantSpec("Q10368958", "scout", ("Scout B",)),
    LaunchVehicleVariantSpec("Q10368959", "scout", ("Scout A",)),
    LaunchVehicleVariantSpec("Q10368961", "scout", ("Scout D-1",)),
    LaunchVehicleVariantSpec("Q10368962", "scout"),
    LaunchVehicleVariantSpec("Q10368963", "scout", ("Scout E-1",)),
    LaunchVehicleVariantSpec("Q10368964", "scout", ("Scout G-1",)),
    LaunchVehicleVariantSpec("Q10368966", "scout", ("Scout X-3",)),
    LaunchVehicleVariantSpec("Q31282992", "scout", ("Scout B-1",)),
    LaunchVehicleVariantSpec("Q604839", "scout", ("Scout X-1",)),
    LaunchVehicleVariantSpec("Q606040", "scout", ("Blue Scout II",)),
    LaunchVehicleVariantSpec("Q606072", "scout", ("Scout X-2",)),
    LaunchVehicleVariantSpec("Q7438333", "scout", ("Scout X-2M",)),
    LaunchVehicleVariantSpec("Q9334624", "scout", ("Scout X-4",)),
    LaunchVehicleVariantSpec("Q117330182", "shavit"),
    LaunchVehicleVariantSpec("Q9335951", "shavit", ("Shavit 1",)),
    LaunchVehicleVariantSpec("Q1460216", "shtil", ("Shtil'-1",)),
    LaunchVehicleVariantSpec("Q109943270", "sls", ("SLS Block 1",)),
    LaunchVehicleVariantSpec("Q65515921", "slv-3"),
    LaunchVehicleVariantSpec("Q12780081", "soyuz-rocket", ("Soyuz-2-1B",)),
    LaunchVehicleVariantSpec("Q13220030", "soyuz-rocket", ("Soyuz-2-1A", "Soyuz-ST-A")),
    LaunchVehicleVariantSpec("Q1705346", "soyuz-rocket"),
    LaunchVehicleVariantSpec("Q2107170", "soyuz-rocket"),
    LaunchVehicleVariantSpec("Q23902660", "soyuz-rocket", ("Soyuz 11A511",)),
    LaunchVehicleVariantSpec("Q2415633", "soyuz-rocket", ("Soyuz-FG",)),
    LaunchVehicleVariantSpec("Q3071792", "soyuz-rocket", ("Soyuz-2-1V",)),
    LaunchVehicleVariantSpec("Q4430522", "soyuz-rocket", ("Soyuz-ST-B",)),
    LaunchVehicleVariantSpec("Q5957052", "soyuz-rocket", ("Soyuz-U2",)),
    LaunchVehicleVariantSpec("Q660345", "soyuz-rocket", ("Soyuz-U",)),
    LaunchVehicleVariantSpec("Q7572046", "soyuz-rocket", ("Soyuz 11A511M",)),
    LaunchVehicleVariantSpec("Q65245255", "spectrum", ("Spectrum",)),
    LaunchVehicleVariantSpec("Q9340746", "sputnik-rocket", ("Sputnik 8A91",)),
    LaunchVehicleVariantSpec("Q9355894", "taurus-minotaur-c", ("Taurus 3110",)),
    LaunchVehicleVariantSpec("Q1093848", "thor-rocket", ("Thor Ablestar",)),
    LaunchVehicleVariantSpec("Q2918347", "thor-rocket"),
    LaunchVehicleVariantSpec("Q582838", "thor-rocket", ("Thorad SLV-2G Agena D",)),
    LaunchVehicleVariantSpec("Q7796057", "thor-rocket", ("Thor DSV-2U",)),
    LaunchVehicleVariantSpec("Q9358550", "thor-rocket", ("Thor Able I",)),
    LaunchVehicleVariantSpec("Q9358551", "thor-rocket", ("Thor Able II",)),
    LaunchVehicleVariantSpec("Q9358552", "thor-rocket", ("Thor Able III",)),
    LaunchVehicleVariantSpec("Q9358553", "thor-rocket", ("Thor Able IV",)),
    LaunchVehicleVariantSpec("Q9358555", "thor-rocket", ("Thor Agena A",)),
    LaunchVehicleVariantSpec(
        "Q9358556",
        "thor-rocket",
        ("Thor Agena B", "Thor SLV-2 Agena B", "Thor SLV-2A Agena B"),
    ),
    LaunchVehicleVariantSpec(
        "Q9358558",
        "thor-rocket",
        ("Thor Agena D", "Thor SLV-2 Agena D", "Thor SLV-2A Agena D"),
    ),
    LaunchVehicleVariantSpec("Q1187235", "titan-rocket", ("Titan IIID",)),
    LaunchVehicleVariantSpec("Q1187238", "titan-rocket", ("Titan II GLV",)),
    LaunchVehicleVariantSpec("Q1187262", "titan-rocket", ("Titan IIIE",)),
    LaunchVehicleVariantSpec(
        "Q1187342",
        "titan-rocket",
        ("Titan 34D", "Titan 34D/IUS", "Titan 34D/Transtage"),
    ),
    LaunchVehicleVariantSpec(
        "Q1187387",
        "titan-rocket",
        ("Titan 23B", "Titan 24B", "Titan 33B", "Titan 34B", "Titan IIIB"),
    ),
    LaunchVehicleVariantSpec("Q1187393", "titan-rocket", ("Titan IIIA",)),
    LaunchVehicleVariantSpec("Q1187865", "titan-rocket", ("Titan IIIC",)),
    LaunchVehicleVariantSpec("Q5152536", "titan-rocket"),
    LaunchVehicleVariantSpec("Q5918827", "titan-rocket", ("Titan II SLV",)),
    LaunchVehicleVariantSpec("Q74369", "titan-rocket"),
    LaunchVehicleVariantSpec("Q247985", "unha", ("Paektusan 1",)),
    LaunchVehicleVariantSpec("Q4390622", "unha", ("Kwangmyongsong", "Unha-3")),
    LaunchVehicleVariantSpec("Q8235033", "unha", ("Unha-2",)),
    LaunchVehicleVariantSpec("Q56010145", "vega", ("Vega C",)),
    LaunchVehicleVariantSpec("Q2142103", "volna", ("Volna",)),
    LaunchVehicleVariantSpec("Q1392578", "vostok-rocket", ("Vostok-L 8K72",)),
    LaunchVehicleVariantSpec("Q1442051", "vostok-rocket", ("Vostok 8K72",)),
    LaunchVehicleVariantSpec("Q1656530", "vostok-rocket", ("Vostok 8A92M",)),
    LaunchVehicleVariantSpec("Q3303767", "vostok-rocket"),
    LaunchVehicleVariantSpec(
        "Q582517", "vostok-rocket", ("Vostok 8A92", "Vostok-2A 11A510")
    ),
    LaunchVehicleVariantSpec("Q1756479", "zenit"),
    LaunchVehicleVariantSpec("Q1756577", "zenit", ("Zenit-2SB",)),
    LaunchVehicleVariantSpec("Q1756732", "zenit"),
    LaunchVehicleVariantSpec("Q6501191", "zenit", ("Zenit-2 11K77.05",)),
    LaunchVehicleVariantSpec("Q8727455", "zenit"),
)

# qid → family slug, for pointing a P375 (launch_vehicle) crossref at its lv- page.
LAUNCH_VEHICLE_VARIANT_QID: dict[str, str] = {
    v.qid: v.family_slug for v in LAUNCH_VEHICLE_VARIANTS
}
# GCAT lv_type → variant qid, for the per-variant breakdown sitelink.
GCAT_LV_TYPE_TO_QID: dict[str, str] = {
    name: v.qid for v in LAUNCH_VEHICLE_VARIANTS for name in v.gcat_names
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
assert len({v.qid for v in LAUNCH_VEHICLE_VARIANTS}) == len(LAUNCH_VEHICLE_VARIANTS), (
    "Duplicate variant QID"
)
assert len(GCAT_LV_TYPE_TO_QID) == sum(
    len(v.gcat_names) for v in LAUNCH_VEHICLE_VARIANTS
), "A GCAT lv_type maps to two variant QIDs"
for _v in LAUNCH_VEHICLE_VARIANTS:
    assert _v.family_slug in LAUNCH_VEHICLE_BY_SLUG, (
        f"variant {_v.qid}: unknown slug {_v.family_slug}"
    )
    assert _v.qid not in LAUNCH_VEHICLE_BY_QID, f"variant {_v.qid} is also a family QID"
for _lv in LAUNCH_VEHICLES:
    if _lv.constellation_slug is not None:
        _c = CONSTELLATION_BY_SLUG.get(_lv.constellation_slug)
        assert _c is not None, (
            f"{_lv.slug}: unknown constellation {_lv.constellation_slug}"
        )
        assert SatelliteCategory.ROCKET in _c.category, (
            f"{_lv.slug}: constellation {_lv.constellation_slug} is not ROCKET"
        )
