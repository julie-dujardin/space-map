#!/usr/bin/env python3
"""One-time migration: convert wikidata/id_map.json → wikidata/ids/*.csv

Also incorporates _partial.json if present. Does NOT delete old files —
verify the output and clean up manually.
"""

import csv
import io
import json
import sys
from pathlib import Path

# Resolve the wikidata download directory
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from space_map_data.utils.paths import DOWNLOAD_DIR  # noqa: E402

WIKIDATA_DIR = DOWNLOAD_DIR / "wikidata"
ID_MAP_FILE = WIKIDATA_DIR / "id_map.json"
PARTIAL_FILE = WIKIDATA_DIR / "_partial.json"
IDS_DIR = WIKIDATA_DIR / "ids"


def write_csv(key: str, mapping: dict[str, list[str]]) -> None:
    csv_path = IDS_DIR / f"{key}.csv"
    buf = io.StringIO()
    writer = csv.writer(buf)
    for search_term, qids in sorted(mapping.items()):
        joined = " ".join(qids) if isinstance(qids, list) else qids
        writer.writerow([search_term, joined])
    csv_path.write_text(buf.getvalue())
    print(f"  {csv_path.name}: {len(mapping)} entries")


def main() -> None:
    if not ID_MAP_FILE.exists():
        print(f"No {ID_MAP_FILE} found — nothing to migrate.")
        return

    id_map: dict[str, dict[str, list[str]]] = json.loads(ID_MAP_FILE.read_text())

    # Incorporate partial progress if it matches a source not yet in id_map
    if PARTIAL_FILE.exists():
        partial = json.loads(PARTIAL_FILE.read_text())
        pid = partial.get("pid")
        if pid and pid not in id_map:
            print(f"Incorporating partial progress for {pid}")
            id_map[pid] = partial["mapping"]

    IDS_DIR.mkdir(exist_ok=True)

    print(f"Migrating {len(id_map)} sources from id_map.json → ids/*.csv")
    for key, mapping in id_map.items():
        write_csv(key, mapping)

    print(
        "\nDone. Verify the output, then delete id_map.json and _partial.json manually."
    )


if __name__ == "__main__":
    main()
