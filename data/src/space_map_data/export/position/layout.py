"""Where position data lives: zone zoom segments, and the chebyshev npz pools.

A zone is multi-zoom where it splits into tiers a file can't mix: ``major``
(chebyshev + Horizons + SBDB), ``small_bodies/{class}`` (named / unnamed) and
``small_body_moons`` (SBDB / AsterSat). Every other zone is flat, like probes.
Centralised so the writers, sidecars, prune pass, and manifest can't disagree.
"""

from pathlib import Path


def zone_has_zoom_segment(zone: str) -> bool:
    return zone in ("major", "small_body_moons") or zone.startswith("small_bodies/")


def position_zone_dir(out_dir: Path, zone: str, zoom: int) -> Path:
    """``{out_dir}/position/{zone}[/{zoom}]`` — zoom segment only for multi-zoom zones."""
    base = out_dir / "position" / zone
    return base / str(zoom) if zone_has_zoom_segment(zone) else base


def chebyshev_npz_paths(download_dir: Path) -> list[Path]:
    """Every body's `.npz`, perturber pool first.

    Probe targets are fit into a second pool because
    `probes.fit_centers.load_candidates` walks the first one, and a body
    appearing there joins the interplanetary fit-center candidate set and
    invalidates every cached probe fit. Consumers of the *fits* want both as
    one body set; a body in both (Ceres, Vesta, Psyche) takes its perturber
    file, whose coverage spans the full export range rather than one mission.
    """
    derived = download_dir / "derived" / "position"
    by_body: dict[str, Path] = {}
    for pool in (derived / "chebyshev", derived / "chebyshev-small-bodies"):
        for path in sorted(pool.glob("*.npz")):
            by_body.setdefault(path.name, path)
    return list(by_body.values())
