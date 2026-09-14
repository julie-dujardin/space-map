"""Download official Navcam mosaics and prepare masked sphere textures."""

from dataclasses import asdict
import csv
import hashlib
import io
import json
import logging
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


def download(
    client,
    source_dir: Path,
    mission: str,
    *,
    start_sol=0,
    end_sol=None,
    limit=None,
    sol_step=1,
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
    accepted, rejected, seen = [], [], set()
    previous_sol = None
    for sol, products in mosaic_listings(
        client, root, mission, start_sol=start_sol, end_sol=end_sol, refresh=refresh
    ):
        # Thinning by sol spreads a bounded download over the whole mission.
        if previous_sol is not None and sol - previous_sol < sol_step:
            continue
        taken = len(accepted)
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
            try:
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
                    counter = mer.mosaic_counter(
                        stated.get("nav"), stated.get("lis"), url, sol, drives
                    )
                    if counter not in lookup:
                        raise ValueError("No exact site/drive localization")
                    image_url = url + name
                    mosaic = read_mer_pds3(ranged_label(client, image_url), counter[1])
                else:
                    label = fetch(
                        client, url + name, root / "labels" / name, refresh=refresh
                    )
                    read = (
                        read_pds3
                        if mission == "curiosity"
                        else read_insight_pds4
                        if mission == "insight"
                        else read_pds4
                    )
                    mosaic = read(label.read_text())
                if not fixed and (mosaic.site, mosaic.drive) not in lookup:
                    raise ValueError("No exact site/drive localization")
                # Keep separate sweeps at the same stop, but not processing revisions.
                revision_key = (
                    mosaic.product_id[:-1]
                    if mission in mer.VOLUMES
                    else re.sub(r"\d{2}$", "", mosaic.product_id)
                )
                if revision_key in seen:
                    continue
                # InSight labels keep only the last three digits of the sol;
                # the directory a product is filed under holds the whole number.
                if mission == "insight" and mosaic.sol == sol % 1000:
                    mosaic.sol = sol
                if mosaic.sol != sol or mosaic.product_id != (
                    Path(name).stem.upper()
                    if mission in mer.VOLUMES
                    else Path(name).stem
                ):
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
                    "position": fixed or lookup[(mosaic.site, mosaic.drive)],
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
            seen.add(revision_key)
            write_json(
                root / "selection.json",
                {"schema_version": 1, "products": accepted, "rejected": rejected},
            )
            logger.info(
                "Downloaded %s sol %s site %s drive %s",
                mission,
                sol,
                mosaic.site,
                mosaic.drive,
            )
            if limit is not None and len(accepted) >= limit:
                break
        if len(accepted) > taken:
            previous_sol = sol
        if limit is not None and len(accepted) >= limit:
            break
    if not accepted:
        write_json(root / "rejected.json", rejected)
        raise ValueError(f"No supported localized panoramas found for {mission}")
    write_json(
        root / "selection.json",
        {
            "schema_version": 1,
            "products": accepted,
            "rejected": rejected,
            "selection": {
                "start_sol": start_sol,
                "end_sol": end_sol,
                "limit": limit,
                "sol_step": sol_step,
            },
        },
    )
    return accepted


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
    grid_dn = coordinate_grid_dn(read_header(path, mosaic))
    if grid_dn is not None:
        pixels, valid = remove_coordinate_grid(pixels, valid, grid_dn)
        pixels, valid = remove_coordinate_label_borders(pixels, valid, mosaic)
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
    return rgba, {
        "stretch_percentiles": [0.5, 99.5],
        "source_dn_range": [float(low), float(high)],
        "transfer": "sRGB",
        "scientific_radiometry": False,
    }


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
BUILD_VERSION = 1


def reusable(metadata: dict, width: int) -> bool:
    """Whether a product on disk is what this run would build anyway."""
    return (
        metadata.get("build_version") == BUILD_VERSION
        and metadata.get("width") == width
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
    rgba, tone = read_pixels(root / product["image"], mosaic)
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
            "includes_source_grid": coordinate_grid_remains(
                read_header(root / product["image"], mosaic)
            ),
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
        # A corrupted cache is an integrity fault, not an unusable mosaic, so it
        # stays fatal rather than being recorded as one product's rejection.
        for key in ("label", "image"):
            if sha256(root / product[key]) != product[key + "_sha256"]:
                raise ValueError(f"Cached {key} checksum mismatch: {product['id']}")
        directory = output_dir / collection / product["id"]
        built = directory / "metadata.json"
        if built.is_file():
            metadata = json.loads(built.read_text())
            if not rebuild and reusable(metadata, width):
                entries.append(catalog_entry(metadata, directory, output_dir))
                kept += 1
                continue
            # Built by a recipe this run no longer agrees with, so it goes
            # rather than leaving the collection half one recipe, half another.
            shutil.rmtree(directory)
        try:
            entries.append(
                build_product(root, output_dir, collection, mission, product, width)
            )
        except (ValueError, KeyError, OSError) as error:
            # One unusable mosaic must not cost the run every other product,
            # which a raise here would, by skipping the catalog write below.
            rejected.append({"id": product["id"], "reason": str(error)})
            logger.warning("Rejected %s: %s", product["id"], error)
    write_json(
        output_dir / collection / "catalog.json",
        {"schema_version": 1, "body": "mars", "panoramas": entries},
    )
    write_json(output_dir / collection / "processing-rejected.json", rejected)
    logger.info(
        "%s: %s panoramas (%s already built), %s rejected",
        mission,
        len(entries),
        kept,
        len(rejected),
    )
    return entries
