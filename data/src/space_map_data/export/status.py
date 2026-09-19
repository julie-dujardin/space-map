"""Freshness report for `v1/status.json`, backing the `/status` page.

One row per download provider, read from the `metadata.json` each writes into
its own output tree. Labels here are proper nouns and ship as-is; the frontend
keys localized category names off `category`.
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import orjson

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.common import SOURCES
from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)


# Render order on the page; ids carry localized labels in the frontend.
CATEGORIES: tuple[str, ...] = (
    "orbits",
    "ephemerides",
    "reference",
    "imagery",
    "models",
    "science",
)


@dataclass(frozen=True)
class SourceInfo:
    """Display metadata for one provider — what the row says before dates."""

    label: str
    homepage: str
    category: str
    # Built here from data already on disk rather than fetched, so an old date
    # means the pipeline step has not re-run, not that an upstream went quiet.
    derived: bool = False


SOURCE_CATALOG: dict[str, SourceInfo] = {
    PROVIDERS.CELESTRAK: SourceInfo("CelesTrak", "https://celestrak.org/", "orbits"),
    PROVIDERS.SPACETRACK: SourceInfo(
        "Space-Track.org", "https://www.space-track.org/", "orbits"
    ),
    PROVIDERS.GCAT: SourceInfo(
        "GCAT — General Catalog of Artificial Space Objects",
        "https://planet4589.org/space/gcat/",
        "orbits",
    ),
    PROVIDERS.GCAT_DEEP: SourceInfo(
        "DeepCat — Deep Space Catalog",
        "https://planet4589.org/space/deepcat/",
        "orbits",
    ),
    PROVIDERS.SBDB: SourceInfo(
        "JPL Small-Body Database",
        "https://ssd.jpl.nasa.gov/tools/sbdb_query.html",
        "orbits",
    ),
    PROVIDERS.SBDB_MOONS: SourceInfo(
        "JPL SBDB — planetary satellites",
        "https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html",
        "orbits",
    ),
    PROVIDERS.ASTERSAT: SourceInfo(
        "Natural Satellites Data Base (SAI / IMCCE)",
        "https://www.sai.msu.ru/neb/nss/",
        "orbits",
    ),
    PROVIDERS.JOHNSTON: SourceInfo(
        "Johnston's Archive — asteroids with satellites",
        "https://www.johnstonsarchive.net/astro/asteroidmoons.html",
        "orbits",
    ),
    PROVIDERS.SSODNET: SourceInfo(
        "SsODNet (IMCCE)", "https://ssp.imcce.fr/webservices/ssodnet/", "orbits"
    ),
    PROVIDERS.JPL_SATELLITE_DISCOVERY: SourceInfo(
        "JPL planetary satellite discovery circumstances",
        "https://ssd.jpl.nasa.gov/sats/discovery.html",
        "orbits",
    ),
    PROVIDERS.SPICE: SourceInfo(
        "NAIF generic kernels",
        "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/",
        "ephemerides",
    ),
    PROVIDERS.SPICE_PROBES: SourceInfo(
        "Mission SPK archives (NAIF, ESA, PDS, JAXA)",
        "https://naif.jpl.nasa.gov/naif/data_archived.html",
        "ephemerides",
    ),
    PROVIDERS.SPICE_HORIZONS_SYNTH: SourceInfo(
        "JPL Horizons", "https://ssd.jpl.nasa.gov/horizons/", "ephemerides"
    ),
    PROVIDERS.SPICE_PROBES_PROPAGATION: SourceInfo(
        "Propagated spacecraft trajectories",
        "https://naif.jpl.nasa.gov/naif/data_archived.html",
        "ephemerides",
        derived=True,
    ),
    PROVIDERS.SPICE_SMALL_BODY_CHEBYSHEV: SourceInfo(
        "Small-body Chebyshev fits",
        "https://ssd.jpl.nasa.gov/tools/sbdb_query.html",
        "ephemerides",
        derived=True,
    ),
    PROVIDERS.SPICE_DEEPCAT: SourceInfo(
        "DeepCat trajectories",
        "https://planet4589.org/space/deepcat/",
        "ephemerides",
        derived=True,
    ),
    PROVIDERS.SPICE_SPACETRACK_TLE: SourceInfo(
        "Escape trajectories from Space-Track elements",
        "https://www.space-track.org/",
        "ephemerides",
        derived=True,
    ),
    PROVIDERS.WIKIDATA: SourceInfo(
        "Wikidata", "https://www.wikidata.org/", "reference"
    ),
    PROVIDERS.WIKIPEDIA: SourceInfo(
        "Wikipedia", "https://www.wikipedia.org/", "reference"
    ),
    PROVIDERS.COMMONS: SourceInfo(
        "Wikimedia Commons", "https://commons.wikimedia.org/", "reference"
    ),
    PROVIDERS.MANUAL: SourceInfo(
        "Wikidata — hand-curated objects", "https://www.wikidata.org/", "reference"
    ),
    PROVIDERS.IAU_NOMENCLATURE: SourceInfo(
        "IAU Gazetteer of Planetary Nomenclature (USGS)",
        "https://planetarynames.wr.usgs.gov/",
        "reference",
    ),
    PROVIDERS.TEXTURE_SOURCES: SourceInfo(
        "Texture provenance pages (NASA, USGS, ESA)",
        "https://photojournal.jpl.nasa.gov/",
        "imagery",
    ),
    PROVIDERS.EARTH_CLOUDS: SourceInfo(
        "Global cloud cover (EUMETSAT, via Matt Eason)",
        "https://clouds.matteason.co.uk/",
        "imagery",
    ),
    PROVIDERS.EARTH_WATER: SourceInfo(
        "OpenStreetMap water polygons",
        "https://osmdata.openstreetmap.de/data/water-polygons.html",
        "imagery",
    ),
    PROVIDERS.BJJ_RINGS: SourceInfo(
        "Björn Jónsson — Saturn ring profiles",
        "https://bjj.mmedia.is/data/s_rings/",
        "imagery",
    ),
    PROVIDERS.NASA_3D: SourceInfo(
        "NASA 3D Resources",
        "https://github.com/nasa/NASA-3D-Resources",
        "models",
    ),
    PROVIDERS.ESA_3D: SourceInfo(
        "ESA Science Satellite Fleet", "https://scifleet.esa.int/", "models"
    ),
    PROVIDERS.BODY_SHAPES: SourceInfo(
        "Shape models (PDS SBN, DARTS, ESAC)",
        "https://sbn.psi.edu/pds/shape-models/",
        "models",
    ),
    PROVIDERS.DAMIT: SourceInfo(
        "DAMIT — asteroid lightcurve inversion models",
        "https://astro.troja.mff.cuni.cz/projects/damit/",
        "models",
    ),
    PROVIDERS.PSG_ATMOSPHERE: SourceInfo(
        "NASA GSFC Planetary Spectrum Generator",
        "https://psg.gsfc.nasa.gov/",
        "science",
    ),
    PROVIDERS.GVP: SourceInfo(
        "Smithsonian Global Volcanism Program",
        "https://volcano.si.edu/",
        "science",
    ),
    PROVIDERS.LAUNCH_PERFORMANCE: SourceInfo(
        "Launch-vehicle escape performance (Zubrin et al.)",
        "https://doi.org/10.48550/arXiv.2310.05994",
        "science",
    ),
}


def _read_metadata(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        meta = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Couldn't read %s: %s", path, exc)
        return None
    return meta if isinstance(meta, dict) else None


def source_entry(
    name: str,
    info: SourceInfo,
    meta: dict | None,
    max_age: timedelta | None,
) -> dict:
    """One `sources` row.

    A provider with no metadata yet keeps its row minus the dates rather than
    being dropped — the page has to be able to say a source has never run.
    """
    entry: dict = {
        "id": name,
        "label": info.label,
        "homepage": info.homepage,
        "category": info.category,
    }
    if info.derived:
        entry["derived"] = True
    if max_age is not None:
        days = max_age.total_seconds() / 86400
        entry["max_age_days"] = int(days) if days.is_integer() else round(days, 1)
    if meta is None:
        return entry

    downloaded_at = meta.get("downloaded_at")
    if isinstance(downloaded_at, str):
        entry["downloaded_at"] = downloaded_at
    # Only SBDB distinguishes the two: `downloaded_at` moves when the mirror
    # content changed, `checked_at` on every completed sync.
    checked_at = meta.get("checked_at")
    if isinstance(checked_at, str) and checked_at != downloaded_at:
        entry["checked_at"] = checked_at
    record_count = meta.get("record_count")
    if isinstance(record_count, int):
        entry["record_count"] = record_count
    return entry


def ordered_catalog() -> list[tuple[str, SourceInfo]]:
    """The catalog in page order: by category, then as listed within one."""
    return sorted(
        SOURCE_CATALOG.items(), key=lambda kv: CATEGORIES.index(kv[1].category)
    )


def build_status() -> dict:
    """Collect every provider's last-download record."""
    sources: list[dict] = []
    with httpx.Client() as client:
        for name, info in ordered_catalog():
            downloader = SOURCES[name](client)
            meta = _read_metadata(downloader.metadata_file)
            if meta is None:
                logger.info("%s: no download recorded yet", name)
            sources.append(source_entry(name, info, meta, downloader.max_age))

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "categories": list(CATEGORIES),
        "sources": sources,
    }


def write_status(out_dir: Path) -> None:
    """Emit `v1/status.json` — one freshness row per download provider."""
    t0 = time.monotonic()
    payload = build_status()
    (out_dir / "status.json").write_bytes(
        orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    )
    dated = sum(1 for s in payload["sources"] if "downloaded_at" in s)
    logger.info(
        "Wrote status.json (%d sources, %d dated) in %.1fs",
        len(payload["sources"]),
        dated,
        time.monotonic() - t0,
    )


def export_status_only() -> None:
    """`space-map-export --only status` — additive, no DB needed."""
    out_dir = EXPORT_DIR / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_status(out_dir)
