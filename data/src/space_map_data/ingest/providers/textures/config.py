"""Shared constants and paths for the textures provider."""

from collections.abc import Iterator
from pathlib import Path

from space_map_data.utils.paths import (
    DERIVED_TEXTURES_DIR,
    EXPORT_DIR,
    SOURCES_TEXTURES_DIR,
)

# Per-body surface textures (flat — filename encodes the body). The main
# download-metadata.yaml at the SOURCES_TEXTURES_DIR root maps them.
RAW_DIR = SOURCES_TEXTURES_DIR / "surfaces"
PROCESSED_DIR = EXPORT_DIR / "v1" / "textures"
# Per-texture scraped source metadata (written by the texture_sources downloader);
# used as a fallback for `attribution` when download-metadata.yaml doesn't provide one.
SOURCE_METADATA_PARSED_DIR = DERIVED_TEXTURES_DIR / "source-metadata" / "parsed"
# Per-body cloud source directories. Earth's is date-partitioned (3h cadence
# from the earth_clouds downloader); other bodies are single static images
# next to a `metadata.json` describing the source.
CLOUDS_DIR = SOURCES_TEXTURES_DIR / "clouds"
EARTH_CLOUDS_DIR = CLOUDS_DIR / "earth"

# Maps cloud subdirectory name → NAIF body id. Each entry's processed bundle
# lands at `PROCESSED_DIR / f"{body_id}_clouds"`.
CLOUD_SOURCES: dict[str, str] = {
    "earth": "naif-399",
    "venus": "naif-299",
}

# User-facing organisation + description for static cloud bundles. The
# downloaded sidecar's `description` is a rendering hint, not credit copy,
# so we override it here. Keyed by NAIF body id.
CLOUDS_STATIC_META: dict[str, tuple[str, str]] = {
    "naif-299": (
        "Björn Jónsson",
        "Ultraviolet cloud map mosaicked from Galileo SSI flyby imagery.",
    ),
}


def iter_extra_asset_yamls() -> Iterator[Path]:
    """Yield per-asset download-metadata.yaml paths for non-surface textures.

    Picks up:
    * depth-1 bodyless assets (e.g. ``star-map/download-metadata.yaml``);
    * depth-2 per-body assets (e.g. ``night/earth/download-metadata.yaml``,
      ``bathymetry/earth/...``).

    The yaml at the SOURCES_TEXTURES_DIR root (the main bodies manifest for
    ``surfaces/``) is depth-0 and isn't matched. Special-cased trees
    (``clouds/``, ``rings/``) use their own metadata filenames.
    """
    yield from SOURCES_TEXTURES_DIR.glob("*/download-metadata.yaml")
    yield from SOURCES_TEXTURES_DIR.glob("*/*/download-metadata.yaml")


# Suffix appended to a body id to name its processed cloud bundle directory.
CLOUDS_SUFFIX = "_clouds"
# Parallel to the Earth surface texture; the renderer layers it on top of naif-399.
EARTH_CLOUDS_OBJECT_ID = f"{CLOUD_SOURCES['earth']}{CLOUDS_SUFFIX}"


def clouds_object_id(body_id: str) -> str:
    """Bundle directory name for a body's cloud overlay (sibling of its surface texture)."""
    return f"{body_id}{CLOUDS_SUFFIX}"


# Suffix on the export directory holding a body's specular/roughness bundle —
# sibling of the surface texture, mirrors the `_clouds` convention.
SPECULAR_SUFFIX = "_specular"
# Sibling bundle for an emissive night-lights map (e.g. NASA Black Marble for
# Earth). Same shape as `_specular`: single-frame, served from
# `{body}{NIGHT_SUFFIX}/{tier}.webp`.
NIGHT_SUFFIX = "_night"
# Sibling bundle for a displacement/height map (LRO LOLA, USGS DEMs). The
# renderer drives `displacementMap` from it, scaled by the km range in metadata.
DISPLACEMENT_SUFFIX = "_displacement"

# Cubemap face order, matching Three.js' CubeTextureLoader expectation
# (+X, -X, +Y, -Y, +Z, -Z).
SKYBOX_FACES = ("px", "nx", "py", "ny", "pz", "nz")
# py360convert.e2c with cube_format="dict" returns Front/Right/Back/Left/Up/Down
# keys (yaw=0 → F; +x → R; +y → U; etc.). This maps each onto its WebGL axis
# label so the on-disk filenames stay aligned with cubemap-sampler conventions.
# Renderer-side RA/dec orientation can apply a rotation if needed.
PY360_TO_FACE = {"R": "px", "L": "nx", "U": "py", "D": "ny", "F": "pz", "B": "nz"}
# Per-face edge length for each tier. UASTC 4K/face would be the eventual
# target; for WebP we keep the same dims and rely on the size cap.
SKYBOX_TIER_SIZES = {"low": 2048, "high": 4096}
# Exposure pre-multiplier applied before Reinhard tonemap. The SVS Deep Star
# Maps EXR has bright stars sitting well above 1.0; bumping exposure brings
# the Milky Way out of the toe before the tonemap squashes the dynamic range.
SKYBOX_EXPOSURE = 4.0
# Source-to-output downsample ratio applied while streaming the EXR. The
# SVS Deep Star Maps 2020 source is 65536×32768 — far above what a 4K-per-face
# cubemap can resolve. Box-averaging 4:1 in each axis lands the working
# equirect at 16384×8192 (~45 px/deg), matching a 4K cube face's angular
# sampling density and keeping the uint8 buffer at ~384 MiB.
SKYBOX_DOWNSAMPLE = 4

WEBP_MAX = 16383  # WebP hard limit per dimension
EXPORT_SIZES = [2048, 8192]  # intermediate sizes to generate for large images

# Upper-bound lookup: (max_dim, tier_name, size_target)
SIZE_TARGETS = [
    (2048, "low", 300 * 1024),
    (8192, "medium", 2 * 1024 * 1024),
    (WEBP_MAX, "high", 6 * 1024 * 1024),
]

# Hard file-size cap, enforced after save. Cloudflare Pages rejects individual
# files over 25 MiB, so high-detail textures (Mercury MDIS, Bennu, Mars Viking)
# need to shrink or re-encode at lower quality to land below this. 23 MiB
# leaves 2 MiB of headroom for upload-wrapper overhead.
MAX_FILE_BYTES = 24 * 1024 * 1024
MIN_QUALITY = 60  # webp artifacts become visible on textures below this
SHRINK_RATIO = 0.85  # how much to downscale per iteration when quality floor is hit
MIN_DIM_AFTER_SHRINK = 4096  # stop shrinking below this — below the medium tier

IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
