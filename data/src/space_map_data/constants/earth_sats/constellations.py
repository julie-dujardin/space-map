"""Satellite constellation catalog.

Each constellation has a ``slug`` (primary key), a display ``name``, an optional
``wikidata_qid``, and either an object-name ``prefix`` (detected from the TLE
``OBJECT_NAME``) or a CelesTrak ``group`` slug (fetched via ``gp.php?GROUP=``).

Prefix-based membership is preferred since it avoids fetching 10k+ rows just to
tag a single constellation (Starlink alone is most of that). Group fetches are
reserved for constellations whose members don't share an obvious name prefix.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConstellationSpec:
    slug: str
    name: str
    wikidata_qid: str | None
    prefix: str | None = None  # TLE OBJECT_NAME startswith
    group: str | None = None  # CelesTrak gp.php GROUP slug


CONSTELLATIONS: tuple[ConstellationSpec, ...] = (
    # Derived from OBJECT_NAME prefix
    ConstellationSpec("starlink", "Starlink", "Q19867977", prefix="STARLINK"),
    ConstellationSpec("oneweb", "OneWeb", "Q17184117", prefix="ONEWEB"),
    ConstellationSpec("iridium", "Iridium", "Q3154356", prefix="IRIDIUM"),
    ConstellationSpec("kuiper", "Project Kuiper", "Q62812537", prefix="KUIPER"),
    ConstellationSpec("qianfan", "Qianfan", "Q124981442", prefix="QIANFAN"),
    ConstellationSpec("guowang", "Guowang", "Q123581514", prefix="HULIANWANG DIGUI"),
    ConstellationSpec("globalstar", "Globalstar", "Q1202533", prefix="GLOBALSTAR"),
    ConstellationSpec("planet", "Planet (Flock)", "Q97380305", prefix="FLOCK"),
    ConstellationSpec("planet", "Planet (SkySat)", "Q27031816", prefix="SKYSAT"),
    ConstellationSpec("spacebee", "SpaceBEE", "Q105334563", prefix="SPACEBEE"),
    ConstellationSpec("sitro-ais", "SITRO-AIS", None, prefix="SITRO-AIS"),
    ConstellationSpec("geesat", "Geely GeeSAT", "Q125167295", prefix="GEESAT"),
    ConstellationSpec("gonets", "Gonets", "Q2041033", prefix="GONETS"),
    ConstellationSpec("tianqi", "Tianqi", None, prefix="TIANQI"),
    ConstellationSpec("connecta-iot", "Connecta IoT", None, prefix="CONNECTA IOT"),
    ConstellationSpec("tianmu", "Tianmu-1", "Q124168307", prefix="TIANMU-1"),
    ConstellationSpec("spire", "Spire Lemur", "Q19877982", prefix="LEMUR"),
    ConstellationSpec("marecs", "MARECS", "Q1881172", prefix="MARECS"),  # operator: Inmarsat (Q827927)
    ConstellationSpec("marisat", "Marisat", "Q6765591", prefix="LEMUR"),  # operator: Inmarsat (Q827927)
    # Derived from CelesTrak group membership
    ConstellationSpec("orbcomm", "Orbcomm", "Q16960684", group="orbcomm"),  # all are named "ORBCOMM-..." except VESSELSAT, which are part of the constellation
    ConstellationSpec("intelsat", "Intelsat", "Q778126", group="intelsat"),
    ConstellationSpec("ses", "SES", "Q333025", group="ses"),
    ConstellationSpec("eutelsat", "Eutelsat", "Q848336", prefix="EUTELSAT"),  # include Ekspress-AT
    ConstellationSpec("telesat", "Telesat Lightspeed", "Q2401935", group="telesat"),
    ConstellationSpec("gps", "GPS", "Q18822", group="gps-ops"),
    ConstellationSpec("glonass", "GLONASS", "Q486250", group="glo-ops"),
    ConstellationSpec("galileo", "Galileo", "Q193902", group="galileo"),
    ConstellationSpec("beidou", "BeiDou", "Q857141", group="beidou"),
)


PREFIX_TO_SLUG: dict[str, str] = {
    c.prefix: c.slug for c in CONSTELLATIONS if c.prefix is not None
}

GROUP_TO_SLUG: dict[str, str] = {
    c.group: c.slug for c in CONSTELLATIONS if c.group is not None
}


def slug_from_name(name: str | None) -> str | None:
    if not name:
        return None
    for prefix, slug in PREFIX_TO_SLUG.items():
        if name.startswith(prefix):
            return slug
    return None
