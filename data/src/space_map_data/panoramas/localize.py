"""Associate Mastcam-Z observation sequences with exact PLACES positions."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import logging
from pathlib import Path
import re
from urllib.parse import urlencode

import httpx

from .pipeline import (
    M20_PLACES,
    bracketed,
    fetch,
    midpoint,
    positions,
    sha256,
    write_json,
)
from .releases import API, plain, refresh_catalog

logger = logging.getLogger(__name__)


def frame_counters(rows, sol, sequence):
    result = set()
    for row in rows:
        title = plain(row["title"]["rendered"])
        match = re.search(
            r"^Z[LR]0\s+(\d+)\s+.*?\bN(\d{3})(\d{4})(ZCAM\d+)\b", title, re.I
        )
        if match and int(match[1]) == sol and match[4].upper() == sequence:
            result.add((int(match[2]), int(match[3])))
    return result


def common_position(counters, lookup, order):
    """Where a sequence was shot from, bounded where it is not one exact place.

    PLACES records the drives it was corrected for, and a sequence can run
    across several of them, so a counter it skips is placed between its
    neighbours and a sequence that moved is placed halfway along what it
    covered. Either way the range travels with the position.
    """
    if not counters:
        raise ValueError("Nothing states the rover position")
    located: dict[tuple, dict] = {}
    for key in sorted(counters):
        found = lookup.get(key) or bracketed(lookup, order, key)
        if found is None:
            raise ValueError(f"PLACES does not reach site/drive {key}")
        located[key] = found
    ends = sorted(located)
    # Only the place matters here; two fixes can reach it by different routes
    # and carry different ranges for having done so.
    where = {
        (found["latitude"], found["longitude"], found["elevation_m"])
        for found in located.values()
    }
    if len(where) == 1:
        return dict(located[ends[0]])
    return midpoint(
        located[ends[0]],
        located[ends[-1]],
        (ends[0], ends[-1]),
        "midpoint of the stops the sequence was shot across",
    )


def localize(client, source_dir):
    directory = source_dir / "mastcamz"
    cache = directory / "localization"
    table = fetch(client, M20_PLACES, cache / "best_interp.csv")
    fetch(client, M20_PLACES + ".xml", cache / "best_interp.csv.xml")
    lookup = positions("perseverance", table)
    order = sorted(lookup)
    table_hash = sha256(table)
    # PLACES records one row per drive step, so a sol with no row is a sol the
    # rover did not move on: it stood where the last earlier row left it.
    timeline = []
    sol_counters = {}
    with table.open() as stream:
        for row in csv.DictReader(stream):
            if row["frame"] == "ROVER":
                counter = (int(row["site"]), int(row["drive"]))
                timeline.append((int(row["sol"]), counter))
                sol_counters.setdefault(int(row["sol"]), set()).add(counter)

    # PLACES is written in sol order, but sorting says so rather than trusting it.
    timeline.sort(key=lambda row: row[0])

    def standing_at(sol):
        """Where the rover already was when a sol began."""
        found = [counter for known, counter in timeline if known < sol]
        return found[-1] if found else None

    inventory = json.loads((directory / "inventory.json").read_text())
    path = directory / "localizations.json"
    results = json.loads(path.read_text()) if path.exists() else {}

    def inspect(product):
        identity = product["id"]
        if (
            results.get(identity, {}).get("position")
            and results[identity].get("table_sha256") == table_hash
        ):
            return identity, results[identity]
        pages = []
        try:
            if product["target"] == "360":
                match = re.search(r"Sols?(\d+)(?:-(\d+))?", product["sequence"], re.I)
                if match is None:
                    raise ValueError("No complete capture-sol interval")
                start, stop = int(match[1]), int(match[2] or match[1])
                counters = set().union(
                    *(sol_counters.get(sol, set()) for sol in range(start, stop + 1))
                )
                # Only a sol with no row of its own needs the position the
                # rover already stood at; adding it to an interval PLACES
                # covers would invent a second position the rover never held.
                if any(sol not in sol_counters for sol in range(start, stop + 1)):
                    standing = standing_at(start)
                    if standing is None and not counters:
                        raise ValueError("Capture interval precedes the PLACES record")
                    counters.add(standing or next(iter(counters)))
                elif not counters:
                    raise ValueError("Capture interval precedes the PLACES record")
                method = (
                    "one identical PLACES position throughout published sol interval"
                )
            else:
                match = re.search(r"ZCAM\d+", product["sequence"])
                if match is None:
                    raise ValueError("Missing observation sequence identifier")
                sequence = match[0]
                counters, page = set(), 1
                while True:
                    url = (
                        API
                        + "gallery_item?"
                        + urlencode(
                            {
                                "gallery": 42,
                                "search": f"{product['sol']:04} {sequence}",
                                "per_page": 100,
                                "page": page,
                                "_fields": "id,title,link",
                            }
                        )
                    )
                    destination = (
                        cache / f"sol{product['sol']:04}-{sequence}-{page}.json"
                    )
                    try:
                        rows = json.loads(fetch(client, url, destination).read_text())
                    except httpx.HTTPStatusError as error:
                        if (
                            error.response.status_code == 400
                            and error.response.json().get("code")
                            == "rest_post_invalid_page_number"
                        ):
                            break
                        raise
                    pages.append({"url": url, "sha256": sha256(destination)})
                    counters.update(frame_counters(rows, product["sol"], sequence))
                    if len(rows) < 100:
                        break
                    page += 1
                method = "exact observation sol/sequence → calibrated-frame site/drive → PLACES"
            located = common_position(counters, lookup, order)
            position = {
                "latitude_type": "planetocentric",
                "longitude_direction": "east",
                "longitude_range": [0, 360],
                "elevation_datum": "Mars MOLA areoid",
                "uncertainty_m": None,
                "reference_point": "rover localization",
                "source_url": M20_PLACES,
                # Last, so a fix that is only bounded keeps its own range.
                **located,
                # Both halves of the provenance: how the counters were found,
                # and, where the fix is only bounded, how it was arrived at
                # from them. Spreading `located` alone would drop the route.
                "method": (
                    f"{method}; {located['method']}"
                    if located.get("method")
                    else method
                ),
            }
            record = {
                "position": position,
                "site_drive_counters": sorted(counters),
                "table_sha256": table_hash,
                "frame_searches": pages,
            }
        except (ValueError, httpx.HTTPError) as error:
            record = {
                "position": None,
                "reason": str(error),
                "table_sha256": table_hash,
                "frame_searches": pages,
            }
        return identity, record

    with ThreadPoolExecutor(max_workers=2) as pool:
        for count, (identity, record) in enumerate(
            pool.map(inspect, inventory["products"]), 1
        ):
            results[identity] = record
            if count % 20 == 0:
                write_json(path, results)
                logger.info(
                    "Localization: %s/%s checked; %s exact matches",
                    count,
                    len(inventory["products"]),
                    sum(bool(v.get("position")) for v in results.values()),
                )
    write_json(path, results)


def apply_localizations(source_dir, output_dir):
    results = json.loads((source_dir / "mastcamz" / "localizations.json").read_text())
    for path in (output_dir / "mastcamz").glob("*/metadata.json"):
        metadata = json.loads(path.read_text())
        record = results.get(metadata["id"])
        if record is None:
            continue
        metadata["position"] = record["position"]
        metadata["position_status"] = (
            (
                "archive association bounded to a stretch of traverse"
                if record["position"].get("position_bounds")
                else "exact archive association"
            )
            if record["position"]
            else record["reason"]
        )
        metadata["localization_evidence"] = record
        write_json(path, metadata)
    refresh_catalog(output_dir, "mastcamz")


def cli():
    parser = argparse.ArgumentParser(
        description="Join Mastcam-Z mosaics to authoritative rover positions"
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--apply-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not args.apply_only:
        with httpx.Client(
            follow_redirects=True, timeout=120, transport=httpx.HTTPTransport(retries=3)
        ) as client:
            localize(client, args.source_dir)
    if args.output_dir:
        apply_localizations(args.source_dir, args.output_dir)


if __name__ == "__main__":
    cli()
