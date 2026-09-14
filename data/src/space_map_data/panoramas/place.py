"""Place the gallery panoramas of the missions the mosaic pipeline does not read.

Most catalogued panoramas never reach the map for want of a body and a
position, not for want of a sphere. A lander has one published place for its
whole mission; a rover has a published traverse, which answers for every sol it
spent standing still.
"""

import argparse
import json
import logging
from pathlib import Path
from urllib.parse import urlencode

import httpx

from . import mer
from .missions import FRAME, LANDERS, body_id, lander_position
from .pipeline import fetch, sha256, write_json
from .releases import refresh_catalog

logger = logging.getLogger(__name__)

M20_RAW = "https://mars.nasa.gov/rss/api/"


def rover_positions(client, cache: Path, mission: str, *, refresh=False):
    """Every sol of a corrected traverse that names one place, and its table."""
    table = fetch(
        client,
        mer.TRAVERSE + mer.TRAVERSE_TABLES[mission],
        cache / mer.TRAVERSE_TABLES[mission],
        refresh=refresh,
    )
    return mer.traverse_sol_positions(mission, table), table


def rover_position(sol_positions: dict, sol: int, mission: str, table: Path) -> dict:
    return {
        **FRAME,
        **sol_positions[sol],
        "elevation_datum": None,
        "method": "corrected traverse; one stop held for the whole sol",
        "reference_point": "rover localization",
        "uncertainty_m": None,
        "source_url": mer.TRAVERSE + mer.TRAVERSE_TABLES[mission],
        "source_sha256": sha256(table),
    }


def sol_date(client, cache: Path, sol: int, *, refresh=False) -> str | None:
    """When a Perseverance sol began, taken from the first frame shot that sol.

    A sol straddles two UTC dates, so this dates the sol rather than the mosaic
    taken during it.
    """
    query = urlencode(
        {
            "feed": "raw_images",
            "category": "mars2020",
            "feedtype": "json",
            "num": 1,
            "page": 0,
            "order": "sol asc",
            "condition_2": f"{sol}:sol:gte",
            "condition_3": f"{sol}:sol:lte",
        }
    )
    found = json.loads(
        fetch(
            client, f"{M20_RAW}?{query}", cache / f"sol{sol:05}.json", refresh=refresh
        ).read_text()
    )
    frames = found.get("images") or []
    return frames[0]["date_taken_utc"] if frames else None


def date_by_sol(client, cache: Path, metadata: dict, *, refresh=False) -> bool:
    """Date a placed sphere the archive left undated, from the sol it names."""
    if metadata.get("mission") != "perseverance" or metadata.get("sol") is None:
        return False
    taken = sol_date(client, cache, metadata["sol"], refresh=refresh)
    if taken is None:
        return False
    metadata.update(
        {
            "capture_time": taken[:10],
            "capture_stop_time": taken[:10],
            "capture_precision": "sol",
            "capture_date_source_url": M20_RAW,
            "capture_date_basis": "first raw frame of the same sol; the sol is "
            "dated, not the mosaic taken during it",
        }
    )
    return True


def place(client, source_dir: Path, output_dir: Path, *, refresh=False):
    """Fill in the body and the position of every gallery panorama that has one.

    A position already recorded is left alone: an exact association beats a
    join on the sol, which only knows where the rover stood, not which mosaic
    it was standing there to build.
    """
    cache = source_dir / "localization"
    traverses = {
        mission: rover_positions(client, cache, mission, refresh=refresh)
        for mission in mer.TRAVERSE_TABLES
    }
    counts: dict[str, int] = {}
    for catalog in sorted(output_dir.glob("*/catalog.json")):
        collection = catalog.parent.name
        changed = 0
        for path in sorted(catalog.parent.glob("*/metadata.json")):
            metadata = json.loads(path.read_text())
            mission = metadata.get("mission")
            dated = bool(metadata.get("start_time") or metadata.get("capture_time"))
            before = (metadata.get("body_id"), bool(metadata.get("position")), dated)
            body = body_id(mission)
            if body and not metadata.get("body_id"):
                metadata["body_id"] = body
            if not metadata.get("position"):
                sol = metadata.get("sol")
                if mission in LANDERS:
                    metadata["position"] = lander_position(mission)
                    metadata["position_status"] = "published landing site"
                elif mission in traverses and sol in traverses[mission][0]:
                    sol_positions, table = traverses[mission]
                    metadata["position"] = rover_position(
                        sol_positions, sol, mission, table
                    )
                    metadata["position_status"] = "corrected traverse sol join"
            # Only a sphere that is placed is worth a request to date it.
            if metadata.get("image") and metadata.get("position") and not dated:
                date_by_sol(client, cache / "sols", metadata, refresh=refresh)
            after = (
                metadata.get("body_id"),
                bool(metadata.get("position")),
                bool(metadata.get("start_time") or metadata.get("capture_time")),
            )
            if before != after:
                write_json(path, metadata)
                changed += 1
        if changed:
            refresh_catalog(output_dir, collection)
            counts[collection] = changed
            logger.info("%s: placed or identified %s panoramas", collection, changed)
    return counts


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with httpx.Client(
        follow_redirects=True, timeout=120, transport=httpx.HTTPTransport(retries=3)
    ) as client:
        counts = place(client, args.source_dir, args.output_dir, refresh=args.refresh)
    print(f"Updated {sum(counts.values())} panoramas across {len(counts)} collections")


if __name__ == "__main__":
    cli()
