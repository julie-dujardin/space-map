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
from space_map_data.download.providers.spice.probes.deepcat_synth import (
    MISSION_DIR_NAME as DERIVED_MISSION,
    PROVENANCE_KEY as DERIVED_PROVENANCE_KEY,
)
from space_map_data.models.object import Object, OrbitalSource
from space_map_data.probes.probe_id import (
    EVENTS_DB_MISSION,
    REGISTRY_PATH as PROBE_IDS_REGISTRY,
    load_registry,
)
from space_map_data.probes.propagation import AU_KM

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
ARCHIVE_SPACETRACK = "spacetrack"
ARCHIVE_GCAT_DEEP = "gcat-deepcat"


# `server` strings written into `_index.json` by `ProbesDownloader`. Synth
# probes get the Horizons credit since their trajectory came from there, and
# catalogue-derived probes credit the catalogue their elements came from —
# their trajectory is nobody's archive solution.
_SERVER_TO_ARCHIVE: dict[str, str] = {
    "NAIF": ARCHIVE_NAIF,
    "ESA": ARCHIVE_ESA,
    "NAIF-PDS3": ARCHIVE_NAIF_PDS3,
    "NAIF-PDS4": ARCHIVE_NAIF_PDS4,
    "JAXA-DARTS": ARCHIVE_JAXA_DARTS,
    "JPL-Horizons-synth": ARCHIVE_HORIZONS,
    "GCAT-DEEP": ARCHIVE_GCAT_DEEP,
}

# Generic SPICE kernels (planets/moons/asteroids) come from NAIF's tree.
_NON_PROBE_ARCHIVE: dict[OrbitalSource, str] = {
    OrbitalSource.sbdb: ARCHIVE_SBDB,
    OrbitalSource.sbdb_moon: ARCHIVE_SBDB,
    OrbitalSource.celestrak: ARCHIVE_CELESTRAK,
    OrbitalSource.spacetrack: ARCHIVE_SPACETRACK,
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


def load_probe_kernel_sources() -> dict[int, str | None]:
    """Build `{probe_id → archive_id | None}` by joining mission `_index.json`
    servers against the probe registry. Joint missions (Cassini in CASSINI +
    HUYGENS) credit the first source that names an archive. `None` suppresses
    the credit (entries with no archived source at all); absent entries fall
    back to NAIF.

    The first source is not always an archive: a probe with no kernels of its
    own is registered under `EVENTS-DB` and only later gains a synthesised
    trajectory, which lands second in the list and is the thing to credit.
    """
    registry = load_registry()
    if not registry:
        logger.info(
            "probe_ids registry missing or empty at %s; no probe sources to map",
            PROBE_IDS_REGISTRY,
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

    out: dict[int, str | None] = {}
    unmapped_servers: set[str] = set()
    missing_missions: set[str] = set()
    for entry in registry:
        sources = entry.get("kernel_sources") or []
        probe_id = entry.get("probe_id")
        if not sources or probe_id is None:
            continue
        credit: str | None = None
        for source in sources:
            mission = source.get("mission")
            # Not a credit decision any more — EVENTS-DB has no mission folder,
            # so the server lookup below would skip it anyway. Skipping early
            # keeps it out of the missing-mission log.
            if mission is None or mission == EVENTS_DB_MISSION:
                continue
            server = mission_to_server.get(mission)
            if server is None:
                missing_missions.add(mission)
                continue
            archive = _SERVER_TO_ARCHIVE.get(server)
            if archive is None:
                unmapped_servers.add(server)
                continue
            credit = archive
            break
        out[int(probe_id)] = credit

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


def load_probe_ephemeris_accuracy() -> dict[int, float]:
    """`{probe_id → median position error, km}` for probes whose trajectory was
    derived rather than tracked.

    Only the catalogue-derived kernels carry a figure: an archive reconstruction
    states no error and inventing one for it would be worse than silence."""
    index = MISSIONS_DIR / DERIVED_MISSION / "_index.json"
    if not index.exists():
        return {}
    try:
        files = json.loads(index.read_text()).get("files", [])
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("derived-ephemeris index at %s unreadable (%s)", index, exc)
        return {}

    by_naif: dict[int, float] = {}
    for record in files:
        error_au = (record.get(DERIVED_PROVENANCE_KEY) or {}).get("median_error_au")
        if error_au is None:
            continue
        for naif in record.get("targets", []):
            by_naif[int(naif)] = float(error_au) * AU_KM

    out: dict[int, float] = {}
    for entry in load_registry():
        for source in entry.get("kernel_sources") or []:
            if source.get("mission") != DERIVED_MISSION:
                continue
            error_km = by_naif.get(int(source["naif_id"]))
            if error_km is not None:
                out[int(entry["probe_id"])] = error_km
    return out


def ephemeris_accuracy_for(
    obj: Object, probe_accuracy: dict[int, float]
) -> float | None:
    """Median position error in km, or None where the trajectory was tracked
    rather than derived."""
    if obj.orbital_source is not OrbitalSource.spice_probe or obj.probe_id is None:
        return None
    return probe_accuracy.get(obj.probe_id)


def ephemeris_archive_for(
    obj: Object, probe_kernel_sources: dict[int, str | None]
) -> str | None:
    """Archive id crediting *obj*'s ephemeris, or None. A registered `None`
    suppresses the credit; unregistered probes fall back to NAIF."""
    src = obj.orbital_source
    if src is None:
        return None
    if src == OrbitalSource.spice_probe:
        if obj.probe_id is not None and obj.probe_id in probe_kernel_sources:
            return probe_kernel_sources[obj.probe_id]
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
        "id": ARCHIVE_SPACETRACK,
        "source": "https://www.space-track.org/",
        "organisation": "Space-Track.org",
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
    {
        "id": ARCHIVE_GCAT_DEEP,
        "source": "https://planet4589.org/space/deepcat/",
        "organisation": "McDowell, Deep Space Catalog",
    },
]
