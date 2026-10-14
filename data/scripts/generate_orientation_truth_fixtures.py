"""Generate SPICE-truth body orientations for the frontend orientation test.

Reads the IAU rotation constants with the production `extract_orientation` and
`extract_nutation`, and pairs them with `pxform("J2000", "IAU_<body>")` at
several epochs. The frontend test
([frontend/src/lib/math/orientation.truth.test.ts]) feeds the constants
through `bodyQuaternion` and compares the result with the SPICE matrices.

Mars sets a quadratic phase polynomial, so Mars, Phobos and Deimos are in
the set. The other bodies use linear phases and guard that path.

The fixture is committed so the test runs without kernels. Regenerate after
a PCK update.
"""

import json
import logging
import sys
from pathlib import Path

import spiceypy

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.download.providers.spice.bodies.pck_extract import (  # noqa: E402
    extract_nutation,
    extract_orientation,
)
from space_map_data.utils.paths import SOURCES_POSITION_DIR  # noqa: E402
from space_map_data.utils.time import jd_to_et  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

PCK = SOURCES_POSITION_DIR / "spice-kernels" / "pck" / "pck00011.tpc"
OUTPUT_PATH = REPO_ROOT / "frontend/src/lib/math/orientation.truth.fixtures.json"

BODIES = {
    499: "Mars",
    401: "Phobos",
    402: "Deimos",
    301: "Moon",
    599: "Jupiter",
    501: "Io",
    899: "Neptune",
    801: "Triton",
}

# JD TDB: 1965-01-01, J2000, 2026-10-14, 2050-01-01. The ends are far from
# J2000, where the quadratic phase term is largest.
EPOCHS_JD = [2438761.5, 2451545.0, 2461327.5, 2469807.5]


def main() -> None:
    spiceypy.furnsh(str(PCK))
    orientation = {row["naif_id"]: row for row in extract_orientation()}
    coefficients, angles, phase_degrees = extract_nutation()

    bodies = []
    owners: set[int] = set()
    for naif_id, name in BODIES.items():
        row = orientation[naif_id]
        owner = naif_id // 100 if naif_id >= 100 else naif_id
        nut_prec = coefficients.get(naif_id)
        if nut_prec is not None:
            owners.add(owner)
        frame = spiceypy.cidfrm(naif_id)[1]
        samples = []
        for jd in EPOCHS_JD:
            matrix = spiceypy.pxform("J2000", frame, jd_to_et(jd))
            samples.append(
                {"jd_tdb": jd, "matrix": [list(map(float, r)) for r in matrix]}
            )
        bodies.append(
            {
                "naif_id": naif_id,
                "name": name,
                "frame": frame,
                "orientation": {k: float(v) for k, v in row.items() if k != "naif_id"},
                "nut_prec": nut_prec,
                "samples": samples,
            }
        )
        logger.info("  %s (%s): %d samples", name, frame, len(samples))

    payload = {
        "_comment": (
            "SPICE pxform J2000 -> IAU_<body> for the orientation test. "
            "Regenerate via `data/scripts/generate_orientation_truth_fixtures.py`."
        ),
        "nut_prec_angles": {str(o): angles[o] for o in sorted(owners)},
        "nut_prec_phase_degree": {
            str(o): phase_degrees[o] for o in sorted(owners) if o in phase_degrees
        },
        "bodies": bodies,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    logger.info("Wrote %d bodies to %s", len(bodies), OUTPUT_PATH)
    spiceypy.kclear()


if __name__ == "__main__":
    main()
