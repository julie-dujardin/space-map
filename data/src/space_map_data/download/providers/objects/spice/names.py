"""Parse Horizons name table to enrich SPICE body names + IAU aliases."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import spiceypy

from space_map_data.constants.providers import PROVIDERS

logger = logging.getLogger(__name__)

_ROMAN_RE = re.compile(r"^[JSUNM][IVXLCDM]+$")
_EXT_NAIF_RE = re.compile(r"^[0-9]{4,5}$")


@dataclass
class HorizonsAlias:
    name: str | None = None
    designation: str | None = None
    iau_roman_designation: str | None = None
    naif_id_extended: int | None = None


def load_horizons_names(download_dir: Path) -> dict[int, HorizonsAlias]:
    """Parse Horizons major_bodies.txt into {naif_id: HorizonsAlias}.

    Horizons publishes names for recently-named moons (e.g. 557 Eirene) that
    the bundled SPICE name table doesn't know about, so we use it as the
    primary name source and fall back to SPICE's `bodc2n` only when absent.
    The IAU/aliases column also carries the Roman-numeral IAU designation and
    the 5-digit extended NAIF ID that SPICE uses for irregular-moon kernels.
    """
    path = download_dir / PROVIDERS.HORIZONS / "major_bodies.txt"
    result: dict[int, HorizonsAlias] = {}
    if not path.exists():
        logger.warning("Horizons major_bodies.txt not found at %s", path)
        return result

    # Fixed-width columns from the separator line:
    #   cols  2–8  = ID, 11–44 = Name, 46–56 = Designation, 59+ = IAU/aliases
    with path.open() as f:
        in_data = False
        for line in f:
            if line.startswith("  -------"):
                in_data = True
                continue
            if not in_data or len(line) < 11:
                continue
            id_str = line[0:9].strip()
            if not id_str.lstrip("-").isdigit():
                continue
            naif_id = int(id_str)
            alias = HorizonsAlias(
                name=line[11:45].strip() or None,
                designation=(line[46:57].strip() if len(line) > 46 else "") or None,
            )
            for token in line[59:].split() if len(line) > 59 else ():
                if alias.iau_roman_designation is None and _ROMAN_RE.match(token):
                    alias.iau_roman_designation = token
                elif alias.naif_id_extended is None and _EXT_NAIF_RE.match(token):
                    alias.naif_id_extended = int(token)
            result[naif_id] = alias
    logger.info("Loaded %d names from Horizons major_bodies.txt", len(result))
    return result


def resolve_name(naif_id: int, horizons_map: dict[int, HorizonsAlias]) -> HorizonsAlias:
    """Resolve name + cross-reference aliases for a body.

    Prefers Horizons (properly cased, broader name coverage); falls back to
    SPICE's built-in name table; returns name=None when neither has one.
    """
    alias = horizons_map.get(naif_id) or HorizonsAlias()
    if alias.name is None:
        try:
            alias.name = spiceypy.bodc2n(naif_id)
        except spiceypy.exceptions.SpiceyError:
            pass
    return alias
