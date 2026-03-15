from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[3]
DOWNLOAD_DIR = DATA_DIR.parent.parent / "space-map-downloads"
DB_DIR = DOWNLOAD_DIR / "db"
DB_FILE = DB_DIR / "space-map.db"
