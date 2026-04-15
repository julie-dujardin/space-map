"""Satellite constellation catalog.

Each constellation has a ``slug`` (primary key), an optional ``wikidata_qid``
(display names are sourced from Wikipedia/Wikidata), a ``category`` (one of
CelesTrak's top-level groupings), and one of three membership selectors: an
object-name ``prefix`` (detected from the TLE ``OBJECT_NAME``), a CelesTrak
``group`` slug (fetched via ``gp.php?GROUP=``), or a SATCAT ``source`` code
(matched against the ``OWNER`` field, i.e. the CelesTrak source/operator code).

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
    wikidata_qid: str | None
    category: ConstellationCategory
    prefix: str | None = None  # TLE OBJECT_NAME startswith
    group: str | None = None  # CelesTrak gp.php GROUP slug
    source: str | None = None  # SATCAT SOURCE/OWNER code


CONSTELLATIONS: tuple[ConstellationSpec, ...] = (
    # Derived from OBJECT_NAME prefix
    ConstellationSpec("starlink", "Q19867977", ConstellationCategory.COMMUNICATIONS, prefix="STARLINK"),
    ConstellationSpec("oneweb", "Q17184117", ConstellationCategory.COMMUNICATIONS, prefix="ONEWEB"),
    ConstellationSpec("iridium", "Q3154356", ConstellationCategory.COMMUNICATIONS, prefix="IRIDIUM"),
    ConstellationSpec("kuiper", "Q62812537", ConstellationCategory.COMMUNICATIONS, prefix="KUIPER"),
    ConstellationSpec("qianfan", "Q124981442", ConstellationCategory.COMMUNICATIONS, prefix="QIANFAN"),
    ConstellationSpec("guowang", "Q123581514", ConstellationCategory.COMMUNICATIONS, prefix="HULIANWANG DIGUI"),
    ConstellationSpec("globalstar", "Q1202533", ConstellationCategory.COMMUNICATIONS, prefix="GLOBALSTAR"),
    ConstellationSpec("planet-flock", "Q97380305", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="FLOCK"),
    ConstellationSpec("planet-skysat", "Q27031816", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="SKYSAT"),
    ConstellationSpec("spacebee", "Q105334563", ConstellationCategory.COMMUNICATIONS, prefix="SPACEBEE"),
    ConstellationSpec("sitro-ais", None, ConstellationCategory.COMMUNICATIONS, prefix="SITRO-AIS"),
    ConstellationSpec("geesat", "Q125167295", ConstellationCategory.COMMUNICATIONS, prefix="GEESAT"),
    ConstellationSpec("gonets", "Q2041033", ConstellationCategory.COMMUNICATIONS, prefix="GONETS"),
    ConstellationSpec("tianqi", None, ConstellationCategory.COMMUNICATIONS, prefix="TIANQI"),
    ConstellationSpec("connecta-iot", None, ConstellationCategory.COMMUNICATIONS, prefix="CONNECTA IOT"),
    ConstellationSpec("tianmu", "Q124168307", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="TIANMU-1"),
    ConstellationSpec("spire", "Q19877982", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="LEMUR"),
    ConstellationSpec("marecs", "Q1881172", ConstellationCategory.COMMUNICATIONS, prefix="MARECS"),
    ConstellationSpec("marisat", "Q6765591", ConstellationCategory.COMMUNICATIONS, prefix="LEMUR"),
    ConstellationSpec("inmarsat", "Q827927", ConstellationCategory.COMMUNICATIONS, prefix="INMARSAT"),
    ConstellationSpec("metop", "Q819651", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="METOP"),
    ConstellationSpec(
        "meteosat", "Q1429889", ConstellationCategory.WEATHER_EARTH_RESOURCES, prefix="METEOSAT"
    ),  # Also see https://en.wikipedia.org/wiki/Jason_satellite_series
    ConstellationSpec("measat", None, ConstellationCategory.COMMUNICATIONS, prefix="MEASAT"),
    ConstellationSpec("africasat", "Q20052527", ConstellationCategory.COMMUNICATIONS, prefix="AFRICASAT"),
    ConstellationSpec("thaicom", None, ConstellationCategory.COMMUNICATIONS, prefix="THAICOM"),
    # Derived from CelesTrak group membership
    ConstellationSpec(
        "orbcomm", "Q16960684", ConstellationCategory.COMMUNICATIONS, group="orbcomm"
    ),  # all are named "ORBCOMM-..." except VESSELSAT, which are part of the constellation
    ConstellationSpec("intelsat", "Q778126", ConstellationCategory.COMMUNICATIONS, group="intelsat"),
    ConstellationSpec("ses", "Q333025", ConstellationCategory.COMMUNICATIONS, group="ses"),
    ConstellationSpec(
        "eutelsat", "Q848336", ConstellationCategory.COMMUNICATIONS, prefix="EUTELSAT"
    ),  # include Ekspress-AT
    ConstellationSpec("telesat", "Q2401935", ConstellationCategory.COMMUNICATIONS, group="telesat"),
    ConstellationSpec("gps", "Q18822", ConstellationCategory.NAVIGATION, group="gps-ops"),
    ConstellationSpec("glonass", "Q486250", ConstellationCategory.NAVIGATION, group="glo-ops"),
    ConstellationSpec("galileo", "Q193902", ConstellationCategory.NAVIGATION, group="galileo"),
    ConstellationSpec("beidou", "Q857141", ConstellationCategory.NAVIGATION, group="beidou"),
    # Derived from SATCAT SOURCE/OWNER code
    ConstellationSpec("arabsat", "Q65277396", ConstellationCategory.COMMUNICATIONS, source="AB"),
    ConstellationSpec("abs", "Q18238088", ConstellationCategory.COMMUNICATIONS, source="ABS"),
    ConstellationSpec("asiasat", "Q726812", ConstellationCategory.COMMUNICATIONS, source="AC"),
    ConstellationSpec("new-ico", "Q3792482", ConstellationCategory.COMMUNICATIONS, source="NICO"),
    ConstellationSpec("o3b", "Q3347484", ConstellationCategory.COMMUNICATIONS, source="O3B"),
    ConstellationSpec("rascomstar", "Q3415056", ConstellationCategory.COMMUNICATIONS, source="RASC"),
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
