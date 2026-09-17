"""Panoramas built from the frames China's planetary data release publishes.

The release carries no mosaics for any of its surface missions, only single
frames. Each frame states where the craft stood and which way every corner of
it points, so the frames of one stop can be put on a sphere without estimating
anything. One geometry serves Mars and the Moon alike; only the naming around
it differs, and not consistently even within a label.
"""

from dataclasses import dataclass, asdict
import argparse
import json
import logging
import math
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import httpx
import numpy as np

from .pipeline import fetch, sha256, write_json

logger = logging.getLogger(__name__)

CATALOGUE = "https://clpds.bao.ac.cn/moon-admin/client/science/dataInfoList"
ANNEX = "https://clpds.bao.ac.cn/moon-admin/client/science/dataInfo/getAnnexZip"
# The release portal serves its metadata from one host and its files from
# another; a record's browse path names the directory the file sits in.
FILES = "https://moon.bao.ac.cn/WEBDATA"
BROWSE_PREFIX = "/img-api/upload"
# A sweep is the frames of one sequence taken without the craft moving.
# Positions are stated to six decimals, finer than any of them can be placed.
POSITION_PLACES = 5
MINIMUM_FRAMES = 3
CREDIT = "China National Space Administration / Ground Research and Application System"
POLICY = "https://clpds.bao.ac.cn/"
# The release states no reuse terms this project can rely on, so its panoramas
# are built and kept but not published until permission is settled.
REUSE = "permission-pending"
# Tags are matched in lower case: a single label spells `Longitude` next to
# `latitude`, and the Moon lower-cases the vectors the Mars labels capitalise.
CORNERS = (
    "up_left_point_observe_vector",
    "down_left_point_observe_vector",
    "up_right_point_observe_vector",
    "down_right_point_observe_vector",
    "center_point_observe_vector",
)
# The archive misspells the principal point on its lunar labels, and names its
# coordinates `x0`/`y0` or `X`/`Y` depending on the mission.
PRINCIPAL = ("principal_point_coordinate", "principle_point_coordinate")
# Three surface missions are deliberately absent. Chang'e 3 publishes its
# panoramic camera frames with no label of any kind, so nothing states where
# Yutu stood or where it looked. The Chang'e 5 and 6 landers point their
# panoramic camera at the sampling area and at themselves: their frames stitch,
# but a dozen of them stack on ground a metre away, and a camera that turns
# about its mast rather than its lens sees that ground from a different place
# in each one. The result is the lander's own deck, not a view from it.
# Only the craft that carried the camera; a rover names its own place, a
# lander the one it never left.
LOCATIONS = ("rover_location", "lander_location")
SAMPLES = {"UnsignedByte": "|u1", "UnsignedLSB2": "<u2", "UnsignedMSB2": ">u2"}
# Metres a craft's two stated positions may disagree by before the frame is
# read as east-north-up wrongly.
FRAME_TOLERANCE_M = 25
# How far the fitted camera model may miss the pointing the label states. A
# pinhole ignores the lens distortion the stated corners include, which costs
# these cameras under a tenth of a degree — a fraction of one output pixel at
# the usual 4096-wide sphere. A wrong axis or sign misses by tens of degrees.
MODEL_TOLERANCE_DEG = 0.5
RADII_M = {"mars": 3396190.0, "moon": 1737400.0}


@dataclass(frozen=True)
class Release:
    """One camera of one mission, as the release system files it."""

    slug: str
    body: str
    body_id: str
    catalogue: int
    instrument: str
    # A panoramic camera is a stereo pair, and one eye covers the sphere.
    eye: str
    suffix: str
    # Mars counts sols; the Moon's sequence number is not a day count.
    counts_sols: bool


RELEASES = {
    release.slug: release
    for release in (
        Release(
            "zhurong", "mars", "naif-499", 489, "NaTeCam", "NaTeCamA", ".2CL", True
        ),
        Release("yutu-2", "moon", "naif-301", 672, "PCAM", "PCAML", ".2BL", False),
    )
}


@dataclass
class Frame:
    product_id: str
    sequence: int
    start_time: str
    latitude: float
    longitude: float
    elevation_m: float | None
    width: int
    height: int
    bands: int
    dtype: str
    focal_mm: float
    pixel_mm: float
    principal_mm: tuple[float, ...]
    # Four corners then the centre, as unit vectors the archive states.
    pointing: tuple[tuple[float, ...], ...]

    def validate(self):
        if min(self.width, self.height) < 2:
            raise ValueError("Expected a raster with area")
        if self.focal_mm <= 0 or self.pixel_mm <= 0:
            raise ValueError("Invalid camera geometry")
        if len(self.pointing) != len(CORNERS):
            raise ValueError("Incomplete frame pointing")


def text(node, path: str) -> str:
    """A field by its lower-cased tag, whichever way the label spells it."""
    found = node.find(path)
    if found is None or found.text is None:
        raise ValueError(f"Missing release field: {path}")
    return found.text.strip()


def first(node, paths, *fields: str) -> str:
    """A field under whichever block and spelling a label happens to use."""
    for path in paths:
        for field in fields:
            found = node.find(f".//{path}/{field}")
            if found is not None and found.text is not None:
                return found.text.strip()
    raise ValueError(f"Missing release field: {fields[0]}")


def confirm_east_north(root, release: Release):
    """Check the two ways a label states one position agree.

    Every pointing vector is read east-north-up. A label that also gives the
    craft's offset from its lander in metres states the same thing twice, so
    the axes can be confirmed per frame rather than assumed from one mission
    to the next.
    """
    offsets = root.find(".//rover_locationxyz")
    lander = root.find(".//lander_location")
    if offsets is None or lander is None:
        return
    try:
        latitude = float(text(lander, "latitude"))
        degree = RADII_M[release.body] * math.pi / 180
        north = (float(first(root, LOCATIONS, "latitude")) - latitude) * degree
        east = (
            (
                float(first(root, LOCATIONS, "longitude"))
                - float(text(lander, "longitude"))
            )
            * degree
            * math.cos(math.radians(latitude))
        )
        stated = (float(text(offsets, "x")), float(text(offsets, "y")))
    except ValueError, KeyError:
        return
    if max(abs(stated[0] - east), abs(stated[1] - north)) > FRAME_TOLERANCE_M:
        raise ValueError("Stated position and lander-frame offset disagree")


def read_label(raw: str, release: Release) -> Frame:
    """The one frame a label describes."""
    root = ET.fromstring(raw)
    for node in root.iter():
        node.tag = node.tag.split("}")[-1].lower()
    area = root.find(".//mission_area")
    if area is None or text(area, "instrument_id") != release.instrument:
        raise ValueError(f"Not a {release.instrument} frame")
    ordered = sorted(
        root.findall(".//axis_array"), key=lambda a: int(text(a, "sequence_number"))
    )
    axes = {text(a, "axis_name").lower(): int(text(a, "elements")) for a in ordered}
    # A band-sequential raster holds the same number of samples as a
    # pixel-interleaved one, so reading the order off the label is the only
    # thing between a colour frame and a silently scrambled one.
    names = [text(a, "axis_name").lower() for a in ordered]
    if names not in (["line", "sample"], ["line", "sample", "band"]):
        raise ValueError(f"Unsupported raster axes: {names}")
    sample = text(root, ".//data_type")
    if sample not in SAMPLES:
        raise ValueError(f"Unsupported sample type: {sample}")
    if text(root, ".//axis_index_order") != "Last Index Fastest":
        raise ValueError("Unsupported axis order")
    elevation = next(
        (
            float(n.text) * 1000
            for path in LOCATIONS
            for n in [root.find(f".//{path}/altitude")]
            if n is not None and n.text
        ),
        None,
    )
    confirm_east_north(root, release)
    result = Frame(
        text(area, "product_id"),
        int(text(area, "sequence_id")),
        text(root, ".//start_date_time"),
        float(first(area, LOCATIONS, "latitude")),
        float(first(area, LOCATIONS, "longitude")) % 360,
        elevation,
        axes["sample"],
        axes["line"],
        axes.get("band", 1),
        SAMPLES[sample],
        float(text(area, ".//focal_length")),
        float(text(area, ".//pixel_size")) / 1000,
        (
            float(first(area, PRINCIPAL, "x0", "x")),
            float(first(area, PRINCIPAL, "y0", "y")),
        ),
        tuple(
            tuple(float(text(area, f".//{corner}/{axis}")) for axis in "xyz")
            for corner in CORNERS
        ),
    )
    result.validate()
    return result


def camera_rays(frame: Frame, columns, rows):
    """Which way the camera looks at each pixel, in its own frame."""
    centre_x = frame.width / 2 + frame.principal_mm[0] / frame.pixel_mm
    centre_y = frame.height / 2 + frame.principal_mm[1] / frame.pixel_mm
    rays = np.stack(
        [
            (columns - centre_x) * frame.pixel_mm,
            (rows - centre_y) * frame.pixel_mm,
            np.full(np.shape(columns), frame.focal_mm),
        ],
        axis=-1,
    )
    return rays / np.linalg.norm(rays, axis=-1, keepdims=True)


def fit(frame: Frame) -> tuple[np.ndarray, float]:
    """Turn the camera's own frame onto the sky, fitted to what the label states.

    The label gives the direction of four corners and the centre; a rigid fit
    onto them carries the whole raster without trusting a sign convention the
    archive never writes down. A fit that misses by more than a pixel means the
    model is wrong, not merely imprecise.
    """
    columns = np.array([0, 0, frame.width - 1, frame.width - 1, frame.width / 2])
    rows = np.array([0, frame.height - 1, 0, frame.height - 1, frame.height / 2])
    stated = np.array(frame.pointing)
    stated = stated / np.linalg.norm(stated, axis=1, keepdims=True)
    rays = camera_rays(frame, columns, rows)
    left, _, right = np.linalg.svd(rays.T @ stated)
    flip = np.diag([1, 1, np.sign(np.linalg.det(right.T @ left.T))])
    found = right.T @ flip @ left.T
    residual = float(
        np.degrees(
            np.arccos(np.clip(((found @ rays.T).T * stated).sum(1), -1, 1))
        ).max()
    )
    if residual > MODEL_TOLERANCE_DEG:
        raise ValueError(f"Camera model misses the stated pointing by {residual:.2f}°")
    return found, residual


def rotation(frame: Frame) -> np.ndarray:
    """Turn the camera's own frame onto the sky."""
    return fit(frame)[0]


def sphere_directions(width: int):
    """Unit vectors for every pixel of a north-first, clockwise sphere.

    The archive states pointing east-north-up, which the rover attitude
    confirms: a heading of 90 degrees minus the stated yaw is the bearing the
    rover actually drove along.
    """
    height = width // 2
    azimuth = np.deg2rad((np.arange(width) + 0.5) / width * 360)
    elevation = np.deg2rad(90 - (np.arange(height) + 0.5) / height * 180)
    cosine = np.cos(elevation)[:, None]
    return np.stack(
        [
            cosine * np.sin(azimuth)[None, :],
            cosine * np.cos(azimuth)[None, :],
            np.repeat(np.sin(elevation)[:, None], width, axis=1),
        ],
        axis=-1,
    )


def frame_window(frame: Frame, width: int):
    """The columns and rows of the sphere one frame can reach.

    A frame that straddles north wraps, so columns are returned unwrapped and
    taken modulo the width when the sphere is written.
    """
    height = width // 2
    corners = np.array(frame.pointing)[:4]
    corners = corners / np.linalg.norm(corners, axis=1, keepdims=True)
    elevations = np.degrees(np.arcsin(np.clip(corners[:, 2], -1, 1)))
    azimuths = np.degrees(np.arctan2(corners[:, 0], corners[:, 1])) % 360
    # A margin of one frame radius keeps a rotated square inside its window.
    margin = math.degrees(math.atan(frame.width * frame.pixel_mm / 2 / frame.focal_mm))
    low = math.floor((azimuths.min() - margin) / 360 * width)
    high = math.ceil((azimuths.max() + margin) / 360 * width)
    if high - low > width / 2:
        shifted = (azimuths + 180) % 360
        low = math.floor((shifted.min() - margin + 180) / 360 * width)
        high = math.ceil((shifted.max() + margin + 180) / 360 * width)
    rows = np.arange(
        max(0, math.floor((90 - elevations.max() - margin) / 180 * height)),
        min(height, math.ceil((90 - elevations.min() + margin) / 180 * height)),
    )
    return np.arange(low, high + 1), rows


def paint(frame: Frame, raster, total, weight, directions):
    """Add one frame to the sphere it covers part of."""
    found = rotation(frame)
    width = total.shape[1]
    columns, rows = frame_window(frame, width)
    if not len(columns) or not len(rows):
        return
    wrapped = columns % width
    rays = directions[np.ix_(rows, wrapped)] @ found
    forward = rays[..., 2] > 0
    scale = frame.focal_mm / frame.pixel_mm
    centre_x = frame.width / 2 + frame.principal_mm[0] / frame.pixel_mm
    centre_y = frame.height / 2 + frame.principal_mm[1] / frame.pixel_mm
    with np.errstate(divide="ignore", invalid="ignore"):
        x = centre_x + rays[..., 0] / rays[..., 2] * scale
        y = centre_y + rays[..., 1] / rays[..., 2] * scale
    inside = (
        forward & (x >= 0) & (x <= frame.width - 1) & (y >= 0) & (y <= frame.height - 1)
    )
    if not inside.any():
        return
    sample_x = np.clip(np.rint(x), 0, frame.width - 1).astype(np.int32)
    sample_y = np.clip(np.rint(y), 0, frame.height - 1).astype(np.int32)
    # Weight a frame by how squarely it looks at each point: a dense scan can
    # stack a dozen frames on one spot, and the camera turns about the mast
    # rather than its own lens, so averaging them all smears anything close
    # enough to shift between them. The nearest-centred frame dominates, and
    # the fall-off still feathers the edges rather than cutting them.
    offset = np.maximum(
        np.abs(x / (frame.width - 1) * 2 - 1), np.abs(y / (frame.height - 1) * 2 - 1)
    )
    share = np.where(inside, np.clip(1 - offset, 1e-3, 1) ** 3, 0)
    taken = raster[sample_y, sample_x].astype(np.float32)
    index = np.ix_(rows, wrapped)
    np.add.at(total, index, taken * share[..., None])
    np.add.at(weight, index, share)


def read_raster(path: Path, frame: Frame):
    """The frame's samples, shaped for the painter."""
    expected = frame.height * frame.width * frame.bands
    raster = np.memmap(path, mode="r", dtype=frame.dtype)
    if raster.size < expected:
        raise ValueError(f"Truncated frame: {path}")
    shape = (frame.height, frame.width, frame.bands)
    return np.asarray(raster[:expected]).reshape(shape)


def sweep_sphere(frames, paths, width: int):
    """One stop's frames on a sphere, with the canvas they never reached clear.

    An eight-bit frame is already a display product and is carried through as
    it is; deeper samples are stretched once across the whole sweep, so frames
    keep their brightness relative to each other.
    """
    height = width // 2
    bands = max(f.bands for f in frames)
    total = np.zeros((height, width, bands), np.float32)
    weight = np.zeros((height, width), np.float32)
    directions = sphere_directions(width)
    for frame, path in zip(frames, paths):
        paint(frame, read_raster(path, frame), total, weight, directions)
    covered = weight > 0
    if not covered.any():
        raise ValueError("Sweep covers none of the sphere")
    value = total[covered] / weight[covered][:, None]
    if any(np.dtype(f.dtype).itemsize > 1 for f in frames):
        # Sunlit insulation on a lander deck is far brighter than any ground,
        # so a stretch reaching into the top half percent leaves the scene grey.
        low, high = np.percentile(value, [2, 98])
        if high <= low:
            raise ValueError("Sweep has no displayable dynamic range")
        value = np.clip((value - low) / (high - low), 0, 1) * 255
    rgb = np.zeros((height, width, 3), np.uint8)
    rgb[covered] = np.clip(
        value if bands == 3 else np.repeat(value, 3, axis=1), 0, 255
    ).astype(np.uint8)
    return np.dstack((rgb, covered.astype(np.uint8) * 255)), covered


def records(client, root: Path, release: Release, *, refresh=False):
    """Every released frame of this camera.

    The whole inventory arrives in one chunked response, and the release drops
    the connection often enough that one attempt is not enough.
    """
    url = f"{CATALOGUE}?dataCatalogueId={release.catalogue}&pageNum=1&pageSize=40000"
    for attempt in range(4):
        try:
            found = json.loads(
                fetch(client, url, root / "inventory.json", refresh=refresh).read_text()
            )
            break
        except (httpx.HTTPError, json.JSONDecodeError) as error:
            if attempt == 3:
                raise
            logger.warning("Inventory attempt %s failed: %s", attempt + 1, error)
            time.sleep(2 ** (attempt + 1))
    return [row for row in found["rows"] if row["name"].endswith(release.suffix)]


def file_url(client, row) -> str:
    """Where the release actually serves a record.

    The browse path names the directory for the missions that have one; the
    rest have to be asked, and the answer is a different host again.
    """
    browse = row.get("image")
    if browse and browse.startswith(BROWSE_PREFIX):
        directory = browse.rsplit("/", 1)[0]
        return f"{FILES}{directory[len(BROWSE_PREFIX) :]}/{row['name']}"
    answer = client.get(f"{ANNEX}/{row['dataInfoId']}")
    answer.raise_for_status()
    found = answer.json().get("data")
    if not found:
        raise ValueError("Release states no download for this record")
    return found


def sweeps(frames):
    """Frames grouped into the stops they were taken from."""
    groups: dict[tuple, list[Frame]] = {}
    for frame in frames:
        key = (
            frame.sequence,
            round(frame.latitude, POSITION_PLACES),
            round(frame.longitude, POSITION_PLACES),
        )
        groups.setdefault(key, []).append(frame)
    return {k: v for k, v in sorted(groups.items()) if len(v) >= MINIMUM_FRAMES}


def download(client, source_dir: Path, slug: str, *, refresh=False):
    release = RELEASES[slug]
    root = source_dir / slug
    accepted, rejected = [], []
    rows = [
        r
        for r in records(client, root, release, refresh=refresh)
        if release.eye in r["name"]
    ]
    logger.info("%s: %s %s frames released", slug, len(rows), release.eye)
    for row in rows:
        try:
            url = file_url(client, row)
            label = fetch(client, url, root / "labels" / row["name"], refresh=refresh)
            frame = read_label(label.read_text(), release)
            raster_url = url.replace(row["name"], row["name"].removesuffix("L"))
            raster = fetch(
                client,
                raster_url,
                root / "frames" / (frame.product_id + release.suffix[:-1]),
                refresh=refresh,
            )
            rotation(frame)
        except (ValueError, httpx.HTTPError, ET.ParseError) as error:
            rejected.append({"label_url": row["name"], "reason": str(error)})
            continue
        accepted.append(
            {
                "frame": asdict(frame),
                "label": str(label.relative_to(root)),
                "raster": str(raster.relative_to(root)),
                "label_url": url,
                "raster_url": raster_url,
                "label_sha256": sha256(label),
                "raster_sha256": sha256(raster),
            }
        )
        if len(accepted) % 50 == 0:
            logger.info("%s: %s frames held", slug, len(accepted))
    write_json(
        root / "selection.json",
        {"schema_version": 1, "frames": accepted, "rejected": rejected},
    )
    logger.info("%s: %s frames, %s rejected", slug, len(accepted), len(rejected))
    return accepted


def process(source_dir: Path, output_dir: Path, slug: str, *, width=4096):
    from PIL import Image

    release = RELEASES[slug]
    root = source_dir / slug
    selection = json.loads((root / "selection.json").read_text())
    held = {f["frame"]["product_id"]: f for f in selection["frames"]}
    frames = [Frame(**f["frame"]) for f in selection["frames"]]
    entries = []
    for (sequence, latitude, longitude), group in sweeps(frames).items():
        group.sort(key=lambda f: f.start_time)
        paths = [root / held[f.product_id]["raster"] for f in group]
        rgba, covered = sweep_sphere(group, paths, width)
        identity = f"{slug}-{sequence:05}-{group[0].product_id.lower()}"
        directory = output_dir / slug / identity
        directory.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgba).save(directory / "panorama.webp", quality=90, method=4)
        preview = Image.fromarray(rgba)
        preview.thumbnail((1536, 768), Image.Resampling.LANCZOS)
        preview.save(directory / "preview.webp", quality=85)
        solid = np.cos(
            np.deg2rad(90 - (np.arange(width // 2) + 0.5) / (width // 2) * 180)
        )
        sphere_percent = float(
            (covered * solid[:, None]).sum() / (width * solid.sum()) * 100
        )
        columns = float(covered.any(axis=0).mean() * 360)
        first_frame = group[0]
        metadata = {
            "schema_version": 1,
            "body": release.body,
            "body_id": release.body_id,
            "id": identity,
            "mission": slug,
            "instrument": release.instrument,
            "sequence_id": sequence,
            "start_time": first_frame.start_time,
            "stop_time": group[-1].start_time,
            "position": {
                "latitude": latitude,
                "longitude": longitude,
                "elevation_m": first_frame.elevation_m,
                "latitude_type": "planetocentric",
                "longitude_direction": "east",
                "longitude_range": [0, 360],
                "elevation_datum": None
                if first_frame.elevation_m is None
                else "source areoid",
                "method": "position stated by every frame of the sweep",
                "reference_point": "craft localization",
                "uncertainty_m": None,
                "source_url": POLICY,
            },
            "projection": "equirectangular",
            "width": width,
            "height": width // 2,
            "hfov_deg": 360,
            "vfov_deg": 180,
            "north_azimuth_offset_deg": 0,
            "orientation_status": "archival",
            "pixel_convention": "pixel centers; left edge north; clockwise; top edge +90 degrees",
            "source_coverage": {
                "frames": len(group),
                "frame_fov_deg": round(
                    math.degrees(
                        2
                        * math.atan(
                            first_frame.width
                            * first_frame.pixel_mm
                            / 2
                            / first_frame.focal_mm
                        )
                    ),
                    2,
                ),
                "frame": "pointing stated per frame, east-north-up",
                # How far the pinhole model missed the pointing the labels
                # state, over every frame of this sweep.
                "model_residual_deg": round(max(fit(f)[1] for f in group), 4),
                "holes": "alpha=0; no synthetic sky or ground",
            },
            "coverage": {
                "horizontal_degrees": columns,
                "horizontal_percent": columns / 360 * 100,
                "sphere_percent": sphere_percent,
                "method": "solid-angle-weighted alpha mask at output resolution",
                "includes_source_grid": False,
            },
            "color": "rgb" if first_frame.bands == 3 else "grayscale",
            "geometry_status": "archival",
            "render_status": "mosaicked from single frames; seams, exposure steps and parallax retained",
            "credit": CREDIT,
            "reuse": {"status": REUSE, "policy_url": POLICY},
            "reuse_policy_url": POLICY,
            "sources": {
                "frames": [
                    {
                        key: held[f.product_id][key]
                        for key in (
                            "label_url",
                            "raster_url",
                            "label_sha256",
                            "raster_sha256",
                        )
                    }
                    for f in group
                ]
            },
            "image": "panorama.webp",
            "preview": "preview.webp",
            "output_sha256": sha256(directory / "panorama.webp"),
        }
        if release.counts_sols:
            metadata["sol"] = sequence
        write_json(directory / "metadata.json", metadata)
        entries.append(
            {
                "id": identity,
                "sol": sequence if release.counts_sols else None,
                "sphere_ready": True,
                "map_ready": True,
                "color": metadata["color"],
                "position": metadata["position"],
                "metadata": str((directory / "metadata.json").relative_to(output_dir)),
            }
        )
        logger.info(
            "%s %s: %s frames, %.0f°, %.1f%% of the sphere",
            slug,
            sequence,
            len(group),
            columns,
            sphere_percent,
        )
    write_json(
        output_dir / slug / "catalog.json",
        {"schema_version": 1, "body": release.body, "panoramas": entries},
    )
    return entries


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["download", "process", "all"])
    parser.add_argument(
        "--missions", nargs="+", choices=sorted(RELEASES), required=True
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, default=4096)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.stage in {"download", "all"}:
        with httpx.Client(
            follow_redirects=True,
            timeout=120,
            transport=httpx.HTTPTransport(retries=3),
            headers={"User-Agent": "SpaceMap panorama data pipeline"},
        ) as client:
            for slug in args.missions:
                download(
                    client,
                    args.source_dir,
                    slug,
                    refresh=args.refresh,
                )
    if args.stage in {"process", "all"}:
        for slug in args.missions:
            process(args.source_dir, args.output_dir, slug, width=args.width)


if __name__ == "__main__":
    cli()
