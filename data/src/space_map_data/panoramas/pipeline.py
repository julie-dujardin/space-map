"""Download official Navcam mosaics and prepare masked sphere textures."""

from bisect import bisect_left
from dataclasses import asdict
import csv
import hashlib
import io
import json
import logging
import math
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import httpx
import numpy as np
from PIL import Image

from . import mer
from .labels import (
    Mosaic,
    attached_constants,
    describes_raster,
    read_insight_pds4,
    read_mer_pds3,
    read_pds3,
    read_pds4,
)
from .missions import lander_position

logger = logging.getLogger(__name__)
ARCHIVE = "https://planetarydata.jpl.nasa.gov/img/data/"
MSL = ARCHIVE + "msl/msl_navcam_mosaic/DATA/"
# The Imaging Node's browsable mirror froze the Mars 2020 ops mosaics at sol 658.
# The release buckets behind the PDS Image Atlas carry the whole mission instead.
# A release inventory lists the whole collection as of that release, but the
# directory beside it serves only what that release delivered — so a product has
# to be fetched from the first release that listed it, and releases before 8 are
# served from `cumulative`.
M20 = "https://d1ejlg980osaur.cloudfront.net/m20/"
M20_MOSAIC = "mars2020_navcam_ops_mosaic/"
M20_INVENTORY = M20_MOSAIC + "data/collection_data_inventory.csv"
M20_FIRST_RELEASE = 8
M20_RELEASE_GAP = 8
INSIGHT = ARCHIVE + "nsyt/insight_cameras/data/sol/"
MER = ARCHIVE + "mer/"
MOSAIC_COLLECTIONS = {
    "curiosity": "curiosity-navcam",
    "insight": "insight-mosaic",
    "spirit": "spirit-mosaic",
    "opportunity": "opportunity-mosaic",
}
MER_CAMERAS = ("NAVCAM", "PANCAM")
PLACES = ARCHIVE + "msl/msl_places/data_localizations/localized_interp.csv"
WAYPOINTS = "https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json"
M20_PLACES = "https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_rover_places/data_localizations/best_interp.csv"
POLICY = "https://www.jpl.nasa.gov/jpl-image-use-policy/"
# VICAR declares the white DN but renders black grid annotations as DN 1.
GRID_BLACK_DN = 1
# Every overlay the supported archives draw. `GRID` is the Mars Exploration
# Rover spelling of `GRID_OVERLAY`; `GRID_LABELS` omits the lines.
GRID_MODES = {"GRID", "GRID_OVERLAY", "GRID_LABELS"}
GRID_LABEL_VERTICAL_MARGIN = 32
GRID_LABEL_SIDE_MARGIN = 48
GRID_SEAM_MARGIN = 8
# An overlay the header never declares, or declares without its value, still
# stands out in the pixels: one value far commoner than the values beside it,
# drawn as vertical lines ten degrees apart.
GRID_LINE_SPACING_DEG = 10
GRID_LINE_MIN_PIXELS = 30
# Of the spacing: a line's own width, not a step.
GRID_LINE_TOLERANCE = 0.03
GRID_SPIKE_MIN_PIXELS = 1500
GRID_SPIKE_RATIO = 20
# Enough of a raster to hold the label attached to its front.
LABEL_PREFIX_BYTES = 1 << 16


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(client: httpx.Client, url: str, path: Path, *, refresh=False) -> Path:
    if path.exists() and not refresh:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    for attempt in range(5):
        with client.stream("GET", url) as response:
            if response.status_code in {429, 502, 503, 504} and attempt < 4:
                retry = response.headers.get("Retry-After", "")
                delay = min(60, int(retry)) if retry.isdigit() else 2 ** (attempt + 1)
                logger.warning(
                    "HTTP %s; retrying in %ss: %s", response.status_code, delay, url
                )
                time.sleep(delay)
                continue
            if response.is_error:
                response.read()
            response.raise_for_status()
            with temporary.open("wb") as stream:
                for chunk in response.iter_bytes():
                    stream.write(chunk)
            break
    temporary.replace(path)
    return path


def ranged_label(client: httpx.Client, url: str) -> str:
    """The label of a raster it is attached to, without the megabytes after it.

    An archive that attaches labels this way would otherwise charge a whole
    image for every product that turns out to be unreadable.
    """
    headers = {"Range": f"bytes=0-{LABEL_PREFIX_BYTES - 1}"}
    with client.stream("GET", url, headers=headers) as response:
        if response.is_error:
            response.read()
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw += chunk
            if len(raw) >= LABEL_PREFIX_BYTES:
                break
    return label_text(bytes(raw).decode("latin-1"))


def links(client, url, path, refresh=False):
    html = fetch(client, url, path, refresh=refresh).read_text()
    return sorted(
        {
            href
            for a in BeautifulSoup(html, "html.parser").find_all("a", href=True)
            if isinstance(href := a.get("href"), str)
            and re.fullmatch(r"[A-Za-z0-9_.-]+/?", href)
        }
    )


def positions(mission: str, path: Path) -> dict:
    if mission in mer.VOLUMES:
        return mer.traverse_positions(mission, path)
    result = {}
    ambiguous = set()
    if mission == "curiosity" or path.suffix == ".csv":
        rows = csv.DictReader(io.StringIO(path.read_text()))
        for row in rows:
            if row["frame"] != "ROVER":
                continue
            key = (int(row["site"]), int(row["drive"]))
            position = {
                "latitude": float(row["planetocentric_latitude"]),
                "longitude": float(row["longitude"]) % 360,
                "elevation_m": float(row["elevation"]),
            }
            if key in result and result[key] != position:
                ambiguous.add(key)
            result[key] = position
    else:
        for feature in json.loads(path.read_text())["features"]:
            row = feature["properties"]
            key = (int(row["site"]), int(row["drive"]))
            position = {
                "latitude": float(row["lat"]),
                "longitude": float(row["lon"]) % 360,
                "elevation_m": float(row["elev_geoid"]),
            }
            if key in result and result[key] != position:
                ambiguous.add(key)
            result[key] = position
    for key in ambiguous:
        del result[key]
    return result


def metres_apart(first: dict, second: dict) -> float:
    """How far apart two rover stops are, along the ground."""
    scale = mer.MARS_RADIUS_M * math.pi / 180
    east = degrees_east(first["longitude"], second["longitude"])
    return math.hypot(
        (second["latitude"] - first["latitude"]) * scale,
        east * scale * math.cos(math.radians(first["latitude"])),
    )


def degrees_east(first: float, second: float) -> float:
    """The signed turn from one longitude to another, the short way round.

    Opportunity landed at 354 degrees east and drove past the prime meridian, so
    two stops metres apart can be written 359 degrees apart.
    """
    return (second - first + 180) % 360 - 180


def midpoint(start: dict, end: dict, between: tuple, method: str) -> dict:
    """A place known only to lie between two rover stops, and how wrong it can be."""
    span = metres_apart(start, end)
    slack = max(start.get("uncertainty_m") or 0, end.get("uncertainty_m") or 0)
    elevations = [start["elevation_m"], end["elevation_m"]]
    return {
        "latitude": (start["latitude"] + end["latitude"]) / 2,
        "longitude": (
            start["longitude"] + degrees_east(start["longitude"], end["longitude"]) / 2
        )
        % 360,
        "elevation_m": None if None in elevations else sum(elevations) / 2,
        "method": method,
        "reference_point": "rover localization",
        # The camera stood somewhere between the two, so the midpoint is wrong
        # by at most half of what separates them, on top of whatever either end
        # is itself unsure by: two stops bounded to the same stretch sit at the
        # same estimate, and nothing separating them does not make them exact.
        "uncertainty_m": round(span / 2 + slack, 1),
        "position_bounds": {
            "between_site_drive": [list(counter) for counter in between],
            "separation_m": round(span, 1),
            "endpoints": [
                {"latitude": stop["latitude"], "longitude": stop["longitude"]}
                for stop in (start, end)
            ],
        },
    }


def bracketed(lookup: dict, order: list, counter: tuple) -> dict | None:
    """Where a stop the localization table does not record must have been.

    A table records the drives it was corrected for, not every drive the rover
    made, and the motion counter only ever advances, so counter order is
    traverse order. A mosaic naming one of the uncorrected drives was still
    taken between the recorded stops either side of it: a position, and a stated
    bound on how wrong it can be, rather than no position at all.

    None where the traverse cannot close around the counter, which is only ever
    before its first recorded stop or after its last.
    """
    index = bisect_left(order, counter)
    if index == 0 or index >= len(order):
        return None
    neighbours = (order[index - 1], order[index])
    return midpoint(
        lookup[neighbours[0]],
        lookup[neighbours[1]],
        neighbours,
        "midpoint of the recorded stops either side on the traverse",
    )


def m20_published(client, name) -> bool:
    """Whether a release directory exists, against a mirror that also answers
    502 and 503. Absence has to be the archive's answer and not the network's:
    a release read as absent hands its products to the next one, whose
    directory does not serve them, and the download dies there."""
    for attempt in range(5):
        status = client.head(M20 + name + "/" + M20_INVENTORY).status_code
        if status not in {429, 502, 503, 504}:
            return status == 200
        delay = 2 ** (attempt + 1)
        logger.warning("HTTP %s; retrying in %ss: %s release", status, delay, name)
        time.sleep(delay)
    raise httpx.HTTPError(f"Mars 2020 release {name} unreadable after 5 attempts")


def m20_releases(client, root, *, refresh):
    """Every published release directory, oldest first, with its inventory text.

    Releases are numbered, not listed, so the end of the sequence is found by
    running off it. Counting starts at the first published release: the empty
    numbers below it are the archive's own history, not a gap, and letting them
    spend the tolerance leaves none for the live releases.
    """
    directories = ["cumulative"]
    release, misses = M20_FIRST_RELEASE, 0
    while misses < M20_RELEASE_GAP:
        name = f"r{release}"
        if m20_published(client, name):
            directories.append(name)
            misses = 0
        else:
            misses += 1
        release += 1
    logger.info("Mars 2020 releases: %s", ", ".join(directories))
    for name in directories:
        yield (
            name,
            fetch(
                client,
                M20 + name + "/" + M20_INVENTORY,
                root / "inventories" / f"{name}.csv",
                refresh=refresh,
            ).read_text(),
        )


def m20_version(version: str) -> str:
    """The two-character version field a Mars 2020 product name ends with.

    It counts 01 to 99 and then carries on in base 36 from A0, so the inventory's
    decimal version has to be re-encoded above 99. The archive holds three such
    products — versions 212, 269 and 280, named D4, EP and F0 — and no counter
    has reached ZZ, which would be 1035.
    """
    number = int(version.split(".")[0])
    if number <= 99:
        return f"{number:02}"
    number += 260
    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if number >= len(digits) ** 2:
        raise ValueError(f"Version {version} exceeds the two-character field")
    return digits[number // len(digits)] + digits[number % len(digits)]


def m20_mosaic_listings(client, root, *, refresh):
    """Cylindrical Navcam mosaics by sol, each with the release URL that serves it."""
    groups: dict[int, list[tuple[str, str]]] = {}
    placed = set()
    for directory, inventory in m20_releases(client, root, refresh=refresh):
        url = M20 + directory + "/" + M20_MOSAIC + "data/sol/"
        for row in csv.reader(io.StringIO(inventory)):
            if len(row) != 2 or ":data:" not in row[1]:
                continue
            identifier, version = row[1].split(":data:")[1].split("::")
            match = re.fullmatch(r"n_lrgb_(\d+)[x_]rzs_\d+_cyl_[ls]_\w+", identifier)
            if not match or identifier in placed:
                continue
            sol = int(match[1])
            name = identifier.upper() + m20_version(version) + ".xml"
            groups.setdefault(sol, []).append((url + f"{sol:05}/ids/rdr/mosaic/", name))
            placed.add(identifier)
    return groups


def insight_mosaic_listings(client, root, *, refresh):
    """Every cylindrical mosaic InSight left, by the sol it was taken on.

    The bundle files its products under one directory per sol, and only some
    sols carry a mosaic at all, so the sols are walked rather than guessed.
    """
    groups: dict[int, list[tuple[str, str]]] = {}
    for directory in links(client, INSIGHT, root / "sols.html", refresh):
        match = re.fullmatch(r"(\d{4})/", directory)
        if not match:
            continue
        url = f"{INSIGHT}{match[1]}/mipl/rdr/mosaic/"
        try:
            names = links(client, url, root / "listings" / f"{match[1]}.html", refresh)
        except httpx.HTTPStatusError as error:
            # Most sols have no mosaic directory at all.
            if error.response.status_code != 404:
                raise
            continue
        found = [(url, name) for name in names if re.fullmatch(r"\w*CYL\w*\.xml", name)]
        if found:
            groups[int(match[1])] = found
    logger.info(
        "InSight cylindrical mosaics: %s across %s sols",
        sum(len(v) for v in groups.values()),
        len(groups),
    )
    return groups


def mer_mosaic_listings(client, root, mission, *, refresh):
    volume = mer.VOLUMES[mission]
    index = MER + volume + "/index/rdrindex."
    groups = mer.mosaic_listings(
        fetch(
            client, index + "tab", root / "rdrindex.tab", refresh=refresh
        ).read_text(),
        fetch(
            client, index + "lbl", root / "rdrindex.lbl", refresh=refresh
        ).read_text(),
        MER,
        MER_CAMERAS,
    )
    if groups:
        logger.info(
            "%s cylindrical mosaics: %s across sols %s-%s",
            mission,
            sum(len(v) for v in groups.values()),
            min(groups),
            max(groups),
        )
    return groups


def mosaic_listings(client, root, mission, *, start_sol, end_sol, refresh):
    if mission in mer.VOLUMES or mission in {"perseverance", "insight"}:
        groups = (
            mer_mosaic_listings(client, root, mission, refresh=refresh)
            if mission in mer.VOLUMES
            else insight_mosaic_listings(client, root, refresh=refresh)
            if mission == "insight"
            else m20_mosaic_listings(client, root, refresh=refresh)
        )
        for sol, products in sorted(groups.items()):
            if sol >= start_sol and (end_sol is None or sol <= end_sol):
                yield sol, products
        return
    for directory in links(client, MSL, root / "sols.html", refresh):
        match = re.fullmatch(r"SOL(\d{5})/", directory)
        if not match:
            continue
        sol = int(match[1])
        if sol < start_sol or (end_sol is not None and sol > end_sol):
            continue
        url = MSL + directory
        yield (
            sol,
            [
                (url, name)
                for name in links(
                    client, url, root / "listings" / f"{sol:05}.html", refresh
                )
            ],
        )


# Identifies the recipe that chose and validated a selection. Bump it whenever
# a change would make a run accept different products, so a resumed run
# revalidates what the old recipe chose instead of trusting it.
SELECTION_VERSION = 4
# The versions whose accepted products this recipe would accept unchanged. A
# resumed run revalidates only what it might now decide differently, so a
# purely additive change belongs here rather than costing a checksum over every
# byte already on disk. The earlier versions are not here: they took the range
# and elevation rasters that share the cylindrical projection for photographs,
# so what they accepted has to be judged again rather than carried.
CARRIED_SELECTIONS = {4}


def revision_key(mission: str, product_id: str) -> str:
    """What two processing revisions of one sweep share, and separate sweeps
    at the same stop do not."""
    if mission in mer.VOLUMES:
        return product_id[:-1]
    return re.sub(r"\d{2}$", "", product_id)


def resumable(previous: dict) -> dict[str, dict]:
    """The products an earlier run already validated, by the label URL that
    names each one before anything is fetched.

    Carrying them costs a dictionary lookup where revalidating costs a request
    and a checksum over every byte already on disk. Only the recipe decides
    whether they can be carried: a sol range bounds what a run looks at again,
    not what the index is allowed to hold, so a run over part of the mission
    resumes the rest rather than discarding it.
    """
    if previous.get("selection_version") not in CARRIED_SELECTIONS:
        return {}
    return {product["label_url"]: product for product in previous.get("products", [])}


def download(
    client,
    source_dir: Path,
    mission: str,
    *,
    start_sol=0,
    end_sol=None,
    refresh=False,
):
    root = source_dir / mission
    root.mkdir(parents=True, exist_ok=True)
    # A lander saw everything from one published place; a rover needs a table.
    fixed = lander_position(mission)
    position_path = None
    lookup: dict = {}
    # Half the Mars Exploration Rover mosaics have no pointing file to name the
    # drive; a sol the rover held one stop for names it just as exactly.
    drives: dict = {}
    if fixed:
        position_url = fixed["source_url"]
    else:
        position_url = (
            mer.TRAVERSE + mer.TRAVERSE_TABLES[mission]
            if mission in mer.VOLUMES
            else PLACES
            if mission == "curiosity"
            else M20_PLACES
        )
        position_path = fetch(
            client, position_url, root / "positions.csv", refresh=refresh
        )
        lookup = positions(mission, position_path)
        if mission in mer.VOLUMES:
            drives = mer.traverse_drives(mission, position_path)
    order = sorted(lookup)

    def place(counter: tuple) -> dict | None:
        """Where a stop was, bounded where the table does not record it."""
        return lookup.get(counter) or bracketed(lookup, order, counter)

    def place_span(span: tuple) -> dict | None:
        """Where a mosaic was shot from, across the stops its frames name.

        A sweep the rover drove during was shot from every stop between its
        ends, so it is placed halfway along and carries the whole stretch as
        its bound.
        """
        first, last = span
        start, end = place(first), place(last)
        if start is None or end is None:
            return None
        if first == last:
            return start
        return midpoint(
            start, end, span, "midpoint of the stops the mosaic was shot across"
        )

    selection_path = root / "selection.json"
    stored = json.loads(selection_path.read_text()) if selection_path.is_file() else {}
    # An older recipe's index states nothing this one can use, neither to skip
    # work nor to speak for the sols this run leaves out.
    previous = stored if stored.get("selection_version") in CARRIED_SELECTIONS else {}
    # A refreshed run revalidates every sol it walks, but that says nothing about
    # the sols it was told not to walk.
    carried = {} if refresh else resumable(previous)
    whole_mission = start_sol == 0 and end_sol is None
    accepted, rejected, seen = [], [], set()

    def outside(product: dict) -> bool:
        """Whether this run's sol range leaves the product's sol out."""
        sol = product["mosaic"]["sol"]
        return sol < start_sol or (end_sol is not None and sol > end_sol)

    def indexed(through: int | None = None) -> list[dict]:
        """Everything the index should name: what this run walked, and what an
        earlier one found in the sols this run has not answered for.

        A product the archive has stopped serving is dropped rather than kept,
        which is why this asks where a sol falls and not whether the run
        happened to reach it. `through` is the last sol walked, and only a
        checkpoint sets it: a run stopped halfway must leave the index whole
        rather than cut down to the part it reached, or the next run resumes
        from a file that has forgotten the rest of the mission.
        """
        kept = [
            item
            for item in previous.get("products", [])
            if outside(item)
            or (through is not None and item["mosaic"]["sol"] > through)
        ]
        # Stable, so the order this run chose between revisions at one stop survives.
        return sorted(accepted + kept, key=lambda product: product["mosaic"]["sol"])

    def checkpoint(complete: bool, through: int | None = None):
        write_json(
            selection_path,
            {
                "schema_version": 1,
                "selection_version": SELECTION_VERSION,
                "selection": {"start_sol": start_sol, "end_sol": end_sol},
                # Only a run that reached the last sol has seen everything the
                # archive offers; an interrupted one is resumed, not trusted. A
                # bounded run inherits the claim, having kept what it skipped.
                "complete": complete
                and (whole_mission or bool(previous.get("complete"))),
                "products": indexed(through),
                "rejected": rejected,
            },
        )

    for sol, products in mosaic_listings(
        client, root, mission, start_sol=start_sol, end_sol=end_sol, refresh=refresh
    ):
        pattern = (
            # The Mars Exploration Rover index has already named the cylindrical
            # mosaics of the cameras that map the ground.
            r".+\.img"
            if mission in mer.VOLUMES
            else r"\w*CYL\w*\.xml"
            if mission == "insight"
            else r"N_L\w+CYL\w+\.LBL"
            if mission == "curiosity"
            else r"N_LRGB_\d+[X_]RZS_\d+_CYL_[LS]_\w+\.xml"
        )
        # Revisions must not crowd out separate sweeps at the same stopping point.
        for url, name in sorted(
            ((u, n) for u, n in products if re.fullmatch(pattern, n)),
            key=lambda product: product[1],
            reverse=True,
        ):
            # Sols are walked in order, so every product carried here is already
            # in `accepted` before the first new one is written beside it.
            found = carried.get(url + name)
            if found is not None:
                accepted.append(found)
                seen.add(revision_key(mission, found["mosaic"]["product_id"]))
                continue
            try:
                # A lander saw everything from the one place it landed.
                shot_from = fixed
                # A name the archive does not serve is one bad product, not a
                # reason to abandon a mission-long run.
                if mission in mer.VOLUMES:
                    # The raster is attached to its label, so the pointing file
                    # decides whether the megabytes are worth fetching at all.
                    stem = name.removesuffix(".img")
                    stated = {}
                    for kind, folder in (("nav", "pointing"), ("lis", "sources")):
                        try:
                            stated[kind] = fetch(
                                client,
                                f"{url}{stem}.{kind}",
                                root / folder / f"{stem}.{kind}",
                                refresh=refresh,
                            ).read_text()
                        except httpx.HTTPStatusError as error:
                            if error.response.status_code != 404:
                                raise
                    span = mer.mosaic_stops(
                        stated.get("nav"), stated.get("lis"), url, sol, drives
                    )
                    shot_from = place_span(span)
                    if shot_from is None:
                        raise ValueError("Traverse does not reach this stop")
                    image_url = url + name
                    # The sweep is filed under the stop it ended at, which is
                    # also the one its label is referenced to.
                    mosaic = read_mer_pds3(
                        ranged_label(client, image_url), span[1][1], sol
                    )
                else:
                    label = fetch(
                        client, url + name, root / "labels" / name, refresh=refresh
                    )
                    text = label.read_text()
                    if mission == "curiosity":
                        # From sol 4712 the volume stopped repeating the raster
                        # description in the detached label, so the only place
                        # left that states it is the raster's own header.
                        mosaic = read_pds3(
                            text,
                            None
                            if describes_raster(text)
                            else ranged_label(
                                client, urljoin(url, Path(name).stem + ".IMG")
                            ),
                        )
                    else:
                        read = read_insight_pds4 if mission == "insight" else read_pds4
                        mosaic = read(text)
                if not fixed and mission not in mer.VOLUMES:
                    shot_from = place((mosaic.site, mosaic.drive))
                    if shot_from is None:
                        raise ValueError("Traverse does not reach this stop")
                # Keep separate sweeps at the same stop, but not processing revisions.
                revision = revision_key(mission, mosaic.product_id)
                if revision in seen:
                    continue
                # InSight labels keep only the last three digits of the sol;
                # the directory a product is filed under holds the whole number.
                if mission == "insight" and mosaic.sol == sol % 1000:
                    mosaic.sol = sol
                # The Mars Exploration Rover volume redelivers a sweep under a
                # later version than the label inside it was written with, so
                # only the sweep the two name has to agree.
                named = (
                    Path(name).stem.upper()
                    if mission in mer.VOLUMES
                    else Path(name).stem
                )
                served = (
                    (
                        revision_key(mission, mosaic.product_id),
                        revision_key(mission, named),
                    )
                    if mission in mer.VOLUMES
                    else (mosaic.product_id, named)
                )
                if mosaic.sol != sol or served[0] != served[1]:
                    raise ValueError("Product identity mismatch")
            except (ValueError, httpx.HTTPStatusError) as error:
                rejected.append({"label_url": url + name, "reason": str(error)})
                continue
            if mission in mer.VOLUMES:
                label = image = fetch(
                    client, image_url, root / "images" / name, refresh=refresh
                )
            elif mission == "insight":
                image_url = urljoin(url, mosaic.product_id + ".VIC")
                image = fetch(
                    client,
                    image_url,
                    root / "images" / (mosaic.product_id + ".VIC"),
                    refresh=refresh,
                )
            else:
                image_url = urljoin(url, mosaic.product_id + ".IMG")
                image = fetch(
                    client,
                    image_url,
                    root / "images" / (mosaic.product_id + ".IMG"),
                    refresh=refresh,
                )
            expected = (
                mosaic.offset
                + mosaic.width
                * mosaic.height
                * mosaic.bands
                * np.dtype(mosaic.dtype).itemsize
            )
            if image.stat().st_size < expected:
                raise ValueError(f"Truncated image: {image}")
            if not mosaic.missing:
                try:
                    mosaic.missing = attached_constants(read_header(image, mosaic))
                except ValueError as error:
                    rejected.append({"label_url": url + name, "reason": str(error)})
                    continue
            accepted.append(
                {
                    "id": f"{mission}-{mosaic.product_id.lower()}",
                    "mission": mission,
                    "mosaic": asdict(mosaic),
                    "position": shot_from,
                    "label": str(label.relative_to(root)),
                    "image": str(image.relative_to(root)),
                    "label_url": url + name,
                    "image_url": image_url,
                    "label_sha256": sha256(label),
                    "image_sha256": sha256(image),
                    "position_source_url": position_url,
                    "position_sha256": sha256(position_path) if position_path else None,
                }
            )
            seen.add(revision)
            checkpoint(False, sol)
            logger.info(
                "Downloaded %s sol %s site %s drive %s",
                mission,
                sol,
                mosaic.site,
                mosaic.drive,
            )
    products = indexed()
    if not products:
        write_json(root / "rejected.json", rejected)
        raise ValueError(f"No supported localized panoramas found for {mission}")
    checkpoint(True)
    logger.info(
        "%s: %s products selected (%s walked this run, %s carried), %s rejected",
        mission,
        len(products),
        len(accepted),
        len(products) - len(accepted),
        len(rejected),
    )
    return products


def label_text(raw: str) -> str:
    """The label an archive attaches to the front of its raster."""
    end = re.search(r"^END\s*$", raw, re.M)
    if end is None:
        raise ValueError("No attached PDS label")
    return raw[: end.end()]


def read_header(path: Path, mosaic: Mosaic) -> str:
    """Everything before the raster: the attached label and its VICAR image header."""
    with path.open("rb") as stream:
        return stream.read(mosaic.offset).decode("latin-1")


def coordinate_grid_dn(header: str) -> float | None:
    """The value an archive drew its coordinate overlay in, if it drew one.

    A mosaic carries the whole overlay, its labels alone, or neither. Only the
    overlay declares a value; labels are drawn black, which the removal treats
    as annotation whatever else it is given.
    """
    match = re.search(r"\bGRID\s*=\s*'?([A-Z_]+)'?", header)
    if match is None or match[1] == "NOGRID":
        return None
    if match[1] not in GRID_MODES:
        raise ValueError(f"Unrecognized coordinate overlay: {match[1]}")
    if match[1] == "GRID_LABELS":
        return GRID_BLACK_DN
    declared = re.search(r"\bGRID_DN\s*=\s*([-+\d.eE]+)", header)
    # An overlay whose value the header never states can only have its black
    # labels taken out; the lines stay, and the product is marked as keeping
    # them rather than passed off as clean.
    return GRID_BLACK_DN if declared is None else float(declared[1])


def coordinate_grid_remains(header: str) -> bool:
    """Whether an overlay was drawn that cannot be taken out completely."""
    match = re.search(r"\bGRID\s*=\s*'?([A-Z_]+)'?", header)
    if match is None or match[1] in {"NOGRID", "GRID_LABELS"}:
        return False
    return re.search(r"\bGRID_DN\s*=\s*([-+\d.eE]+)", header) is None


def undeclared_grid_dn(pixels, valid, mosaic: Mosaic) -> float | None:
    """The value an overlay was drawn in, read from the pixels: a value far
    commoner than its neighbours, standing in vertical lines at the grid's
    spacing. None where the pixels show no such thing."""
    band = pixels[:, :, 0]
    values = band[valid]
    if values.size == 0 or not np.all(values == np.rint(values)):
        return None
    values = values.astype(np.int64)
    counts = np.bincount(values[values > 0])
    step = GRID_LINE_SPACING_DEG * mosaic.scale_x
    for dn in np.argsort(counts)[::-1][:5]:
        if counts[dn] < GRID_SPIKE_MIN_PIXELS:
            return None
        beside = np.concatenate((counts[max(1, dn - 3) : dn], counts[dn + 1 : dn + 4]))
        if counts[dn] < GRID_SPIKE_RATIO * max(1, beside.mean()):
            continue
        columns = np.flatnonzero((band == dn).sum(axis=0) >= GRID_LINE_MIN_PIXELS)
        lines = columns[np.r_[True, np.diff(columns) > 2]]
        if len(lines) < 4:
            continue
        gaps = np.diff(lines)
        turns = np.rint(gaps / step)
        spaced = (turns >= 1) & (
            np.abs(gaps - turns * step) <= GRID_LINE_TOLERANCE * step
        )
        if spaced.mean() >= 0.5:
            return float(dn)
    return None


def remove_coordinate_grid(pixels, valid, grid_dn):
    """Reconstruct grid-covered image samples without extending into empty canvas."""
    annotation = np.all(pixels == grid_dn, axis=2) | np.all(
        pixels == GRID_BLACK_DN, axis=2
    )
    valid &= ~annotation
    height, width = valid.shape
    padded_pixels = np.pad(pixels, ((1, 1), (1, 1), (0, 0)))
    padded_valid = np.pad(valid, 1)
    total = np.zeros_like(pixels)
    count = np.zeros_like(valid, dtype=np.uint8)
    for dy, dx in (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    ):
        neighbor_valid = padded_valid[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]
        neighbor_pixels = padded_pixels[
            1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width
        ]
        total += neighbor_pixels * neighbor_valid[:, :, None]
        count += neighbor_valid
    fill = annotation & (count > 0)
    pixels[fill] = total[fill] / count[fill, None]
    valid |= fill
    return pixels, valid


def remove_coordinate_label_borders(pixels, valid, mosaic: Mosaic):
    """Drop overwritten borders; only a full panorama may bridge its wrapped seam."""
    height, width = valid.shape
    if height >= GRID_LABEL_VERTICAL_MARGIN * 4:
        valid[:GRID_LABEL_VERTICAL_MARGIN] = False
        valid[-GRID_LABEL_VERTICAL_MARGIN:] = False
    full = abs(width / mosaic.scale_x - 360) <= 2 / mosaic.scale_x
    if not full:
        if width >= GRID_LABEL_SIDE_MARGIN * 4:
            valid[:, :GRID_LABEL_SIDE_MARGIN] = False
            valid[:, -GRID_LABEL_SIDE_MARGIN:] = False
        return pixels, valid
    if width < GRID_SEAM_MARGIN * 4:
        return pixels, valid
    rows = valid[:, GRID_SEAM_MARGIN] & valid[:, -GRID_SEAM_MARGIN - 1]
    left = pixels[rows, GRID_SEAM_MARGIN]
    right = pixels[rows, -GRID_SEAM_MARGIN - 1]
    amount = np.linspace(0, 1, GRID_SEAM_MARGIN * 2 + 2, dtype=np.float32)[1:-1, None]
    bridge = right[:, None] * (1 - amount) + left[:, None] * amount
    pixels[rows, -GRID_SEAM_MARGIN:] = bridge[:, :GRID_SEAM_MARGIN]
    pixels[rows, :GRID_SEAM_MARGIN] = bridge[:, GRID_SEAM_MARGIN:]
    valid[rows, -GRID_SEAM_MARGIN:] = True
    valid[rows, :GRID_SEAM_MARGIN] = True
    return pixels, valid


def read_pixels(path: Path, mosaic: Mosaic):
    raster = np.memmap(
        path,
        mode="r",
        dtype=mosaic.dtype,
        offset=mosaic.offset,
        shape=(mosaic.bands, mosaic.height, mosaic.width),
    )
    pixels = np.moveaxis(np.asarray(raster), 0, -1).astype(np.float32)
    valid = np.all(np.isfinite(pixels), axis=2)
    for missing in mosaic.missing:
        valid &= np.all(pixels != missing, axis=2)
    header = read_header(path, mosaic)
    declared = coordinate_grid_dn(header)
    # Only a declared value is taken as read; an overlay drawn without one, or
    # without any declaration, is found in the pixels.
    found = (
        undeclared_grid_dn(pixels, valid, mosaic)
        if declared in (None, GRID_BLACK_DN)
        else None
    )
    grid_dn = declared if found is None else found
    if found is not None:
        logger.info(
            "%s coordinate overlay at DN %g: %s",
            "Undeclared" if declared is None else "Unvalued",
            found,
            path.name,
        )
    if grid_dn is not None:
        pixels, valid = remove_coordinate_grid(pixels, valid, grid_dn)
        pixels, valid = remove_coordinate_label_borders(pixels, valid, mosaic)
    grid_remains = coordinate_grid_remains(header) and found is None
    if grid_remains:
        logger.warning("Coordinate overlay lines stay, value not found: %s", path.name)
    if not valid.any():
        raise ValueError("Mosaic has no valid pixels")
    low, high = np.percentile(pixels[valid], [0.5, 99.5])
    if high <= low:
        raise ValueError("Mosaic has no displayable dynamic range")
    # One stretch across RGB preserves channel ratios better than per-channel balancing.
    pixels = np.clip((pixels - low) / (high - low), 0, 1)
    pixels = np.where(
        pixels <= 0.0031308, pixels * 12.92, 1.055 * pixels ** (1 / 2.4) - 0.055
    )
    rgb = np.rint(pixels * 255).astype(np.uint8)
    if mosaic.bands == 1:
        rgb = np.repeat(rgb, 3, axis=2)
    rgba = np.dstack((rgb, valid.astype(np.uint8) * 255))
    rgba[~valid] = 0
    tone = {
        "stretch_percentiles": [0.5, 99.5],
        "source_dn_range": [float(low), float(high)],
        "transfer": "sRGB",
        "scientific_radiometry": False,
    }
    return rgba, tone, grid_remains


def sphere_texture(rgba, mosaic: Mosaic, width: int):
    height = width // 2
    azimuth = (np.arange(width) + 0.5) * 360 / width
    elevation = 90 - (np.arange(height) + 0.5) * 180 / height
    sx = np.rint(((azimuth - mosaic.azimuth) % 360) * mosaic.scale_x).astype(int)
    # PDS line numbers are one-based; texture samples lie at pixel centers.
    sy = np.rint(mosaic.zero_line - 1 - elevation * mosaic.scale_y).astype(int)
    valid_y = (sy >= 0) & (sy < mosaic.height)
    full = abs(mosaic.width / mosaic.scale_x - 360) <= 2 / mosaic.scale_x
    valid_x = np.ones(width, dtype=bool) if full else sx < mosaic.width
    result = np.zeros((height, width, 4), dtype=np.uint8)
    result[valid_y] = rgba[sy[valid_y, None], np.minimum(sx, mosaic.width - 1)[None, :]]
    result[:, ~valid_x] = 0
    return Image.fromarray(result)


def coverage(texture: Image.Image, mosaic: Mosaic) -> dict:
    """Weight latitude bands by their solid angle, not their canvas area."""
    alpha = np.asarray(texture)[:, :, 3] > 0
    edges = np.linspace(np.pi / 2, -np.pi / 2, alpha.shape[0] + 1)
    weights = np.sin(edges[:-1]) - np.sin(edges[1:])
    horizontal = min(360.0, mosaic.width / mosaic.scale_x)
    return {
        "horizontal_degrees": horizontal,
        "horizontal_percent": horizontal / 3.6,
        "observed_horizontal_percent": float(alpha.any(axis=0).mean() * 100),
        "sphere_percent": float(np.sum(alpha.mean(axis=1) * weights) * 50),
        "canvas_percent": float(alpha.mean() * 100),
        "method": "solid-angle-weighted alpha mask at output resolution",
    }


# Identifies the recipe that produced a sphere. Bump it whenever a change would
# make a texture or its metadata come out different, so a resumed run discards
# what the old recipe built instead of keeping a mix of both.
BUILD_VERSION = 2


def reusable(metadata: dict, width: int, product: dict | None = None) -> bool:
    """Whether a product on disk is what this run would build anyway.

    `product` is the selection row it would be built from. A download rewrites
    the selection every run, and a stop the traverse now only bounds is a
    different answer from the exact one an earlier run wrote, so a build that
    no longer agrees with its row is rebuilt rather than kept.
    """
    if metadata.get("build_version") != BUILD_VERSION or metadata.get("width") != width:
        return False
    if product is None:
        return True
    position = metadata.get("position") or {}
    return metadata.get("sol") == product["mosaic"]["sol"] and all(
        position.get(key) == value for key, value in product["position"].items()
    )


def catalog_entry(metadata: dict, directory: Path, output_dir: Path) -> dict:
    """The index entry for a product, however it came to be on disk."""
    return {
        "id": metadata["id"],
        "sol": metadata.get("sol"),
        "sphere_ready": True,
        "map_ready": True,
        "color": metadata["color"],
        "position": metadata["position"],
        "metadata": str((directory / "metadata.json").relative_to(output_dir)),
    }


def build_product(root, output_dir, collection, mission, product, width):
    """Render one mosaic to a sphere and write its metadata."""
    mosaic = Mosaic(**product["mosaic"])
    mosaic.validate()
    rgba, tone, grid_remains = read_pixels(root / product["image"], mosaic)
    texture = sphere_texture(rgba, mosaic, width)
    directory = output_dir / collection / product["id"]
    directory.mkdir(parents=True, exist_ok=True)
    texture.save(directory / "panorama.webp", quality=90, method=4)
    preview = Image.fromarray(rgba)
    preview.thumbnail((1536, 768), Image.Resampling.LANCZOS)
    preview.save(directory / "preview.webp", quality=85)
    metadata = {
        "schema_version": 1,
        "build_version": BUILD_VERSION,
        "id": product["id"],
        "body": "mars",
        "body_id": "naif-499",
        "mission": mission,
        "instrument": (
            mer.instrument(mosaic.product_id)
            if mission in mer.VOLUMES
            else "IDC"
            if mission == "insight"
            else "Navcam"
        ),
        "sol": mosaic.sol,
        "start_time": mosaic.start_time,
        "stop_time": mosaic.stop_time,
        "site": mosaic.site,
        "drive": mosaic.drive,
        "position": {
            "latitude_type": "planetocentric",
            "longitude_direction": "east",
            "longitude_range": [0, 360],
            "elevation_datum": "source Mars geoid",
            "method": "exact site/drive join",
            "reference_point": "rover localization",
            "uncertainty_m": None,
            "source_url": product["position_source_url"],
            **product["position"],
        },
        "projection": "equirectangular",
        "width": width,
        "height": width // 2,
        "hfov_deg": 360,
        "vfov_deg": 180,
        # A site frame is referenced to north, so the sphere is already
        # aligned. A lander frame is referenced to the lander, and nothing
        # in the label ties it to north, so no heading may be claimed.
        "north_azimuth_offset_deg": None if mosaic.frame == "LANDER_FRAME" else 0,
        "pixel_convention": (
            "pixel centers; left edge is the frame's zero azimuth; clockwise; "
            "top edge +90 degrees"
            if mosaic.frame == "LANDER_FRAME"
            else "pixel centers; left edge north; clockwise; top edge +90 degrees"
        ),
        "source_coverage": {
            "hfov_deg": min(360, mosaic.width / mosaic.scale_x),
            "azimuth_start_deg": mosaic.azimuth,
            "elevation_max_deg": (mosaic.zero_line - 0.5) / mosaic.scale_y,
            "elevation_min_deg": (mosaic.zero_line - mosaic.height - 0.5)
            / mosaic.scale_y,
            "frame": mosaic.frame,
            "frame_is_north_referenced": mosaic.frame != "LANDER_FRAME",
            "holes": "alpha=0; no synthetic sky or ground",
        },
        "coverage_fraction": float(
            np.count_nonzero(np.asarray(texture)[:, :, 3]) / (width * (width // 2))
        ),
        "coverage": {
            **coverage(texture, mosaic),
            "includes_source_grid": grid_remains,
        },
        "color": "rgb" if mosaic.bands == 3 else "grayscale",
        "source_width": mosaic.width,
        "source_height": mosaic.height,
        "image": "panorama.webp",
        "preview": "preview.webp",
        "tone_mapping": tone,
        "quality_notes": [
            "The archived coordinate underlay is excluded; the viewer draws its own angular grid.",
            "Mosaic seams and near-rover parallax are retained.",
        ],
        "credit": "Courtesy NASA/JPL-Caltech",
        "reuse_policy_url": POLICY,
        "sources": {
            k: v for k, v in product.items() if k.endswith(("_url", "_sha256"))
        },
        "output_sha256": sha256(directory / "panorama.webp"),
    }
    write_json(directory / "metadata.json", metadata)
    logger.info(
        "Processed %s (%.1f%% sphere coverage)",
        product["id"],
        metadata["coverage"]["sphere_percent"],
    )
    return catalog_entry(metadata, directory, output_dir)


def process(
    source_dir: Path, output_dir: Path, mission: str, *, width=4096, rebuild=False
):
    root = source_dir / mission
    # Keep an archive's mosaics separate from the curated galleries of the same
    # rover, so rebuilding one cannot replace the other.
    collection = MOSAIC_COLLECTIONS.get(mission, mission)
    selection = json.loads((root / "selection.json").read_text())
    entries, rejected, kept = [], [], 0
    for product in selection["products"]:
        directory = output_dir / collection / product["id"]
        built = directory / "metadata.json"
        if built.is_file():
            metadata = json.loads(built.read_text())
            if not rebuild and reusable(metadata, width, product):
                entries.append(catalog_entry(metadata, directory, output_dir))
                kept += 1
                continue
            # Built by a recipe this run no longer agrees with, so it goes
            # rather than leaving the collection half one recipe, half another.
            shutil.rmtree(directory)
        # Only the bytes this run is about to read. A product it reuses was
        # built from bytes an earlier run checked, and rechecking the whole
        # cache to skip it costs a resumed run hours of hashing.
        # A corrupted cache is an integrity fault, not an unusable mosaic, so it
        # stays fatal rather than being recorded as one product's rejection.
        for key in ("label", "image"):
            if sha256(root / product[key]) != product[key + "_sha256"]:
                raise ValueError(f"Cached {key} checksum mismatch: {product['id']}")
        try:
            entries.append(
                build_product(root, output_dir, collection, mission, product, width)
            )
        except (ValueError, KeyError, OSError) as error:
            # One unusable mosaic must not cost the run every other product,
            # which a raise here would, by skipping the catalog write below.
            rejected.append({"id": product["id"], "reason": str(error)})
            logger.warning("Rejected %s: %s", product["id"], error)
    # A download still in progress is a legitimate thing to process, but the
    # collection it yields is not the whole traverse, and nothing else on disk
    # says so.
    complete = bool(selection.get("complete"))
    write_json(
        output_dir / collection / "catalog.json",
        {
            "schema_version": 1,
            "body": "mars",
            "source_complete": complete,
            "panoramas": entries,
        },
    )
    write_json(output_dir / collection / "processing-rejected.json", rejected)
    logger.info(
        "%s: %s panoramas (%s already built), %s rejected, from %s selection",
        mission,
        len(entries),
        kept,
        len(rejected),
        "a complete" if complete else "an unfinished",
    )
    return entries
