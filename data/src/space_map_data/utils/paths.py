from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[3]
CONFIG_FILE = DATA_DIR / "config.toml"

PROJECT_ROOT = DATA_DIR.parent

DOWNLOAD_DIR = PROJECT_ROOT.parent / "space-map-downloads"
DB_DIR = DOWNLOAD_DIR / "db"
DB_FILE = DB_DIR / "space-map.db"

# Top-level split inside DOWNLOAD_DIR. Sources are raw external downloads,
# derived/ holds pipeline output (regenerable), archive/ holds bytes kept for
# reference but not on any active code path.
SOURCES_DIR = DOWNLOAD_DIR / "sources"
DERIVED_DIR = DOWNLOAD_DIR / "derived"
ARCHIVE_DIR = DOWNLOAD_DIR / "archive"

SOURCES_POSITION_DIR = SOURCES_DIR / "position"
SOURCES_TEXTURES_DIR = SOURCES_DIR / "textures"
SOURCES_MAPS_DIR = SOURCES_DIR / "maps"
SOURCES_IMAGES_DIR = SOURCES_DIR / "images"
SOURCES_MODELS_DIR = SOURCES_DIR / "models"
SOURCES_METADATA_DIR = SOURCES_DIR / "metadata"
SOURCES_ATMOSPHERE_DIR = SOURCES_DIR / "atmosphere"

# Hand-authored supplemental overlays the automated providers can't discover
# (mirrors sources/models/manual + Commons manual-extra.json). See
# utils/manual_overlay.py.
SOURCES_MANUAL_DIR = SOURCES_METADATA_DIR / "manual"

DERIVED_POSITION_DIR = DERIVED_DIR / "position"
DERIVED_TEXTURES_DIR = DERIVED_DIR / "textures"
DERIVED_MODELS_DIR = DERIVED_DIR / "models"

EXPORT_DIR = PROJECT_ROOT.parent / "space-map-export"
# Build-only sidecar metadata (incremental sidecars, texture/ring metadata.json)
# is mirrored here so EXPORT_DIR can be served as-is to Cloudflare Pages, which
# caps a deployment at 20k files. Layout under this dir mirrors EXPORT_DIR
# exactly; use sidecar_io.mirror_path to translate between the two.
EXPORT_METADATA_DIR = PROJECT_ROOT.parent / "space-map-export-metadata"
