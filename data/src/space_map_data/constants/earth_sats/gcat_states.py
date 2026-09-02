"""GCAT state codes → the countries this project shows.

GCAT files every object under the state that registered it *at the time*, so a
1975 launch is Soviet and a 1995 one Russian — a distinction CelesTrak's single
``CIS`` owner code cannot make, and the reason this replaces the owner pivot.
Codes are mostly ISO 3166-1 alpha-2 already; only the ones GCAT spells its own
way, the two dissolved states, and the intergovernmental organisations need
saying here.

Organisation codes (``I-``) have no country of their own. They keep the country
this project already attributed them to, because a satellite page with no
country reads as missing data rather than as a statement about registration.
"""

from space_map_data.constants.countries import COUNTRY_BY_CODE

# GCAT state code → ISO alpha-2, for the codes that differ. Anything else is
# used as-is when countries.py knows it.
_ALIASES: dict[str, tuple[str, ...]] = {
    "B": ("BE",),
    "BGN": ("BG",),
    "CSFR": ("CS",),
    "CSSR": ("CS",),
    "CYM": ("KY",),
    "D": ("DE",),
    "E": ("ES",),
    "ESIB": ("ES",),  # Islas Baleares
    "F": ("FR",),
    "HKUK": ("HK",),  # Hong Kong before the 1997 handover
    "I": ("IT",),
    "J": ("JP",),
    "L": ("LU",),
    "MYM": ("MM",),
    "N": ("NO",),
    "P": ("PT",),
    "S": ("SE",),
    "T": ("TH",),
    "UAE": ("AE",),
    "UK": ("GB",),
    # Intergovernmental organisations, mirroring the owner-code table they
    # replace: European bodies read as EU, the rest as their seat or members.
    "I-ARAB": ("SA", "KW", "LY", "QA"),
    "I-ESA": ("EU",),
    "I-ESRO": ("EU",),
    "I-EU": ("EU",),
    "I-EUM": ("EU",),
    "I-EUT": ("FR",),  # Eutelsat, a French company since 2001
    "I-INM": ("GB",),  # Inmarsat, London
    "I-INT": ("LU", "US"),  # Intelsat
    "I-NATO": ("US",),
}


def countries_for_state(state: str | None) -> tuple[str, ...]:
    """Country codes for a GCAT state code, empty when it maps to none."""
    if not state or state == "-":
        return ()
    aliased = _ALIASES.get(state)
    if aliased is not None:
        return aliased
    return (state,) if state in COUNTRY_BY_CODE else ()
