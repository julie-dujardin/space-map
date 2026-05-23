"""Shared constants and paths for the textures provider."""

from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR

RAW_DIR = DOWNLOAD_DIR / "textures" / "raw"
# Per-asset subdirs under `misc/` carry their own download-metadata.yaml; used
# for manually downloaded files (e.g. GEBCO bathymetry) that don't flow through
# the auto-downloader. TextureProcessor merges every misc/*/download-metadata.yaml
# into the main bodies list at startup.
MISC_DIR = DOWNLOAD_DIR / "textures" / "misc"
PROCESSED_DIR = EXPORT_DIR / "v1" / "textures"
# Per-texture scraped source metadata (written by the texture_sources downloader);
# used as a fallback for `attribution` when download-metadata.yaml doesn't provide one.
SOURCE_METADATA_PARSED_DIR = DOWNLOAD_DIR / "textures" / "source_metadata" / "parsed"
# Date-partitioned snapshots written by the earth_clouds downloader at 3h cadence.
EARTH_CLOUDS_DIR = DOWNLOAD_DIR / "textures" / "earth_clouds"
# Parallel to the Earth surface texture; the renderer layers it on top of naif-399.
EARTH_CLOUDS_OBJECT_ID = "naif-399_clouds"
# Suffix on the export directory holding a body's specular/roughness bundle —
# sibling of the surface texture, mirrors the `_clouds` convention.
SPECULAR_SUFFIX = "_specular"

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
