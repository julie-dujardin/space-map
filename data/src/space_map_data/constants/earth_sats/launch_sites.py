"""CelesTrak SATCAT launch-site catalog.

See: https://celestrak.org/satcat/launchsites.php
"""

from dataclasses import dataclass

# Group slug namespace: launch-site group slugs are
# ``f"{LAUNCH_SITE_SLUG_PREFIX}{site.slug}"`` so they don't collide with
# constellation or operator slugs in the group registry.
LAUNCH_SITE_SLUG_PREFIX = "site-"


@dataclass(frozen=True)
class LaunchSiteSpec:
    code: str  # SATCAT short code (primary key)
    slug: str  # URL slug used for the per-site group page
    name: str  # Human-readable description
    wikidata_qid: str | None = None


LAUNCH_SITES: tuple[LaunchSiteSpec, ...] = (
    LaunchSiteSpec(
        "AFETR",
        "cape-canaveral",
        "Air Force Eastern Test Range, Florida, USA",
        "Q334465",
    ),
    LaunchSiteSpec(
        "AFWTR",
        "vandenberg",
        "Air Force Western Test Range, California, USA",
        "Q461492",
    ),
    LaunchSiteSpec("ANDSP", "andoya", "Andøya Spaceport, Nordland, Norway", "Q528446"),
    LaunchSiteSpec(
        "ALCLC",
        "alcantara",
        "Alâcantara Launch Center, Maranhão, Brazil",
        "Q922797",
    ),
    LaunchSiteSpec(
        "BOS",
        "bowen",
        "Bowen Orbital Spaceport, Queensland, Australia",
        "Q131056918",
    ),
    LaunchSiteSpec("CAS", "canaries-airspace", "Canaries Airspace"),
    LaunchSiteSpec(
        "DLS", "dombarovskiy", "Dombarovskiy Launch Site, Russia", "Q627080"
    ),
    LaunchSiteSpec("ERAS", "eastern-range-airspace", "Eastern Range Airspace"),
    LaunchSiteSpec(
        "FRGUI", "kourou", "Europe's Spaceport, Kourou, French Guiana", "Q308987"
    ),
    LaunchSiteSpec(
        "HGSTR", "hammaguir", "Hammaguira Space Track Range, Algeria", "Q1054217"
    ),
    LaunchSiteSpec(
        "JJSLA",
        "jeju-sea-launch",
        "Jeju Island Sea Launch Area, Republic of Korea",
        "Q41164",
    ),
    LaunchSiteSpec("JSC", "jiuquan", "Jiuquan Space Center, PRC", "Q692677"),
    LaunchSiteSpec("KODAK", "kodiak", "Kodiak Launch Complex, Alaska, USA", "Q283842"),
    LaunchSiteSpec(
        "KSCUT",
        "uchinoura",
        "Uchinoura Space Center (formerly Kagoshima Space Center)",
        "Q1077124",
    ),
    LaunchSiteSpec("KWAJ", "kwajalein", "US Army Kwajalein Atoll (USAKA)", "Q1794892"),
    LaunchSiteSpec(
        "KYMSC",
        "kapustin-yar",
        "Kapustin Yar Missile and Space Complex, Russia",
        "Q753201",
    ),
    LaunchSiteSpec("NSC", "naro", "Naro Space Complex, Republic of Korea", "Q495281"),
    LaunchSiteSpec(
        "PLMSC", "plesetsk", "Plesetsk Missile and Space Complex, Russia", "Q15778"
    ),
    LaunchSiteSpec(
        "RLLB",
        "mahia",
        "Rocket Lab Launch Base, Mahia Peninsula, New Zealand",
        "Q28180879",
    ),
    LaunchSiteSpec(
        "SCSLA", "south-china-sea-launch", "South China Sea Launch Area, PRC"
    ),
    LaunchSiteSpec("SEAL", "sea-launch", "Sea Launch Platform (mobile)", "Q3177009"),
    LaunchSiteSpec(
        "SEMLS", "semnan", "Semnan Satellite Launch Site, Iran", "Q16047974"
    ),
    LaunchSiteSpec("SMTS", "shahrud", "Shahrud Missile Test Site, Iran", "Q112648507"),
    LaunchSiteSpec(
        "SNMLP",
        "san-marco",
        "San Marco Launch Platform, Indian Ocean (Kenya)",
        "Q644399",
    ),
    LaunchSiteSpec("SPKII", "space-port-kii", "Space Port Kii, Japan", "Q122375877"),
    LaunchSiteSpec(
        "SRILR", "satish-dhawan", "Satish Dhawan Space Centre, India", "Q640273"
    ),
    LaunchSiteSpec("SUBL", "submarine-launch", "Submarine Launch Platform (mobile)"),
    LaunchSiteSpec(
        "SVOBO", "svobodnyy", "Svobodnyy Launch Complex, Russia", "Q1366384"
    ),
    LaunchSiteSpec("TAISC", "taiyuan", "Taiyuan Space Center, PRC", "Q1194479"),
    LaunchSiteSpec(
        "TANSC", "tanegashima", "Tanegashima Space Center, Japan", "Q742683"
    ),
    LaunchSiteSpec(
        "TYMSC",
        "baikonur",
        "Tyuratam Missile and Space Center / Baikonur Cosmodrome, Kazakhstan",
        "Q177477",
    ),  # See https://www.cia.gov/readingroom/docs/CIA-RDP78T05439A000200390120-8.pdf
    LaunchSiteSpec("UNK", "unknown-site", "Unknown"),
    LaunchSiteSpec("VOSTO", "vostochny", "Vostochny Cosmodrome, Russia", "Q1166191"),
    LaunchSiteSpec("WLPIS", "wallops", "Wallops Island, Virginia, USA", "Q182348"),
    LaunchSiteSpec("WOMRA", "woomera", "Woomera, Australia", "Q17239134"),
    LaunchSiteSpec("WRAS", "western-range-airspace", "Western Range Airspace"),
    LaunchSiteSpec(
        "WSC", "wenchang", "Wenchang Satellite Launch Site, PRC", "Q1246624"
    ),
    LaunchSiteSpec("XICLF", "xichang", "Xichang Launch Facility, PRC", "Q734306"),
    LaunchSiteSpec(
        "YAVNE",
        "palmachim",
        "Yavne Launch Facility / Palmachim Airbase, Israel",
        "Q590092",
    ),
    LaunchSiteSpec("YSLA", "yellow-sea-launch", "Yellow Sea Launch Area, PRC"),
    LaunchSiteSpec(
        "YUN",
        "sohae",
        "Yunsong Launch Site (Sohae Satellite Launching Station), DPRK",
        "Q377158",
    ),
)

LAUNCH_SITE_CODES: frozenset[str] = frozenset(s.code for s in LAUNCH_SITES)

LAUNCH_SITE_BY_CODE: dict[str, LaunchSiteSpec] = {s.code: s for s in LAUNCH_SITES}

LAUNCH_SITE_BY_SLUG: dict[str, LaunchSiteSpec] = {s.slug: s for s in LAUNCH_SITES}

assert len(LAUNCH_SITE_BY_SLUG) == len(LAUNCH_SITES), "Duplicate launch-site slug"
