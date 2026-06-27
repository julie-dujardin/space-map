"""Which position zones carry a ``{zoom}`` path segment.

Only ``major`` (chebyshev + Horizons tiers) and ``small_bodies/{class}`` (named
/ unnamed) are multi-zoom; every other zone is flat, like probes. Centralised
so the writers, sidecars, prune pass, and manifest can't disagree.
"""

from pathlib import Path


def zone_has_zoom_segment(zone: str) -> bool:
    return zone == "major" or zone.startswith("small_bodies/")


def position_zone_dir(out_dir: Path, zone: str, zoom: int) -> Path:
    """``{out_dir}/position/{zone}[/{zoom}]`` — zoom segment only for multi-zoom zones."""
    base = out_dir / "position" / zone
    return base / str(zoom) if zone_has_zoom_segment(zone) else base
