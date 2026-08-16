"""Typed enums for CelesTrak SATCAT coded fields.

Raw SATCAT codes (``+``, ``R/B``, ``PRC``, ...) become descriptive string-enum
values during ingest. Unknown codes raise ``ValueError``.

Sources:
- https://celestrak.org/satcat/satcat-format.php
- https://celestrak.org/satcat/sources.php
- https://celestrak.org/satcat/status.php
- https://celestrak.org/satcat/launchsites.php
"""

from enum import StrEnum


# https://celestrak.org/satcat/satcat-format.php (OBJECT_TYPE)
class SatcatObjectType(StrEnum):
    PAYLOAD = "payload"
    ROCKET_BODY = "rocket_body"
    DEBRIS = "debris"
    UNKNOWN = "unknown"


OBJECT_TYPE_CODES: dict[str, SatcatObjectType] = {
    "PAY": SatcatObjectType.PAYLOAD,
    "R/B": SatcatObjectType.ROCKET_BODY,
    "DEB": SatcatObjectType.DEBRIS,
    "UNK": SatcatObjectType.UNKNOWN,
}


# https://celestrak.org/satcat/status.php
class OpsStatus(StrEnum):
    OPERATIONAL = "operational"
    NONOPERATIONAL = "nonoperational"
    PARTIAL = "partial"
    BACKUP = "backup"
    SPARE = "spare"
    EXTENDED_MISSION = "extended_mission"
    DECAYED = "decayed"
    UNKNOWN = "unknown"


OPS_STATUS_CODES: dict[str, OpsStatus] = {
    "+": OpsStatus.OPERATIONAL,
    "-": OpsStatus.NONOPERATIONAL,
    "P": OpsStatus.PARTIAL,
    "p": OpsStatus.PARTIAL,  # seen in live data
    "B": OpsStatus.BACKUP,
    "S": OpsStatus.SPARE,
    "X": OpsStatus.EXTENDED_MISSION,
    "D": OpsStatus.DECAYED,
    "?": OpsStatus.UNKNOWN,
}


# https://celestrak.org/satcat/satcat-format.php (ORBIT_CENTER)
class OrbitCenter(StrEnum):
    """Body at the center of the object's orbit.

    ``DOCKED`` is a SATCAT special case: when the raw ``ORBIT_CENTER`` field
    holds a NORAD catalog number (numeric), the object is docked to that one.
    The catalog number is captured in a sibling column.
    """

    ASTEROID = "asteroid"
    COMET = "comet"
    EARTH = "earth"
    EARTH_LAGRANGE = "earth_lagrange"
    EARTH_L1 = "earth_l1"
    EARTH_L2 = "earth_l2"
    EARTH_MOON_BARYCENTER = "earth_moon_barycenter"
    JUPITER = "jupiter"
    MARS = "mars"
    MERCURY = "mercury"
    MOON = "moon"
    NEPTUNE = "neptune"
    PLUTO = "pluto"
    SATURN = "saturn"
    SOLAR_SYSTEM_ESCAPE = "solar_system_escape"
    SUN = "sun"
    URANUS = "uranus"
    VENUS = "venus"
    DOCKED = "docked"


ORBIT_CENTER_CODES: dict[str, OrbitCenter] = {
    "AS": OrbitCenter.ASTEROID,
    "CO": OrbitCenter.COMET,
    "EA": OrbitCenter.EARTH,
    "EL": OrbitCenter.EARTH_LAGRANGE,
    "EL1": OrbitCenter.EARTH_L1,
    "EL2": OrbitCenter.EARTH_L2,
    "EM": OrbitCenter.EARTH_MOON_BARYCENTER,
    "JU": OrbitCenter.JUPITER,
    "MA": OrbitCenter.MARS,
    "ME": OrbitCenter.MERCURY,
    "MO": OrbitCenter.MOON,
    "NE": OrbitCenter.NEPTUNE,
    "PL": OrbitCenter.PLUTO,
    "SA": OrbitCenter.SATURN,
    "SS": OrbitCenter.SOLAR_SYSTEM_ESCAPE,
    "SU": OrbitCenter.SUN,
    "UR": OrbitCenter.URANUS,
    "VE": OrbitCenter.VENUS,
}


# https://celestrak.org/satcat/satcat-format.php (ORBIT_TYPE)
class OrbitType(StrEnum):
    ORBIT = "orbit"
    LANDING = "landing"
    IMPACT = "impact"
    DOCKED = "docked"
    ROUNDTRIP = "roundtrip"


ORBIT_TYPE_CODES: dict[str, OrbitType] = {
    "ORB": OrbitType.ORBIT,
    "LAN": OrbitType.LANDING,
    "IMP": OrbitType.IMPACT,
    "DOC": OrbitType.DOCKED,
    "R/T": OrbitType.ROUNDTRIP,
}


# https://celestrak.org/satcat/satcat-format.php (DATA_STATUS_CODE)
class DataStatus(StrEnum):
    NO_CURRENT_ELEMENTS = "no_current_elements"
    NO_INITIAL_ELEMENTS = "no_initial_elements"
    NO_ELEMENTS_AVAILABLE = "no_elements_available"


DATA_STATUS_CODES: dict[str, DataStatus] = {
    "NCE": DataStatus.NO_CURRENT_ELEMENTS,
    "NIE": DataStatus.NO_INITIAL_ELEMENTS,
    "NEA": DataStatus.NO_ELEMENTS_AVAILABLE,
}


def _lookup[T](table: dict[str, T], code: str | None, field: str) -> T | None:
    if code is None or code == "":
        return None
    result = table.get(code)
    if result is None:
        raise ValueError(f"Unknown SATCAT {field} code: {code!r}")
    return result


def parse_object_type(code: str | None) -> SatcatObjectType | None:
    return _lookup(OBJECT_TYPE_CODES, code, "OBJECT_TYPE")


def parse_ops_status(code: str | None) -> OpsStatus | None:
    return _lookup(OPS_STATUS_CODES, code, "OPS_STATUS_CODE")


def parse_orbit_type(code: str | None) -> OrbitType | None:
    return _lookup(ORBIT_TYPE_CODES, code, "ORBIT_TYPE")


def parse_data_status(code: str | None) -> DataStatus | None:
    return _lookup(DATA_STATUS_CODES, code, "DATA_STATUS_CODE")


def parse_orbit_center(code: str | None) -> tuple[OrbitCenter | None, int | None]:
    """Return (orbit_center, docked_norad_id).

    When the SATCAT ``ORBIT_CENTER`` field holds a numeric NORAD catalog number
    the object is docked; we map it to ``OrbitCenter.DOCKED`` and return the
    numeric ID separately.
    """
    if code is None or code == "":
        return None, None
    if code.isdigit():
        return OrbitCenter.DOCKED, int(code)
    enum = ORBIT_CENTER_CODES.get(code)
    if enum is None:
        raise ValueError(f"Unknown SATCAT ORBIT_CENTER code: {code!r}")
    return enum, None
