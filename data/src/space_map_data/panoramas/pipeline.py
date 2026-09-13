"""Download official Navcam mosaics and prepare masked sphere textures."""

from dataclasses import asdict
import csv
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import httpx
import numpy as np
from PIL import Image

from .labels import Mosaic, attached_constants, read_pds3, read_pds4

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
PLACES = ARCHIVE + "msl/msl_places/data_localizations/localized_interp.csv"
WAYPOINTS = "https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json"
M20_PLACES = "https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_rover_places/data_localizations/best_interp.csv"
POLICY = "https://www.jpl.nasa.gov/jpl-image-use-policy/"
# VICAR declares the white DN but renders black grid annotations as DN 1.
GRID_BLACK_DN = 1
GRID_LABEL_VERTICAL_MARGIN = 32
GRID_LABEL_SIDE_MARGIN = 48
GRID_SEAM_MARGIN = 8


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


def mosaic_listings(client, root, mission, *, start_sol, end_sol, refresh):
    if mission == "perseverance":
        groups = m20_mosaic_listings(client, root, refresh=refresh)
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
    position_url = PLACES if mission == "curiosity" else M20_PLACES
    position_path = fetch(
        client,
        position_url,
        root / "positions.csv",
        refresh=refresh,
    )
    lookup = positions(mission, position_path)
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
            r"N_L\w+CYL\w+\.LBL"
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
                label = fetch(
                    client, url + name, root / "labels" / name, refresh=refresh
                )
                mosaic = (read_pds3 if mission == "curiosity" else read_pds4)(
                    label.read_text()
                )
                if (mosaic.site, mosaic.drive) not in lookup:
                    raise ValueError("No exact site/drive localization")
                # Keep separate sweeps at the same stop, but not processing revisions.
                revision_key = re.sub(r"\d{2}$", "", mosaic.product_id)
                if revision_key in seen:
                    continue
                if mosaic.sol != sol or mosaic.product_id != Path(name).stem:
                    raise ValueError("Product identity mismatch")
            except (ValueError, httpx.HTTPStatusError) as error:
                rejected.append({"label_url": url + name, "reason": str(error)})
                continue
            image_url = urljoin(url, mosaic.product_id + ".IMG")
            image = fetch(
                client,
                image_url,
                root / "images" / (mosaic.product_id + ".IMG"),
                refresh=refresh,
            )
            expected = mosaic.offset + mosaic.width * mosaic.height * mosaic.bands * 2
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
                    "position": lookup[(mosaic.site, mosaic.drive)],
                    "label": str(label.relative_to(root)),
                    "image": str(image.relative_to(root)),
                    "label_url": url + name,
                    "image_url": image_url,
                    "label_sha256": sha256(label),
                    "image_sha256": sha256(image),
                    "position_source_url": position_url,
                    "position_sha256": sha256(position_path),
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


def read_header(path: Path, mosaic: Mosaic) -> str:
    """Everything before the raster: the attached label and its VICAR image header."""
    with path.open("rb") as stream:
        return stream.read(mosaic.offset).decode("latin-1")


def coordinate_grid_dn(header: str) -> float | None:
    """Return the declared grid value so annotations never enter exported imagery."""
    if not re.search(r"\bGRID\s*=\s*['\"]?GRID_OVERLAY['\"]?", header):
        return None
    match = re.search(r"\bGRID_DN\s*=\s*([-+\d.eE]+)", header)
    if match is None:
        raise ValueError("Grid overlay has no declared DN")
    return float(match.group(1))


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


def process(source_dir: Path, output_dir: Path, mission: str, *, width=4096):
    root = source_dir / mission
    # Keep grayscale Navcam separate so rebuilding it cannot replace color Mastcam.
    collection = "curiosity-navcam" if mission == "curiosity" else mission
    selection = json.loads((root / "selection.json").read_text())
    entries = []
    for product in selection["products"]:
        mosaic = Mosaic(**product["mosaic"])
        mosaic.validate()
        for key in ("label", "image"):
            if sha256(root / product[key]) != product[key + "_sha256"]:
                raise ValueError(f"Cached {key} checksum mismatch: {product['id']}")
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
            "id": product["id"],
            "body": "mars",
            "body_id": "naif-499",
            "mission": mission,
            "instrument": "Navcam",
            "sol": mosaic.sol,
            "start_time": mosaic.start_time,
            "stop_time": mosaic.stop_time,
            "site": mosaic.site,
            "drive": mosaic.drive,
            "position": {
                **product["position"],
                "latitude_type": "planetocentric",
                "longitude_direction": "east",
                "longitude_range": [0, 360],
                "elevation_datum": "source Mars geoid",
                "method": "exact site/drive join",
                "reference_point": "rover localization",
                "uncertainty_m": None,
                "source_url": product["position_source_url"],
            },
            "projection": "equirectangular",
            "width": width,
            "height": width // 2,
            "hfov_deg": 360,
            "vfov_deg": 180,
            "north_azimuth_offset_deg": 0,
            "pixel_convention": "pixel centers; left edge north; clockwise; top edge +90 degrees",
            "source_coverage": {
                "hfov_deg": min(360, mosaic.width / mosaic.scale_x),
                "azimuth_start_deg": mosaic.azimuth,
                "elevation_max_deg": (mosaic.zero_line - 0.5) / mosaic.scale_y,
                "elevation_min_deg": (mosaic.zero_line - mosaic.height - 0.5)
                / mosaic.scale_y,
                "frame": mosaic.frame,
                "holes": "alpha=0; no synthetic sky or ground",
            },
            "coverage_fraction": float(
                np.count_nonzero(np.asarray(texture)[:, :, 3]) / (width * (width // 2))
            ),
            "coverage": {**coverage(texture, mosaic), "includes_source_grid": False},
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
        entries.append(
            {
                "id": product["id"],
                "sol": mosaic.sol,
                "sphere_ready": True,
                "map_ready": True,
                "color": metadata["color"],
                "position": metadata["position"],
                "metadata": str((directory / "metadata.json").relative_to(output_dir)),
            }
        )
        logger.info(
            "Processed %s (%.1f%% sphere coverage)",
            product["id"],
            metadata["coverage"]["sphere_percent"],
        )
    write_json(
        output_dir / collection / "catalog.json",
        {"schema_version": 1, "body": "mars", "panoramas": entries},
    )
    return entries
