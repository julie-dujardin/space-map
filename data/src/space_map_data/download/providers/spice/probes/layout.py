"""On-disk layout for probe SPKs.

Probe kernels share the SPICE tree because the runtime furnishes generic
kernels (lsk/pck/de/satellite ephemerides) and mission-trajectory kernels
together.

Surface/post-touchdown kernels live in a sibling tree: mixing `*_atls_*`
into the same furnish as `*_cruise_*` lets SPICE's last-loaded-wins paint
the cruise NAIF at the surface during EDL, contaminating landed-detection;
keeping them apart also stops cruise/EDL motion bleeding into the landed
exporter's surface trace. Each mission has its own `_index.json` in both
trees.
"""

from pathlib import Path

from space_map_data.utils.paths import SOURCES_POSITION_DIR

_KERNELS_DIR = SOURCES_POSITION_DIR / "spice-kernels"
MISSIONS_DIR = _KERNELS_DIR / "missions"
LANDED_MISSIONS_DIR = _KERNELS_DIR / "landed-missions"


def collect_generic_kernels(
    kernels_dir: Path,
) -> tuple[list[Path], list[Path]]:
    """Collect generic kernels under `kernels/`, splitting them by role.

    Returns `(lsk_pck_paths, generic_spk_paths)`. Generic SPKs (planetary
    ephemerides) must furnish AFTER mission kernels so they win for shared
    targets — mission kernels like p11-a.bsp embed their own 1970s-era
    planetary data that would otherwise contaminate the fit.

    `missions/`, `landed-missions/`, and `probes/` subtrees are excluded
    (handled per-probe): landed kernels especially must not leak in here,
    since a recycled NAIF (MSL's -76 = old Mariner 10) would win
    last-loaded-wins and drag the earlier probe onto the lander's body.
    """
    skip_dirs = {"missions", "landed-missions", "probes", "attitude-benchmark"}
    lsk_pck: list[Path] = []
    generic_spk: list[Path] = []
    for path in sorted(kernels_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.relative_to(kernels_dir).parts):
            continue
        suffix = path.suffix.lower()
        # .tf: frame kernels — Hayabusa's SPKs are expressed in the
        # ITOKAWA_FIXED frame and can't be evaluated without one.
        if suffix in (".tls", ".tpc", ".tf"):
            lsk_pck.append(path)
        elif suffix == ".bsp":
            generic_spk.append(path)
    return lsk_pck, generic_spk
