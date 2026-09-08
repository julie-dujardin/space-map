"""Standalone download/processing stage; no database or frontend required."""

import argparse
import logging
from pathlib import Path

import httpx

from space_map_data.utils.paths import SOURCES_IMAGES_DIR, DERIVED_DIR
from .pipeline import download, process


def cli():
    parser = argparse.ArgumentParser(
        description="Prepare official Mars Navcam panoramas, including partial coverage"
    )
    parser.add_argument("stage", choices=["download", "process", "all"])
    parser.add_argument(
        "--missions",
        nargs="+",
        choices=["curiosity", "perseverance"],
        default=["perseverance"],
    )
    parser.add_argument(
        "--source-dir", type=Path, default=SOURCES_IMAGES_DIR / "panoramas"
    )
    parser.add_argument("--output-dir", type=Path, default=DERIVED_DIR / "panoramas")
    parser.add_argument("--start-sol", type=int, default=0)
    parser.add_argument("--end-sol", type=int)
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional maximum panoramas per mission; default: all supported products",
    )
    parser.add_argument(
        "--include-monochrome",
        action="store_true",
        help="Opt in to Curiosity's grayscale Navcam; color Mastcam is a separate collection",
    )
    parser.add_argument(
        "--width", type=int, default=4096, help="Even sphere texture width, 256–8192"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh source metadata and selected images",
    )
    args = parser.parse_args()
    if (
        (args.limit is not None and args.limit < 1)
        or args.start_sol < 0
        or (args.end_sol is not None and args.end_sol < args.start_sol)
    ):
        parser.error("Require positive limit and an ordered, nonnegative sol range")
    if "curiosity" in args.missions and not args.include_monochrome:
        parser.error(
            "Curiosity Navcam is monochrome; use color releases or explicitly opt in with --include-monochrome"
        )
    if args.width % 2 or not 256 <= args.width <= 8192:
        parser.error("Width must be even and between 256 and 8192")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.stage in {"download", "all"}:
        with httpx.Client(
            follow_redirects=True,
            timeout=120,
            transport=httpx.HTTPTransport(retries=3),
            headers={"User-Agent": "SpaceMap panorama data pipeline"},
        ) as client:
            for mission in args.missions:
                download(
                    client,
                    args.source_dir,
                    mission,
                    start_sol=args.start_sol,
                    end_sol=args.end_sol,
                    limit=args.limit,
                    refresh=args.refresh,
                )
    if args.stage in {"process", "all"}:
        for mission in args.missions:
            process(args.source_dir, args.output_dir, mission, width=args.width)


if __name__ == "__main__":
    cli()
