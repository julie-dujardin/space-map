"""CelesTrak SATCAT launch-site catalog.

See: https://celestrak.org/satcat/launchsites.php
"""

from dataclasses import dataclass

# Prefix so launch-site group slugs don't collide with constellation/operator
# slugs in the group registry: ``f"{LAUNCH_SITE_SLUG_PREFIX}{site.slug}"``.
LAUNCH_SITE_SLUG_PREFIX = "site-"


@dataclass(frozen=True)
class LaunchSiteSpec:
    code: str  # SATCAT short code (primary key)
    slug: str  # URL slug used for the per-site group page
    name: str  # Human-readable description
    wikidata_qid: str | None = None
    # GCAT unified site codes (sites.tsv UCode) this site covers — position and
    # pads come from here. Curated: SATCAT names ranges ("Eastern Test Range"),
    # GCAT names places within them, so one SATCAT code can span several.
    # Empty for mobile platforms and air-launch release boxes (no fixed point).
    gcat_sites: tuple[str, ...] = ()


LAUNCH_SITES: tuple[LaunchSiteSpec, ...] = (
    LaunchSiteSpec(
        "AFETR",
        "cape-canaveral",
        "Air Force Eastern Test Range, Florida, USA",
        "Q334465",
        # The range spans the Air Force station, Kennedy next door, and the
        # commercial Space Florida pads on the same shoreline.
        gcat_sites=("CC", "KSC", "CCA"),
    ),
    LaunchSiteSpec(
        "AFWTR",
        "vandenberg",
        "Air Force Western Test Range, California, USA",
        "Q461492",
        gcat_sites=("V", "PA"),
    ),
    LaunchSiteSpec(
        "ANDSP",
        "andoya",
        "Andøya Spaceport, Nordland, Norway",
        "Q528446",
        gcat_sites=("AND",),
    ),
    LaunchSiteSpec(
        "ALCLC",
        "alcantara",
        "Alâcantara Launch Center, Maranhão, Brazil",
        "Q922797",
        gcat_sites=("ALCA",),
    ),
    LaunchSiteSpec(
        "BOS",
        "bowen",
        "Bowen Orbital Spaceport, Queensland, Australia",
        "Q131056918",
        gcat_sites=("BOWEN",),
    ),
    LaunchSiteSpec("CAS", "canaries-airspace", "Canaries Airspace"),
    LaunchSiteSpec(
        "DLS",
        "dombarovskiy",
        "Dombarovskiy Launch Site, Russia",
        "Q627080",
        gcat_sites=("YAS",),
    ),
    LaunchSiteSpec("ERAS", "eastern-range-airspace", "Eastern Range Airspace"),
    LaunchSiteSpec(
        "FRGUI",
        "kourou",
        "Europe's Spaceport, Kourou, French Guiana",
        "Q308987",
        gcat_sites=("CSG",),
    ),
    LaunchSiteSpec(
        "HGSTR",
        "hammaguir",
        "Hammaguira Space Track Range, Algeria",
        "Q1054217",
        gcat_sites=("HMG",),
    ),
    LaunchSiteSpec(
        "JJSLA",
        "jeju-sea-launch",
        "Jeju Island Sea Launch Area, Republic of Korea",
        "Q41164",
        gcat_sites=("JEJU",),
    ),
    LaunchSiteSpec(
        "JSC",
        "jiuquan",
        "Jiuquan Space Center, PRC",
        "Q692677",
        gcat_sites=("JQ",),
    ),
    LaunchSiteSpec(
        "KODAK",
        "kodiak",
        "Kodiak Launch Complex, Alaska, USA",
        "Q283842",
        gcat_sites=("KLC",),
    ),
    LaunchSiteSpec(
        "KSCUT",
        "uchinoura",
        "Uchinoura Space Center (formerly Kagoshima Space Center)",
        "Q1077124",
        gcat_sites=("KASC",),
    ),
    LaunchSiteSpec(
        "KWAJ",
        "kwajalein",
        "US Army Kwajalein Atoll (USAKA)",
        "Q1794892",
        gcat_sites=("KMR",),
    ),
    LaunchSiteSpec(
        "KYMSC",
        "kapustin-yar",
        "Kapustin Yar Missile and Space Complex, Russia",
        "Q753201",
        gcat_sites=("GTsP-4",),
    ),
    LaunchSiteSpec(
        "NSC",
        "naro",
        "Naro Space Complex, Republic of Korea",
        "Q495281",
        gcat_sites=("NARO",),
    ),
    LaunchSiteSpec(
        "PLMSC",
        "plesetsk",
        "Plesetsk Missile and Space Complex, Russia",
        "Q15778",
        gcat_sites=("GIK-1", "GNIIP"),
    ),
    LaunchSiteSpec(
        "RLLB",
        "mahia",
        "Rocket Lab Launch Base, Mahia Peninsula, New Zealand",
        "Q28180879",
        gcat_sites=("MAHIA",),
    ),
    LaunchSiteSpec(
        "SCSLA",
        "south-china-sea-launch",
        "South China Sea Launch Area, PRC",
        gcat_sites=("YJ",),
    ),
    LaunchSiteSpec(
        "SEAL",
        "sea-launch",
        "Sea Launch Platform (mobile)",
        "Q3177009",
        # Odyssey's equatorial station, the only fixed point a mobile platform
        # has; it launched from there for all but its first flight.
        gcat_sites=("KLA",),
    ),
    LaunchSiteSpec(
        "SEMLS",
        "semnan",
        "Semnan Satellite Launch Site, Iran",
        "Q16047974",
        gcat_sites=("SEM",),
    ),
    LaunchSiteSpec(
        "SMTS",
        "shahrud",
        "Shahrud Missile Test Site, Iran",
        "Q112648507",
        gcat_sites=("SHAHR",),
    ),
    LaunchSiteSpec(
        "SNMLP",
        "san-marco",
        "San Marco Launch Platform, Indian Ocean (Kenya)",
        "Q644399",
        gcat_sites=("SMLC",),
    ),
    LaunchSiteSpec(
        "SPKII",
        "space-port-kii",
        "Space Port Kii, Japan",
        "Q122375877",
        gcat_sites=("KII",),
    ),
    LaunchSiteSpec(
        "SRILR",
        "satish-dhawan",
        "Satish Dhawan Space Centre, India",
        "Q640273",
        gcat_sites=("SHAR",),
    ),
    LaunchSiteSpec(
        "SUBL",
        "submarine-launch",
        "Submarine Launch Platform (mobile)",
        # The Barents box the submarine launches were fired from.
        gcat_sites=("BLA",),
    ),
    # GCAT files Svobodnyy and Vostochny under one code — the cosmodrome was
    # built on the old missile base — so both sites resolve to the same place.
    LaunchSiteSpec(
        "SVOBO",
        "svobodnyy",
        "Svobodnyy Launch Complex, Russia",
        "Q1366384",
        gcat_sites=("VOST",),
    ),
    LaunchSiteSpec(
        "TAISC",
        "taiyuan",
        "Taiyuan Space Center, PRC",
        "Q1194479",
        gcat_sites=("TYSC",),
    ),
    LaunchSiteSpec(
        "TANSC",
        "tanegashima",
        "Tanegashima Space Center, Japan",
        "Q742683",
        gcat_sites=("TNSC",),
    ),
    LaunchSiteSpec(
        "TYMSC",
        "baikonur",
        "Tyuratam Missile and Space Center / Baikonur Cosmodrome, Kazakhstan",
        "Q177477",
        gcat_sites=("GIK-5",),
    ),  # See https://www.cia.gov/readingroom/docs/CIA-RDP78T05439A000200390120-8.pdf
    LaunchSiteSpec("UNK", "unknown-site", "Unknown"),
    LaunchSiteSpec(
        "VOSTO",
        "vostochny",
        "Vostochny Cosmodrome, Russia",
        "Q1166191",
        gcat_sites=("VOST",),
    ),
    LaunchSiteSpec(
        "WLPIS",
        "wallops",
        "Wallops Island, Virginia, USA",
        "Q182348",
        gcat_sites=("WI", "MARS", "NAOTS"),
    ),
    LaunchSiteSpec(
        "WOMRA",
        "woomera",
        "Woomera, Australia",
        "Q17239134",
        gcat_sites=("WOO",),
    ),
    LaunchSiteSpec("WRAS", "western-range-airspace", "Western Range Airspace"),
    LaunchSiteSpec(
        "WSC",
        "wenchang",
        "Wenchang Satellite Launch Site, PRC",
        "Q1246624",
        gcat_sites=("WEN", "HCSLS"),
    ),
    LaunchSiteSpec(
        "XICLF",
        "xichang",
        "Xichang Launch Facility, PRC",
        "Q734306",
        gcat_sites=("XSC",),
    ),
    LaunchSiteSpec(
        "YAVNE",
        "palmachim",
        "Yavne Launch Facility / Palmachim Airbase, Israel",
        "Q590092",
        gcat_sites=("PALB",),
    ),
    LaunchSiteSpec(
        "YSLA",
        "yellow-sea-launch",
        "Yellow Sea Launch Area, PRC",
        gcat_sites=("HHAI",),
    ),
    LaunchSiteSpec(
        "YUN",
        "sohae",
        "Yunsong Launch Site (Sohae Satellite Launching Station), DPRK",
        "Q377158",
        gcat_sites=("SOHAE",),
    ),
)

LAUNCH_SITE_CODES: frozenset[str] = frozenset(s.code for s in LAUNCH_SITES)

LAUNCH_SITE_BY_CODE: dict[str, LaunchSiteSpec] = {s.code: s for s in LAUNCH_SITES}

LAUNCH_SITE_BY_SLUG: dict[str, LaunchSiteSpec] = {s.slug: s for s in LAUNCH_SITES}

assert len(LAUNCH_SITE_BY_SLUG) == len(LAUNCH_SITES), "Duplicate launch-site slug"
