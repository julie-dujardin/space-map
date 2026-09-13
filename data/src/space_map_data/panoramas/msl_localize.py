"""Place Curiosity's released colour panoramas on the traverse.

The colour releases carry a caption but no localization: unlike the Navcam
mosaics they have no PDS label with a site and drive. The caption does name
the capture sol, and PLACES records where the rover stood at the end of every
drive, so the sol joins the two. Between drives the rover does not move, which
is why a sol PLACES never mentions still resolves exactly.
"""

import argparse
import csv
import json
import logging
from pathlib import Path
import re

from .pipeline import PLACES, sha256, write_json
from .releases import refresh_catalog

logger = logging.getLogger(__name__)

# "the 1,647th Martian day, or sol" and "(Sol 2137)"; the ordinal form wins
# because captions also cite the sol of an earlier drive.
ORDINAL = re.compile(
    r"\b(\d{1,2},?\d{3}|\d{1,4})(?:st|nd|rd|th)\s+(?:Martian\s+day|sol)\b", re.I
)
PLAIN = re.compile(r"\bsol\s+(\d{1,4})\b", re.I)


def caption_sol(text: str) -> int | None:
    """The capture sol a NASA caption states, or None."""
    for pattern in (ORDINAL, PLAIN):
        match = pattern.search(text or "")
        if match:
            return int(match[1].replace(",", ""))
    return None


def drives(path: Path) -> list[dict]:
    """Rover stopping points in sol order, each with the sol it was reached."""
    rows = []
    with path.open() as stream:
        for row in csv.DictReader(stream):
            if row["frame"] != "ROVER":
                continue
            rows.append(
                {
                    "sol": int(row["sol"]),
                    "site": int(row["site"]),
                    "drive": int(row["drive"]),
                    "latitude": float(row["planetocentric_latitude"]),
                    "longitude": float(row["longitude"]) % 360,
                    "elevation_m": float(row["elevation"]),
                    "easting": float(row["easting"]),
                    "northing": float(row["northing"]),
                }
            )
    rows.sort(key=lambda r: (r["sol"], r["site"], r["drive"]))
    return rows


def locate(rows: list[dict], sol: int) -> tuple[dict, float] | None:
    """Where the rover stood on `sol`, with how far it drove that sol.

    The last stopping point up to and including the sol is where the rover
    ended it. A sol with no stopping point of its own was spent parked, so
    that distance is zero and the fix is exact.
    """
    before = [r for r in rows if r["sol"] < sol]
    same = [r for r in rows if r["sol"] == sol]
    if not same:
        return (before[-1], 0.0) if before else None
    start = before[-1] if before else same[0]
    spread = max(
        (
            (r["easting"] - start["easting"]) ** 2
            + (r["northing"] - start["northing"]) ** 2
        )
        ** 0.5
        for r in same
    )
    return same[-1], spread


def position_of(row: dict, spread: float, table_sha: str) -> dict:
    return {
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "elevation_m": row["elevation_m"],
        "latitude_type": "planetocentric",
        "longitude_direction": "east",
        "longitude_range": [0, 360],
        "elevation_datum": "source Mars geoid",
        "method": "caption capture sol joined to the PLACES stopping point it ended on",
        "reference_point": "rover localization",
        # A sol the rover drove leaves the panorama anywhere along that drive.
        "uncertainty_m": round(spread, 1) or None,
        "source_url": PLACES,
        "source_sha256": table_sha,
    }


def capture_sol(metadata: dict) -> tuple[int | None, str]:
    """The sol a product was captured on, and where that came from.

    A reviewed sol on the product wins: it is checked in against the source,
    whereas the caption is re-read from NASA on every refresh.
    """
    if metadata.get("sol"):
        return metadata["sol"], metadata.get("sol_basis", "reviewed product record")
    stated = caption_sol(metadata.get("description", ""))
    if stated:
        return stated, "NASA caption"
    return None, "no capture sol stated"


def apply(derived_dir: Path, positions_path: Path, collection="curiosity") -> int:
    rows = drives(positions_path)
    table_sha = sha256(positions_path)
    catalog = json.loads((derived_dir / collection / "catalog.json").read_text())
    placed = 0
    for item in catalog["panoramas"]:
        path = derived_dir / item["metadata"]
        metadata = json.loads(path.read_text())
        if not metadata.get("image"):
            continue
        sol, basis = capture_sol(metadata)
        found = locate(rows, sol) if sol else None
        if found is None:
            metadata["position_status"] = (
                basis if sol is None else f"sol {sol} precedes the first PLACES drive"
            )
            write_json(path, metadata)
            continue
        row, spread = found
        metadata.update(
            {
                "sol": sol,
                "body": "mars",
                "body_id": "naif-499",
                "site": row["site"],
                "drive": row["drive"],
                "position": position_of(row, spread, table_sha),
                "position_status": "caption sol joined to PLACES",
                "localization_evidence": {
                    "capture_sol": sol,
                    "capture_sol_basis": basis,
                    "stopping_point_sol": row["sol"],
                    "site_drive": [row["site"], row["drive"]],
                    "sol_drive_distance_m": round(spread, 1),
                    "source_url": PLACES,
                    "table_sha256": table_sha,
                },
            }
        )
        write_json(path, metadata)
        placed += 1
        logger.info(
            "Placed %s at sol %d via site %d drive %d (%.1f m driven that sol)",
            metadata["id"],
            sol,
            row["site"],
            row["drive"],
            spread,
        )
    refresh_catalog(derived_dir, collection)
    return placed


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--positions", type=Path, required=True)
    parser.add_argument("--collection", default="curiosity")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"Placed {apply(args.directory, args.positions, args.collection)} panoramas")


if __name__ == "__main__":
    cli()
