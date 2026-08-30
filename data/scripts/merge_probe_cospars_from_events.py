"""Fold the COSPAR ids curated in the v2 events files into the probe registry.

Identity belongs to ``probe_ids.json``; the events files carried a second copy
of it, and the two had drifted. Where the registry holds the parent craft's id
for a lander or a balloon, the events file's more specific id wins — it is the
one the 2026-07 audit checked against NSSDCA.

    uv run python scripts/merge_probe_cospars_from_events.py [--apply]
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from space_map_data.probes.probe_id import load_registry, save_registry  # noqa: E402
from space_map_data.utils.paths import ARCHIVE_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("cospar")

V2_DIR = ARCHIVE_DIR / "probe-events-v2-2026-08-25"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the registry")
    args = parser.parse_args()

    from_events: dict[int, str] = {}
    for path in sorted(V2_DIR.glob("*.json")):
        for probe in json.loads(path.read_text()).get("probes", []):
            if probe.get("probe_id") is not None and probe.get("cospar_id"):
                from_events[int(probe["probe_id"])] = probe["cospar_id"]

    registry = load_registry()
    filled = replaced = 0
    for entry in registry:
        curated = from_events.get(int(entry["probe_id"]))
        if curated is None or curated == entry.get("cospar_id"):
            continue
        if entry.get("cospar_id") is None:
            filled += 1
        else:
            replaced += 1
            logger.info(
                "  %-34s %s -> %s", entry.get("name"), entry["cospar_id"], curated
            )
        entry["cospar_id"] = curated
    logger.info(
        "%d filled, %d replaced%s", filled, replaced, "" if args.apply else " (dry run)"
    )
    if args.apply:
        save_registry(registry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
