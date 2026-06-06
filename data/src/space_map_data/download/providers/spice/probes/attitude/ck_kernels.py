"""Mirror per-mission CK + FK + SCLK from NAIF / ESA.

The probe SPK downloader already runs per `MissionSource`; the attitude
downloader plugs into the same per-mission loop. For each mission that
has a curated `AttitudePattern`:

  1. List `kernels/{ck,fk,sclk}/` on the mirror.
  2. Filter CK by `ck_glob` (typically the SC-bus pattern — `mro_sc_*`).
  3. Pick the lex-last FK matching `fk_glob` and SCLK matching `sclk_glob`.
  4. Download all matched files into `MISSIONS_DIR/<MISSION>/`.
  5. Write `_attitude_index.json` listing what's on disk + the chosen
     frame name + bus instrument ID so the extractor can skip a re-walk.

Missions without a pattern are silently skipped — the orchestrator can
log this once for visibility but it's not an error (we expect PDS3/PDS4
missions to land via a separate path).
"""

import fnmatch
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..layout import MISSIONS_DIR
from ..sources import ESA_BASE, MissionSource, NAIF_BASE
from ...naif_http import list_naif_dir, stream_to
from .patterns import PATTERNS

logger = logging.getLogger(__name__)

# Filename of the per-mission attitude index. Sits next to the existing
# `_index.json` so a glance at the missions dir tells you which probes
# have both trajectory and attitude data.
ATTITUDE_INDEX_NAME = "_attitude_index.json"


@dataclass(frozen=True)
class DownloadResult:
    mission: str
    n_ck: int
    n_total_files: int
    total_bytes: int
    skipped_reason: str | None = None


def _kernels_base_url(server: str, mission: str) -> str:
    base = NAIF_BASE if server == "NAIF" else ESA_BASE
    return f"{base}/{mission}/kernels"


def download_attitude_for(
    client: httpx.Client, source: MissionSource
) -> DownloadResult:
    """Download the curated attitude kernel set for one mission.

    Returns a result regardless of outcome — callers can decide whether to
    log skip reasons or surface them. We return rather than raise because
    a missing-pattern mission is the common case in early phases and
    shouldn't trip up the whole batch.
    """
    pattern = PATTERNS.get(source.mission)
    if pattern is None:
        return DownloadResult(
            mission=source.mission,
            n_ck=0,
            n_total_files=0,
            total_bytes=0,
            skipped_reason="no curated pattern",
        )

    base = _kernels_base_url(source.server, source.mission)
    mission_dir = MISSIONS_DIR / source.mission
    mission_dir.mkdir(parents=True, exist_ok=True)

    ck_files = _download_matching(
        client, f"{base}/ck/", mission_dir, pattern.ck_glob, take_all=True
    )
    if not ck_files:
        return DownloadResult(
            mission=source.mission,
            n_ck=0,
            n_total_files=0,
            total_bytes=0,
            skipped_reason="no CK matches",
        )

    fk_files = _download_matching(
        client, f"{base}/fk/", mission_dir, pattern.fk_glob, take_all=False
    )
    sclk_files = _download_matching(
        client, f"{base}/sclk/", mission_dir, pattern.sclk_glob, take_all=False
    )
    if not fk_files or not sclk_files:
        return DownloadResult(
            mission=source.mission,
            n_ck=len(ck_files),
            n_total_files=len(ck_files),
            total_bytes=sum(p.stat().st_size for p in ck_files),
            skipped_reason="missing FK or SCLK",
        )

    all_files = ck_files + fk_files + sclk_files
    index = {
        "server": source.server,
        "mission": source.mission,
        "frame_name": pattern.frame_name,
        "ck_files": [p.name for p in ck_files],
        "fk": fk_files[0].name,
        "sclk": sclk_files[0].name,
    }
    (mission_dir / ATTITUDE_INDEX_NAME).write_text(
        json.dumps(index, indent=2, sort_keys=True)
    )
    return DownloadResult(
        mission=source.mission,
        n_ck=len(ck_files),
        n_total_files=len(all_files),
        total_bytes=sum(p.stat().st_size for p in all_files),
    )


def _download_matching(
    client: httpx.Client, url: str, dest_dir: Path, glob: str, *, take_all: bool
) -> list[Path]:
    """List `url`, pick files matching `glob`, download into `dest_dir`.

    `take_all=True` → download every match (used for CK — every bus file
    contributes attitude coverage). `take_all=False` → download just the
    lex-last match (used for FK + SCLK — we want the latest revision).
    """
    try:
        hrefs = list_naif_dir(client, url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return []
        raise
    matches = sorted(
        h
        for h in hrefs
        if not h.endswith("/")
        and not h.startswith(("http://", "https://"))
        and fnmatch.fnmatch(h, glob)
    )
    if not matches:
        return []
    if not take_all:
        matches = [matches[-1]]

    out: list[Path] = []
    for name in matches:
        local = dest_dir / name
        file_url = url + name
        try:
            head = client.head(file_url, follow_redirects=True)
            head.raise_for_status()
            expected = int(head.headers.get("content-length", 0))
            if local.exists() and expected and local.stat().st_size == expected:
                out.append(local)
                continue
            stream_to(client, file_url, local, expected)
            out.append(local)
        except httpx.HTTPError as exc:
            logger.warning("download failed for %s: %s", file_url, exc)
    return out
