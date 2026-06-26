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
# Resolved QID → vehicle, for pointing a Wikidata launch_vehicle (P375) crossref
# at its lv- page. Keyed on the family QID; variant-specific QIDs (e.g. a single
# Atlas V configuration) fall through to a plain Wikipedia ref.
LAUNCH_VEHICLE_BY_QID: dict[str, LaunchVehicleSpec] = {
    qid: lv for lv in LAUNCH_VEHICLES if (qid := lv.qid) is not None
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


assert len(LAUNCH_VEHICLE_BY_SLUG) == len(LAUNCH_VEHICLES), "Duplicate lv slug"
for _lv in LAUNCH_VEHICLES:
    if _lv.constellation_slug is not None:
        _c = CONSTELLATION_BY_SLUG.get(_lv.constellation_slug)
        assert _c is not None, (
            f"{_lv.slug}: unknown constellation {_lv.constellation_slug}"
        )
        assert SatelliteCategory.ROCKET in _c.category, (
            f"{_lv.slug}: constellation {_lv.constellation_slug} is not ROCKET"
        )
