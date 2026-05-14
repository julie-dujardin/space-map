"""Ingest spacecraft Object rows from `missions/*/_index.json`.

Walks every per-mission index file written by `ProbesDownloader`, classifies
trajectory coverage to skip landed/static probes, computes the inception MJD
of each spacecraft NAIF ID's longest contiguous SPK interval, and persists
one Object row per `(mission, naif_id)` with `id_type=PROBE`.

The primary key is `probe-<probe_id>` so the row survives NAIF-ID recycling
(e.g. -76 was Mariner 10 and is MSL today — two separate rows with distinct
probe_ids). `naif_id` is still stored on the row but as an attribute, not
the primary key.

Inception MJDs are cached at `spice/probe_ids.json` (see
`probes/probe_id.py`) so probe_ids stay stable across DB rebuilds.
"""

import json
import logging
from pathlib import Path

from sqlalchemy import delete, insert
from tqdm import tqdm

from space_map_data.constants.providers import ID_TYPES, PROVIDERS, make_object_id
from space_map_data.models.object import Object, ObjectType, OrbitalSource
from space_map_data.probes.probe_id import assign_many, et_to_mjd
from space_map_data.probes.trace import _coverage, is_landed_probe
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

# Kernels we never want to feed `_coverage()`: they park a destroyed/landed
# probe at fixed coords for decades and would push the longest-coverage
# interval past mission end.
_STATIONARY_PATTERNS = ("_imp_", "_crashsite_")


def _mission_kernels(mission_dir: Path) -> list[Path]:
    return [
        k
        for k in (sorted(mission_dir.glob("*.bsp")) + sorted(mission_dir.glob("*.BSP")))
        if not any(p in k.name for p in _STATIONARY_PATTERNS)
    ]


def _collect_probes(missions_dir: Path) -> list[dict]:
    """Walk `missions/*/_index.json` and return one record per spacecraft.

    Skips landed probes (TODO: lat/lon pipeline for surface installations).
    Each record carries `(mission, naif_id, inception_mjd, kernel_paths)`.
    """
    out: list[dict] = []
    for mdir in sorted(missions_dir.iterdir()):
        if not mdir.is_dir():
            continue
        idx_path = mdir / "_index.json"
        if not idx_path.exists():
            continue
        kernels = _mission_kernels(mdir)
        if not kernels:
            continue
        idx = json.loads(idx_path.read_text())
        spacecraft_ids = sorted(
            t for t in (int(s) for s in idx.get("targets", {})) if -999 <= t <= -1
        )
        if not spacecraft_ids:
            continue
        kpaths = [str(k) for k in kernels]
        for naif_id in spacecraft_ids:
            landed, body = is_landed_probe(naif_id, kpaths)
            if landed:
                logger.info(
                    "[skipped] %s naif=%d is landed on body %s (TODO lat/lon pipeline)",
                    mdir.name,
                    naif_id,
                    body,
                )
                continue
            cov = _coverage(naif_id, kpaths)
            if cov is None:
                logger.warning("no coverage for %s/%d", mdir.name, naif_id)
                continue
            out.append(
                {
                    "mission": mdir.name,
                    "naif_id": naif_id,
                    "inception_mjd": et_to_mjd(cov[0]),
                }
            )
    # Deterministic dedupe order: (inception, naif_id, mission).
    out.sort(key=lambda r: (r["inception_mjd"], r["naif_id"], r["mission"]))
    return out


class ProbesIngestor:
    BATCH = 500

    def __init__(self, download_dir: Path) -> None:
        self.session = get_session()
        self.missions_dir = download_dir / PROVIDERS.SPICE / "kernels" / "missions"

    def _clear(self) -> None:
        """Drop previously-ingested probe rows. Safe: probes live under their
        own orbital_source enum and don't get takeovers from other providers."""
        self.session.execute(
            delete(Object).where(Object.orbital_source == OrbitalSource.spice_probe)
        )
        self.session.commit()

    def _build_row(self, record: dict, probe_id: int) -> dict:
        object_pk = make_object_id(ID_TYPES.PROBE, probe_id)
        return {
            "id": object_pk,
            "name": f"{record['mission']} ({record['naif_id']})",
            "object_type": ObjectType.spacecraft,
            # `Object.naif_id` is `unique=True`, but NAIF IDs are recycled
            # across missions (-76 = Mariner 10 and MSL), so we intentionally
            # don't populate it here — the canonical (mission, naif_id)→probe_id
            # map lives in `spice/probe_ids.json`.
            "probe_id": probe_id,
            "orbital_source": OrbitalSource.spice_probe,
            # Probe positions live in the per-zone chunk files, not in a
            # Kepler/SGP4 sub-table — `has_position=False` so element-based
            # writers skip them. The probes/ zone writer reads kernels directly.
            "has_position": False,
        }

    def run(self) -> None:
        if not self.missions_dir.exists():
            logger.warning(
                "Probes missions dir not found at %s, skipping", self.missions_dir
            )
            return
        records = _collect_probes(self.missions_dir)
        if not records:
            logger.info("No probes found under %s", self.missions_dir)
            return

        # Pin every (mission, naif_id) to a stable probe_id via the on-disk cache.
        assignments = assign_many(
            [(r["mission"], r["naif_id"], r["inception_mjd"]) for r in records]
        )

        self._clear()
        rows: list[dict] = []
        for r in tqdm(records, desc="Probes ingest"):
            rec = assignments[(r["mission"], r["naif_id"])]
            rows.append(self._build_row(r, rec.probe_id))
            if len(rows) >= self.BATCH:
                self.session.execute(insert(Object), rows)
                rows = []
        if rows:
            self.session.execute(insert(Object), rows)
        self.session.commit()
        logger.info("Ingested %d probe Objects", len(records))


def ingest(download_dir: Path) -> None:
    ProbesIngestor(download_dir).run()
