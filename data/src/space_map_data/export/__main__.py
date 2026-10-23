"""CLI entry point for: space-map-export"""

import argparse
import logging
import logging.config
import tomllib

from space_map_data.export.atmospheres import export_atmospheres_only
from space_map_data.export.groups import export_groups_only
from space_map_data.export.nomenclature.quadrangles import export_quadrangles_only
from space_map_data.export.panoramas import export_panoramas_only
from space_map_data.export.pipeline.orchestrator import export, export_probes_only

# After the orchestrator: credits imported first hits the import cycle
# between export.ephemeris and export.objects.
from space_map_data.export.credits import export_credits_only  # isort: skip
from space_map_data.export.about_data import export_about_data_only
from space_map_data.export.extrasolar.build import export_extrasolar_only
from space_map_data.export.seo_pages import export_seo_only
from space_map_data.export.spacecraft import export_spacecraft_only
from space_map_data.export.status import export_status_only
from space_map_data.export.systems import export_systems_only
from space_map_data.utils.db import engine_scope
from space_map_data.utils.mirror import sync_all
from space_map_data.utils.paths import DATA_DIR


def cli():
    parser = argparse.ArgumentParser(
        description="Export space-map data to static files"
    )
    parser.add_argument(
        "--only",
        choices=(
            "groups",
            "quadrangles",
            "atmospheres",
            "spacecraft",
            "panoramas",
            "probes",
            "systems",
            "status",
            "credits",
            "about-data",
            "seo",
            "extrasolar",
        ),
        default=None,
        help="Run only the named tier (additive — leaves other outputs untouched)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Worker processes of the extrasolar export",
    )
    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    # It reads only the registry, so it needs no mirror and no DB.
    if args.only == "extrasolar":
        export_extrasolar_only(args.workers)
        return
    sync_all()
    if args.only == "atmospheres":
        # Pure constants + derivation — no DB.
        export_atmospheres_only()
        return
    if args.only == "spacecraft":
        export_spacecraft_only()
        return
    if args.only == "panoramas":
        export_panoramas_only()
        return
    if args.only == "status":
        export_status_only()
        return
    with engine_scope() as engine:
        if args.only == "groups":
            export_groups_only(engine)
        elif args.only == "probes":
            export_probes_only(engine)
        elif args.only == "quadrangles":
            export_quadrangles_only(engine)
        elif args.only == "systems":
            export_systems_only(engine)
        elif args.only == "credits":
            export_credits_only(engine)
        elif args.only == "about-data":
            export_about_data_only(engine)
        elif args.only == "seo":
            export_seo_only(engine)
        else:
            export(engine)


if __name__ == "__main__":
    cli()
