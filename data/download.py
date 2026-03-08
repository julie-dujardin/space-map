"""
Space-map data downloader.

Usage:
  uv run download.py                          # all sources, no limit
  uv run download.py --sources celestrak sbdb # specific sources
  uv run download.py --limit 100              # max records/bodies per source
  uv run download.py --sources horizons --limit 5  # quick test
  uv run download.py --sources probes --limit 10  # first 10 spacecraft trajectories
"""

import argparse
import json
from pathlib import Path

import httpx

from downloaders import celestrak, horizons, probes, sbdb

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)
METADATA_FILE = DOWNLOAD_DIR / "metadata.json"
USER_AGENT = "space-map/0.1 (github personal project)"

SOURCES = {
    "celestrak": (celestrak.download, DOWNLOAD_DIR / "celes-trak"),
    "sbdb": (sbdb.download, DOWNLOAD_DIR / "sbdb"),
    "horizons": (horizons.download, DOWNLOAD_DIR / "horizons"),
    "probes": (probes.download, DOWNLOAD_DIR / "probes"),
}


def update_metadata(results: dict) -> None:
    existing = {}
    if METADATA_FILE.exists():
        existing = json.loads(METADATA_FILE.read_text())
    existing.update(results)
    METADATA_FILE.write_text(json.dumps(existing, indent=2))
    print("Metadata written → metadata.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download space-map data")
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=[*SOURCES.keys(), "all"],
        default=["all"],
        metavar="SOURCE",
        help=f"Sources to download: {', '.join(SOURCES)}, all (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50_000,
        metavar="N",
        help="Max records/bodies per source (default: 50000)",
    )
    parser.add_argument(
        "--no-limit",
        dest="limit",
        action="store_const",
        const=None,
        help="Remove the row limit and download everything",
    )
    args = parser.parse_args()
    selected = list(SOURCES.keys()) if "all" in args.sources else args.sources

    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=60.0,
    ) as client:
        results = {}
        for name in selected:
            fn, out_dir = SOURCES[name]
            results[name] = fn(client, out_dir, limit=args.limit)

        update_metadata(results)

    print("Done.")


if __name__ == "__main__":
    main()
