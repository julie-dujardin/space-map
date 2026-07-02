"""Paths, schema version, and per-tier knobs for the 3D-model provider."""

from space_map_data.utils.paths import (
    DERIVED_MODELS_DIR,
    EXPORT_DIR,
    SOURCES_MODELS_BODIES_DIR,
    SOURCES_MODELS_SPACECRAFT_DIR,
)

MODELS_DOWNLOAD_DIR = SOURCES_MODELS_SPACECRAFT_DIR
NASA_MANIFEST = MODELS_DOWNLOAD_DIR / "nasa-3d-resources.yaml"
NASA_CHECKOUT = MODELS_DOWNLOAD_DIR / "NASA-3D-Resources"
ESA_DIR = MODELS_DOWNLOAD_DIR / "ESA-SciFleet"
# Hand-curated manifest for slugs whose files span multiple catalogs.
# No top-level `source:` block; each file carries its own `source` key.
MERGED_MANIFEST = MODELS_DOWNLOAD_DIR / "merged.yaml"

PROCESSED_DIR = EXPORT_DIR / "v1" / "models"
# Compressed-GLB cache: one pair (high+low knobs) per manifest source file,
# keyed by source sha256 + compression-knobs version. Survives across runs.
CONVERTED_DIR = DERIVED_MODELS_DIR / "converted"

# Bump when the public per-slug metadata.json shape changes — _try_skip
# treats older files as stale and reprocesses them.
SCHEMA_VERSION = 5
# Bump when gltf-transform invocation flags change. Caches with a different
# value reconvert from source.
COMPRESSION_KNOBS_VERSION = "v3-meshopt-webp-doublesided-opaque"

# Catalog metadata propagated into each model's metadata.json and into the
# credits.json aggregate. Keyed by the manifest's top-level ``source.name``
# (NASA) or ``source.catalog`` (ESA) value.
MODEL_CATALOGS: dict[str, dict[str, str]] = {
    "NASA-3D-Resources": {
        "url": "https://www.nasa.gov/3d-resources/",
        # Repo doesn't ship a license header; the catalog page covers it.
        "default_attribution": "NASA",
    },
    "ESA SciFleet": {
        "url": "https://scifleet.esa.int/",
        "default_attribution": "ESA / scifleet.esa.int",
    },
    # Natural-body shape-model archives. Each body bundle sets its tier
    # ``catalog`` to one of these keys so the credits roll-up lists the archive.
    "PDS Small Bodies Node": {
        "url": "https://pds-smallbodies.astro.umd.edu/",
        "default_attribution": "NASA PDS Small Bodies Node",
    },
    "JAXA/ISAS DARTS": {
        "url": "https://data.darts.isas.jaxa.jp/",
        "default_attribution": "JAXA / ISAS DARTS",
    },
    "ESA/ESAC Rosetta": {
        "url": "https://www.cosmos.esa.int/web/rosetta",
        "default_attribution": "ESA / Rosetta / DLR",
    },
    "DAMIT": {
        "url": "https://damit.cuni.cz/projects/damit/",
        "default_attribution": "DAMIT (Ďurech et al.) / CC BY 4.0",
    },
}


# --- Natural-body shape models -------------------------------------------
# Missions + radar tiers convert through Blender like spacecraft; the DAMIT
# lightcurve tier has its own Blender-free path (see bodies/damit.py).
BODY_MANIFEST_TIERS = ("missions", "radar")
# Per-tier cache root; keeps body candidates out of the spacecraft slug space
# on disk while sharing the sha256 + knobs-version scheme.
BODY_CONVERTED_DIR = DERIVED_MODELS_DIR / "converted-bodies"
DAMIT_DIR = SOURCES_MODELS_BODIES_DIR / "lightcurve" / "damit"
# High tier keeps source detail up to this before hitting the file cap; low is
# the distant-LOD budget (~20k tris ≈ 90 KiB meshopt). Bumping either, or the
# gltf-transform flags, invalidates the body cache.
BODY_HIGH_TIER_MAX_TRIS = 400_000
BODY_LOW_TIER_TRIS = 20_000
BODY_KNOBS_VERSION = "v1-body-weld-smooth-decimate-meshopt"
# Blender-free convex-model conversion writes GLBs with this generator tag; the
# resumable DAMIT pass rebuilds when it changes.
DAMIT_KNOBS_VERSION = "v1-convex-direct-meshopt"

# Convertible source formats. `.glb` skips Blender; the rest need it.
# Anything outside this set (`.lwo`, `.7z`, `.7z.001`, …) is silently ignored.
CONVERTIBLE_FORMATS = frozenset({"glb", "fbx", "blend", "obj", "3ds"})

# Cloudflare Pages 25 MiB per-file cap; matches what textures use.
# Slugs whose smallest high-tier conversion exceeds this are skipped with a warning.
MAX_FILE_BYTES = 24 * 1024 * 1024

# Low-tier gltf-transform knobs. Texture-resize is the longest-side cap in pixels;
# simplify ratio is the fraction of triangles to retain.
LOW_TIER_TEXTURE_DIM = 1024
LOW_TIER_SIMPLIFY_RATIO = 0.5
