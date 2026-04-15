"""Typed enums for CelesTrak SATCAT lunch sites.

Source: https://celestrak.org/satcat/launchsites.php
"""

from dataclasses import dataclass


# https://celestrak.org/satcat/sources.php
@dataclass(frozen=True)
class SourceSpec:
    code: str  # SATCAT short code (primary key)
    name: str  # CelesTrak sources.php description
    countries: tuple[str, ...] = ()  # ISO 3166-1 alpha-2 codes


# Operator metadata (name + Wikidata QID, keyed by source code) lives in
# operators.py — query OPERATOR_BY_SOURCE for the structured operator linked to
# any of the non-country source codes below.
# https://en.wikipedia.org/wiki/List_of_ISO_3166_country_codes
SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec("AB", "Arab Satellite Communications Organization", countries=("SA", "KW", "LY", "QA")),  # HQ in Riyadh
    SourceSpec("ABS", "Asia Broadcast Satellite / Agility Beyond Space", countries=("AE",)),  # HQ in dubai
    SourceSpec("AC", "AsiaSat", countries=("HK",)),  # Hong kong company
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
    SourceSpec("CIS", "Commonwealth of Independent States (USSR)", countries=("SU",)),
    SourceSpec("COL", "Colombia", countries=("CO",)),
    SourceSpec("CRI", "Costa Rica", countries=("CR",)),
    SourceSpec("CZCH", "Czech Republic", countries=("CZ",)),
    SourceSpec("DEN", "Denmark", countries=("DK",)),
    SourceSpec("DJI", "Djibouti", countries=("DJ",)),
    SourceSpec("ECU", "Ecuador", countries=("EC",)),
    SourceSpec("EGYP", "Egypt", countries=("EG",)),
    SourceSpec("ESA", "European Space Agency", countries=("EU",)),  # European agency
    SourceSpec("ESRO", "European Space Research Organization", countries=("EU",)),  # European agency
    SourceSpec("EST", "Estonia", countries=("EE",)),
    SourceSpec("ETH", "Ethiopia", countries=("ET",)),
    SourceSpec("EUME", "EUMETSAT", countries=("EU",)),  # European agency
    SourceSpec("EUTE", "EUTELSAT", countries=("FR",)),  # French company
    SourceSpec("FGER", "France-Germany", countries=("FR", "DE")),
    SourceSpec("FIN", "Finland", countries=("FI",)),
    SourceSpec("FR", "France", countries=("FR",)),
    SourceSpec("FRIT", "France-Italy", countries=("FR", "IT")),
    SourceSpec("GER", "Germany", countries=("DE",)),
    SourceSpec("GHA", "Ghana", countries=("GH",)),
    SourceSpec("GLOB", "Globalstar", countries=("US",)),
    SourceSpec("GREC", "Greece", countries=("GR",)),
    SourceSpec("GRSA", "Greece-Saudi Arabia", countries=("GR", "SA")),
    SourceSpec("GUAT", "Guatemala", countries=("GT",)),
    SourceSpec("HRV", "Croatia", countries=("HR",)),
    SourceSpec("HUN", "Hungary", countries=("HU",)),
    SourceSpec("IM", "Inmarsat", countries=("GB",)),
    SourceSpec("IND", "India", countries=("IN",)),
    SourceSpec("INDO", "Indonesia", countries=("ID",)),
    SourceSpec("IRAN", "Iran", countries=("IR",)),
    SourceSpec("IRAQ", "Iraq", countries=("IQ",)),
    SourceSpec("IRID", "Iridium", countries=("US",)),  # not present in data, use prefix
    SourceSpec("IRL", "Ireland", countries=("IE",)),
    SourceSpec("ISRA", "Israel", countries=("IL",)),
    SourceSpec("ISRO", "Indian Space Research Organisation", countries=("IN",)),
    SourceSpec("ISS", "International Space Station"),
    SourceSpec("IT", "Italy", countries=("IT",)),
    SourceSpec("ITSO", "Intelsat", countries=("LU", "US")),
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
    SourceSpec("NATO", "North Atlantic Treaty Organization", countries=("US",)),
    SourceSpec("NETH", "Netherlands", countries=("NL",)),
    SourceSpec("NICO", "New ICO / Pendrell Corporation", countries=("US",)),
    SourceSpec("NIG", "Nigeria", countries=("NG",)),
    SourceSpec("NKOR", "North Korea", countries=("KP",)),
    SourceSpec("NOR", "Norway", countries=("NO",)),
    SourceSpec("NPL", "Nepal", countries=("NP",)),
    SourceSpec("NZ", "New Zealand", countries=("NZ",)),
    SourceSpec("O3B", "O3b Networks", countries=("US",)),
    SourceSpec("ORB", "ORBCOMM", countries=("US",)),
    SourceSpec("PAKI", "Pakistan", countries=("PK",)),
    SourceSpec("PERU", "Peru", countries=("PE",)),
    SourceSpec("POL", "Poland", countries=("PL",)),
    SourceSpec("POR", "Portugal", countries=("PT",)),
    SourceSpec("PRC", "People's Republic of China", countries=("CN",)),
    SourceSpec("PRY", "Paraguay", countries=("PY",)),
    SourceSpec("PRES", "People's Republic of China / ESA", countries=("CN", "EU")),
    SourceSpec("QAT", "Qatar", countries=("QA",)),
    SourceSpec("RASC", "RascomStar-QAF"),  # Africa, see https://rascom.org/member-states/
    SourceSpec("ROC", "Taiwan", countries=("TW",)),
    SourceSpec("ROM", "Romania", countries=("RO",)),
    SourceSpec("RP", "Philippines", countries=("PH",)),
    SourceSpec("RWA", "Rwanda", countries=("RW",)),
    SourceSpec("SAFR", "South Africa", countries=("ZA",)),
    SourceSpec("SAUD", "Saudi Arabia", countries=("SA",)),
    SourceSpec("SDN", "Sudan", countries=("SD",)),
    SourceSpec("SEAL", "Sea Launch", countries=("NO", "RU", "UA", "US")),
    SourceSpec("SEN", "Senegal", countries=("SN",)),
    SourceSpec("SES", "SES", countries=("LU",)),
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


def parse_source(code: str | None) -> str | None:
    """Validate a CelesTrak SATCAT SOURCE code and return it unchanged."""
    if code is None or code == "":
        return None
    if code not in SOURCE_CODES:
        raise ValueError(f"Unknown SATCAT SOURCE code: {code!r}")
    return code
