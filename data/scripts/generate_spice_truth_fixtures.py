"""Generate SPICE-truth fixtures for the frontend integration tests.

For a curated set of non-whitelisted moons, this script reads the per-chunk
mean elements from `moon_chunks/<naif_id>.npz` (the same sidecars the export
consumes) and pairs each chunk's element row with several SPICE-truth
positions sampled inside that chunk's validity window. The frontend test
([frontend/src/lib/integration/spice-truth.test.ts]) imports the resulting
JSON and asserts that propagating those elements with the production Kepler
+ secular-drift code reproduces the SPICE positions within tolerance.

The fixture is committed (a few hundred KB at most) so the test runs in CI
without needing kernels. Regenerate locally after a download run if the
sidecars change.

Run with the kernels already downloaded under
`space-map-downloads/spice/kernels` and the chunk sidecars under
`space-map-downloads/spice/moon_chunks`.
"""

import json
import logging
import sys
from pathlib import Path

import numpy as np
import spiceypy

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.utils.paths import DOWNLOAD_DIR  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

KERNEL_DIR = DOWNLOAD_DIR / "spice" / "kernels"
CHUNKS_DIR = DOWNLOAD_DIR / "spice" / "moon_chunks"
OUTPUT_PATH = REPO_ROOT / "frontend/src/lib/integration/spice-truth.fixtures.json"

# JD-TDB of J2000. SPICE works in ET (≈ TDB seconds past J2000); convert via
# `et = (jd - J2000_JD) * 86400`. The TDB/TT split is sub-millisecond so this
# is exact for our km-scale tolerance.
J2000_JD = 2451545.0
S_PER_DAY = 86400.0


# Bodies to sample. Each is a non-whitelisted moon — the production path is
# Method C (mean-element fit + secular om/w drift). Picked to span parents
# (Uranus / Neptune outer irregulars) and accuracy bands so a regression in
# any sub-population shows up. We deliberately stay away from Jupiter/Saturn
# outer irregulars where solar perturbations dwarf J2 and Method C is just
# "rough position" (~10⁶ km errors); those are documented in
# `validate_moon_propagation.py` and aren't useful here. NAIF IDs are SPICE
# body codes.
TEST_BODIES = [
    # Best-fit Method C bodies — small osculation amplitude
    {"naif_id": 802, "name": "Nereid", "parent": 8},  # Neptune
    {"naif_id": 722, "name": "Francisco", "parent": 7},  # Uranus
    {"naif_id": 716, "name": "Caliban", "parent": 7},  # Uranus
    # Moderate-fit
    {"naif_id": 717, "name": "Sycorax", "parent": 7},  # Uranus
    {"naif_id": 811, "name": "Sao", "parent": 8},  # Neptune
]

# Offsets (days) from each picked chunk's midpoint at which to sample SPICE.
# The Method C fit is valid within ±half_chunk_width (≈ 91 days for 0.5y
# chunks). 90 d covers the chunk edge; 0 hits the fit's anchor; the
# intermediates catch in-chunk drift.
SAMPLE_OFFSETS_DAYS = [0.0, 30.0, 60.0, 90.0, -45.0]


def _jd_to_et(jd: float) -> float:
    return (jd - J2000_JD) * S_PER_DAY


def _furnish_kernels() -> int:
    if not KERNEL_DIR.exists():
        raise FileNotFoundError(
            f"SPICE kernels not found at {KERNEL_DIR}; "
            "run the data downloader first (uv run space-map-download)."
        )
    paths = sorted(KERNEL_DIR.glob("*"))
    paths = [p for p in paths if p.suffix in (".bsp", ".tpc", ".tls")]
    for p in paths:
        spiceypy.furnsh(str(p))
    return len(paths)


def _pick_chunk_idx(midpoints_jd: np.ndarray, target_jd: float) -> int:
    """Pick the chunk whose midpoint is closest to `target_jd`."""
    return int(np.argmin(np.abs(midpoints_jd - target_jd)))


def _truth_position_km(naif_id: int, parent: int, jd: float) -> list[float]:
    """Parent-relative ECLIPJ2000 position in km from SPICE."""
    state, _ = spiceypy.spkezr(
        str(naif_id), _jd_to_et(jd), "ECLIPJ2000", "NONE", str(parent)
    )
    return [float(state[0]), float(state[1]), float(state[2])]


def _build_fixture_entry(body: dict) -> dict:
    naif_id = body["naif_id"]
    parent = body["parent"]
    chunk_path = CHUNKS_DIR / f"{naif_id}.npz"
    if not chunk_path.exists():
        raise FileNotFoundError(
            f"missing moon_chunks sidecar for {body['name']} (naif {naif_id}) "
            f"at {chunk_path}"
        )
    with np.load(chunk_path) as data:
        midpoints_jd = np.asarray(data["chunk_midpoints_jd"], dtype=np.float64)
        elements = np.asarray(data["elements"], dtype=np.float64)

    # Pick the chunk closest to 2026-01-01 (JD 2461041.5) — keeps the test
    # data relevant to the current epoch and well-inside SPK coverage.
    target_jd = 2461041.5
    chunk_idx = _pick_chunk_idx(midpoints_jd, target_jd)
    midpoint_jd = float(midpoints_jd[chunk_idx])
    el = elements[chunk_idx]
    half_chunk_jd = (
        float((midpoints_jd[1] - midpoints_jd[0]) / 2)
        if len(midpoints_jd) > 1
        else 91.0
    )

    samples: list[dict] = []
    for dt_days in SAMPLE_OFFSETS_DAYS:
        jd = midpoint_jd + dt_days
        samples.append(
            {
                "jd": jd,
                "expected_parent_relative_km": _truth_position_km(naif_id, parent, jd),
            }
        )

    return {
        "id": f"naif-{naif_id}",
        "name": body["name"],
        "parent_id": f"naif-{parent}",
        "propagation": "keplerian_with_drift",
        "chunk_idx": chunk_idx,
        "chunk_validity_jd": [
            midpoint_jd - half_chunk_jd,
            midpoint_jd + half_chunk_jd,
        ],
        # Quantize to float32 — that's what the binary export carries and what
        # the frontend parses. Matching the precision here lets the test pin a
        # tight propagation-only tolerance instead of mixing in quantization
        # noise (~kilometres for 0.1-AU moons at single precision).
        "elements": {
            "epoch": midpoint_jd,  # epoch_jd is float64 in the binary
            "a": float(np.float32(el[0])),
            "e": float(np.float32(el[1])),
            "i": float(np.float32(el[2])),
            "om": float(np.float32(el[3])),
            "w": float(np.float32(el[4])),
            "ma": float(np.float32(el[5])),
            "n": float(np.float32(el[6])),
            "omDot": float(np.float32(el[7])),
            "wDot": float(np.float32(el[8])),
            "equatorial": False,
        },
        "samples": samples,
    }


def main() -> None:
    n_kernels = _furnish_kernels()
    logger.info("Furnished %d kernels from %s", n_kernels, KERNEL_DIR)

    entries = []
    for body in TEST_BODIES:
        try:
            entries.append(_build_fixture_entry(body))
            logger.info(
                "  %s (naif %d): chunk %d, %d samples",
                body["name"],
                body["naif_id"],
                entries[-1]["chunk_idx"],
                len(entries[-1]["samples"]),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("  failed for %s: %s", body["name"], exc)
            raise

    payload = {
        "_comment": (
            "SPICE truth positions for frontend integration tests. "
            "Regenerate via `data/scripts/generate_spice_truth_fixtures.py`."
        ),
        "frame": "ECLIPJ2000",
        "units": "km",
        "scale": "parent_relative",
        "entries": entries,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    logger.info(
        "Wrote %d entries (%d samples) to %s",
        len(entries),
        sum(len(e["samples"]) for e in entries),
        OUTPUT_PATH,
    )

    spiceypy.kclear()


if __name__ == "__main__":
    main()
