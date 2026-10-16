"""Traverses in the frame of the panoramas, for craft that a SPICE kernel lands.

The kernels of Spirit and Opportunity follow the rovers for three months and
then hold them at the landing site. The Viking kernels put the landers 12 km to
17 km west of where orbital images show them. Each traverse here comes from the
source that places the panoramas of the craft. The craft then stands where its
panoramas were taken.

    uv run python -m space_map_data.probes.panorama_traverse
"""

import argparse
import logging
import math
from datetime import datetime, timedelta
from pathlib import Path

from space_map_data.panoramas import mer, viking
from space_map_data.panoramas.missions import MISSION_PROBE, body_id
from space_map_data.probes.events import load_event_probes
from space_map_data.probes.traverses import TRAVERSES_DIR, write_traverse
from space_map_data.utils.paths import PANORAMA_SOURCES_DIR

logger = logging.getLogger(__name__)

# Mars24 (Allison and McEwen 2000): the Mars sol date of a Julian date in TT.
MSD_EPOCH_JD = 2405522.0028779
SOL_DAYS = 1.0274912517
# MER drove around local noon. The stops of one sol are spread over these hours
# of local mean solar time.
DRIVE_HOURS = (11.0, 15.0)
# A centimetre on Mars.
PLACES = 7

ROVERS = ("spirit", "opportunity")
LANDERS = {"viking1": 1, "viking2": 2}


def local_sol_date(jd: float, east_lon_deg: float) -> float:
    """The sol count at a place: its integer part numbers the sol, and its
    fraction is the local mean solar time. UTC is taken for TT, as the events
    files do."""
    return (jd - MSD_EPOCH_JD) / SOL_DAYS + east_lon_deg / 360


def _iso(local: float, east_lon_deg: float) -> str:
    jd = (local - east_lon_deg / 360) * SOL_DAYS + MSD_EPOCH_JD
    moment = datetime(2000, 1, 1, 12) + timedelta(days=jd - 2451545.0)
    return moment.replace(microsecond=0).isoformat() + "Z"


def _landing_jd(probe_id: int) -> float:
    for probe in load_event_probes():
        if probe.probe_id == probe_id:
            for event in probe.events:
                if event.type == "landing":
                    return event.jd
    raise ValueError(f"probe {probe_id}: the events state no landing")


def rover_waypoints(
    mission: str, table: Path, landing_jd: float
) -> list[tuple[str, float, float]]:
    """Each new stop of the corrected traverse, dated inside the sol it was
    reached on. MER numbers the sol of the landing 1."""
    lat, lon = mer.LANDING[mission]
    first = math.floor(local_sol_date(landing_jd, lon))
    last = (round(lat, PLACES), round(lon, PLACES))
    sols: list[tuple[int, list[tuple[float, float]]]] = []
    sol = 1
    for _, held, position in mer.stops(mission, table):
        place = (
            round(position["latitude"], PLACES),
            round(position["longitude"], PLACES),
        )
        if place == last:
            continue
        last = place
        # A row dated before the row above it keeps the order of the table.
        sol = max(sol, held.start)
        if sols and sols[-1][0] == sol:
            sols[-1][1].append(place)
        else:
            sols.append((sol, [place]))
    start, end = DRIVE_HOURS
    out = []
    for sol, places in sols:
        for i, place in enumerate(places):
            hour = start + (end - start) * (i + 1) / (len(places) + 1)
            out.append((_iso(first + sol - 1 + hour / 24, lon), *place))
    return out


def _body_naif(mission: str) -> int:
    body = body_id(mission)
    if body is None or not body.startswith("naif-"):
        raise ValueError(f"{mission}: no NAIF body")
    return int(body.removeprefix("naif-"))


def build_rover(mission: str, source_dir: Path, output_dir: Path) -> Path:
    table = source_dir / "localization" / mer.TRAVERSE_TABLES[mission]
    probe_id = MISSION_PROBE[mission]
    track = rover_waypoints(mission, table, _landing_jd(probe_id))
    path = write_traverse(
        output_dir,
        probe_id=probe_id,
        body_naif=_body_naif(mission),
        sources=("mer_traverse",),
        landing_point=mer.LANDING[mission],
        waypoints=track,
    )
    logger.info(
        "%s: %d waypoints, %s to %s", mission, len(track), track[0][0], track[-1][0]
    )
    return path


def build_lander(mission: str, output_dir: Path) -> Path:
    site = viking.position(LANDERS[mission])
    path = write_traverse(
        output_dir,
        probe_id=MISSION_PROBE[mission],
        body_naif=_body_naif(mission),
        sources=("viking_sites",),
        landing_point=(site["latitude"], site["longitude"]),
        waypoints=[],
    )
    logger.info("%s: at %.2f, %.2f", mission, site["latitude"], site["longitude"])
    return path


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    missions = (*ROVERS, *LANDERS)
    parser.add_argument("--missions", nargs="+", choices=missions, default=missions)
    parser.add_argument("--source-dir", type=Path, default=PANORAMA_SOURCES_DIR)
    parser.add_argument("--output-dir", type=Path, default=TRAVERSES_DIR)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for mission in args.missions:
        if mission in ROVERS:
            build_rover(mission, args.source_dir, args.output_dir)
        else:
            build_lander(mission, args.output_dir)


if __name__ == "__main__":
    cli()
