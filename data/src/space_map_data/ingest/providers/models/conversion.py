"""Subprocess wrappers around Blender and gltf-transform.

Both tools are external system deps. ``*_available()`` short-circuits the
pipeline at startup when a dep is missing so the caller can log + skip
instead of crashing.
"""

import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from space_map_data.ingest.providers.models import config

log = logging.getLogger(__name__)

_DRIVER = Path(__file__).parent / "blender_driver.py"
_BODY_DRIVER = Path(__file__).parent / "bodies" / "body_blender_driver.py"

# Fallbacks for distros where `blender` isn't on PATH (e.g. Flatpak-only installs).
# Override with the ``BLENDER_EXECUTABLE`` env var on weirder setups.
_BLENDER_FALLBACKS = (
    "/var/lib/flatpak/exports/bin/org.blender.Blender",
    str(Path.home() / ".local/share/flatpak/exports/bin/org.blender.Blender"),
)


@lru_cache(maxsize=1)
def _blender_executable() -> str | None:
    override = os.environ.get("BLENDER_EXECUTABLE")
    if override and Path(override).is_file():
        return override
    found = shutil.which("blender")
    if found:
        return found
    for path in _BLENDER_FALLBACKS:
        if Path(path).is_file():
            return path
    return None


def blender_available() -> bool:
    return _blender_executable() is not None


@lru_cache(maxsize=1)
def gltf_transform_available() -> bool:
    """Detect gltf-transform CLI (either installed globally or via npx/pnpm dlx)."""
    return shutil.which("gltf-transform") is not None or shutil.which("npx") is not None


def _gltf_transform_cmd() -> list[str]:
    """Resolve how to invoke gltf-transform — direct CLI, then `npx`."""
    direct = shutil.which("gltf-transform")
    if direct:
        return [direct]
    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", "@gltf-transform/cli"]
    raise RuntimeError("gltf-transform not available")


def blender_to_glb(src: Path, dst: Path) -> None:
    """Run Blender headless to convert ``src`` (.fbx/.blend/.obj/.3ds) to .glb at ``dst``.

    Raises ``CalledProcessError`` on failure. Output is suppressed by default;
    set ``LOG_LEVEL=DEBUG`` to see Blender's stderr.
    """
    blender = _blender_executable()
    if blender is None:
        raise RuntimeError("blender not on PATH (set $BLENDER_EXECUTABLE to override)")
    cmd = [
        blender,
        "-b",
        "--python-exit-code",
        "1",
        "--python",
        str(_DRIVER),
        "--",
        str(src),
        str(dst),
    ]
    log.debug("blender %s → %s", src.name, dst.name)
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)


def body_blender_to_glb(src: Path, dst: Path, *, target_tris: int = 0) -> None:
    """Convert a natural-body mesh (.obj/.ply/.stl) to .glb via the body driver.

    Welds seam duplicates, shades smooth, optionally decimates to
    ``target_tris`` (0 = no decimation). Preserves km units — no texture or
    double-sided handling. Raises ``CalledProcessError`` on failure.
    """
    blender = _blender_executable()
    if blender is None:
        raise RuntimeError("blender not on PATH (set $BLENDER_EXECUTABLE to override)")
    cmd = [
        blender,
        "-b",
        "--python-exit-code",
        "1",
        "--python",
        str(_BODY_DRIVER),
        "--",
        str(src),
        str(dst),
    ]
    if target_tris:
        cmd.append(str(target_tris))
    log.debug("body blender %s → %s (target_tris=%d)", src.name, dst.name, target_tris)
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)


def gltf_transform_meshopt(src: Path, dst: Path) -> None:
    """Meshopt-compress a geometry-only glTF (shape models carry no textures).

    Dedup + weld + Meshopt; no texture/simplify passes — decimation already
    happened in Blender so the tri budget is fixed per tier.
    """
    base = _gltf_transform_cmd()
    cmd = [
        *base,
        "optimize",
        str(src),
        str(dst),
        "--compress",
        "meshopt",
        "--texture-compress",
        "false",
        "--simplify",
        "false",
    ]
    log.debug("gltf-transform meshopt %s → %s", src.name, dst.name)
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)


def gltf_transform_optimize(src: Path, dst: Path, *, tier: str) -> None:
    """Optimise a glTF: dedup, weld, Meshopt geometry, WebP textures.

    ``tier='low'`` additionally downsamples textures to
    ``LOW_TIER_TEXTURE_DIM`` and simplifies geometry to
    ``LOW_TIER_SIMPLIFY_RATIO`` of original triangle count.

    Texture format is WebP (transmission-optimised); KTX2 would also be valid
    (GPU-memory-optimised, ~10× smaller VRAM) but needs the external `ktx`
    CLI from Khronos KTX-Software, which isn't in most distros. With a single
    spacecraft model loaded at a time GPU pressure is minimal, so WebP wins
    on dep footprint.
    """
    base = _gltf_transform_cmd()
    cmd = [
        *base,
        "optimize",
        str(src),
        str(dst),
        "--compress",
        "meshopt",
        "--texture-compress",
        "webp",
    ]
    if tier == "low":
        cmd += [
            "--texture-size",
            str(config.LOW_TIER_TEXTURE_DIM),
            "--simplify",
            "true",
            "--simplify-ratio",
            str(config.LOW_TIER_SIMPLIFY_RATIO),
        ]
    else:
        cmd += ["--simplify", "false"]
    log.debug("gltf-transform optimize (%s) %s → %s", tier, src.name, dst.name)
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
