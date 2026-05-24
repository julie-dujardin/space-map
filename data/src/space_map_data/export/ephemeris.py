"""Per-object ephemeris-archive attribution.

Probes are the only case where the archive varies per body — mission SPKs
come from NAIF, ESA, NAIF PDS3/4, or JAXA DARTS. Everything else maps
deterministically from `OrbitalSource`.
"""

import json
import logging
from pathlib import Path

from space_map_data.download.providers.spice.probes import (
    LANDED_MISSIONS_DIR,
    MISSIONS_DIR,
)
from space_map_data.models.object import Object, OrbitalSource
from space_map_data.probes.probe_id import CACHE_PATH as PROBE_IDS_CACHE

logger = logging.getLogger(__name__)


# Archive ids shipped in the global JSON; the frontend keys localized labels off them.
ARCHIVE_NAIF = "naif"
ARCHIVE_ESA = "esa"
ARCHIVE_NAIF_PDS3 = "naif-pds3"
ARCHIVE_NAIF_PDS4 = "naif-pds4"
ARCHIVE_JAXA_DARTS = "jaxa-darts"
ARCHIVE_HORIZONS = "horizons"
ARCHIVE_SBDB = "sbdb"
ARCHIVE_CELESTRAK = "celestrak"


# `server` strings written into `_index.json` by `ProbesDownloader`. Synth
# probes get the Horizons credit since their trajectory came from there.
_SERVER_TO_ARCHIVE: dict[str, str] = {
    "NAIF": ARCHIVE_NAIF,
    "ESA": ARCHIVE_ESA,
    "NAIF-PDS3": ARCHIVE_NAIF_PDS3,
    "NAIF-PDS4": ARCHIVE_NAIF_PDS4,
    "JAXA-DARTS": ARCHIVE_JAXA_DARTS,
    "JPL-Horizons-synth": ARCHIVE_HORIZONS,
}

# Generic SPICE kernels (planets/moons/asteroids) come from NAIF's tree.
_NON_PROBE_ARCHIVE: dict[OrbitalSource, str] = {
    OrbitalSource.sbdb: ARCHIVE_SBDB,
    OrbitalSource.sbdb_moon: ARCHIVE_SBDB,
    OrbitalSource.celestrak: ARCHIVE_CELESTRAK,
    OrbitalSource.spice: ARCHIVE_NAIF,
}


def _read_mission_server(mission_dir: Path) -> str | None:
    """Return the `server` field from `<mission_dir>/_index.json`, or None."""
    idx = mission_dir / "_index.json"
    if not idx.exists():
        return None
    try:
        return json.loads(idx.read_text()).get("server")
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Couldn't read %s: %s", idx, exc)
        return None


def load_probe_kernel_sources() -> dict[int, str]:
    """Build `{probe_id → archive_id}` by joining mission `_index.json` servers
    against the probe_ids cache."""
    if not PROBE_IDS_CACHE.exists():
        logger.info(
            "probe_ids cache missing at %s; no probe sources to map", PROBE_IDS_CACHE
        )
        return {}

    mission_to_server: dict[str, str] = {}
    for root in (MISSIONS_DIR, LANDED_MISSIONS_DIR):
        if not root.exists():
            continue
        for mdir in sorted(root.iterdir()):
            if not mdir.is_dir() or mdir.name in mission_to_server:
                continue
            server = _read_mission_server(mdir)
            if server is not None:
                mission_to_server[mdir.name] = server

    try:
        cache = json.loads(PROBE_IDS_CACHE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("probe_ids cache at %s unreadable (%s)", PROBE_IDS_CACHE, exc)
        return {}

    out: dict[int, str] = {}
    unmapped_servers: set[str] = set()
    missing_missions: set[str] = set()
    for rec in cache.values():
        mission = rec.get("mission")
        probe_id = rec.get("probe_id")
        if mission is None or probe_id is None:
            continue
        server = mission_to_server.get(mission)
        if server is None:
            missing_missions.add(mission)
            continue
        archive = _SERVER_TO_ARCHIVE.get(server)
        if archive is None:
            unmapped_servers.add(server)
            continue
        out[int(probe_id)] = archive

    if missing_missions:
        logger.info(
            "No _index.json for %d probe missions (%s); their probes will fall back "
            "to the generic SPICE credit",
            len(missing_missions),
            ", ".join(sorted(missing_missions)),
        )
    if unmapped_servers:
        logger.warning(
            "Unknown probe-archive server(s) %s — extend _SERVER_TO_ARCHIVE",
            sorted(unmapped_servers),
        )
    return out


def ephemeris_archive_for(
    obj: Object, probe_kernel_sources: dict[int, str]
) -> str | None:
    """Archive id crediting *obj*'s ephemeris, or None. Probes without a
    mapped mission fall back to NAIF (every probe SPK we fetch passes through
    a NAIF-hosted archive at minimum)."""
    src = obj.orbital_source
    if src is None:
        return None
    if src == OrbitalSource.spice_probe:
        if obj.probe_id is not None:
            archive = probe_kernel_sources.get(obj.probe_id)
            if archive is not None:
                return archive
        return ARCHIVE_NAIF
    return _NON_PROBE_ARCHIVE.get(src)


# Shipped in `credits.json` so the frontend's orbital-credits section is
# data-driven. Horizons / SBDB / CelesTrak aren't SPICE archives but ride
# along since they're orbital-data sources too.
EPHEMERIS_ARCHIVES: list[dict[str, str]] = [
    {
        "id": ARCHIVE_HORIZONS,
        "source": "https://ssd.jpl.nasa.gov/horizons/",
        "organisation": "NASA JPL Horizons",
    },
    {
        "id": ARCHIVE_SBDB,
        "source": "https://ssd.jpl.nasa.gov/tools/sbdb_query.html",
        "organisation": "NASA JPL Small-Body Database",
    },
    {
        "id": ARCHIVE_CELESTRAK,
        "source": "https://celestrak.org/",
        "organisation": "CelesTrak",
    },
    {
        "id": ARCHIVE_NAIF,
        "source": "https://naif.jpl.nasa.gov/naif/",
        "organisation": "NASA NAIF (SPICE)",
    },
    {
        "id": ARCHIVE_ESA,
        "source": "https://spiftp.esac.esa.int/",
        "organisation": "ESA SPICE Service",
    },
    {
        "id": ARCHIVE_NAIF_PDS3,
        "source": "https://naif.jpl.nasa.gov/naif/data_archived.html",
        "organisation": "NASA PDS Navigation Node (PDS3)",
    },
    {
        "id": ARCHIVE_NAIF_PDS4,
        "source": "https://pds.nasa.gov/",
        "organisation": "NASA PDS Navigation Node (PDS4)",
    },
    {
        "id": ARCHIVE_JAXA_DARTS,
        "source": "https://darts.isas.jaxa.jp/",
        "organisation": "JAXA DARTS",
    },
]
