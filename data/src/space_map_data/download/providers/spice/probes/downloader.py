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

from ..naif_http import spk_targets, stream_to
from .attitude.ck_kernels import DownloadResult as AttitudeDownloadResult
from .attitude.ck_kernels import download_attitude_for
from .layout import LANDED_MISSIONS_DIR, MISSIONS_DIR
from .listings import list_mission_pcks, list_mission_spks
from .sources import (
    ESA_BASE,
    NAIF_BASE,
    NAIF_PDS_BASE,
    MissionSource,
    discover_all_sources,
)

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

        results: list[dict] = []
        for source in sources:
            if selected is not None and source.mission not in selected:
                continue
            results.append(self._process_mission(source, max_mib))

        total_files = sum(r.get("files", 0) for r in results if not r.get("skipped"))
        total_mib = sum(r.get("mib", 0.0) for r in results if not r.get("skipped"))
        logger.info(
            "ProbesDownloader: %d missions, %d files, %.1f MiB",
            sum(1 for r in results if r.get("files")),
            total_files,
            total_mib,
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

        # Attitude kernels (CK + FK + SCLK for the SC bus frame) are pulled
        # via a curated per-mission pattern table. Missions without a pattern
        # are quietly skipped — the table grows as we validate new missions.
        att_result = download_attitude_for(self.client, source)
        if att_result.n_total_files:
            logger.info(
                "%s/%s: %d attitude files (%d CK, %.1f MiB)",
                source.server,
                source.mission,
                att_result.n_total_files,
                att_result.n_ck,
                att_result.total_bytes / 1024 / 1024,
            )
        elif (
            att_result.skipped_reason
            and att_result.skipped_reason != "no curated pattern"
        ):
            logger.warning(
                "%s/%s: attitude download skipped: %s",
                source.server,
                source.mission,
                att_result.skipped_reason,
            )

        return {
            "mission": source.mission,
            "skipped": False,
            "mib": (total_bytes + pck_bytes + att_result.total_bytes) / 1024 / 1024,
            "files": total_files + len(pck_files) + att_result.n_total_files,
            "attitude": _attitude_summary(att_result),
        }


def _attitude_summary(result: AttitudeDownloadResult) -> dict | None:
    """Compact summary surfaced in the per-mission download metadata."""
    if not result.n_total_files:
        return None
    return {
        "n_ck": result.n_ck,
        "total_bytes": result.total_bytes,
    }
