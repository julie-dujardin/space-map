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
class Owner(StrEnum):
    ARAB_SATELLITE_COMMUNICATIONS = "arab_satellite_communications"
    ASIA_BROADCAST_SATELLITE = "asia_broadcast_satellite"
    ASIASAT = "asiasat"
    ALGERIA = "algeria"
    ANGOLA = "angola"
    ARGENTINA = "argentina"
    ARMENIA = "armenia"
    AUSTRIA = "austria"
    AUSTRALIA = "australia"
    AZERBAIJAN = "azerbaijan"
    BELGIUM = "belgium"
    BELARUS = "belarus"
    BERMUDA = "bermuda"
    BANGLADESH = "bangladesh"
    BAHRAIN = "bahrain"
    BHUTAN = "bhutan"
    BOLIVIA = "bolivia"
    BRAZIL = "brazil"
    BULGARIA = "bulgaria"
    BOTSWANA = "botswana"
    CANADA = "canada"
    CHINA_BRAZIL = "china_brazil"
    CHINA_TURKIYE = "china_turkiye"
    CHILE = "chile"
    COMMONWEALTH_OF_INDEPENDENT_STATES = "commonwealth_of_independent_states"
    COLOMBIA = "colombia"
    COSTA_RICA = "costa_rica"
    CZECH_REPUBLIC = "czech_republic"
    DENMARK = "denmark"
    DJIBOUTI = "djibouti"
    ECUADOR = "ecuador"
    EGYPT = "egypt"
    EUROPEAN_SPACE_AGENCY = "european_space_agency"
    EUROPEAN_SPACE_RESEARCH_ORGANIZATION = "european_space_research_organization"
    ESTONIA = "estonia"
    ETHIOPIA = "ethiopia"
    EUMETSAT = "eumetsat"
    EUTELSAT = "eutelsat"
    FRANCE_GERMANY = "france_germany"
    FINLAND = "finland"
    FRANCE = "france"
    FRANCE_ITALY = "france_italy"
    GERMANY = "germany"
    GHANA = "ghana"
    GLOBALSTAR = "globalstar"
    GREECE = "greece"
    GREECE_SAUDI_ARABIA = "greece_saudi_arabia"
    GUATEMALA = "guatemala"
    CROATIA = "croatia"
    HUNGARY = "hungary"
    INMARSAT = "inmarsat"
    INDIA = "india"
    INDONESIA = "indonesia"
    IRAN = "iran"
    IRAQ = "iraq"
    IRIDIUM = "iridium"
    IRELAND = "ireland"
    ISRAEL = "israel"
    ISRO = "isro"
    INTERNATIONAL_SPACE_STATION = "international_space_station"
    ITALY = "italy"
    INTELSAT = "intelsat"
    JORDAN = "jordan"
    JAPAN = "japan"
    KAZAKHSTAN = "kazakhstan"
    KENYA = "kenya"
    KUWAIT = "kuwait"
    LAOS = "laos"
    SRI_LANKA = "sri_lanka"
    LITHUANIA = "lithuania"
    LUXEMBOURG = "luxembourg"
    MOROCCO = "morocco"
    MALAYSIA = "malaysia"
    MONACO = "monaco"
    MOLDOVA = "moldova"
    MEXICO = "mexico"
    MYANMAR = "myanmar"
    MONTENEGRO = "montenegro"
    MONGOLIA = "mongolia"
    MAURITIUS = "mauritius"
    NATO = "nato"
    NETHERLANDS = "netherlands"
    NEW_ICO = "new_ico"
    NIGERIA = "nigeria"
    NORTH_KOREA = "north_korea"
    NORWAY = "norway"
    NEPAL = "nepal"
    NEW_ZEALAND = "new_zealand"
    O3B_NETWORKS = "o3b_networks"
    ORBCOMM = "orbcomm"
    PAKISTAN = "pakistan"
    PERU = "peru"
    POLAND = "poland"
    PORTUGAL = "portugal"
    CHINA = "china"
    PARAGUAY = "paraguay"
    CHINA_ESA = "china_esa"
    QATAR = "qatar"
    RASCOMSTAR_QAF = "rascomstar_qaf"
    TAIWAN = "taiwan"
    ROMANIA = "romania"
    PHILIPPINES = "philippines"
    RWANDA = "rwanda"
    SOUTH_AFRICA = "south_africa"
    SAUDI_ARABIA = "saudi_arabia"
    SUDAN = "sudan"
    SEA_LAUNCH = "sea_launch"
    SENEGAL = "senegal"
    SES = "ses"
    SINGAPORE_JAPAN = "singapore_japan"
    SINGAPORE = "singapore"
    SOUTH_KOREA = "south_korea"
    SOLOMON_ISLANDS = "solomon_islands"
    SPAIN = "spain"
    SINGAPORE_TAIWAN = "singapore_taiwan"
    SLOVAKIA = "slovakia"
    SLOVENIA = "slovenia"
    SWEDEN = "sweden"
    SWITZERLAND = "switzerland"
    TBD = "tbd"
    THAILAND = "thailand"
    TURKMENISTAN_MONACO = "turkmenistan_monaco"
    TUNISIA = "tunisia"
    TURKIYE = "turkiye"
    UNITED_ARAB_EMIRATES = "united_arab_emirates"
    UGANDA = "uganda"
    UNITED_KINGDOM = "united_kingdom"
    UKRAINE = "ukraine"
    UNKNOWN = "unknown"
    URUGUAY = "uruguay"
    UNITED_STATES = "united_states"
    UNITED_STATES_BRAZIL = "united_states_brazil"
    VATICAN = "vatican"
    VENEZUELA = "venezuela"
    VIETNAM = "vietnam"
    ZIMBABWE = "zimbabwe"


OWNER_CODES: dict[str, Owner] = {
    "AB": Owner.ARAB_SATELLITE_COMMUNICATIONS,
    "ABS": Owner.ASIA_BROADCAST_SATELLITE,
    "AC": Owner.ASIASAT,
    "ALG": Owner.ALGERIA,
    "ANG": Owner.ANGOLA,
    "ARGN": Owner.ARGENTINA,
    "ARM": Owner.ARMENIA,
    "ASRA": Owner.AUSTRIA,
    "AUS": Owner.AUSTRALIA,
    "AZER": Owner.AZERBAIJAN,
    "BEL": Owner.BELGIUM,
    "BELA": Owner.BELARUS,
    "BERM": Owner.BERMUDA,
    "BGD": Owner.BANGLADESH,
    "BHR": Owner.BAHRAIN,
    "BHUT": Owner.BHUTAN,
    "BOL": Owner.BOLIVIA,
    "BRAZ": Owner.BRAZIL,
    "BUL": Owner.BULGARIA,
    "BWA": Owner.BOTSWANA,
    "CA": Owner.CANADA,
    "CHBZ": Owner.CHINA_BRAZIL,
    "CHTU": Owner.CHINA_TURKIYE,
    "CHLE": Owner.CHILE,
    "CIS": Owner.COMMONWEALTH_OF_INDEPENDENT_STATES,
    "COL": Owner.COLOMBIA,
    "CRI": Owner.COSTA_RICA,
    "CZCH": Owner.CZECH_REPUBLIC,
    "DEN": Owner.DENMARK,
    "DJI": Owner.DJIBOUTI,
    "ECU": Owner.ECUADOR,
    "EGYP": Owner.EGYPT,
    "ESA": Owner.EUROPEAN_SPACE_AGENCY,
    "ESRO": Owner.EUROPEAN_SPACE_RESEARCH_ORGANIZATION,
    "EST": Owner.ESTONIA,
    "ETH": Owner.ETHIOPIA,
    "EUME": Owner.EUMETSAT,
    "EUTE": Owner.EUTELSAT,
    "FGER": Owner.FRANCE_GERMANY,
    "FIN": Owner.FINLAND,
    "FR": Owner.FRANCE,
    "FRIT": Owner.FRANCE_ITALY,
    "GER": Owner.GERMANY,
    "GHA": Owner.GHANA,
    "GLOB": Owner.GLOBALSTAR,
    "GREC": Owner.GREECE,
    "GRSA": Owner.GREECE_SAUDI_ARABIA,
    "GUAT": Owner.GUATEMALA,
    "HRV": Owner.CROATIA,
    "HUN": Owner.HUNGARY,
    "IM": Owner.INMARSAT,
    "IND": Owner.INDIA,
    "INDO": Owner.INDONESIA,
    "IRAN": Owner.IRAN,
    "IRAQ": Owner.IRAQ,
    "IRID": Owner.IRIDIUM,
    "IRL": Owner.IRELAND,
    "ISRA": Owner.ISRAEL,
    "ISRO": Owner.ISRO,
    "ISS": Owner.INTERNATIONAL_SPACE_STATION,
    "IT": Owner.ITALY,
    "ITSO": Owner.INTELSAT,
    "JOR": Owner.JORDAN,
    "JPN": Owner.JAPAN,
    "KAZ": Owner.KAZAKHSTAN,
    "KEN": Owner.KENYA,
    "KWT": Owner.KUWAIT,
    "LAOS": Owner.LAOS,
    "LKA": Owner.SRI_LANKA,
    "LTU": Owner.LITHUANIA,
    "LUXE": Owner.LUXEMBOURG,
    "MA": Owner.MOROCCO,
    "MALA": Owner.MALAYSIA,
    "MCO": Owner.MONACO,
    "MDA": Owner.MOLDOVA,
    "MEX": Owner.MEXICO,
    "MMR": Owner.MYANMAR,
    "MNE": Owner.MONTENEGRO,
    "MNG": Owner.MONGOLIA,
    "MUS": Owner.MAURITIUS,
    "NATO": Owner.NATO,
    "NETH": Owner.NETHERLANDS,
    "NICO": Owner.NEW_ICO,
    "NIG": Owner.NIGERIA,
    "NKOR": Owner.NORTH_KOREA,
    "NOR": Owner.NORWAY,
    "NPL": Owner.NEPAL,
    "NZ": Owner.NEW_ZEALAND,
    "O3B": Owner.O3B_NETWORKS,
    "ORB": Owner.ORBCOMM,
    "PAKI": Owner.PAKISTAN,
    "PERU": Owner.PERU,
    "POL": Owner.POLAND,
    "POR": Owner.PORTUGAL,
    "PRC": Owner.CHINA,
    "PRY": Owner.PARAGUAY,
    "PRES": Owner.CHINA_ESA,
    "QAT": Owner.QATAR,
    "RASC": Owner.RASCOMSTAR_QAF,
    "ROC": Owner.TAIWAN,
    "ROM": Owner.ROMANIA,
    "RP": Owner.PHILIPPINES,
    "RWA": Owner.RWANDA,
    "SAFR": Owner.SOUTH_AFRICA,
    "SAUD": Owner.SAUDI_ARABIA,
    "SDN": Owner.SUDAN,
    "SEAL": Owner.SEA_LAUNCH,
    "SEN": Owner.SENEGAL,
    "SES": Owner.SES,
    "SGJP": Owner.SINGAPORE_JAPAN,
    "SING": Owner.SINGAPORE,
    "SKOR": Owner.SOUTH_KOREA,
    "SLB": Owner.SOLOMON_ISLANDS,
    "SPN": Owner.SPAIN,
    "STCT": Owner.SINGAPORE_TAIWAN,
    "SVK": Owner.SLOVAKIA,
    "SVN": Owner.SLOVENIA,
    "SWED": Owner.SWEDEN,
    "SWTZ": Owner.SWITZERLAND,
    "TBD": Owner.TBD,
    "THAI": Owner.THAILAND,
    "TMMC": Owner.TURKMENISTAN_MONACO,
    "TUN": Owner.TUNISIA,
    "TURK": Owner.TURKIYE,
    "UAE": Owner.UNITED_ARAB_EMIRATES,
    "UGA": Owner.UGANDA,
    "UK": Owner.UNITED_KINGDOM,
    "UKR": Owner.UKRAINE,
    "UNK": Owner.UNKNOWN,
    "URY": Owner.URUGUAY,
    "US": Owner.UNITED_STATES,
    "USBZ": Owner.UNITED_STATES_BRAZIL,
    "VAT": Owner.VATICAN,
    "VENZ": Owner.VENEZUELA,
    "VTNM": Owner.VIETNAM,
    "ZWE": Owner.ZIMBABWE,
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


def parse_owner(code: str | None) -> Owner | None:
    return _lookup(OWNER_CODES, code, "OWNER")


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
