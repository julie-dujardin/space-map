"""Rover traverses: the places a rover moved to, and when.

One file for each probe under ``derived/position/traverses/``, named by
``probe_id``. It is for a rover that no SPICE kernel covers, when its archive
states the position of the rover on each product.

    {"schema_version": 1, "probe_id": 113217538, "body_naif": 499,
     "source_url": "https://clpds.bao.ac.cn/",
     "landing_point": {"lat_deg": 25.083304, "lon_deg": 109.908429},
     "waypoints": [{"time": "2021-06-03T09:01:52Z",
                    "lat_deg": 25.083231, "lon_deg": 109.908435}]}

The positions are in the frame of the archive. That frame can differ from the
frame of the map. China's release puts the Tianwen-1 lander 1.3 km from the
place its orbital imagery gives. Distances inside the frame are correct.
``landing_point`` is where the frame puts the landing site. A reader moves each
waypoint by its offset from ``landing_point`` onto the site that the curated
events state.

A waypoint is the first time the archive shows the rover at a place. The rover
stays there until the next waypoint.
"""

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from space_map_data.probes.events import event_jd
from space_map_data.utils.paths import DERIVED_POSITION_DIR

logger = logging.getLogger(__name__)

TRAVERSES_DIR = DERIVED_POSITION_DIR / "traverses"

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Waypoint:
    jd: float
    lat_deg: float
    lon_deg: float


@dataclass(frozen=True)
class Traverse:
    probe_id: int
    body_naif: int
    # The landing site in the frame of the waypoints.
    landing_lat_deg: float
    landing_lon_deg: float
    waypoints: tuple[Waypoint, ...]

    def from_site(self, lat_deg: float, lon_deg: float) -> tuple[Waypoint, ...]:
        """The waypoints in the frame that puts the landing site at
        ``(lat_deg, lon_deg)``."""
        # A degree of longitude is a different length at the two latitudes.
        stretch = math.cos(math.radians(self.landing_lat_deg)) / math.cos(
            math.radians(lat_deg)
        )
        return tuple(
            Waypoint(
                w.jd,
                lat_deg + (w.lat_deg - self.landing_lat_deg),
                lon_deg + (w.lon_deg - self.landing_lon_deg) * stretch,
            )
            for w in self.waypoints
        )


def _read(path: Path) -> Traverse:
    data = json.loads(path.read_text())
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"{path}: schema {data['schema_version']} is not supported")
    waypoints = tuple(
        Waypoint(event_jd(w["time"]), float(w["lat_deg"]), float(w["lon_deg"]))
        for w in data["waypoints"]
    )
    if any(a.jd >= b.jd for a, b in zip(waypoints, waypoints[1:])):
        raise ValueError(f"{path}: waypoints are not in time order")
    return Traverse(
        probe_id=int(data["probe_id"]),
        body_naif=int(data["body_naif"]),
        landing_lat_deg=float(data["landing_point"]["lat_deg"]),
        landing_lon_deg=float(data["landing_point"]["lon_deg"]),
        waypoints=waypoints,
    )


def load_traverses(root: Path | None = None) -> dict[int, Traverse]:
    """Every traverse on disk, by probe id. Empty when none was built."""
    out: dict[int, Traverse] = {}
    for path in sorted((root or TRAVERSES_DIR).glob("*.json")):
        traverse = _read(path)
        out[traverse.probe_id] = traverse
    logger.info("traverses: %d loaded", len(out))
    return out


def write_traverse(
    root: Path,
    *,
    probe_id: int,
    body_naif: int,
    source_url: str,
    landing_point: tuple[float, float],
    waypoints: list[tuple[str, float, float]],
) -> Path:
    """Write the traverse of one probe. ``waypoints`` are ``(time, lat, lon)``."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{probe_id}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "probe_id": probe_id,
                "body_naif": body_naif,
                "source_url": source_url,
                "landing_point": {
                    "lat_deg": landing_point[0],
                    "lon_deg": landing_point[1],
                },
                "waypoints": [
                    {"time": time, "lat_deg": lat, "lon_deg": lon}
                    for time, lat, lon in waypoints
                ],
            },
            indent=1,
        )
        + "\n"
    )
    return path
