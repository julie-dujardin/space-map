"""Recover which way a released panorama faces by matching it to an archival one.

A NASA release is published as a flat strip with no stated heading, so the
sphere built from it starts at an arbitrary azimuth. An archival Navcam mosaic
taken from the same stopping point does carry a heading, and both look at the
same skyline, so the azimuth that lines the two skylines up is the release's
start azimuth.

The match is only as good as the parallax allows: run it against references
the rover took from the same spot, and treat the score as a proposal for
review, not a measurement. `propose` ranks candidates; the reviewed answer
belongs in `curated_strips.json` where the rest of each strip's geometry lives.
"""

import argparse
import json
import logging
import math
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Mars' volumetric mean radius, for turning a degree gap into metres.
BODY_RADIUS_M = 3389500.0
# Beyond this the near field no longer lines up and the peak means little.
MAX_REFERENCE_M = 60.0
MIN_OVERLAP = 0.15


# Sky sits above the horizon, so the darker end of the upper hemisphere is
# already ground; splitting there beats a whole-image threshold, which the
# far larger ground area drags away from the horizon.
SKY_QUANTILE = 0.35


def skyline(path: Path, smooth: int = 5) -> np.ndarray:
    """Per-column horizon row of a sphere texture, NaN where unobserved.

    One threshold over the upper hemisphere keeps the profile comparable
    between two instruments that tone-map the same scene differently.
    """
    pixels = np.asarray(Image.open(path).convert("RGBA"))
    seen = pixels[..., 3] > 0
    if seen.sum() < 5000:
        return np.full(pixels.shape[1], np.nan)
    luminance = pixels[..., :3].astype(float) @ [0.2126, 0.7152, 0.0722]
    above = slice(0, pixels.shape[0] // 2)
    sky = luminance[above][seen[above]]
    if sky.size < 100:
        return np.full(pixels.shape[1], np.nan)
    threshold = float(np.quantile(sky, SKY_QUANTILE))
    profile = np.full(pixels.shape[1], np.nan)
    for column in range(pixels.shape[1]):
        rows = np.flatnonzero(seen[:, column])
        if rows.size < 30:
            continue
        ground = rows[luminance[rows, column] < threshold]
        if ground.size:
            profile[column] = ground[0]
    return _median_filter(profile, smooth)


def _median_filter(profile: np.ndarray, width: int) -> np.ndarray:
    if width < 3:
        return profile
    half = width // 2
    padded = np.concatenate([profile[-half:], profile, profile[:half]])
    windows = np.lib.stride_tricks.sliding_window_view(padded, width)
    with np.errstate(invalid="ignore"):
        return np.where(np.isfinite(profile), np.nanmedian(windows, axis=1), np.nan)


def _standardise(profile: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    seen = np.isfinite(profile)
    values = np.zeros(len(profile))
    if seen.sum() > 10:
        values[seen] = (profile[seen] - profile[seen].mean()) / (
            profile[seen].std() or 1
        )
    return values, seen.astype(float)


def correlate(reference: np.ndarray, strip: np.ndarray) -> np.ndarray:
    """Correlation of the two skylines at every circular shift of `strip`."""
    left, left_seen = _standardise(reference)
    right, right_seen = _standardise(strip)
    size = len(reference)
    product = np.fft.irfft(np.fft.rfft(left) * np.conj(np.fft.rfft(right)), size)
    overlap = np.fft.irfft(
        np.fft.rfft(left_seen) * np.conj(np.fft.rfft(right_seen)), size
    )
    score = product / np.maximum(overlap, 1)
    score[overlap < size * MIN_OVERLAP] = -1.0
    return score


def match(reference: Path, strip: Path) -> tuple[float, float]:
    """Degrees to rotate the strip sphere onto north, and how well it fits."""
    profile = skyline(reference)
    shifts = correlate(profile, skyline(strip))
    best = int(np.argmax(shifts))
    return best * 360 / len(shifts), float(shifts[best])


def ground_distance(first: dict, second: dict) -> float:
    """Metres between two panorama positions on the body's surface."""
    lat, other = math.radians(first["latitude"]), math.radians(second["latitude"])
    dlon = math.radians(second["longitude"] - first["longitude"])
    east = BODY_RADIUS_M * dlon * math.cos((lat + other) / 2)
    return math.hypot(east, BODY_RADIUS_M * (other - lat))


def _products(derived_dir: Path, collection: str) -> list[tuple[Path, dict]]:
    catalog = derived_dir / collection / "catalog.json"
    if not catalog.exists():
        return []
    out = []
    for item in json.loads(catalog.read_text())["panoramas"]:
        path = derived_dir / item["metadata"]
        out.append((path, json.loads(path.read_text())))
    return out


def references(derived_dir: Path, collection: str) -> list[dict]:
    """Archival spheres that state a heading, as match candidates."""
    found = []
    for path, metadata in _products(derived_dir, collection):
        if (
            metadata.get("north_azimuth_offset_deg") is None
            or metadata.get("orientation_status") == "unknown"
            or not metadata.get("position")
            or not metadata.get("image")
        ):
            continue
        found.append(
            {
                "id": metadata["id"],
                "image": path.parent / metadata["image"],
                "position": metadata["position"],
                "sol": metadata.get("sol"),
                "hfov_deg": (metadata.get("source_coverage") or {}).get("hfov_deg"),
            }
        )
    return found


def propose(
    derived_dir: Path,
    collection: str,
    reference_collection: str,
    *,
    limit=4,
    max_distance_m=MAX_REFERENCE_M,
) -> list[dict]:
    """For every unoriented strip, the best-fitting references and their scores.

    The reported azimuth is absolute: it already includes whatever start
    azimuth the strip was last rendered with, so it can be written straight
    back to the manifest.
    """
    pool = references(derived_dir, reference_collection)
    results = []
    for path, metadata in _products(derived_dir, collection):
        position = metadata.get("position")
        if not metadata.get("image") or not position:
            continue
        near = sorted(
            (
                (ground_distance(position, ref["position"]), ref)
                for ref in pool
                if ref["hfov_deg"] and ref["hfov_deg"] > 340
            ),
            key=lambda pair: pair[0],
        )
        rendered = (metadata.get("projection_bounds") or {}).get(
            "start_azimuth_deg"
        ) or 0
        candidates = []
        for distance, ref in near:
            if distance > max_distance_m or len(candidates) >= limit:
                break
            shift, score = match(ref["image"], path.parent / metadata["image"])
            candidates.append(
                {
                    "start_azimuth_deg": round((rendered + shift) % 360, 2),
                    "score": round(score, 3),
                    "reference": ref["id"],
                    "reference_sol": ref["sol"],
                    "distance_m": round(distance, 1),
                }
            )
        candidates.sort(key=lambda c: -c["score"])
        results.append(
            {
                "id": metadata["id"],
                "sol": metadata.get("sol"),
                "rendered_start_azimuth_deg": rendered,
                "stated": metadata.get("orientation_status") == "caption-aligned",
                "candidates": candidates,
            }
        )
        logger.info(
            "%s: %d candidate references, best %s",
            metadata["id"],
            len(candidates),
            candidates[0] if candidates else "none",
        )
    return results


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--references", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-distance", type=float, default=MAX_REFERENCE_M)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    found = propose(
        args.directory,
        args.collection,
        args.references,
        max_distance_m=args.max_distance,
    )
    args.output.write_text(json.dumps(found, indent=2) + "\n")
    print(f"Proposed headings for {len(found)} panoramas in {args.output}")


if __name__ == "__main__":
    cli()
