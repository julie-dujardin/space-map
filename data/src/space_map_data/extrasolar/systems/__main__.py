"""Dry run of the star-system builder against the committed registry.

    python -m space_map_data.extrasolar.systems --out <dir>

It reads the sources, holds the registry's shared lock while it builds, and
writes the report section and the output tables to `--out`. It writes
nothing into the registry or the exports.
"""

import argparse
import logging.config
import resource
import time
import tomllib
from pathlib import Path

import pyarrow.parquet as pq

from space_map_data.extrasolar.exoplanets import catalogues, hosts
from space_map_data.extrasolar.exoplanets import simbad as exoplanet_simbad
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources.simbad import SimbadList
from space_map_data.extrasolar.systems.build import build
from space_map_data.extrasolar.systems.msc import read_msc, refuted_pairs
from space_map_data.extrasolar.systems.pairs import read_el_badry
from space_map_data.extrasolar.systems.planets import (
    read_oec_trees,
    read_planet_systems,
)
from space_map_data.extrasolar.systems.prepare import Inputs
from space_map_data.extrasolar.systems.registry import (
    RegistryResolver,
    registry_orbits,
    registry_planets,
)
from space_map_data.extrasolar.systems.report import report_lines, target_keys
from space_map_data.extrasolar.systems.simbad import SimbadIndex, read_simbad
from space_map_data.extrasolar.systems.wds import WdsCatalogue
from space_map_data.utils.paths import DATA_DIR, REGISTRY_ROOT

logger = logging.getLogger(__name__)


def _peak_mb() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024


def cli() -> None:
    parser = argparse.ArgumentParser(description="Dry run of the star systems")
    parser.add_argument("--root", type=Path, default=REGISTRY_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--examples", type=int, default=20)
    args = parser.parse_args()
    with open(DATA_DIR / "logging.toml", "rb") as f:
        logging.config.dictConfig(tomllib.load(f))

    started = time.monotonic()
    stars = SimbadList.read()
    index = SimbadIndex.build(stars)
    cats = [catalogues.read_archive(), catalogues.read_eu(), catalogues.read_oec()]
    hub = exoplanet_simbad.read_simbad()
    identities = hosts.build_stars(cats, hub, hosts.read_neighbours())
    planet_systems = hosts.group_systems(identities)
    inputs = Inputs(
        msc=read_msc(),
        simbad=read_simbad(stars),
        simbad_index=index,
        planet_systems=read_planet_systems(
            identities, planet_systems, read_oec_trees()
        ),
        wds=WdsCatalogue.read(),
        refuted=refuted_pairs(),
        el_badry=read_el_badry(),
    )
    read = time.monotonic()
    logger.info(
        "systems: sources read in %.0f s, peak %d MB", read - started, _peak_mb()
    )

    registry = Registry(args.root)
    with registry.reader():
        inputs.planets = registry_planets(registry, hub)
        inputs.orbits = registry_orbits(registry)
        resolver = RegistryResolver(registry)
        systems = build(inputs, resolver)
        targets = target_keys(index, resolver)
    built = time.monotonic()
    logger.info("systems: built in %.0f s, peak %d MB", built - read, _peak_mb())

    args.out.mkdir(parents=True, exist_ok=True)
    for name in (
        "nodes",
        "members",
        "points",
        "absorbed",
        "distances",
        "hosts",
        "overlaps",
        "names",
        "events",
    ):
        pq.write_table(getattr(systems, name), args.out / f"{name}.parquet")
    lines = report_lines(systems, targets, examples=args.examples)
    lines += [
        "",
        f"timings: sources {read - started:.0f} s, build {built - read:.0f} s",
        f"peak memory: {_peak_mb():,} MB",
        "resolver: "
        + ", ".join(f"{k} {v:,}" for k, v in sorted(resolver.counts.items())),
    ]
    (args.out / "report.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    cli()
