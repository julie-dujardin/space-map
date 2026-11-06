"""CLI entry point for: space-map-export"""

import argparse
import logging
import logging.config
import tomllib
from pathlib import Path

from space_map_data.export.atmospheres import export_atmospheres_only
from space_map_data.export.groups import export_groups_only
from space_map_data.export.nomenclature.quadrangles import export_quadrangles_only
from space_map_data.export.objects.stars import export_star_objects_only
from space_map_data.export.panoramas import export_panoramas_only
from space_map_data.export.pipeline.orchestrator import export, export_probes_only
from space_map_data.export.position.probes.attitude.orchestrator import (
    export_attitude_only,
)

# After the orchestrator: credits imported first hits the import cycle
# between export.ephemeris and export.objects.
from space_map_data.export.credits import export_credits_only  # isort: skip
from space_map_data.dust import DEFAULT_VARIANT, VARIANTS
from space_map_data.export.about_data import export_about_data_only
from space_map_data.export.extrasolar.build import export_extrasolar_only
from space_map_data.export.seo_pages import export_seo_only
from space_map_data.export.spacecraft import export_spacecraft_only
from space_map_data.export.status import export_status_only
from space_map_data.export.swap import ExportRefused
from space_map_data.export.systems import export_systems_only
from space_map_data.utils.db import engine_scope
from space_map_data.utils.heap import limit_arenas
from space_map_data.utils.mirror import sync_all
from space_map_data.utils.paths import DATA_DIR, EXTRASOLAR_DIR, REGISTRY_ROOT


def cli():
    # Before the mirror sync and the zone exports start their threads.
    limit_arenas(2)
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
            "attitude",
            "systems",
            "status",
            "credits",
            "about-data",
            "seo",
            "extrasolar",
            "star-objects",
            "dust",
            "glow",
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
    parser.add_argument(
        "--registry-root",
        type=Path,
        default=REGISTRY_ROOT,
        help=f"extrasolar: the registry to read (default: {REGISTRY_ROOT}); another"
        " root reads its matched sky cultures from <root>/skycultures",
    )
    parser.add_argument(
        "--extrasolar-root",
        type=Path,
        default=EXTRASOLAR_DIR,
        help="extrasolar, dust and glow: the root of v1/x/, v1/dust/ and v1/glow/"
        f" (default: {EXTRASOLAR_DIR}, only for the default registry)",
    )
    parser.add_argument(
        "--dust-variant",
        choices=VARIANTS,
        default=DEFAULT_VARIANT,
        help="dust: the regional variant of the nest",
    )
    parser.add_argument(
        "--glow-build",
        type=Path,
        default=None,
        help="glow: the grid's build (default: glow-build)",
    )
    parser.add_argument(
        "--model-build",
        type=Path,
        default=None,
        help="glow: the model build that goes with the grid (default: model-build)",
    )
    parser.add_argument(
        "--emission-build",
        type=Path,
        default=None,
        help="glow: the emission build that goes with the model (default: emission-build)",
    )
    args = parser.parse_args()

    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    # A refusal is an expected stop, so it shows only its message.
    try:
        # It reads the registry and the star items of the Wikidata cache in place,
        # and no DB.
        if args.only == "extrasolar":
            export_extrasolar_only(
                args.workers, args.registry_root, args.extrasolar_root
            )
            return
        # It reads the nest build, and no DB.
        if args.only == "dust":
            # Late, because the nest build pulls in h5py, scipy and astropy.
            from space_map_data.export.dust import export_dust_only

            export_dust_only(args.dust_variant, args.extrasolar_root)
            return
        # It reads the builds and the tokens of the tree and the nest, and no DB.
        if args.only == "glow":
            # Late, because the nest build pulls in h5py, scipy and astropy.
            from space_map_data.emission.build import BUILD_DIR as EMISSION_BUILD_DIR
            from space_map_data.export.glow import export_glow_only
            from space_map_data.galaxy.build import BUILD_DIR as MODEL_BUILD_DIR
            from space_map_data.glow.build import BUILD_DIR as GLOW_BUILD_DIR

            export_glow_only(
                args.extrasolar_root,
                args.glow_build or GLOW_BUILD_DIR,
                args.model_build or MODEL_BUILD_DIR,
                args.emission_build or EMISSION_BUILD_DIR,
            )
            return
    except ExportRefused as error:
        raise SystemExit(f"export refused: {error}") from None
    sync_all()
    if args.only == "star-objects":
        export_star_objects_only()
        return
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
    if args.only == "attitude":
        export_attitude_only()
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
