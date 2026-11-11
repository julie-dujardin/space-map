"""Ingenuity's flights, from the location map of Perseverance.

The map publishes each airfield and the ground track of each flight
(`download/providers/ingenuity.py`). Both are in the frame of the rover
localizations, which Perseverance's SPICE kernels share. The landing event
names the first airfield, so the waypoints do not move.

The map dates a track only at its two ends. Each track is sampled at a steady
rate, so the samples are spread evenly between the ends. Where the telemetry
dropped samples, the helicopter is ahead of the clock in mid-flight and lands
on time.

    uv run python -m space_map_data.probes.ingenuity_traverse
"""

import argparse
import bisect
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import spiceypy

from space_map_data.download.providers.ingenuity import (
    FLIGHT_PATH_FILE,
    INGENUITY_DIR,
    SCLK_FILE,
    WAYPOINTS_FILE,
)
from space_map_data.probes.traverses import (
    TRAVERSES_DIR,
    distance_m,
    write_traverse,
)
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

PROBE_ID = 113246209
MARS_NAIF = 499
M2020_CLOCK = -168
SOURCES = ("m20_heli",)

# The newest leap-second kernel sorts last, so it is loaded last and wins.
_LSK_DIR = SOURCES_POSITION_DIR / "spice-kernels" / "lsk"
# The sphere of the map's projection.
_RADIUS_M = 3396190.0
# The tracks start and end on their airfields to the millimetre. A larger gap
# means that a track is paired with the wrong flight.
_ON_AIRFIELD_M = 1.0
# Eight decimals of a degree are less than a millimetre on Mars.
PLACES = 8


@dataclass(frozen=True)
class Airfield:
    lat_deg: float
    lon_deg: float
    # Rover clock seconds when the helicopter came to rest here.
    rest_sclk: float


@dataclass(frozen=True)
class Track:
    # `(lon_deg, lat_deg)` in time order.
    points: tuple[tuple[float, float], ...]
    takeoff_sclk: float
    landing_sclk: float


def read_airfields(raw: dict) -> list[Airfield]:
    """The airfields in time order. The first is where the rover set the
    helicopter down."""
    out = [
        Airfield(
            float(f["properties"]["Lat"]),
            float(f["properties"]["Lon"]),
            float(f["properties"]["SCLK_START"]),
        )
        for f in raw["features"]
    ]
    return sorted(out, key=lambda a: a.rest_sclk)


def read_tracks(raw: dict) -> list[Track]:
    """The ground tracks in time order."""
    out = [
        Track(
            tuple(
                (float(lon), float(lat))
                for lon, lat, *_ in f["geometry"]["coordinates"]
            ),
            float(f["properties"]["SCLK_START"]),
            float(f["properties"]["SCLK_END"]),
        )
        for f in raw["features"]
    ]
    return sorted(out, key=lambda t: t.takeoff_sclk)


def flights(
    airfields: list[Airfield], tracks: list[Track]
) -> list[tuple[Track, Airfield]]:
    """Each track with the airfield it lands on.

    The clock places a track between two airfields. The map numbers the
    tracks of flights 12 and 13 the other way round, so their numbers are
    not used.
    """
    if len(tracks) != len(airfields) - 1:
        raise ValueError(f"{len(tracks)} tracks for {len(airfields)} airfields")
    rests = [a.rest_sclk for a in airfields]
    out = []
    for i, track in enumerate(tracks):
        n = bisect.bisect_right(rests, track.takeoff_sclk)
        if n != i + 1:
            raise ValueError(f"track {i + 1} takes off after airfield {n - 1}")
        start, end = airfields[n - 1], airfields[n]
        if not track.takeoff_sclk < track.landing_sclk <= end.rest_sclk:
            raise ValueError(f"track {i + 1} does not land on airfield {n}")
        for airfield, (lon, lat) in ((start, track.points[0]), (end, track.points[-1])):
            gap = distance_m(
                (airfield.lat_deg, airfield.lon_deg), (lat, lon), _RADIUS_M
            )
            if gap > _ON_AIRFIELD_M:
                raise ValueError(f"track {i + 1} misses its airfield by {gap:.1f} m")
        out.append((track, end))
    return out


def _sclk_to_et(seconds: float) -> float:
    modulus = int(spiceypy.gdpool(f"SCLK01_MODULI_{-M2020_CLOCK}", 1, 1)[0])
    return spiceypy.sct2e(M2020_CLOCK, seconds * modulus)


def _utc(et: float) -> str:
    return spiceypy.et2utc(et, "ISOC", 0) + "Z"


def _position(track: Track, start_et: float, end_et: float, et: float):
    """`(lat_deg, lon_deg)` along the track at `et`."""
    last = len(track.points) - 1
    x = (et - start_et) / (end_et - start_et) * last
    i = min(int(x), last - 1)
    f = x - i
    (lon_a, lat_a), (lon_b, lat_b) = track.points[i], track.points[i + 1]
    return lat_a + (lat_b - lat_a) * f, lon_a + (lon_b - lon_a) * f


def flight_waypoints(
    track: Track, end: Airfield, takeoff_et: float, landing_et: float
) -> list[tuple[float, float, float]]:
    """`(et, lat, lon)` on each whole UTC second after takeoff, and the
    airfield at the first whole second after landing. A traverse dates its
    waypoints to the second."""
    first = spiceypy.str2et(spiceypy.et2utc(takeoff_et, "ISOC", 0))
    if first <= takeoff_et:
        first += 1.0
    out = []
    et = first
    while et < landing_et:
        out.append((et, *_position(track, takeoff_et, landing_et, et)))
        et += 1.0
    out.append((et, end.lat_deg, end.lon_deg))
    return out


def waypoints(airfields: list[Airfield], tracks: list[Track]):
    """The waypoints of every flight as `(time, lat, lon)`."""
    out = []
    for track, end in flights(airfields, tracks):
        takeoff_et = _sclk_to_et(track.takeoff_sclk)
        landing_et = _sclk_to_et(track.landing_sclk)
        for et, lat, lon in flight_waypoints(track, end, takeoff_et, landing_et):
            out.append((_utc(et), round(lat, PLACES), round(lon, PLACES)))
    return out


def build(source_dir: Path, output_dir: Path) -> Path:
    airfields = read_airfields(json.loads((source_dir / WAYPOINTS_FILE).read_text()))
    tracks = read_tracks(json.loads((source_dir / FLIGHT_PATH_FILE).read_text()))
    kernels = [
        str(k) for k in (*sorted(_LSK_DIR.glob("*.tls")), source_dir / SCLK_FILE)
    ]
    try:
        for kernel in kernels:
            spiceypy.furnsh(kernel)
        track = waypoints(airfields, tracks)
        deployed = _utc(_sclk_to_et(airfields[0].rest_sclk))
    finally:
        for kernel in kernels:
            spiceypy.unload(kernel)
    path = write_traverse(
        output_dir,
        probe_id=PROBE_ID,
        body_naif=MARS_NAIF,
        sources=SOURCES,
        landing_point=(airfields[0].lat_deg, airfields[0].lon_deg),
        waypoints=track,
    )
    logger.info(
        "Ingenuity: set down %s at %.8f, %.8f; %d flights, %d waypoints to %s",
        deployed,
        airfields[0].lat_deg,
        airfields[0].lon_deg,
        len(tracks),
        len(track),
        track[-1][0],
    )
    return path


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=INGENUITY_DIR)
    parser.add_argument("--output-dir", type=Path, default=TRAVERSES_DIR)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build(args.source_dir, args.output_dir)


if __name__ == "__main__":
    cli()
