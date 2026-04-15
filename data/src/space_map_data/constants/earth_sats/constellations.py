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


class SatelliteCategory(StrEnum):
    """Top-level grouping from https://celestrak.org/NORAD/elements/"""

    DISASTER = "disaster-sar"
    WEATHER = "weather"
    OBSERVATION = "observation"
    COMMUNICATIONS = "communications"
    NAVIGATION = "navigation"
    SCIENCE = "science"
    MILITARY = "military"
    DEBRIS = "debris"
    STATION = "station"
    MISCELLANEOUS = "miscellaneous"


@dataclass(frozen=True)
class ConstellationSpec:
    slug: str
    wikidata_qid: str | None
    category: SatelliteCategory
    prefix: str | None = None  # TLE OBJECT_NAME startswith
    group: str | None = None  # CelesTrak gp.php GROUP slug
    source: str | None = None  # SATCAT SOURCE/OWNER code


CONSTELLATIONS: tuple[ConstellationSpec, ...] = (
    # Derived from OBJECT_NAME prefix
    ConstellationSpec(
        "starlink", "Q19867977", SatelliteCategory.COMMUNICATIONS, prefix="STARLINK"
    ),
    ConstellationSpec(
        "oneweb", "Q17184117", SatelliteCategory.COMMUNICATIONS, prefix="ONEWEB"
    ),
    ConstellationSpec(
        "iridium", "Q3154356", SatelliteCategory.COMMUNICATIONS, prefix="IRIDIUM"
    ),
    ConstellationSpec(
        "kuiper", "Q62812537", SatelliteCategory.COMMUNICATIONS, prefix="KUIPER"
    ),
    ConstellationSpec(
        "qianfan", "Q124981442", SatelliteCategory.COMMUNICATIONS, prefix="QIANFAN"
    ),
    ConstellationSpec(
        "guowang",
        "Q123581514",
        SatelliteCategory.COMMUNICATIONS,
        prefix="HULIANWANG DIGUI",
    ),
    ConstellationSpec(
        "globalstar", "Q1202533", SatelliteCategory.COMMUNICATIONS, prefix="GLOBALSTAR"
    ),
    ConstellationSpec(
        "planet-flock", "Q97380305", SatelliteCategory.OBSERVATION, prefix="FLOCK"
    ),
    ConstellationSpec(
        "planet-skysat", "Q27031816", SatelliteCategory.OBSERVATION, prefix="SKYSAT"
    ),
    ConstellationSpec(
        "spacebee", "Q105334563", SatelliteCategory.COMMUNICATIONS, prefix="SPACEBEE"
    ),
    ConstellationSpec(
        "sitro-ais", None, SatelliteCategory.COMMUNICATIONS, prefix="SITRO-AIS"
    ),
    ConstellationSpec(
        "geesat", "Q125167295", SatelliteCategory.COMMUNICATIONS, prefix="GEESAT"
    ),
    ConstellationSpec(
        "gonets", "Q2041033", SatelliteCategory.COMMUNICATIONS, prefix="GONETS"
    ),
    ConstellationSpec(
        "tianqi", None, SatelliteCategory.COMMUNICATIONS, prefix="TIANQI"
    ),
    ConstellationSpec(
        "connecta-iot", None, SatelliteCategory.COMMUNICATIONS, prefix="CONNECTA IOT"
    ),
    ConstellationSpec(
        "tianmu", "Q124168307", SatelliteCategory.WEATHER, prefix="TIANMU-1"
    ),
    ConstellationSpec(
        "spire", "Q19877982", SatelliteCategory.OBSERVATION, prefix="LEMUR"
    ),
    ConstellationSpec(
        "marecs", "Q1881172", SatelliteCategory.COMMUNICATIONS, prefix="MARECS"
    ),
    ConstellationSpec(
        "marisat", "Q6765591", SatelliteCategory.COMMUNICATIONS, prefix="LEMUR"
    ),
    ConstellationSpec(
        "inmarsat", "Q827927", SatelliteCategory.COMMUNICATIONS, prefix="INMARSAT"
    ),
    ConstellationSpec("metop", "Q819651", SatelliteCategory.WEATHER, prefix="METOP"),
    ConstellationSpec(
        "meteosat", "Q1429889", SatelliteCategory.WEATHER, prefix="METEOSAT"
    ),  # Also see https://en.wikipedia.org/wiki/Jason_satellite_series
    ConstellationSpec(
        "measat", None, SatelliteCategory.COMMUNICATIONS, prefix="MEASAT"
    ),
    ConstellationSpec(
        "africasat", "Q20052527", SatelliteCategory.COMMUNICATIONS, prefix="AFRICASAT"
    ),
    ConstellationSpec(
        "thaicom", None, SatelliteCategory.COMMUNICATIONS, prefix="THAICOM"
    ),
    ConstellationSpec(
        "fengyun", "Q1404722", SatelliteCategory.WEATHER, prefix="FENGYUN"
    ),
    # Derived from CelesTrak group membership
    ConstellationSpec(
        "orbcomm", "Q16960684", SatelliteCategory.COMMUNICATIONS, group="orbcomm"
    ),  # all are named "ORBCOMM-..." except VESSELSAT, which are part of the constellation
    ConstellationSpec(
        "intelsat", "Q778126", SatelliteCategory.COMMUNICATIONS, group="intelsat"
    ),
    ConstellationSpec("ses", "Q333025", SatelliteCategory.COMMUNICATIONS, group="ses"),
    ConstellationSpec(
        "eutelsat", "Q848336", SatelliteCategory.COMMUNICATIONS, prefix="EUTELSAT"
    ),  # include Ekspress-AT
    ConstellationSpec(
        "telesat", "Q2401935", SatelliteCategory.COMMUNICATIONS, group="telesat"
    ),
    ConstellationSpec("gps", "Q18822", SatelliteCategory.NAVIGATION, group="gps-ops"),
    ConstellationSpec(
        "glonass", "Q486250", SatelliteCategory.NAVIGATION, group="glo-ops"
    ),
    ConstellationSpec(
        "galileo", "Q193902", SatelliteCategory.NAVIGATION, group="galileo"
    ),
    ConstellationSpec(
        "beidou", "Q857141", SatelliteCategory.NAVIGATION, group="beidou"
    ),
    ConstellationSpec(
        "transit", "Q651136", SatelliteCategory.NAVIGATION, group="nnss"
    ),  # Navy Navigation Satellite System
    ConstellationSpec("sbas", "Q2165162", SatelliteCategory.NAVIGATION, group="sbas"),
    ConstellationSpec(
        "fengyun-1c-asat-debris",
        "Q182183",
        SatelliteCategory.DEBRIS,
        group="fengyun-1c-debris",
    ),
    ConstellationSpec(
        "iridium-33-debris",
        "Q843912",
        SatelliteCategory.DEBRIS,
        group="iridium-33-debris",
    ),
    ConstellationSpec(
        "cosmos-2251-debris",
        "Q843912",
        SatelliteCategory.DEBRIS,
        group="cosmos-2251-debris",
    ),
    ConstellationSpec("tdrss", "Q3522774", SatelliteCategory.DEBRIS, group="tdrss"),
    ConstellationSpec("argos", "Q649489", SatelliteCategory.DEBRIS, group="argos"),
    # Derived from SATCAT SOURCE/OWNER code
    ConstellationSpec(
        "arabsat", "Q65277396", SatelliteCategory.COMMUNICATIONS, source="AB"
    ),
    ConstellationSpec(
        "abs", "Q18238088", SatelliteCategory.COMMUNICATIONS, source="ABS"
    ),
    ConstellationSpec(
        "asiasat", "Q726812", SatelliteCategory.COMMUNICATIONS, source="AC"
    ),
    ConstellationSpec(
        "new-ico", "Q3792482", SatelliteCategory.COMMUNICATIONS, source="NICO"
    ),
    ConstellationSpec(
        "o3b", "Q3347484", SatelliteCategory.COMMUNICATIONS, source="O3B"
    ),
    ConstellationSpec(
        "rascomstar", "Q3415056", SatelliteCategory.COMMUNICATIONS, source="RASC"
    ),
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

# CelesTrak groups that tag sats with a category directly, without belonging to
# a named constellation. See https://celestrak.org/NORAD/elements/.
GROUP_TO_CATEGORY: dict[str, SatelliteCategory] = {
    "military": SatelliteCategory.MILITARY,
    "radar": SatelliteCategory.MISCELLANEOUS,
    "other-comm": SatelliteCategory.COMMUNICATIONS,
    "analyst": SatelliteCategory.DEBRIS,
    "stations": SatelliteCategory.STATION,
    "dmc": SatelliteCategory.DISASTER,
    "sarsat": SatelliteCategory.DISASTER,
    "science": SatelliteCategory.SCIENCE,
    "engineering": SatelliteCategory.SCIENCE,
    "education": SatelliteCategory.SCIENCE,
    "geodetic": SatelliteCategory.SCIENCE,
}


def slug_from_name(name: str | None) -> str | None:
    if not name:
        return None
    for prefix, slug in PREFIX_TO_SLUG.items():
        if name.startswith(prefix):
            return slug
    return None
