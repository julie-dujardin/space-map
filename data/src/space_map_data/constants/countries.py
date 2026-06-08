"""ISO 3166-1 alpha-2 country codes mapped to Wikidata entities.

Covers every code referenced from ``earth_sats/sources.py`` (SATCAT OWNER →
countries pivot) plus the ``EU`` pseudo-code used for European
intergovernmental sources. QIDs sourced from Wikidata property P297 except
``EU`` (which has no ISO 3166-1 code — Q458 is the canonical European Union
entity).

Note: ``NL`` maps to Q29999 (Kingdom of the Netherlands), not Q55
(Netherlands constituent country), because Wikidata's P297 attaches the ISO
code to the sovereign-state level.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CountrySpec:
    code: str  # ISO 3166-1 alpha-2 (primary key); ``EU`` is a non-ISO pseudo-code
    slug: str  # URL slug used for the country group page
    wikidata_qid: str


COUNTRIES: tuple[CountrySpec, ...] = (
    CountrySpec("AE", "ae", "Q878"),  # United Arab Emirates
    CountrySpec("AM", "am", "Q399"),  # Armenia
    CountrySpec("AO", "ao", "Q916"),  # Angola
    CountrySpec("AR", "ar", "Q414"),  # Argentina
    CountrySpec("AT", "at", "Q40"),  # Austria
    CountrySpec("AU", "au", "Q408"),  # Australia
    CountrySpec("AZ", "az", "Q227"),  # Azerbaijan
    CountrySpec("BD", "bd", "Q902"),  # Bangladesh
    CountrySpec("BE", "be", "Q31"),  # Belgium
    CountrySpec("BG", "bg", "Q219"),  # Bulgaria
    CountrySpec("BH", "bh", "Q398"),  # Bahrain
    CountrySpec("BM", "bm", "Q23635"),  # Bermuda
    CountrySpec("BO", "bo", "Q750"),  # Bolivia
    CountrySpec("BR", "br", "Q155"),  # Brazil
    CountrySpec("BT", "bt", "Q917"),  # Bhutan
    CountrySpec("BW", "bw", "Q963"),  # Botswana
    CountrySpec("BY", "by", "Q184"),  # Belarus
    CountrySpec("CA", "ca", "Q16"),  # Canada
    CountrySpec("CH", "ch", "Q39"),  # Switzerland
    CountrySpec("CL", "cl", "Q298"),  # Chile
    CountrySpec("CN", "cn", "Q148"),  # China (PRC)
    CountrySpec("CO", "co", "Q739"),  # Colombia
    CountrySpec("CR", "cr", "Q800"),  # Costa Rica
    CountrySpec("CZ", "cz", "Q213"),  # Czech Republic
    CountrySpec("DE", "de", "Q183"),  # Germany
    CountrySpec("DJ", "dj", "Q977"),  # Djibouti
    CountrySpec("DK", "dk", "Q35"),  # Denmark
    CountrySpec("DZ", "dz", "Q262"),  # Algeria
    CountrySpec("EC", "ec", "Q736"),  # Ecuador
    CountrySpec("EE", "ee", "Q191"),  # Estonia
    CountrySpec("EG", "eg", "Q79"),  # Egypt
    CountrySpec("ES", "es", "Q29"),  # Spain
    CountrySpec("ET", "et", "Q115"),  # Ethiopia
    CountrySpec("EU", "eu", "Q458"),  # European Union (pseudo-code)
    CountrySpec("FI", "fi", "Q33"),  # Finland
    CountrySpec("FR", "fr", "Q142"),  # France
    CountrySpec("GB", "gb", "Q145"),  # United Kingdom
    CountrySpec("GH", "gh", "Q117"),  # Ghana
    CountrySpec("GR", "gr", "Q41"),  # Greece
    CountrySpec("GT", "gt", "Q774"),  # Guatemala
    CountrySpec("HK", "hk", "Q8646"),  # Hong Kong
    CountrySpec("HR", "hr", "Q224"),  # Croatia
    CountrySpec("HU", "hu", "Q28"),  # Hungary
    CountrySpec("ID", "id", "Q252"),  # Indonesia
    CountrySpec("IE", "ie", "Q27"),  # Ireland
    CountrySpec("IL", "il", "Q801"),  # Israel
    CountrySpec("IN", "in", "Q668"),  # India
    CountrySpec("IQ", "iq", "Q796"),  # Iraq
    CountrySpec("IR", "ir", "Q794"),  # Iran
    CountrySpec("IT", "it", "Q38"),  # Italy
    CountrySpec("JO", "jo", "Q810"),  # Jordan
    CountrySpec("JP", "jp", "Q17"),  # Japan
    CountrySpec("KE", "ke", "Q114"),  # Kenya
    CountrySpec("KP", "kp", "Q423"),  # North Korea / DPRK
    CountrySpec("KR", "kr", "Q884"),  # South Korea
    CountrySpec("KW", "kw", "Q817"),  # Kuwait
    CountrySpec("KZ", "kz", "Q232"),  # Kazakhstan
    CountrySpec("LA", "la", "Q819"),  # Laos
    CountrySpec("LK", "lk", "Q854"),  # Sri Lanka
    CountrySpec("LT", "lt", "Q37"),  # Lithuania
    CountrySpec("LU", "lu", "Q32"),  # Luxembourg
    CountrySpec("LY", "ly", "Q1016"),  # Libya
    CountrySpec("MA", "ma", "Q1028"),  # Morocco
    CountrySpec("MC", "mc", "Q235"),  # Monaco
    CountrySpec("MD", "md", "Q217"),  # Moldova
    CountrySpec("ME", "me", "Q236"),  # Montenegro
    CountrySpec("MM", "mm", "Q836"),  # Myanmar
    CountrySpec("MN", "mn", "Q711"),  # Mongolia
    CountrySpec("MU", "mu", "Q1027"),  # Mauritius
    CountrySpec("MX", "mx", "Q96"),  # Mexico
    CountrySpec("MY", "my", "Q833"),  # Malaysia
    CountrySpec("NG", "ng", "Q1033"),  # Nigeria
    CountrySpec("NL", "nl", "Q29999"),  # Kingdom of the Netherlands
    CountrySpec("NO", "no", "Q20"),  # Norway
    CountrySpec("NP", "np", "Q837"),  # Nepal
    CountrySpec("NZ", "nz", "Q664"),  # New Zealand
    CountrySpec("PE", "pe", "Q419"),  # Peru
    CountrySpec("PH", "ph", "Q928"),  # Philippines
    CountrySpec("PK", "pk", "Q843"),  # Pakistan
    CountrySpec("PL", "pl", "Q36"),  # Poland
    CountrySpec("PT", "pt", "Q45"),  # Portugal
    CountrySpec("PY", "py", "Q733"),  # Paraguay
    CountrySpec("QA", "qa", "Q846"),  # Qatar
    CountrySpec("RO", "ro", "Q218"),  # Romania
    CountrySpec("RU", "ru", "Q159"),  # Russia
    CountrySpec("RW", "rw", "Q1037"),  # Rwanda
    CountrySpec("SA", "sa", "Q851"),  # Saudi Arabia
    CountrySpec("SB", "sb", "Q685"),  # Solomon Islands
    CountrySpec("SD", "sd", "Q1049"),  # Sudan
    CountrySpec("SE", "se", "Q34"),  # Sweden
    CountrySpec("SG", "sg", "Q334"),  # Singapore
    CountrySpec("SI", "si", "Q215"),  # Slovenia
    CountrySpec("SK", "sk", "Q214"),  # Slovakia
    CountrySpec("SN", "sn", "Q1041"),  # Senegal
    CountrySpec("TH", "th", "Q869"),  # Thailand
    CountrySpec("TM", "tm", "Q874"),  # Turkmenistan
    CountrySpec("TN", "tn", "Q948"),  # Tunisia
    CountrySpec("TR", "tr", "Q43"),  # Türkiye
    CountrySpec("TW", "tw", "Q865"),  # Taiwan
    CountrySpec("UA", "ua", "Q212"),  # Ukraine
    CountrySpec("UG", "ug", "Q1036"),  # Uganda
    CountrySpec("US", "us", "Q30"),  # United States of America
    CountrySpec("UY", "uy", "Q77"),  # Uruguay
    CountrySpec("VA", "va", "Q237"),  # Vatican City
    CountrySpec("VE", "ve", "Q717"),  # Venezuela
    CountrySpec("VN", "vn", "Q881"),  # Vietnam
    CountrySpec("ZA", "za", "Q258"),  # South Africa
    CountrySpec("ZW", "zw", "Q954"),  # Zimbabwe
)


COUNTRY_SLUG_PREFIX = "country-"

COUNTRY_BY_CODE: dict[str, CountrySpec] = {c.code: c for c in COUNTRIES}
COUNTRY_BY_SLUG: dict[str, CountrySpec] = {c.slug: c for c in COUNTRIES}
COUNTRY_BY_QID: dict[str, CountrySpec] = {c.wikidata_qid: c for c in COUNTRIES}

assert len(COUNTRY_BY_CODE) == len(COUNTRIES), "Duplicate country code"
assert len(COUNTRY_BY_SLUG) == len(COUNTRIES), "Duplicate country slug"
