"""Mirror per-mission CK + FK + SCLK from NAIF / ESA.

Drives a two-phase attitude download:

  1. `download_attitude_for(client, source)` — pulls one mission's
     curated kernel set (CK + FK + SCLK). Per-mission contract: returns
     a `DownloadResult` regardless of outcome so the orchestrator can
     decide whether to surface failures.

  2. `download_attitude_capped(client, sources, max_total_mib)` — orders
     the sources by `AttitudePattern.estimated_total_mib`, runs each
     mission through `download_attitude_for`, and skips remaining
     missions once cumulative *newly-downloaded* bytes exceed the cap.
     Files already present on disk (from a previous run) don't count —
     the cap reflects what we spent on this run's network calls.
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
    total_bytes: int  # on-disk bytes of the full kernel set after run
    new_bytes: int  # bytes actually fetched this run (skip-on-match)
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
            new_bytes=0,
            skipped_reason="no curated pattern",
        )

    base = _kernels_base_url(source.server, source.mission)
    mission_dir = MISSIONS_DIR / source.mission
    mission_dir.mkdir(parents=True, exist_ok=True)

    ck_files, ck_new = _download_matching(
        client,
        f"{base}/ck/",
        mission_dir,
        pattern.ck_glob,
        take_all=True,
        exclude_glob=pattern.ck_exclude_glob,
    )
    if not ck_files:
        return DownloadResult(
            mission=source.mission,
            n_ck=0,
            n_total_files=0,
            total_bytes=0,
            new_bytes=ck_new,
            skipped_reason="no CK matches",
        )

    fk_files, fk_new = _download_matching(
        client, f"{base}/fk/", mission_dir, pattern.fk_glob, take_all=False
    )
    sclk_files, sclk_new = _download_matching(
        client, f"{base}/sclk/", mission_dir, pattern.sclk_glob, take_all=False
    )
    if not fk_files or not sclk_files:
        return DownloadResult(
            mission=source.mission,
            n_ck=len(ck_files),
            n_total_files=len(ck_files),
            total_bytes=sum(p.stat().st_size for p in ck_files),
            new_bytes=ck_new + fk_new + sclk_new,
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
        new_bytes=ck_new + fk_new + sclk_new,
    )


def download_attitude_capped(
    client: httpx.Client,
    sources: list[MissionSource],
    max_total_mib: float | None,
) -> list[DownloadResult]:
    """Run `download_attitude_for` on every source in size-ascending order,
    short-circuiting once cumulative *new* bytes exceed `max_total_mib`.

    Missions without a pattern are skipped entirely (no listing call). The
    ordering means we tackle GAIA / ORX / SIRTF first and only get to MRO
    if the cap allows it — so a fresh run does the cheap missions in full
    instead of running out of budget on the alphabetical-first one.
    """
    targets: list[tuple[int, MissionSource]] = []
    for source in sources:
        pattern = PATTERNS.get(source.mission)
        if pattern is None:
            continue
        # Dedupe — BepiColombo / JUICE show up at both NAIF and ESA mirrors
        # but the patterns table is keyed by mission, so the second source
        # would re-download the same files. Skip the second occurrence.
        if any(s.mission == source.mission for _, s in targets):
            continue
        targets.append((pattern.estimated_total_mib, source))

    targets.sort(key=lambda t: t[0])

    results: list[DownloadResult] = []
    total_new_mib = 0.0
    cap = max_total_mib
    for est_mib, source in targets:
        # Predictive cap: skip a mission if its estimated download would
        # push the running total over the budget. Estimates can be off by
        # 50 %, so this keeps the actual run close to the target without
        # one giant mission blowing through the cap halfway in.
        if cap is not None and total_new_mib + est_mib > cap:
            logger.info(
                "attitude: skipping %s (est %d MiB would push %.1f → %.1f MiB, cap %.1f)",
                source.mission,
                est_mib,
                total_new_mib,
                total_new_mib + est_mib,
                cap,
            )
            results.append(
                DownloadResult(
                    mission=source.mission,
                    n_ck=0,
                    n_total_files=0,
                    total_bytes=0,
                    new_bytes=0,
                    skipped_reason="global cap",
                )
            )
            continue
        logger.info(
            "attitude: %s (est %d MiB) — running total %.1f / %s MiB",
            source.mission,
            est_mib,
            total_new_mib,
            f"{cap:.0f}" if cap is not None else "∞",
        )
        result = download_attitude_for(client, source)
        results.append(result)
        total_new_mib += result.new_bytes / (1024 * 1024)
        if result.n_total_files:
            logger.info(
                "attitude: %s done — %d CK, %.1f MiB new, %.1f MiB on disk",
                source.mission,
                result.n_ck,
                result.new_bytes / (1024 * 1024),
                result.total_bytes / (1024 * 1024),
            )
        elif result.skipped_reason:
            logger.info(
                "attitude: %s skipped — %s", source.mission, result.skipped_reason
            )
    return results


def _download_matching(
    client: httpx.Client,
    url: str,
    dest_dir: Path,
    glob: str,
    *,
    take_all: bool,
    exclude_glob: str | None = None,
) -> tuple[list[Path], int]:
    """List `url`, download files matching `glob` into `dest_dir`.

    Returns `(local_paths, bytes_newly_downloaded)` — paths covers both
    cached and freshly-downloaded files, while the byte count only sums
    the network spend so the cap reflects what we actually fetched.

    `take_all=True` → download every match (used for CK — every bus file
    contributes attitude coverage). `take_all=False` → download just the
    lex-last match (used for FK + SCLK — we want the latest revision).
    """
    try:
        hrefs = list_naif_dir(client, url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return [], 0
        raise
    matches = sorted(
        h
        for h in hrefs
        if not h.endswith("/")
        and not h.startswith(("http://", "https://"))
        and fnmatch.fnmatch(h, glob)
        and not (exclude_glob and fnmatch.fnmatch(h, exclude_glob))
    )
    if not matches:
        return [], 0
    if not take_all:
        matches = [matches[-1]]

    out: list[Path] = []
    new_bytes = 0
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
            new_bytes += local.stat().st_size
        except httpx.HTTPError as exc:
            logger.warning("download failed for %s: %s", file_url, exc)
    return out, new_bytes
