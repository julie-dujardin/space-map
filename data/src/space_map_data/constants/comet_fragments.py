"""Parsing of split-comet fragment designations.

SBDB encodes a fragment as ``<parent pdes>-<letters>`` (``73P-C``, ``73P-BB``,
``C/2019 Y4-A``); the prefix (P/C/D/X) lives in ``SBDB.prefix``, never in
``pdes``.

The comet-prefix guard matters: Palomar-Leiden / Trojan survey asteroids reuse
the same dash syntax (``6344 P-L``, ``3138 T-1``) with no comet prefix, and a
comet ``pdes`` never has a hyphen except to mark a fragment — so requiring the
prefix excludes the false positives unambiguously.
"""

import re
from typing import NamedTuple

from space_map_data.models.object.sbdb import CometPrefix

# Slug prefix for the synthetic group page of a parentless split-comet family
# (no intact body in the catalog, e.g. Shoemaker-Levy 9).
FAMILY_GROUP_SLUG_PREFIX = "comet-family-"

# Prefixes that denote a comet (and thus can fragment). A (asteroidal) and
# I (interstellar) are excluded.
COMET_PREFIXES: frozenset[CometPrefix] = frozenset(
    {CometPrefix.P, CometPrefix.C, CometPrefix.D, CometPrefix.X}
)

_FRAGMENT_RE = re.compile(r"^(?P<parent>.+)-(?P<suffix>[A-Z]+)$")


class FragmentDesignation(NamedTuple):
    """A fragment's parent designation and its fragment letters."""

    parent_pdes: str  # e.g. "73P", "C/2019 Y4"
    suffix: str  # e.g. "C", "BB"


def split_fragment(
    pdes: str | None, prefix: CometPrefix | None
) -> FragmentDesignation | None:
    """Return the parent designation + suffix if ``pdes`` names a comet fragment.

    ``None`` when the row isn't a comet or its designation has no fragment
    suffix.
    """
    if prefix not in COMET_PREFIXES or not pdes:
        return None
    match = _FRAGMENT_RE.match(pdes)
    if match is None:
        return None
    return FragmentDesignation(match["parent"], match["suffix"])


def family_group_slug(parent_pdes: str) -> str:
    """Stable ``/g/`` slug for a parentless family, e.g. ``1993 F2`` → ``comet-family-1993-f2``."""
    core = re.sub(r"[^a-z0-9]+", "-", parent_pdes.lower()).strip("-")
    return f"{FAMILY_GROUP_SLUG_PREFIX}{core}"
