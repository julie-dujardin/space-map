"""ProbesDownloader: mirror per-mission spacecraft SPKs into the SPICE tree.

Outputs a per-mission `_index.json` recording each file's size + target NAIF
IDs. The ingest step (see `ingest/providers/objects/probes.py`) reads these
indexes and creates Object rows with `id_type=PROBE`.
"""

import json
import logging
from collections import defaultdict

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader

from ..naif_http import merge_intervals, spk_coverage, spk_targets, stream_to
from .attitude.ck_kernels import download_attitude_capped
from .layout import LANDED_MISSIONS_DIR, MISSIONS_DIR
from .listings import list_mission_pcks, list_mission_spks
from .sources import (
    ESA_BASE,
    NAIF_BASE,
    NAIF_PDS_BASE,
    MissionSource,
    discover_all_sources,
)

# Cap on attitude bytes newly downloaded per run. Sized so a fresh run on
# an empty disk targets ~100 GiB of CK data — enough to cover the smaller
# Phase 2 missions in full before bumping up against the budget. Override
# via env var `SPACE_MAP_ATTITUDE_MAX_GIB` for one-off larger runs.
import os as _os

_ATTITUDE_MAX_GIB = float(_os.environ.get("SPACE_MAP_ATTITUDE_MAX_GIB", "100"))

logger = logging.getLogger(__name__)


class ProbesDownloader(Downloader):
    """Mirror per-mission spacecraft SPK kernels (NAIF / ESA / NAIF-PDS).

    `out_dir` is forced to live under the SPICE provider tree because the
    chunk-builder furnishes generic kernels (lsk, pck, planet/satellite SPKs)
    and probe SPKs together; keeping both under `spice/kernels/` lets the
    furnish step walk one tree.
    """

    name = PROVIDERS.SPICE_PROBES

    def __init__(self, client: httpx.Client) -> None:
        # Skip the base class' `out_dir = DOWNLOAD_DIR / self.name` — we point
        # at the SPICE tree's `kernels/missions/` instead.
        self.client = client
        self.out_dir = MISSIONS_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)
        LANDED_MISSIONS_DIR.mkdir(parents=True, exist_ok=True)

    def download(
        self,
        limit: int | None = None,
        *,
        missions: list[str] | None = None,
        max_mib: float | None = None,
        **_: object,
    ) -> None:
        """Fetch every whitelisted SPK for every selected mission.

        `limit` is ignored (it's a record-count cap that doesn't map cleanly
        to a file-count cap — the natural cap is `max_mib`). `missions`
        restricts to specific local mission names across all servers.
        """
        selected = set(missions) if missions else None
        sources = discover_all_sources(self.client)

        # Phase 1: SPK + PCK mirror, in discovery (alphabetical) order.
        results: list[dict] = []
        for source in sources:
            if selected is not None and source.mission not in selected:
                continue
            results.append(self._process_mission(source, max_mib))

        # Phase 2: Attitude CK + FK + SCLK, in size-ascending order, capped
        # at `_ATTITUDE_MAX_GIB`. Runs as a separate pass so the small
        # missions land first regardless of where they fall alphabetically.
        attitude_sources = [
            s for s in sources if selected is None or s.mission in selected
        ]
        att_results = download_attitude_capped(
            self.client, attitude_sources, _ATTITUDE_MAX_GIB * 1024
        )
        att_new_mib = sum(r.new_bytes for r in att_results) / (1024 * 1024)
        att_total_mib = sum(r.total_bytes for r in att_results) / (1024 * 1024)

        total_files = sum(r.get("files", 0) for r in results if not r.get("skipped"))
        total_mib = sum(r.get("mib", 0.0) for r in results if not r.get("skipped"))
        att_files = sum(r.n_total_files for r in att_results)
        logger.info(
            "ProbesDownloader: %d missions, %d SPK/PCK files (%.1f MiB), "
            "%d attitude files (%.1f MiB new / %.1f MiB on disk)",
            sum(1 for r in results if r.get("files")),
            total_files,
            total_mib,
            att_files,
            att_new_mib,
            att_total_mib,
        )

        self._save_metadata(
            url=f"{NAIF_BASE}|{ESA_BASE}|{NAIF_PDS_BASE}",
            record_count=total_files,
            complete=False,
            missions=len([r for r in results if r.get("files")]),
            total_mib=round(total_mib, 1),
        )

    def _process_mission(self, source: MissionSource, max_mib: float | None) -> dict:
        files = list_mission_spks(self.client, source)
        pck_files = list_mission_pcks(self.client, source)
        bucket_files = (
            ("trajectory", files.trajectory, MISSIONS_DIR),
            ("landed", files.landed, LANDED_MISSIONS_DIR),
        )
        if not files.trajectory and not files.landed and not pck_files:
            return {"mission": source.mission, "skipped": False, "mib": 0.0, "files": 0}
        total = sum(f.size_bytes for b in bucket_files for f in b[1])
        mib = total / 1024 / 1024
        if max_mib is not None and mib > max_mib:
            logger.warning(
                "%s/%s: %.1f MiB exceeds --max-mib=%.0f, skipping",
                source.server,
                source.mission,
                mib,
                max_mib,
            )
            return {"mission": source.mission, "skipped": True, "mib": mib}

        logger.info(
            "%s/%s: %d trajectory + %d landed files (%.1f MiB)",
            source.server,
            source.mission,
            len(files.trajectory),
            len(files.landed),
            mib,
        )

        total_bytes = 0
        total_files = 0
        for bucket_name, bucket, root in bucket_files:
            if not bucket:
                continue
            mission_dir = root / source.mission
            mission_dir.mkdir(parents=True, exist_ok=True)
            coverage_by_naif: dict[int, list[str]] = defaultdict(list)
            intervals_by_naif: dict[int, list[tuple[float, float]]] = defaultdict(list)
            file_records: list[dict] = []
            for f in bucket:
                local = mission_dir / f.name
                try:
                    stream_to(self.client, f.url, local, f.size_bytes)
                except httpx.HTTPError as exc:
                    logger.warning("download failed for %s: %s", f.name, exc)
                    continue
                targets = sorted(spk_targets(local))
                for t in targets:
                    coverage_by_naif[t].append(f.name)
                    intervals_by_naif[t].extend(spk_coverage(local, t))
                file_records.append(
                    {
                        "name": f.name,
                        "size_bytes": local.stat().st_size,
                        "targets": targets,
                    }
                )
            index = {
                "server": source.server,
                "mission": source.mission,
                "spk_url": source.spk_url,
                "bucket": bucket_name,
                "files": file_records,
                "targets": {
                    str(naif): sorted(set(names))
                    for naif, names in sorted(coverage_by_naif.items())
                },
                "targets_coverage": {
                    str(naif): [list(iv) for iv in merge_intervals(intervals)]
                    for naif, intervals in sorted(intervals_by_naif.items())
                },
            }
            (mission_dir / "_index.json").write_text(
                json.dumps(index, indent=2, sort_keys=True)
            )
            total_bytes += sum(r["size_bytes"] for r in file_records)
            total_files += len(file_records)

        # PCKs are fetched into MISSIONS_DIR/<mission>/ next to the SPKs but
        # not added to _index.json — the ingest step turns indexed targets
        # into probe Object rows, and PCKs reference small-body targets that
        # are already Object rows from SBDB. The bodies/ downloader's extract
        # step discovers these files via MISSIONS_DIR.glob("*/*.tpc").
        pck_bytes = 0
        if pck_files:
            mission_dir = MISSIONS_DIR / source.mission
            mission_dir.mkdir(parents=True, exist_ok=True)
            for f in pck_files:
                local = mission_dir / f.name
                try:
                    stream_to(self.client, f.url, local, f.size_bytes)
                except httpx.HTTPError as exc:
                    logger.warning("PCK download failed for %s: %s", f.name, exc)
                    continue
                pck_bytes += local.stat().st_size
            logger.info(
                "%s/%s: %d PCK files (%.1f KiB)",
                source.server,
                source.mission,
                len(pck_files),
                pck_bytes / 1024,
            )

        return {
            "mission": source.mission,
            "skipped": False,
            "mib": (total_bytes + pck_bytes) / 1024 / 1024,
            "files": total_files + len(pck_files),
        }
