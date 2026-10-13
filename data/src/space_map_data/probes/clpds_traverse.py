"""Rover traverses from the labels of China's planetary data release.

Each product label of a rover instrument states the position of the rover.
The labels of one camera in time order give the traverse. The panorama
pipeline downloads the labels (`panoramas/clpds.py`).

    uv run python -m space_map_data.probes.clpds_traverse
"""

import argparse
import logging
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from space_map_data.probes.traverses import TRAVERSES_DIR, write_traverse
from space_map_data.utils.paths import PANORAMA_SOURCES_DIR

logger = logging.getLogger(__name__)

SOURCE_URL = "https://clpds.bao.ac.cn/"
# The labels state positions to six decimals.
PLACES = 6


@dataclass(frozen=True)
class Rover:
    """The labels of one rover, and how to find its lander in their frame."""

    slug: str
    probe_id: int
    body_naif: int
    radius_m: float
    # Lander position from the first stop, metres east and north. For labels
    # that do not state the lander position.
    lander_from_first_stop_m: tuple[float, float] | None = None


ROVERS = {
    rover.slug: rover
    for rover in (
        # Measured on the sweep of the first stop. The lander footpads are 18°
        # to 26° below the horizon of a lens 1.54 m above the ground.
        Rover("zhurong", 113217538, 499, 3389500.0, (-0.3, 4.3)),
        Rover("yutu-2", 110784513, 301, 1737400.0),
    )
}


def _field(root, path: str) -> str | None:
    found = root.find(path)
    return found.text.strip() if found is not None and found.text else None


def read_position(raw: str) -> dict | None:
    """The time and position that one label states, or None when it states no
    rover position.

    Tags are compared in lower case. Their spelling changes between missions.
    """
    root = ET.fromstring(raw)
    for node in root.iter():
        node.tag = node.tag.split("}")[-1].lower()
    time = _field(root, ".//start_date_time")
    lat = _field(root, ".//rover_location/latitude")
    lon = _field(root, ".//rover_location/longitude")
    if time is None or lat is None or lon is None:
        return None
    lander = (
        _field(root, ".//lander_location/latitude"),
        _field(root, ".//lander_location/longitude"),
    )
    return {
        # A drive is not dated to a fraction of a second.
        "time": time.split(".")[0].rstrip("Z") + "Z",
        "lat": round(float(lat), PLACES),
        "lon": round(float(lon) % 360, PLACES),
        "lander": (
            (round(float(lander[0]), PLACES), round(float(lander[1]) % 360, PLACES))
            if lander[0] is not None and lander[1] is not None
            else None
        ),
    }


def waypoints(positions: list[dict]) -> list[tuple[str, float, float]]:
    """The first label at each place the rover came to, in time order."""
    out: list[tuple[str, float, float]] = []
    for position in sorted(positions, key=lambda p: p["time"]):
        place = (position["lat"], position["lon"])
        if not out or out[-1][1:] != place:
            out.append((position["time"], *place))
    return out


def landing_point(rover: Rover, positions: list[dict]) -> tuple[float, float]:
    """The position of the lander in the frame of the labels."""
    stated = {p["lander"] for p in positions if p["lander"] is not None}
    if len(stated) == 1:
        return stated.pop()
    if stated:
        raise ValueError(f"{rover.slug}: labels disagree on where the lander is")
    if rover.lander_from_first_stop_m is None:
        raise ValueError(f"{rover.slug}: nothing states where the lander is")
    first = min(positions, key=lambda p: p["time"])
    east_m, north_m = rover.lander_from_first_stop_m
    degree_m = rover.radius_m * math.pi / 180
    return (
        round(first["lat"] + north_m / degree_m, PLACES),
        round(
            first["lon"] + east_m / (degree_m * math.cos(math.radians(first["lat"]))),
            PLACES,
        ),
    )


def build(rover: Rover, source_dir: Path, output_dir: Path) -> Path:
    labels = sorted((source_dir / rover.slug / "labels").iterdir())
    positions = [
        position
        for label in labels
        if (position := read_position(label.read_text())) is not None
    ]
    if not positions:
        raise ValueError(f"{rover.slug}: no label states a rover position")
    track = waypoints(positions)
    path = write_traverse(
        output_dir,
        probe_id=rover.probe_id,
        body_naif=rover.body_naif,
        source_url=SOURCE_URL,
        landing_point=landing_point(rover, positions),
        waypoints=track,
    )
    logger.info(
        "%s: %d waypoints from %d of %d labels, %s to %s",
        rover.slug,
        len(track),
        len(positions),
        len(labels),
        track[0][0],
        track[-1][0],
    )
    return path


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rovers", nargs="+", choices=sorted(ROVERS), default=ROVERS)
    parser.add_argument("--source-dir", type=Path, default=PANORAMA_SOURCES_DIR)
    parser.add_argument("--output-dir", type=Path, default=TRAVERSES_DIR)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for slug in args.rovers:
        build(ROVERS[slug], args.source_dir, args.output_dir)


if __name__ == "__main__":
    cli()
