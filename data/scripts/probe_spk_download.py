"""Standalone CLI for the spacecraft SPK downloader.

Thin wrapper around `ProbesDownloader` — the actual provider lives in
`space_map_data.download.providers.objects.probes` and is also wired into
the global `space-map-download` command via `download.common`. Use this
script for ad-hoc invocation with `--missions` / `--max-mib` overrides
without running every other downloader.

Run from data/:
    uv run python scripts/probe_spk_download.py
    uv run python scripts/probe_spk_download.py --missions VOYAGER JUNO
    uv run python scripts/probe_spk_download.py --max-mib 500
"""

import argparse
import logging
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.download.providers.objects.probes import (  # noqa: E402
    ProbesDownloader,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--missions", nargs="+", help="restrict to these mission names")
    p.add_argument(
        "--max-mib",
        type=float,
        default=None,
        help="skip any mission whose total kept-SPK size exceeds this (MiB)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    with httpx.Client(follow_redirects=True) as client:
        ProbesDownloader(client).download(missions=args.missions, max_mib=args.max_mib)
    return 0


if __name__ == "__main__":
    sys.exit(main())
