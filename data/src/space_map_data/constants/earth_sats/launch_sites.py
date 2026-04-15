"""CelesTrak SATCAT launch-site catalog.

See: https://celestrak.org/satcat/launchsites.php
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LaunchSiteSpec:
    code: str  # SATCAT short code (primary key)
    name: str  # Human-readable description
    wikidata_qid: str | None = None


LAUNCH_SITES: tuple[LaunchSiteSpec, ...] = (
    LaunchSiteSpec("AFETR", "Air Force Eastern Test Range, Florida, USA", "Q334465"),
    LaunchSiteSpec("AFWTR", "Air Force Western Test Range, California, USA", "Q461492"),
    LaunchSiteSpec("ANDSP", "Andøya Spaceport, Nordland, Norway", "Q528446"),
    LaunchSiteSpec("ALCLC", "Alâcantara Launch Center, Maranhão, Brazil", "Q922797"),
    LaunchSiteSpec(
        "BOS", "Bowen Orbital Spaceport, Queensland, Australia", "Q131056918"
    ),
    LaunchSiteSpec("CAS", "Canaries Airspace"),
    LaunchSiteSpec("DLS", "Dombarovskiy Launch Site, Russia", "Q627080"),
    LaunchSiteSpec("ERAS", "Eastern Range Airspace"),
    LaunchSiteSpec("FRGUI", "Europe's Spaceport, Kourou, French Guiana", "Q308987"),
    LaunchSiteSpec("HGSTR", "Hammaguira Space Track Range, Algeria", "Q1054217"),
    LaunchSiteSpec("JJSLA", "Jeju Island Sea Launch Area, Republic of Korea", "Q41164"),
    LaunchSiteSpec("JSC", "Jiuquan Space Center, PRC", "Q692677"),
    LaunchSiteSpec("KODAK", "Kodiak Launch Complex, Alaska, USA", "Q283842"),
    LaunchSiteSpec(
        "KSCUT", "Uchinoura Space Center (formerly Kagoshima Space Center)", "Q1077124"
    ),
    LaunchSiteSpec("KWAJ", "US Army Kwajalein Atoll (USAKA)", "Q1794892"),
    LaunchSiteSpec(
        "KYMSC", "Kapustin Yar Missile and Space Complex, Russia", "Q753201"
    ),
    LaunchSiteSpec("NSC", "Naro Space Complex, Republic of Korea", "Q495281"),
    LaunchSiteSpec("PLMSC", "Plesetsk Missile and Space Complex, Russia", "Q15778"),
    LaunchSiteSpec(
        "RLLB", "Rocket Lab Launch Base, Mahia Peninsula, New Zealand", "Q28180879"
    ),
    LaunchSiteSpec("SCSLA", "South China Sea Launch Area, PRC"),
    LaunchSiteSpec("SEAL", "Sea Launch Platform (mobile)", "Q3177009"),
    LaunchSiteSpec("SEMLS", "Semnan Satellite Launch Site, Iran", "Q16047974"),
    LaunchSiteSpec("SMTS", "Shahrud Missile Test Site, Iran", "Q112648507"),
    LaunchSiteSpec(
        "SNMLP", "San Marco Launch Platform, Indian Ocean (Kenya)", "Q644399"
    ),
    LaunchSiteSpec("SPKII", "Space Port Kii, Japan", "Q122375877"),
    LaunchSiteSpec("SRILR", "Satish Dhawan Space Centre, India", "Q640273"),
    LaunchSiteSpec("SUBL", "Submarine Launch Platform (mobile)"),
    LaunchSiteSpec("SVOBO", "Svobodnyy Launch Complex, Russia", "Q1366384"),
    LaunchSiteSpec("TAISC", "Taiyuan Space Center, PRC", "Q1194479"),
    LaunchSiteSpec("TANSC", "Tanegashima Space Center, Japan", "Q742683"),
    LaunchSiteSpec(
        "TYMSC",
        "Tyuratam Missile and Space Center / Baikonur Cosmodrome, Kazakhstan",
        "Q177477",
    ),  # See https://www.cia.gov/readingroom/docs/CIA-RDP78T05439A000200390120-8.pdf
    LaunchSiteSpec("UNK", "Unknown"),
    LaunchSiteSpec("VOSTO", "Vostochny Cosmodrome, Russia", "Q1166191"),
    LaunchSiteSpec("WLPIS", "Wallops Island, Virginia, USA", "Q182348"),
    LaunchSiteSpec("WOMRA", "Woomera, Australia", "Q17239134"),
    LaunchSiteSpec("WRAS", "Western Range Airspace"),
    LaunchSiteSpec("WSC", "Wenchang Satellite Launch Site, PRC", "Q1246624"),
    LaunchSiteSpec("XICLF", "Xichang Launch Facility, PRC", "Q734306"),
    LaunchSiteSpec(
        "YAVNE", "Yavne Launch Facility / Palmachim Airbase, Israel", "Q590092"
    ),
    LaunchSiteSpec("YSLA", "Yellow Sea Launch Area, PRC"),
    LaunchSiteSpec(
        "YUN",
        "Yunsong Launch Site (Sohae Satellite Launching Station), DPRK",
        "Q377158",
    ),
)

LAUNCH_SITE_CODES: frozenset[str] = frozenset(s.code for s in LAUNCH_SITES)

LAUNCH_SITE_BY_CODE: dict[str, LaunchSiteSpec] = {s.code: s for s in LAUNCH_SITES}
