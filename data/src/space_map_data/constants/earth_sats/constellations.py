"""Satellite constellation catalog.

Each constellation has a ``slug`` (primary key), a display ``name``, an optional
``wikidata_qid``, a ``category`` (one of CelesTrak's top-level groupings), and
one of three membership selectors: an object-name ``prefix`` (detected from the
TLE ``OBJECT_NAME``), a CelesTrak ``group`` slug (fetched via
``gp.php?GROUP=``), or a SATCAT ``source`` code (matched against the ``OWNER``
field, i.e. the CelesTrak source/operator code).

Prefix-based membership is preferred since it avoids fetching 10k+ rows just to
tag a single constellation (Starlink alone is most of that). Group fetches are
reserved for constellations whose members don't share an obvious name prefix.
Source-based membership is used for commercial operators whose fleet is
identified in SATCAT but whose satellites don't share a name prefix.

Categories mirror the top-level sections of https://celestrak.org/NORAD/elements/
"""

from dataclasses import dataclass
from enum import StrEnum


class ConstellationCategory(StrEnum):
    """Top-level grouping from https://celestrak.org/NORAD/elements/"""

    SPECIAL_INTEREST = "special_interest"
    WEATHER_EARTH_RESOURCES = "weather_earth_resources"
    COMMUNICATIONS = "communications"
    NAVIGATION = "navigation"
    SCIENTIFIC = "scientific"
    MISCELLANEOUS = "miscellaneous"


@dataclass(frozen=True)
class ConstellationSpec:
    slug: str
    name: str
    wikidata_qid: str | None
    category: ConstellationCategory
    prefix: str | None = None  # TLE OBJECT_NAME startswith
    group: str | None = None  # CelesTrak gp.php GROUP slug
    source: str | None = None  # SATCAT SOURCE/OWNER code


CONSTELLATIONS: tuple[ConstellationSpec, ...] = (
    # Derived from OBJECT_NAME prefix
    ConstellationSpec("starlink", "Starlink", "Q19867977", ConstellationCategory.COMMUNICATIONS, prefix="STARLINK"),
    ConstellationSpec("oneweb", "OneWeb", "Q17184117", ConstellationCategory.COMMUNICATIONS, prefix="ONEWEB"),
    ConstellationSpec("iridium", "Iridium", "Q3154356", ConstellationCategory.COMMUNICATIONS, prefix="IRIDIUM"),
    ConstellationSpec("kuiper", "Project Kuiper", "Q62812537", ConstellationCategory.COMMUNICATIONS, prefix="KUIPER"),
    ConstellationSpec("qianfan", "Qianfan", "Q124981442", ConstellationCategory.COMMUNICATIONS, prefix="QIANFAN"),
    ConstellationSpec("guowang", "Guowang", "Q123581514", ConstellationCategory.COMMUNICATIONS, prefix="HULIANWANG DIGUI"),
    ConstellationSpec("globalstar", "Globalstar", "Q1202533", ConstellationCategory.COMMUNICATIONS, prefix="GLOBALSTAR"),
    ConstellationSpec("planet", "Planet (Flock)", "Q97380305", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="FLOCK"),
    ConstellationSpec("planet", "Planet (SkySat)", "Q27031816", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="SKYSAT"),
    ConstellationSpec("spacebee", "SpaceBEE", "Q105334563", ConstellationCategory.COMMUNICATIONS, prefix="SPACEBEE"),
    ConstellationSpec("sitro-ais", "SITRO-AIS", None, ConstellationCategory.COMMUNICATIONS, prefix="SITRO-AIS"),
    ConstellationSpec("geesat", "Geely GeeSAT", "Q125167295", ConstellationCategory.COMMUNICATIONS, prefix="GEESAT"),
    ConstellationSpec("gonets", "Gonets", "Q2041033", ConstellationCategory.COMMUNICATIONS, prefix="GONETS"),
    ConstellationSpec("tianqi", "Tianqi", None, ConstellationCategory.COMMUNICATIONS, prefix="TIANQI"),
    ConstellationSpec("connecta-iot", "Connecta IoT", None, ConstellationCategory.COMMUNICATIONS, prefix="CONNECTA IOT"),
    ConstellationSpec("tianmu", "Tianmu-1", "Q124168307", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="TIANMU-1"),
    ConstellationSpec("spire", "Spire Lemur", "Q19877982", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="LEMUR"),
    ConstellationSpec("marecs", "MARECS", "Q1881172", ConstellationCategory.COMMUNICATIONS, prefix="MARECS"),
    ConstellationSpec("marisat", "Marisat", "Q6765591", ConstellationCategory.COMMUNICATIONS, prefix="LEMUR"),
    ConstellationSpec("inmarsat", "Inmarsat", "Q827927", ConstellationCategory.COMMUNICATIONS, prefix="INMARSAT"),
    ConstellationSpec("metop", "MetOp", "Q819651", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="METOP"),
    ConstellationSpec(
        "meteosat", "Meteosat", "Q1429889", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="METEOSAT"
    ),  # Also see https://en.wikipedia.org/wiki/Jason_satellite_series
    # Derived from CelesTrak group membership
    ConstellationSpec(
        "orbcomm", "Orbcomm", "Q16960684", ConstellationCategory.COMMUNICATIONS, group="orbcomm"
    ),  # all are named "ORBCOMM-..." except VESSELSAT, which are part of the constellation
    ConstellationSpec("intelsat", "Intelsat", "Q778126", ConstellationCategory.COMMUNICATIONS, group="intelsat"),
    ConstellationSpec("ses", "SES", "Q333025", ConstellationCategory.COMMUNICATIONS, group="ses"),
    ConstellationSpec(
        "eutelsat", "Eutelsat", "Q848336", ConstellationCategory.COMMUNICATIONS, prefix="EUTELSAT"
    ),  # include Ekspress-AT
    ConstellationSpec("telesat", "Telesat Lightspeed", "Q2401935", ConstellationCategory.COMMUNICATIONS, group="telesat"),
    ConstellationSpec("gps", "GPS", "Q18822", ConstellationCategory.NAVIGATION, group="gps-ops"),
    ConstellationSpec("glonass", "GLONASS", "Q486250", ConstellationCategory.NAVIGATION, group="glo-ops"),
    ConstellationSpec("galileo", "Galileo", "Q193902", ConstellationCategory.NAVIGATION, group="galileo"),
    ConstellationSpec("beidou", "BeiDou", "Q857141", ConstellationCategory.NAVIGATION, group="beidou"),
    # Derived from SATCAT SOURCE/OWNER code
    ConstellationSpec("arabsat", "Arabsat", "Q65277396", ConstellationCategory.COMMUNICATIONS, source="AB"),
    ConstellationSpec("abs", "Asia Broadcast Satellite / Agility Beyond Space", "Q18238088", ConstellationCategory.COMMUNICATIONS, source="ABS"),
    ConstellationSpec("asiasat", "AsiaSat", "Q726812", ConstellationCategory.COMMUNICATIONS, source="AC"),
    ConstellationSpec("new-ico", "New ICO", "Q3792482", ConstellationCategory.COMMUNICATIONS, source="NICO"),
    ConstellationSpec("o3b", "O3b", "Q3347484", ConstellationCategory.COMMUNICATIONS, source="O3B"),
    ConstellationSpec("rascomstar", "RascomStar-QAF", "Q3415056", ConstellationCategory.COMMUNICATIONS, source="RASC"),
)


PREFIX_TO_SLUG: dict[str, str] = {
    c.prefix: c.slug for c in CONSTELLATIONS if c.prefix is not None
}

GROUP_TO_SLUG: dict[str, str] = {
    c.group: c.slug for c in CONSTELLATIONS if c.group is not None
}

SOURCE_TO_SLUG: dict[str, str] = {
    c.source: c.slug for c in CONSTELLATIONS if c.source is not None
}


def slug_from_name(name: str | None) -> str | None:
    if not name:
        return None
    for prefix, slug in PREFIX_TO_SLUG.items():
        if name.startswith(prefix):
            return slug
    return None
