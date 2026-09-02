"""Read the per-object columns of GCAT's satcat.tsv.

GCAT states hardware (bus, builder), registration (state of registry, owner)
and physical size for nearly every catalogued object, keyed by the same NORAD
number CelesTrak uses. Most of it has no CelesTrak equivalent; where both
sources speak, GCAT is the one that dates its answer to the object's own era —
a Soviet-era launch is Soviet, not Russian.

Manufacturer and owner arrive as org codes, which orgs.tsv also resolves to a
UCode — the code for the whole corporate lineage. Both are kept: the code says
who it was at the time (Matra Espace, not Airbus), the UCode catches an
organisation this project only knows under a later name.

Sizes carry a flag column that marks an estimate; ``?`` there means GCAT
inferred the number rather than read it off a source, and it is passed through
so nothing presents a guess as a measurement.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# GCAT writes a joint build as "NPOL/KOMET" and an unsure attribution with a
# trailing "?"; both carry information we keep rather than drop.
_JOINT = "/"
_UNSURE = "?"
_EMPTY = ("", "-", _UNSURE)


@dataclass(frozen=True)
class GcatHardware:
    bus: str | None
    manufacturer_codes: tuple[str, ...]
    manufacturer_ucodes: tuple[str, ...]
    state: str | None
    owner_code: str | None
    owner_ucode: str | None
    mass_kg: float | None
    dry_mass_kg: float | None
    span_m: float | None
    length_m: float | None
    diameter_m: float | None
    shape: str | None
    # True where GCAT flags the size as its own estimate.
    mass_estimated: bool = False
    span_estimated: bool = False


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", errors="replace") as f:
        header = f.readline().lstrip("#").rstrip("\n").split("\t")
        out = []
        for line in f:
            if line.startswith("#"):
                continue
            values = line.rstrip("\n").split("\t")
            if len(values) < len(header):
                continue
            out.append({k: v.strip() for k, v in zip(header, values)})
    return out


def _clean(value: str) -> str | None:
    value = value.strip()
    return None if value in _EMPTY else value


def _number(value: str) -> float | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_gcat_hardware(download_dir: Path) -> dict[int, GcatHardware]:
    """NORAD → GCAT's view of the object, empty when GCAT is not downloaded."""
    gcat_dir = download_dir / "sources" / "position" / "gcat"
    satcat_path = gcat_dir / "satcat.tsv"
    orgs_path = gcat_dir / "orgs.tsv"
    if not satcat_path.exists():
        logger.warning("GCAT satcat not found at %s — no buses", satcat_path)
        return {}

    ucode_by_code: dict[str, str] = {}
    if orgs_path.exists():
        for row in _rows(orgs_path):
            code, ucode = row.get("Code", ""), row.get("UCode", "")
            if code and ucode:
                ucode_by_code[code] = ucode
    else:
        logger.warning(
            "GCAT orgs not found at %s — manufacturer codes unresolved", orgs_path
        )

    out: dict[int, GcatHardware] = {}
    for row in _rows(satcat_path):
        norad = row.get("Satcat", "")
        if not norad.isdigit():
            continue
        raw = row.get("Manufacturer", "").replace(_UNSURE, "")
        codes = tuple(
            part
            for part in (p.strip() for p in raw.split(_JOINT))
            if part and part != "-"
        )
        owner = _clean(row.get("Owner", "").replace(_UNSURE, ""))
        out[int(norad)] = GcatHardware(
            bus=_clean(row.get("Bus", "")),
            manufacturer_codes=codes,
            manufacturer_ucodes=tuple(ucode_by_code.get(c, c) for c in codes),
            state=_clean(row.get("State", "")),
            owner_code=owner,
            owner_ucode=ucode_by_code.get(owner or "", owner),
            mass_kg=_number(row.get("Mass", "")),
            dry_mass_kg=_number(row.get("DryMass", "")),
            span_m=_number(row.get("Span", "")),
            length_m=_number(row.get("Length", "")),
            diameter_m=_number(row.get("Diameter", "")),
            shape=_clean(row.get("Shape", "")),
            mass_estimated=row.get("MassFlag", "").strip() == _UNSURE,
            span_estimated=row.get("SpanFlag", "").strip() == _UNSURE,
        )
    logger.info("GCAT hardware: %d catalogued objects", len(out))
    return out
