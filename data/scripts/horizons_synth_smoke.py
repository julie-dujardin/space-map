"""Smoke-test horizons_synth.fetch_one + build_one on 3 spacecraft.

  - Voyager 2 (-32):   deep cruise, decades-long span, no refinement expected
  - Mangalyaan (-3):   Mars orbiter, should refine around Mars proximity
  - CAPSTONE (-1176):  cislunar NRHO, should refine around Earth+Moon

Run with: `uv run python scripts/horizons_synth_smoke.py`
"""

import logging

import httpx

from space_map_data.download.providers.objects.horizons_synth import (
    SYNTH_ROOT,
    build_one,
    fetch_one,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

TARGETS = [
    (-32, "Voyager 2"),
    (-3, "Mangalyaan / Mars Orbiter Mission"),
    (-1176, "CAPSTONE"),
]


def main() -> None:
    with httpx.Client(
        headers={"User-Agent": "space-map/horizons-synth-smoke"},
        timeout=180.0,
    ) as client:
        for naif_id, label in TARGETS:
            print(f"\n=== {label} ({naif_id}) ===")
            meta = fetch_one(client, naif_id)
            print(
                f"  cached: {meta['coarse']['count']} coarse, "
                f"{len(meta['refined'])} refinement windows"
            )
            spk = build_one(naif_id)
            print(f"  built: {spk} ({spk.stat().st_size / 1024:.1f} KiB)")

    print(f"\nAll artefacts under {SYNTH_ROOT}")


if __name__ == "__main__":
    main()
