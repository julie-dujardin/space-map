"""Typed enums for CelesTrak SATCAT coded fields.

Raw SATCAT codes (e.g. ``+``, ``R/B``, ``PRC``) are converted into descriptive
string-enum values during ingest. Unknown codes raise ``ValueError`` to keep
the downstream schema honest.

Sources:
- https://celestrak.org/satcat/satcat-format.php
- https://celestrak.org/satcat/sources.php
- https://celestrak.org/satcat/status.php
- https://celestrak.org/satcat/launchsites.php
"""

from dataclasses import dataclass
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


# https://celestrak.org/satcat/sources.php
@dataclass(frozen=True)
class SourceSpec:
    code: str  # SATCAT short code (primary key)
    name: str  # CelesTrak sources.php description
    countries: tuple[str, ...] = ()  # ISO 3166-1 alpha-2 codes
    operator: str | None = None  # Free-text operator name


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec("AB", "Arab Satellite Communications Organization", operator="Arabsat"),
    SourceSpec("ABS", "Asia Broadcast Satellite", operator="Asia Broadcast Satellite"),
    SourceSpec("AC", "AsiaSat", operator="AsiaSat"),
    SourceSpec("ALG", "Algeria", countries=("DZ",)),
    SourceSpec("ANG", "Angola", countries=("AO",)),
    SourceSpec("ARGN", "Argentina", countries=("AR",)),
    SourceSpec("ARM", "Armenia", countries=("AM",)),
    SourceSpec("ASRA", "Austria", countries=("AT",)),
    SourceSpec("AUS", "Australia", countries=("AU",)),
    SourceSpec("AZER", "Azerbaijan", countries=("AZ",)),
    SourceSpec("BEL", "Belgium", countries=("BE",)),
    SourceSpec("BELA", "Belarus", countries=("BY",)),
    SourceSpec("BERM", "Bermuda", countries=("BM",)),
    SourceSpec("BGD", "Bangladesh", countries=("BD",)),
    SourceSpec("BHR", "Bahrain", countries=("BH",)),
    SourceSpec("BHUT", "Bhutan", countries=("BT",)),
    SourceSpec("BOL", "Bolivia", countries=("BO",)),
    SourceSpec("BRAZ", "Brazil", countries=("BR",)),
    SourceSpec("BUL", "Bulgaria", countries=("BG",)),
    SourceSpec("BWA", "Botswana", countries=("BW",)),
    SourceSpec("CA", "Canada", countries=("CA",)),
    SourceSpec("CHBZ", "China-Brazil", countries=("CN", "BR")),
    SourceSpec("CHTU", "China-Türkiye", countries=("CN", "TR")),
    SourceSpec("CHLE", "Chile", countries=("CL",)),
    SourceSpec("CIS", "Commonwealth of Independent States"),
    SourceSpec("COL", "Colombia", countries=("CO",)),
    SourceSpec("CRI", "Costa Rica", countries=("CR",)),
    SourceSpec("CZCH", "Czech Republic", countries=("CZ",)),
    SourceSpec("DEN", "Denmark", countries=("DK",)),
    SourceSpec("DJI", "Djibouti", countries=("DJ",)),
    SourceSpec("ECU", "Ecuador", countries=("EC",)),
    SourceSpec("EGYP", "Egypt", countries=("EG",)),
    SourceSpec("ESA", "European Space Agency", operator="ESA"),
    SourceSpec("ESRO", "European Space Research Organization", operator="ESRO"),
    SourceSpec("EST", "Estonia", countries=("EE",)),
    SourceSpec("ETH", "Ethiopia", countries=("ET",)),
    SourceSpec("EUME", "EUMETSAT", operator="EUMETSAT"),
    SourceSpec("EUTE", "EUTELSAT", operator="Eutelsat"),
    SourceSpec("FGER", "France-Germany", countries=("FR", "DE")),
    SourceSpec("FIN", "Finland", countries=("FI",)),
    SourceSpec("FR", "France", countries=("FR",)),
    SourceSpec("FRIT", "France-Italy", countries=("FR", "IT")),
    SourceSpec("GER", "Germany", countries=("DE",)),
    SourceSpec("GHA", "Ghana", countries=("GH",)),
    SourceSpec("GLOB", "Globalstar", operator="Globalstar"),
    SourceSpec("GREC", "Greece", countries=("GR",)),
    SourceSpec("GRSA", "Greece-Saudi Arabia", countries=("GR", "SA")),
    SourceSpec("GUAT", "Guatemala", countries=("GT",)),
    SourceSpec("HRV", "Croatia", countries=("HR",)),
    SourceSpec("HUN", "Hungary", countries=("HU",)),
    SourceSpec("IM", "Inmarsat", operator="Inmarsat"),
    SourceSpec("IND", "India", countries=("IN",)),
    SourceSpec("INDO", "Indonesia", countries=("ID",)),
    SourceSpec("IRAN", "Iran", countries=("IR",)),
    SourceSpec("IRAQ", "Iraq", countries=("IQ",)),
    SourceSpec("IRID", "Iridium", operator="Iridium"),
    SourceSpec("IRL", "Ireland", countries=("IE",)),
    SourceSpec("ISRA", "Israel", countries=("IL",)),
    SourceSpec(
        "ISRO", "Indian Space Research Organisation", countries=("IN",), operator="ISRO"
    ),
    SourceSpec("ISS", "International Space Station"),
    SourceSpec("IT", "Italy", countries=("IT",)),
    SourceSpec("ITSO", "Intelsat", operator="Intelsat"),
    SourceSpec("JOR", "Jordan", countries=("JO",)),
    SourceSpec("JPN", "Japan", countries=("JP",)),
    SourceSpec("KAZ", "Kazakhstan", countries=("KZ",)),
    SourceSpec("KEN", "Kenya", countries=("KE",)),
    SourceSpec("KWT", "Kuwait", countries=("KW",)),
    SourceSpec("LAOS", "Laos", countries=("LA",)),
    SourceSpec("LKA", "Sri Lanka", countries=("LK",)),
    SourceSpec("LTU", "Lithuania", countries=("LT",)),
    SourceSpec("LUXE", "Luxembourg", countries=("LU",)),
    SourceSpec("MA", "Morocco", countries=("MA",)),
    SourceSpec("MALA", "Malaysia", countries=("MY",)),
    SourceSpec("MCO", "Monaco", countries=("MC",)),
    SourceSpec("MDA", "Moldova", countries=("MD",)),
    SourceSpec("MEX", "Mexico", countries=("MX",)),
    SourceSpec("MMR", "Myanmar", countries=("MM",)),
    SourceSpec("MNE", "Montenegro", countries=("ME",)),
    SourceSpec("MNG", "Mongolia", countries=("MN",)),
    SourceSpec("MUS", "Mauritius", countries=("MU",)),
    SourceSpec("NATO", "North Atlantic Treaty Organization", operator="NATO"),
    SourceSpec("NETH", "Netherlands", countries=("NL",)),
    SourceSpec("NICO", "New ICO", operator="ICO Global Communications"),
    SourceSpec("NIG", "Nigeria", countries=("NG",)),
    SourceSpec("NKOR", "North Korea", countries=("KP",)),
    SourceSpec("NOR", "Norway", countries=("NO",)),
    SourceSpec("NPL", "Nepal", countries=("NP",)),
    SourceSpec("NZ", "New Zealand", countries=("NZ",)),
    SourceSpec("O3B", "O3b Networks", operator="O3b Networks"),
    SourceSpec("ORB", "ORBCOMM", operator="Orbcomm"),
    SourceSpec("PAKI", "Pakistan", countries=("PK",)),
    SourceSpec("PERU", "Peru", countries=("PE",)),
    SourceSpec("POL", "Poland", countries=("PL",)),
    SourceSpec("POR", "Portugal", countries=("PT",)),
    SourceSpec("PRC", "People's Republic of China", countries=("CN",)),
    SourceSpec("PRY", "Paraguay", countries=("PY",)),
    SourceSpec("PRES", "People's Republic of China / ESA"),
    SourceSpec("QAT", "Qatar", countries=("QA",)),
    SourceSpec("RASC", "RascomStar-QAF", operator="RascomStar-QAF"),
    SourceSpec("ROC", "Taiwan", countries=("TW",)),
    SourceSpec("ROM", "Romania", countries=("RO",)),
    SourceSpec("RP", "Philippines", countries=("PH",)),
    SourceSpec("RWA", "Rwanda", countries=("RW",)),
    SourceSpec("SAFR", "South Africa", countries=("ZA",)),
    SourceSpec("SAUD", "Saudi Arabia", countries=("SA",)),
    SourceSpec("SDN", "Sudan", countries=("SD",)),
    SourceSpec("SEAL", "Sea Launch", operator="Sea Launch"),
    SourceSpec("SEN", "Senegal", countries=("SN",)),
    SourceSpec("SES", "SES", operator="SES"),
    SourceSpec("SGJP", "Singapore-Japan", countries=("SG", "JP")),
    SourceSpec("SING", "Singapore", countries=("SG",)),
    SourceSpec("SKOR", "South Korea", countries=("KR",)),
    SourceSpec("SLB", "Solomon Islands", countries=("SB",)),
    SourceSpec("SPN", "Spain", countries=("ES",)),
    SourceSpec("STCT", "Singapore-Taiwan", countries=("SG", "TW")),
    SourceSpec("SVK", "Slovakia", countries=("SK",)),
    SourceSpec("SVN", "Slovenia", countries=("SI",)),
    SourceSpec("SWED", "Sweden", countries=("SE",)),
    SourceSpec("SWTZ", "Switzerland", countries=("CH",)),
    SourceSpec("TBD", "To Be Determined"),
    SourceSpec("THAI", "Thailand", countries=("TH",)),
    SourceSpec("TMMC", "Turkmenistan-Monaco", countries=("TM", "MC")),
    SourceSpec("TUN", "Tunisia", countries=("TN",)),
    SourceSpec("TURK", "Türkiye", countries=("TR",)),
    SourceSpec("UAE", "United Arab Emirates", countries=("AE",)),
    SourceSpec("UGA", "Uganda", countries=("UG",)),
    SourceSpec("UK", "United Kingdom", countries=("GB",)),
    SourceSpec("UKR", "Ukraine", countries=("UA",)),
    SourceSpec("UNK", "Unknown"),
    SourceSpec("URY", "Uruguay", countries=("UY",)),
    SourceSpec("US", "United States", countries=("US",)),
    SourceSpec("USBZ", "United States-Brazil", countries=("US", "BR")),
    SourceSpec("VAT", "Vatican City", countries=("VA",)),
    SourceSpec("VENZ", "Venezuela", countries=("VE",)),
    SourceSpec("VTNM", "Vietnam", countries=("VN",)),
    SourceSpec("ZWE", "Zimbabwe", countries=("ZW",)),
)

SOURCE_CODES: frozenset[str] = frozenset(o.code for o in SOURCES)
SOURCE_BY_CODE: dict[str, SourceSpec] = {o.code: o for o in SOURCES}


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


def parse_source(code: str | None) -> str | None:
    """Validate a CelesTrak SATCAT SOURCE code and return it unchanged."""
    if code is None or code == "":
        return None
    if code not in SOURCE_CODES:
        raise ValueError(f"Unknown SATCAT SOURCE code: {code!r}")
    return code


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
