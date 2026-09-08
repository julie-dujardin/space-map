"""Count active catalog products and validate their local preview assets."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

from .pipeline import write_json


def audit(directory):
    groups = defaultdict(list)
    errors = []
    for path in sorted(directory.glob("*/catalog.json")):
        seen = set()
        for entry in json.loads(path.read_text())["panoramas"]:
            identity = entry["id"]
            if identity in seen:
                errors.append(f"Duplicate in {path.parent.name}: {identity}")
            seen.add(identity)
            metadata_path = directory / entry["metadata"]
            try:
                metadata = json.loads(metadata_path.read_text())
                for key in ("preview", "image"):
                    if (
                        metadata.get(key)
                        and not (metadata_path.parent / metadata[key]).is_file()
                    ):
                        errors.append(f"Missing {key}: {identity}")
                groups[
                    (path.parent.name, metadata["mission"], metadata["instrument"])
                ].append(metadata)
            except (OSError, ValueError, KeyError) as error:
                errors.append(f"{identity}: {error}")
    summaries = []
    for (collection, mission, instrument), rows in groups.items():
        largest = max(rows, key=lambda m: m["source_width"] * m["source_height"])
        summaries.append(
            {
                "collection": collection,
                "mission": mission,
                "instrument": instrument,
                "products": len(rows),
                "spherical_renditions": sum(bool(m.get("image")) for m in rows),
                "estimated_geometry": sum(
                    m.get("grid_geometry_status") == "estimated"
                    or m.get("geometry_status") == "estimated"
                    for m in rows
                ),
                "located": sum(bool(m.get("position")) for m in rows),
                "known_horizontal_coverage": sum(
                    m.get("coverage", {}).get("horizontal_degrees") is not None
                    for m in rows
                ),
                "known_sphere_coverage": sum(
                    m.get("coverage", {}).get("sphere_percent") is not None
                    for m in rows
                ),
                "largest_source": {
                    "id": largest["id"],
                    "width": largest["source_width"],
                    "height": largest["source_height"],
                },
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "active catalogs; products are not unique locations",
        "collections": summaries,
        "errors": errors,
    }


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.directory)
    write_json(args.directory / "audit.json", report)
    print(json.dumps(report, indent=2))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
