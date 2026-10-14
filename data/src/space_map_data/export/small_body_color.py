"""Resolve the representative sRGB surface colour of a body.

The colour is a hue at a luminance equal to the body's V-band geometric
albedo. The hue comes from ``constants/small_body_colors.json`` (generated
offline by ``scripts/generate_small_body_colors.py`` from TrueColorTools). The
*method* names the source of the hue, most to least specific:

  spectrum    measured reflectance spectrum
  photometry  SBDB B-V/U-B colour indices
  taxonomy    hue of the Bus-DeMeo class
  albedo      neutral hue
  None        no colour — caller omits the field; the frontend keeps its tint

The albedo is the first one known of: ``constants/geometric_albedos.py``
(published values), the Horizons albedo of a moon (``moon_albedos.json``) or
the SBDB albedo of a small body, and the albedo of the TrueColorTools entry.

A small body with no albedo takes ``_DEFAULT_ALBEDO``. A moon with no albedo
gets no colour. A planet gets its albedo and no colour, so that its map keeps
its own hue. A colour too bright for a hex keeps its hue at the brightest value
a hex holds; ``geometric_albedo`` keeps the true value.
"""

import json
import logging
from collections import Counter
from functools import lru_cache
from importlib.resources import files
from typing import NamedTuple

from space_map_data.constants.geometric_albedos import GEOMETRIC_ALBEDOS

logger = logging.getLogger(__name__)

# Geometric albedo assumed for a small body that has no measured albedo.
_DEFAULT_ALBEDO = 0.10

# Tholen (SBDB spec_T) classes absent from the Bus-DeMeo taxonomy, mapped to the
# nearest Bus-DeMeo key. Brightness comes from albedo, so only hue matters here.
_THOLEN_ALIAS = {
    "M": "Xk",  # metallic
    "E": "Xe",  # enstatite
    "P": "X",  # primitive (dark; albedo carries the darkness)
    "F": "B",  # flat / blue
    "G": "Cgh",  # hydrated C
}

_stats: Counter = Counter()


class SurfaceColor(NamedTuple):
    """``#rrggbb``, the source of its hue, and the measured V-band geometric
    albedo it is scaled to. All None when nothing is known."""

    color: str | None
    method: str | None
    geometric_albedo: float | None


_NO_COLOR = SurfaceColor(None, None, None)


@lru_cache(maxsize=1)
def _table() -> dict:
    try:
        raw = (
            files("space_map_data.constants")
            .joinpath("small_body_colors.json")
            .read_text(encoding="UTF-8")
        )
    except FileNotFoundError:
        logger.warning(
            "small_body_colors.json missing — small-body colours disabled "
            "(run scripts/generate_small_body_colors.py)"
        )
        return {
            "neutral_linear": None,
            "by_taxon": {},
            "by_spkid": {"spectrum": {}, "photometry": {}},
            "by_naif": {"spectrum": {}},
        }
    return json.loads(raw)


def _encode(chroma: list[float], albedo: float) -> str:
    """sRGB hex of a luminance-1 hue at this albedo. Past the range of a hex,
    the hue stays and the brightest channel is 1."""
    scale = min(albedo, 1 / max(chroma))

    def oetf(c: float) -> int:
        c = min(1.0, max(0.0, c * scale))
        s = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return round(s * 255)

    return "#{:02x}{:02x}{:02x}".format(*(oetf(v) for v in chroma))


def _luminance_of_hex(hexcol: str) -> float:
    def eotf(i: int) -> float:
        s = int(hexcol[i : i + 2], 16) / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    return 0.2126 * eotf(1) + 0.7152 * eotf(3) + 0.0722 * eotf(5)


def albedo_beyond_hex(surface: SurfaceColor) -> float | None:
    """The albedo of ``surface`` where its hex cannot hold it, else None. A
    small body writes it only then; a moon or a planet always writes it."""
    albedo = surface.geometric_albedo
    if albedo is None or surface.color is None:
        return None
    # A hex that falls short has a full channel. Rounding alone has none.
    full = "ff" in (surface.color[1:3], surface.color[3:5], surface.color[5:7])
    return albedo if full and _luminance_of_hex(surface.color) < 0.98 * albedo else None


def _taxon_key(spec: str) -> str | None:
    """Map an SBDB spec_B (Bus-DeMeo) or spec_T (Tholen) code to a by_taxon key.
    Strips uncertainty markers, then falls back to the leading complex letter."""
    by_taxon = _table()["by_taxon"]
    s = spec.strip().rstrip(":").strip()
    if not s:
        return None
    if s in by_taxon:
        return s
    if s in _THOLEN_ALIAS:
        return _THOLEN_ALIAS[s]
    head = s[0]  # compound codes (CX, XC, SU, ...) reduce to their first complex
    if head in by_taxon:
        return head
    return _THOLEN_ALIAS.get(head)


def _published_albedo(object_id: str) -> float | None:
    entry = GEOMETRIC_ALBEDOS.get(object_id)
    return None if entry is None else entry.value


def resolve_small_body_color(
    object_id: str, spkid: str | None, spec: str | None, sbdb_albedo: float | None
) -> SurfaceColor:
    """Colour of a small body or a dwarf planet."""
    table = _table()
    by_spkid = table["by_spkid"]
    published = _published_albedo(object_id)
    albedo = published if published is not None else sbdb_albedo
    if spkid is not None:
        for method in ("spectrum", "photometry"):
            if entry := by_spkid[method].get(spkid):
                measured = albedo if albedo is not None else entry.get("albedo")
                _stats[method] += 1
                return SurfaceColor(
                    _encode(entry["chroma"], measured or _DEFAULT_ALBEDO),
                    method,
                    measured,
                )
    key = _taxon_key(spec) if spec else None
    if key is not None:
        _stats["taxonomy"] += 1
        return SurfaceColor(
            _encode(table["by_taxon"][key], albedo or _DEFAULT_ALBEDO),
            "taxonomy",
            albedo,
        )
    if albedo is not None and table["neutral_linear"] is not None:
        _stats["albedo"] += 1
        return SurfaceColor(_encode(table["neutral_linear"], albedo), "albedo", albedo)
    _stats["none"] += 1
    return _NO_COLOR


@lru_cache(maxsize=1)
def _moon_albedos() -> dict[str, float]:
    """``{naif: geometric_albedo}`` harvested from JPL Horizons (offline, by
    ``scripts/generate_moon_albedos.py``). Empty if the constant is absent."""
    try:
        raw = (
            files("space_map_data.constants")
            .joinpath("moon_albedos.json")
            .read_text(encoding="UTF-8")
        )
    except FileNotFoundError:
        logger.warning(
            "moon_albedos.json missing — moon albedo-grey tier disabled "
            "(run scripts/generate_moon_albedos.py)"
        )
        return {}
    return json.loads(raw)


def _is_planet(naif_id: int) -> bool:
    """NAIF ids P99 are the planets; 999 is Pluto, a dwarf planet."""
    return 100 <= naif_id < 999 and naif_id % 100 == 99


def resolve_major_body_color(naif_id: int | None) -> SurfaceColor:
    """Colour of a moon, or the albedo alone of a planet, keyed by NAIF id."""
    if naif_id is None:
        _stats["major_none"] += 1
        return _NO_COLOR
    entry = _table()["by_naif"]["spectrum"].get(str(naif_id))
    albedo = _published_albedo(f"naif-{naif_id}")
    if albedo is None:
        albedo = _moon_albedos().get(str(naif_id), entry and entry.get("albedo"))
    if albedo is None:
        _stats["major_none"] += 1
        return _NO_COLOR
    if _is_planet(naif_id):
        _stats["major_planet"] += 1
        return SurfaceColor(None, None, albedo)
    if entry is not None:
        _stats["major_spectrum"] += 1
        return SurfaceColor(_encode(entry["chroma"], albedo), "spectrum", albedo)
    neutral = _table()["neutral_linear"]
    if neutral is None:
        _stats["major_none"] += 1
        return _NO_COLOR
    _stats["major_albedo"] += 1
    return SurfaceColor(_encode(neutral, albedo), "albedo", albedo)


def log_color_stats() -> None:
    """Emit the per-tier resolution tally, then reset. Call once per export so
    fall-through to the hue-less / no-colour tiers is visible."""
    if not _stats:
        return
    total = sum(_stats.values())
    breakdown = ", ".join(f"{tier}={n}" for tier, n in sorted(_stats.items()))
    logger.info("surface colours resolved (%d): %s", total, breakdown)
    _stats.clear()
