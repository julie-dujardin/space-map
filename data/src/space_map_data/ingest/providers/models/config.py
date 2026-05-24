"""Paths, schema version, and per-tier knobs for the 3D-model provider."""

from space_map_data.utils.paths import DOWNLOAD_DIR, EXPORT_DIR

MODELS_DOWNLOAD_DIR = DOWNLOAD_DIR / "3d"
NASA_MANIFEST = MODELS_DOWNLOAD_DIR / "nasa-3d-resources.yaml"
ESA_DIR = MODELS_DOWNLOAD_DIR / "ESA-SciFleet"

PROCESSED_DIR = EXPORT_DIR / "v1" / "models"

SCHEMA_VERSION = 1

# Source-format priority within a single manifest entry. Smaller index = preferred.
# `.glb` skips the Blender step entirely. `.fbx`/`.blend`/`.obj`/`.3ds` need Blender.
# `.lwo` and `.7z` are out of scope for this iteration.
FORMAT_PRIORITY = ("glb", "fbx", "blend", "obj", "3ds")
CONVERTIBLE_FORMATS = set(FORMAT_PRIORITY)

# When a manifest entry has 2+ models, the smallest convertible model is treated
# as a hand-authored low tier only if it's at most this fraction of the largest.
# Above this, the two are likely variants (e.g. with/without docked craft) rather
# than LODs, and we synthesise `low` from `high` instead.
LOW_TIER_AUTHORED_MAX_RATIO = 0.5

# Cloudflare Pages 25 MiB per-file cap; matches what textures use.
MAX_FILE_BYTES = 24 * 1024 * 1024

# Low-tier gltf-transform knobs. Texture-resize is the longest-side cap in pixels;
# simplify ratio is the fraction of triangles to retain.
LOW_TIER_TEXTURE_DIM = 1024
LOW_TIER_SIMPLIFY_RATIO = 0.5
