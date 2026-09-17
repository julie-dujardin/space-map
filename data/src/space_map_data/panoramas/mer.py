"""Place Spirit and Opportunity, and list the mosaics they left behind."""

import csv
import io
import logging
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

VOLUMES = {"spirit": "mer2om_0xxx", "opportunity": "mer1om_0xxx"}
# The Rover Motion Counter bundle in the PDS carries only wheel odometry, which
# drifts over a mission-long drive. The Analyst's Notebook publishes the
# traverse the science team corrected against orbital imagery instead.
TRAVERSE = "https://an.rsl.wustl.edu/merb/merxbrowser/meri/MER/traverse/"
TRAVERSE_TABLES = {
    "spirit": "MERA_traverse.csv",
    "opportunity": "MERB_traverse_5130.csv",
}
# Spirit's corrected columns are projected metres and Opportunity's are metres
# from its lander, so both are read as a displacement from the landing site.
LANDING = {"spirit": (-14.5692, 175.4729), "opportunity": (-1.9462, 354.4734)}
LANDING_SOURCE = "mer1om_0xxx/catalog/mission.cat"
# IAU 2000, the frame `mission.cat` states the landing sites in.
MARS_RADIUS_M = 3396190.0


def stops(mission: str, path: Path):
    """Every corrected stop: its counter, the sols it held, and where it was."""
    latitude, longitude = LANDING[mission]
    metres_per_degree = MARS_RADIUS_M * math.pi / 180
    origin = None
    for row in csv.DictReader(io.StringIO(path.read_text())):
        easting, northing = float(row["CORRECTED_X"]), float(row["CORRECTED_Y"])
        if origin is None:
            origin = (easting, northing)
        yield (
            (int(row["SITE"]), int(row["DRIVE"])),
            range(int(row["START_SOL"]), int(row["END_SOL"]) + 1),
            {
                "latitude": latitude + (northing - origin[1]) / metres_per_degree,
                "longitude": (
                    longitude
                    + (easting - origin[0])
                    / (metres_per_degree * math.cos(math.radians(latitude)))
                )
                % 360,
                "elevation_m": None,
            },
        )


def traverse_positions(mission: str, path: Path) -> dict[tuple[int, int], dict]:
    """Where each site and drive of a corrected traverse put the rover.

    A counter the table repeats with a different position is dropped rather
    than resolved, matching how the PLACES tables are read.
    """
    result: dict[tuple[int, int], dict] = {}
    ambiguous = set()
    for counter, _, position in stops(mission, path):
        if counter in result and result[counter] != position:
            ambiguous.add(counter)
        result[counter] = position
    for counter in ambiguous:
        del result[counter]
    return result


def traverse_drives(mission: str, path: Path) -> dict[tuple[int, int], tuple[int, int]]:
    """The first and last drive a site and sol cover, for mosaics with no
    pointing file.

    A sol the rover spent standing in one place names its stop exactly, and the
    two drives are then the same one. A sol it drove on covers a stretch of the
    traverse, which bounds where the mosaic was taken rather than naming it.
    """
    covered: dict[tuple[int, int], list[int]] = {}
    for (site, drive), sols, _ in stops(mission, path):
        for sol in sols:
            covered.setdefault((site, sol), []).append(drive)
    return {key: (min(drives), max(drives)) for key, drives in covered.items()}


def traverse_sol_positions(mission: str, path: Path) -> dict[int, dict]:
    """Where a sol finds the rover, for the sols it spent in one place.

    A sol it drove on covers several stops, and none of them is where a
    panorama taken that sol was taken from.
    """
    found: dict[int, dict] = {}
    ambiguous = set()
    for _, sols, position in stops(mission, path):
        for sol in sols:
            if sol in found and found[sol] != position:
                ambiguous.add(sol)
            found[sol] = position
    for sol in ambiguous:
        del found[sol]
    return found


def path_site(url: str) -> int:
    """The site a mosaic is filed under, which the archive spells in decimal."""
    match = re.search(r"/site(\d+)/?$", url)
    if match is None:
        raise ValueError("Mosaic is not filed under a site")
    return int(match[1])


def nav_stops(text: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """The first and last stop the frames of a mosaic were shot at, if it says.

    A mosaic assembled across a drive has no single place to stand, so both ends
    are returned and the traverse between them bounds it. Some products carry an
    empty pointing file, which states nothing rather than states a span.
    """
    if not text.strip():
        return None
    try:
        solutions = ET.fromstring(text).iter("solution")
    except ET.ParseError as error:
        raise ValueError(f"Unreadable pointing correction: {error}") from error
    counters = {(node.get("index1"), node.get("index2")) for node in solutions}
    if not counters:
        return None
    ordered = []
    for site, drive in counters:
        if site is None or drive is None:
            raise ValueError("Pointing correction states no rover position")
        ordered.append((int(site), int(drive)))
    ordered.sort()
    return ordered[0], ordered[-1]


# Two-character counter field: 00 to 99, then on in base 36 from A0. The same
# scheme numbers the Mars 2020 product versions.
DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SOURCE_FRAME = re.compile(r"\d[A-Z]\d{9}[A-Z]{3}([0-9A-Z]{2})([0-9A-Z]{2})")


def counter_field(field: str) -> int:
    """The number a two-character counter field stands for."""
    if field.isdigit():
        return int(field)
    return DIGITS.index(field[0]) * len(DIGITS) + DIGITS.index(field[1]) - 260


def source_stops(listing: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """The first and last stop the frames of a mosaic were shot at, if they say.

    Every source frame names its own rover position, so the input list answers
    for the mosaics that have no pointing file beside them.
    """
    counters = sorted(
        (counter_field(site), counter_field(drive))
        for site, drive in SOURCE_FRAME.findall(listing.upper())
    )
    if not counters:
        return None
    return counters[0], counters[-1]


def mosaic_stops(
    pointing: str | None, listing: str | None, url: str, sol: int, drives
) -> tuple[tuple[int, int], tuple[int, int]]:
    """The stretch of traverse a mosaic was shot over, as its first and last stop.

    The pointing correction states the rover positions outright; failing that
    the source frames each name their own; failing both, the sol names the
    stretch it covered. A mosaic shot standing still returns the same stop twice.
    """
    site = path_site(url)
    span = nav_stops(pointing) if pointing else None
    if span is None and listing:
        span = source_stops(listing)
    if span is None:
        drives_that_sol = drives.get((site, sol))
        if drives_that_sol is None:
            raise ValueError("The sol names no stop on the traverse")
        first, last = drives_that_sol
        return (site, first), (site, last)
    if any(counter[0] != site for counter in span):
        raise ValueError("Stated and archived rover position disagree on the site")
    return span


def instrument(product_id: str) -> str:
    """Which camera took a mosaic, from the second character of its name."""
    return {"N": "Navcam", "P": "Pancam"}[product_id[1].upper()]


def index_fields(label: str) -> list[str]:
    return re.findall(r"^\s*NAME\s*=\s*(\w+)\s*$", label, re.M)


def mosaic_listings(index: str, label: str, base: str, cameras: tuple[str, ...]):
    """Every cylindrical mosaic of the wanted cameras, grouped by sol.

    The volume indexes the whole mission in one table, so unlike the sol
    directories the other rovers publish there is nothing to crawl.
    """
    fields = index_fields(label)
    groups: dict[int, list[tuple[str, str]]] = {}
    for line in index.splitlines():
        row = dict(
            zip(fields, (cell.strip().strip('"').strip() for cell in line.split("\t")))
        )
        if row.get("MAP_PROJECTION_TYPE") != "CYL":
            continue
        if row["INSTRUMENT_ID"].split("_")[0] not in cameras:
            continue
        groups.setdefault(int(row["PLANET_DAY_NUMBER"]), []).append(
            (base + row["PATH_NAME"].lstrip("/"), row["FILE_NAME"])
        )
    return groups
