from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[3]
CONFIG_FILE = DATA_DIR / "config.toml"

PROJECT_ROOT = DATA_DIR.parent

DOWNLOAD_DIR = PROJECT_ROOT.parent / "space-map-downloads"
DB_DIR = DOWNLOAD_DIR / "db"
DB_FILE = DB_DIR / "space-map.db"

EXPORT_DIR = PROJECT_ROOT.parent / "space-map-export"
