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
    ConstellationSpec("starlink", "Starlink", "Q2154802", prefix="STARLINK"),
    ConstellationSpec("oneweb", "OneWeb", "Q18642935", prefix="ONEWEB"),
    ConstellationSpec("iridium", "Iridium", "Q679277", prefix="IRIDIUM"),
    ConstellationSpec("kuiper", "Project Kuiper", "Q100264108", prefix="KUIPER"),
    ConstellationSpec("qianfan", "Qianfan", None, prefix="QIANFAN"),
    ConstellationSpec("guowang", "Guowang", None, prefix="HULIANWANG DIGUI"),
    ConstellationSpec("globalstar", "Globalstar", "Q1540809", prefix="GLOBALSTAR"),
    ConstellationSpec("orbcomm", "Orbcomm", "Q1316306", prefix="ORBCOMM"),
    ConstellationSpec("planet", "Planet (Flock)", "Q2289277", prefix="FLOCK"),
    ConstellationSpec("spacebee", "SpaceBEE", "Q28441022", prefix="SPACEBEE"),
    ConstellationSpec("sitro-ais", "SITRO-AIS", None, prefix="SITRO-AIS"),
    ConstellationSpec("geesat", "Geely GeeSAT", None, prefix="GEESAT"),
    ConstellationSpec("gonets", "Gonets", "Q1540821", prefix="GONETS-M"),
    ConstellationSpec("tianqi", "Tianqi", None, prefix="TIANQI"),
    ConstellationSpec("connecta-iot", "Connecta IoT", None, prefix="CONNECTA IOT"),
    ConstellationSpec("tianmu", "Tianmu-1", None, prefix="TIANMU-1"),
    # Derived from CelesTrak group membership
    ConstellationSpec("spire", "Spire Lemur", "Q7580085", group="spire"),
    ConstellationSpec("intelsat", "Intelsat", "Q559731", group="intelsat"),
    ConstellationSpec("ses", "SES", "Q1003451", group="ses"),
    ConstellationSpec("eutelsat", "Eutelsat", "Q310463", group="eutelsat"),
    ConstellationSpec("telesat", "Telesat Lightspeed", "Q2390120", group="telesat"),
    ConstellationSpec("gps", "GPS", "Q49088", group="gps-ops"),
    ConstellationSpec("glonass", "GLONASS", "Q170268", group="glo-ops"),
    ConstellationSpec("galileo", "Galileo", "Q1038", group="galileo"),
    ConstellationSpec("beidou", "BeiDou", "Q182780", group="beidou"),
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
