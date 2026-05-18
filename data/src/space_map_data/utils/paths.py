from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[3]
CONFIG_FILE = DATA_DIR / "config.toml"

PROJECT_ROOT = DATA_DIR.parent

DOWNLOAD_DIR = PROJECT_ROOT.parent / "space-map-downloads"
DB_DIR = DOWNLOAD_DIR / "db"
DB_FILE = DB_DIR / "space-map.db"

EXPORT_DIR = PROJECT_ROOT.parent / "space-map-export"
# Build-only sidecar metadata (incremental sidecars, texture/ring metadata.json)
# is mirrored here so EXPORT_DIR can be served as-is to Cloudflare Pages, which
# caps a deployment at 20k files. Layout under this dir mirrors EXPORT_DIR
# exactly; use sidecar_io.mirror_path to translate between the two.
EXPORT_METADATA_DIR = PROJECT_ROOT.parent / "space-map-export-metadata"
