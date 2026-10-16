"""Lunokhod traverses, from the routes mapped on LRO images.

Karachevtseva et al. traced both routes on LROC NAC images. The papers give
the place of each lunar night, and the Lunokhod 2 paper also dates its points
of interest. Both tables are tied to laser ranging: the final place of each
rover is the position of its reflector. The events put Luna 21 where the 2017
paper does, and Luna 17 1 m from where the 2013 paper does.

    uv run python -m space_map_data.probes.lunokhod_traverse
"""

import argparse
import datetime
import logging
import math
from pathlib import Path
from typing import NamedTuple

from space_map_data.probes.traverses import TRAVERSES_DIR, write_traverse

logger = logging.getLogger(__name__)

MOON_NAIF = 301
MOON_RADIUS_M = 1737400.0

# The 2017 paper states a plane accuracy of about 2 m; the 2013 paper maps at
# 0.5 m a pixel and states none. A row closer than this to the rover's last
# place is the same place.
SAME_PLACE_M = 2.0


class Row(NamedTuple):
    """A place from a table, east longitude. ``dates`` are the days the table
    puts the rover there, the first day of each stay."""

    dates: tuple[str, ...]
    lat_deg: float
    lon_deg: float


class Rover(NamedTuple):
    probe_id: int
    sources: tuple[str, ...]
    landing: tuple[float, float]
    rows: tuple[Row, ...]


# Karachevtseva et al. 2013, PSS 85, Table 5. The table gives west longitude.
LUNOKHOD_1 = Rover(
    probe_id=38862849,
    sources=("karachevtseva_2013",),
    landing=(38.23761, -35.00164),
    rows=(
        Row(("1970-11-23",), 38.23393, -34.99757),
        Row(("1970-12-23",), 38.19845, -34.98082),
        Row(("1971-01-21",), 38.23742, -35.00159),
        Row(("1971-02-22",), 38.27192, -35.00720),
        Row(("1971-03-22",), 38.26539, -35.01416),
        Row(("1971-04-21",), 38.27774, -35.01038),
        Row(("1971-05-20",), 38.28150, -35.01446),
        Row(("1971-06-19",), 38.31882, -35.01168),
        Row(("1971-07-18",), 38.31716, -35.00860),
        Row(("1971-08-17",), 38.31513, -35.00789),
        Row(("1971-09-29",), 38.31516, -35.00796),
    ),
)

# Karachevtseva et al. 2017, Icarus 283: the points of interest of Table 7 and
# the nights of Table 6, in time order. Table 7 lists the landing module first.
LUNOKHOD_2 = Rover(
    probe_id=42098689,
    sources=("karachevtseva_2017",),
    landing=(25.99910, 30.40754),
    rows=(
        Row(("1973-01-16",), 25.99947, 30.40705),
        Row(("1973-01-16",), 25.99926, 30.40776),
        Row(("1973-01-25",), 25.97351, 30.43749),
        Row(("1973-02-09",), 25.97350, 30.43749),
        Row(("1973-02-11",), 25.90731, 30.45223),
        Row(("1973-02-12",), 25.89795, 30.45234),
        Row(("1973-02-12",), 25.87743, 30.45742),
        Row(("1973-02-19",), 25.74316, 30.44376),
        Row(("1973-02-19", "1973-03-13"), 25.73441, 30.45239),
        Row(("1973-02-23",), 25.76436, 30.47531),
        Row(("1973-03-12",), 25.76455, 30.47489),
        Row(("1973-03-14",), 25.79006, 30.48155),
        Row(("1973-03-15",), 25.80803, 30.54591),
        Row(("1973-03-16",), 25.79995, 30.61975),
        Row(("1973-03-18",), 25.80347, 30.72665),
        Row(("1973-03-21",), 25.82145, 30.84048),
        Row(("1973-03-22",), 25.82145, 30.84048),
        Row(("1973-04-10",), 25.78983, 30.87385),
        Row(("1973-04-11",), 25.79523, 30.89129),
        Row(("1973-04-15",), 25.78517, 30.89013),
        Row(("1973-04-16",), 25.79656, 30.90668),
        Row(("1973-04-16",), 25.78380, 30.92409),
        Row(("1973-04-22",), 25.82212, 30.91493),
        Row(("1973-05-10",), 25.83233, 30.92211),
    ),
)

ROVERS = {"lunokhod-1": LUNOKHOD_1, "lunokhod-2": LUNOKHOD_2}


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[0] + b[0]) / 2)
    dy = math.radians(b[0] - a[0])
    dx = math.radians(b[1] - a[1]) * math.cos(lat)
    return MOON_RADIUS_M * math.hypot(dx, dy)


def waypoints(rover: Rover) -> list[tuple[str, float, float]]:
    """A waypoint for each new place. The tables date a place to the day only,
    so the places of one day are spread over it in table order. A later row of
    the same place is the better tied one, so its coordinate is kept."""
    visits = sorted(
        (
            (date, i, (row.lat_deg, row.lon_deg))
            for i, row in enumerate(rover.rows)
            for date in row.dates
        ),
    )
    track: list[tuple[str, tuple[float, float]]] = []
    last = rover.landing
    for date, _, place in visits:
        if _distance_m(last, place) >= SAME_PLACE_M:
            track.append((date, place))
        elif track:
            track[-1] = (track[-1][0], place)
        last = place
    days: dict[str, list[tuple[float, float]]] = {}
    for date, place in track:
        days.setdefault(date, []).append(place)
    out = []
    for date, places in days.items():
        if len(places) == 1:
            out.append((date, *places[0]))
            continue
        day = datetime.datetime.fromisoformat(date)
        for i, place in enumerate(places):
            moment = day + datetime.timedelta(days=(i + 1) / (len(places) + 1))
            out.append((moment.strftime("%Y-%m-%dT%H:%MZ"), *place))
    return out


def build(rover: Rover, output_dir: Path) -> Path:
    track = waypoints(rover)
    path = write_traverse(
        output_dir,
        probe_id=rover.probe_id,
        body_naif=MOON_NAIF,
        sources=rover.sources,
        landing_point=rover.landing,
        waypoints=track,
    )
    logger.info(
        "probe %d: %d waypoints, %s to %s",
        rover.probe_id,
        len(track),
        track[0][0] if track else "-",
        track[-1][0] if track else "-",
    )
    return path


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rovers", nargs="+", choices=ROVERS, default=list(ROVERS))
    parser.add_argument("--output-dir", type=Path, default=TRAVERSES_DIR)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for name in args.rovers:
        build(ROVERS[name], args.output_dir)


if __name__ == "__main__":
    cli()
