"""Display forms for provisional satellite designations.

SPICE/NAIF writes them compressed (``S2019_S37``, ``S2020 S48``); the IAU form
is ``S/2019 S 37``. The compressed string stays the identifier — it's what
minor-planet moon QIDs are matched on — so this is display-only.
"""

import re

# S, year, the host's letter, the running number — in any of the separator
# spellings NAIF and the DB use between them.
_PROVISIONAL_RE = re.compile(r"^S[/ _]?(\d{4})[ _]?([A-Z])[ _]?(\d+)$")


def format_provisional_designation(value: str | None) -> str | None:
    """``S2019_S37`` → ``S/2019 S 37``. Anything that doesn't parse — notably
    minor-planet forms like ``S/2008 (524531) 1`` — is returned unchanged."""
    if not value:
        return None
    m = _PROVISIONAL_RE.match(value.strip())
    if not m:
        return value
    return f"S/{m.group(1)} {m.group(2)} {m.group(3)}"


# Every designation form carries the discovery year — `S/2019 S 37`,
# `S2019_S37`, `2023U1`, `S/2008 (524531) 1`. A name never does.
_YEAR_RE = re.compile(r"\d{4}")


def _alnum(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum()).upper()


def is_iau_named(name: str | None, provisional_designation: str | None) -> bool:
    """Whether a moon carries a real IAU name rather than a designation.

    The DB's ``name`` column holds a designation whenever there's no name yet
    (SPICE spells unnamed moons ``S2019_S37``), so a name counts only when it
    is neither absent nor a restatement of ``provisional_designation``. The
    year check catches the handful that carry a designation with no
    ``provisional_designation`` recorded to compare against.
    """
    if not name:
        return False
    if provisional_designation and _alnum(name) in (
        _alnum(provisional_designation),
        _alnum("S" + provisional_designation),
    ):
        return False
    return not _YEAR_RE.search(name)
