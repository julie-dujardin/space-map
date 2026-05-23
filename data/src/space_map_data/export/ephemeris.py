"""Per-object ephemeris-source attribution.

Names the upstream archive that provided each body's orbital data so the
frontend can credit the right organisation (NAIF, ESA, JAXA DARTS, …). For
most sources the mapping is constant (`OrbitalSource.horizons` → Horizons,
etc.); probes are the only case where it varies per row because mission SPK
kernels come from different mirrors (NAIF operational, ESA SPICE Service,
NAIF PDS3/PDS4 archives, JAXA DARTS).
"""

import json
import logging
from pathlib import Path

from space_map_data.download.providers.objects.probes import (
    LANDED_MISSIONS_DIR,
    MISSIONS_DIR,
)
from space_map_data.models.object import Object, OrbitalSource
from space_map_data.probes.probe_id import CACHE_PATH as PROBE_IDS_CACHE

logger = logging.getLogger(__name__)


# Stable archive identifiers shipped in the global JSON. Short lowercase
# strings so the frontend can map them to localized labels without parsing.
ARCHIVE_NAIF = "naif"
ARCHIVE_ESA = "esa"
ARCHIVE_NAIF_PDS3 = "naif-pds3"
ARCHIVE_NAIF_PDS4 = "naif-pds4"
ARCHIVE_JAXA_DARTS = "jaxa-darts"
ARCHIVE_HORIZONS = "horizons"
ARCHIVE_SBDB = "sbdb"
ARCHIVE_CELESTRAK = "celestrak"


# Maps the `server` field written by `ProbesDownloader` into _index.json to
# our archive id. `JPL-Horizons-synth` is for probes whose trajectory was
# synthesized from Horizons API queries rather than fetched as a real SPK —
# so its archive credit goes to Horizons, not to a SPICE mirror.
_SERVER_TO_ARCHIVE: dict[str, str] = {
    "NAIF": ARCHIVE_NAIF,
    "ESA": ARCHIVE_ESA,
    "NAIF-PDS3": ARCHIVE_NAIF_PDS3,
    "NAIF-PDS4": ARCHIVE_NAIF_PDS4,
    "JAXA-DARTS": ARCHIVE_JAXA_DARTS,
    "JPL-Horizons-synth": ARCHIVE_HORIZONS,
}

# Static fallbacks for non-probe orbital sources. SPICE generic kernels
# (planets/moons/asteroids) come from NAIF's `generic_kernels/` tree.
_NON_PROBE_ARCHIVE: dict[OrbitalSource, str] = {
    OrbitalSource.horizons: ARCHIVE_HORIZONS,
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
    """Build `{probe_id → archive_id}` from on-disk indices and the probe cache.

    Walks `missions/*/_index.json` and `landed_missions/*/_index.json` to
    discover which `server` published each mission, then joins against the
    `probe_ids.json` cache (which records the mission → probe_id mapping)
    to produce a probe-keyed map. Missions present in both trees agree on
    `server`; one read suffices.
    """
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
    """Return the archive id crediting *obj*'s orbital ephemeris, or None.

    For probes, dispatches to the kernel-source map (one entry per probe id).
    For everything else, falls back to the constant per-`OrbitalSource` map.
    Probes whose mission isn't in the map fall back to NAIF — every probe SPK
    we currently fetch goes through a NAIF-hosted archive at minimum.
    """
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


# Static archive catalog shipped in `credits.json` so the frontend can render
# the orbital-credits section data-driven. Each entry is the URL the
# corresponding archive id (above) resolves to. CelesTrak / Horizons / SBDB
# aren't SPICE archives but live alongside since they're orbital-data sources.
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
        "source": "https://data.darts.isas.jaxa.jp/",
        "organisation": "JAXA DARTS",
    },
]
