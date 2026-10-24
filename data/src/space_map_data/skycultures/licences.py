"""The licence of a sky culture, and the distribution tier it allows.

The tiers are those of the texture manifests (docs/export-format/textures.md):
`open` when anyone may serve the data, `non-commercial` when the terms forbid
commercial use. A culture that states no licence is `non-commercial`. As in
the catalogue manifests, `undecided` marks a statement that this module cannot
read. It is cleared for no export.

A culture can give one licence for its text and data and another for its
illustrations, so each of the two has its own tier.

Flags mark what the tiers do not hold:
- `no-derivatives`: a CC ND licence. Only an unchanged copy may be served.
- `non-commercial`: a CC NC licence or a Traditional Knowledge NC label.
- `tk-labels`: Traditional Knowledge labels add terms to the licence.
- `no-licence`: the culture states no licence, so it is non-commercial.
- `unknown-licence`: a statement that this module cannot read.
"""

import re
from dataclasses import dataclass, field

OPEN, NON_COMMERCIAL, UNDECIDED = "open", "non-commercial", "undecided"
ALL, DATA, ILLUSTRATIONS = "all", "data", "illustrations"
NO_DERIVATIVES, NC, TK_LABELS, NO_LICENCE, UNKNOWN_LICENCE = (
    "no-derivatives",
    "non-commercial",
    "tk-labels",
    "no-licence",
    "unknown-licence",
)

_SECTION = re.compile(
    r"^##[ \t]*Licen[cs]es?[ \t]*\n(.*?)(?=^##[ \t]|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
_CC = re.compile(r"\bCC[ -]?(0|BY(?:-(?:NC|SA|ND))*)(?:\s+(\d\.\d))?", re.IGNORECASE)
_GPL = re.compile(r"\bGNU\s+GPL\s*v?(\d(?:\.\d)?)", re.IGNORECASE)
_FREE_ART = re.compile(r"\bFree Art Licen[cs]e(?:\s+(\d\.\d))?", re.IGNORECASE)
_TK = re.compile(r"\bTK (?:Labels?|[A-Z][a-z]+)\b|Traditional Knowledge Labels?")
_TK_NC = re.compile(r"\bTK Non-Commercial\b|\(TK NC\)")


@dataclass(frozen=True)
class Part:
    # ALL, DATA or ILLUSTRATIONS.
    applies_to: str
    licence: str


@dataclass(frozen=True)
class Licence:
    # The statement as published.
    text: str
    parts: tuple[Part, ...]
    data: str
    illustrations: str
    flags: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "parts": [
                {"applies_to": p.applies_to, "licence": p.licence} for p in self.parts
            ],
            "distribution": self.data,
            "illustrations_distribution": self.illustrations,
            "flags": list(self.flags),
        }


def licence_section(markdown: str) -> str | None:
    """The text under the `## License` heading of a description, or None."""
    found = _SECTION.search(markdown)
    return found[1].strip() if found else None


def normalise(text: str) -> str | None:
    """The first licence that `text` names, in a fixed spelling, or None."""
    if cc := _CC.search(text):
        name = "CC0" if cc[1] == "0" else f"CC {cc[1].upper()}"
        return f"{name} {cc[2]}" if cc[2] else name
    if gpl := _GPL.search(text):
        return f"GPL-{gpl[1] if '.' in gpl[1] else gpl[1] + '.0'}"
    if art := _FREE_ART.search(text):
        return f"Free Art License {art[1]}" if art[1] else "Free Art License"
    return None


def tier(licence: str) -> str:
    return NON_COMMERCIAL if "-NC" in licence else OPEN


def _applies_to(label: str) -> str:
    label = label.lower()
    if "illustration" in label or "artwork" in label:
        return ILLUSTRATIONS
    if "data" in label or "text" in label or "sky culture" in label:
        return DATA
    return ALL


def parse_parts(text: str) -> tuple[Part, ...]:
    """The licences of a statement, one per line that names one.

    The lines after a sub-heading are notes on the licence, not parts of it.
    """
    parts = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            break
        licence = normalise(line)
        if licence is None:
            continue
        label = line.split(":", 1)[0] if ":" in line else ""
        parts.append(Part(_applies_to(label), licence))
    return tuple(parts)


def _part_tier(parts: tuple[Part, ...], applies_to: str) -> str | None:
    tiers = {tier(p.licence) for p in parts if p.applies_to in (ALL, applies_to)}
    if not tiers:
        return None
    return NON_COMMERCIAL if NON_COMMERCIAL in tiers else OPEN


def read_licence(text: str | None) -> Licence:
    """The licence of a culture from its statement; None is no statement."""
    statement = (text or "").strip()
    parts = parse_parts(statement)
    flags = []
    if not statement:
        flags.append(NO_LICENCE)
    elif not parts:
        flags.append(UNKNOWN_LICENCE)
    if any("-ND" in p.licence for p in parts):
        flags.append(NO_DERIVATIVES)
    tk_nc = bool(_TK_NC.search(statement))
    if any("-NC" in p.licence for p in parts) or tk_nc:
        flags.append(NC)
    if _TK.search(statement):
        flags.append(TK_LABELS)
    no_parts = NON_COMMERCIAL if not statement else UNDECIDED
    data = _part_tier(parts, DATA) or no_parts
    illustrations = _part_tier(parts, ILLUSTRATIONS) or data
    # A TK NC label covers the whole culture, whatever its CC licence.
    if tk_nc and data != UNDECIDED:
        data = illustrations = NON_COMMERCIAL
    return Licence(statement, parts, data, illustrations, tuple(flags))
