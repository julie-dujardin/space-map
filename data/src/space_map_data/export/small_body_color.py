"""Resolve a small body's representative sRGB surface colour.

Reads ``constants/small_body_colors.json`` (generated offline by
``scripts/generate_small_body_colors.py`` from TrueColorTools — see that file
for provenance). Physically-derived colours replace the old frontend taxonomy
heuristic. Each colour carries the *method* it was derived by, so the export can
credit it. Priority, most→least specific:

  spectrum    per-body colour from a measured reflectance spectrum (final hex)
  photometry  per-body colour from SBDB B-V/U-B colour indices (final hex)
  taxonomy    per-class chroma (Bus-DeMeo) scaled by the body's geometric albedo
  albedo      neutral chroma scaled by the body's geometric albedo (no hue)
  None        no colour — caller omits the field; the frontend keeps its tint

The first three run through TrueColorTools' colour engine. taxonomy/albedo take
brightness from the body's own measured albedo, so a dark P-type and a bright
E-type sharing a featureless X spectrum still read correctly.

Moons resolve separately via ``resolve_moon_color`` (NAIF-keyed): a measured TCT
spectrum if there is one, else a neutral grey scaled by the moon's JPL Horizons
geometric albedo (``constants/moon_albedos.json``) so an unmeasured dark P-type
and a bright icy moon still read apart by brightness. Moons carry no SBDB
taxonomy, so there is no hue (taxonomy) tier for them.
"""

import json
import logging
from collections import Counter
from functools import lru_cache
from importlib.resources import files

logger = logging.getLogger(__name__)

# Geometric albedo assumed for a classified body that has no measured albedo.
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
            "by_spkid": {},
            "by_naif": {},
        }
    return json.loads(raw)


def _encode(linear: list[float], albedo: float) -> str:
    """sRGB-encode a luminance-1 chroma scaled to a geometric albedo."""

    def oetf(c: float) -> int:
        c = min(1.0, max(0.0, c * albedo))
        s = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return round(s * 255)

    return "#{:02x}{:02x}{:02x}".format(*(oetf(v) for v in linear))


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


def resolve_small_body_color(
    spkid: str | None, spec: str | None, albedo: float | None
) -> tuple[str | None, str | None]:
    """``(#rrggbb, method)`` for a small body, or ``(None, None)`` when nothing
    is known. ``method`` is one of ``spectrum``/``photometry``/``taxonomy``/
    ``albedo`` (see module docstring for the priority order)."""
    table = _table()
    by_spkid = table["by_spkid"]
    if spkid is not None:
        for method in ("spectrum", "photometry"):
            if hexcol := by_spkid[method].get(spkid):
                _stats[method] += 1
                return hexcol, method
    key = _taxon_key(spec) if spec else None
    if key is not None:
        _stats["taxonomy"] += 1
        alb = albedo if albedo is not None else _DEFAULT_ALBEDO
        return _encode(table["by_taxon"][key], alb), "taxonomy"
    if albedo is not None and table["neutral_linear"] is not None:
        _stats["albedo"] += 1
        return _encode(table["neutral_linear"], albedo), "albedo"
    _stats["none"] += 1
    return None, None


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


def resolve_moon_color(naif_id: int | None) -> tuple[str | None, str | None]:
    """``(#rrggbb, method)`` for a moon, keyed by NAIF id, or ``(None, None)``.
    Priority: a measured TrueColorTools colour (``spectrum``), else a neutral grey
    scaled by the moon's Horizons geometric albedo (``albedo``). Moons carry no
    SBDB taxonomy, so there is no hue fallback — a moon with neither keeps the
    frontend's generic moon tint."""
    if naif_id is not None:
        by_naif = _table().get("by_naif", {})
        if hexcol := by_naif.get("spectrum", {}).get(str(naif_id)):
            _stats["moon_spectrum"] += 1
            return hexcol, "spectrum"
        albedo = _moon_albedos().get(str(naif_id))
        neutral = _table().get("neutral_linear")
        if albedo is not None and neutral is not None:
            _stats["moon_albedo"] += 1
            return _encode(neutral, albedo), "albedo"
    _stats["moon_none"] += 1
    return None, None


def log_color_stats() -> None:
    """Emit the per-tier resolution tally, then reset. Call once per export so
    fall-through to the hue-less / no-colour tiers is visible."""
    if not _stats:
        return
    total = sum(_stats.values())
    breakdown = ", ".join(f"{tier}={n}" for tier, n in sorted(_stats.items()))
    logger.info("small-body colours resolved (%d): %s", total, breakdown)
    _stats.clear()
