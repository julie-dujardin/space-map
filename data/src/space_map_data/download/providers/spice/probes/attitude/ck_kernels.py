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
from .patterns import patterns_for

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
    client: httpx.Client,
    source: MissionSource,
    *,
    max_new_bytes: int | None = None,
) -> DownloadResult:
    """Download the curated attitude kernel set for one mission.

    `max_new_bytes` caps newly-fetched CK bytes for the whole mission
    (shared across craft); once hit, the CK loop stops and we write the
    index for whatever landed. FK/SCLK are uncapped (KB-MB scale).

    The index carries top-level `frame_name`/`ck_files`/`fk`/`sclk` for the
    first craft plus a `spacecraft` array (one entry per craft), so a
    multi-craft mission round-trips on the single-craft index contract.

    Always returns a result (never raises) so one uncurated or failed
    mission can't abort the batch.
    """
    patterns = patterns_for(source.mission)
    if not patterns:
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

    craft: list[dict] = []
    all_files: list[Path] = []
    new_bytes = 0
    truncated = False
    remaining = max_new_bytes
    for pattern in patterns:
        ck_files, ck_new, ck_trunc = _download_matching(
            client,
            f"{base}/ck/",
            mission_dir,
            pattern.ck_glob,
            take_all=True,
            exclude_glob=pattern.ck_exclude_glob,
            max_new_bytes=remaining,
        )
        new_bytes += ck_new
        if remaining is not None:
            remaining = max(0, remaining - ck_new)
        truncated = truncated or ck_trunc
        if not ck_files:
            logger.info(
                "attitude: %s/%s — no CK (%s)",
                source.mission,
                pattern.frame_name,
                "cap reached" if ck_trunc else "no match",
            )
            continue

        fk_files, fk_new, _ = _download_matching(
            client, f"{base}/fk/", mission_dir, pattern.fk_glob, take_all=False
        )
        sclk_files, sclk_new, _ = _download_matching(
            client, f"{base}/sclk/", mission_dir, pattern.sclk_glob, take_all=False
        )
        new_bytes += fk_new + sclk_new
        if not fk_files or not sclk_files:
            logger.info(
                "attitude: %s/%s — missing FK or SCLK",
                source.mission,
                pattern.frame_name,
            )
            continue

        all_files += ck_files + fk_files + sclk_files
        craft.append(
            {
                "frame_name": pattern.frame_name,
                "ck_files": [p.name for p in ck_files],
                "fk": fk_files[0].name,
                "sclk": sclk_files[0].name,
            }
        )

    if not craft:
        return DownloadResult(
            mission=source.mission,
            n_ck=0,
            n_total_files=0,
            total_bytes=0,
            new_bytes=new_bytes,
            skipped_reason="cap reached before any CK"
            if truncated
            else "no usable spacecraft (CK + FK + SCLK)",
        )

    first = craft[0]
    index = {
        "server": source.server,
        "mission": source.mission,
        "frame_name": first["frame_name"],
        "ck_files": first["ck_files"],
        "fk": first["fk"],
        "sclk": first["sclk"],
        "spacecraft": craft,
    }
    (mission_dir / ATTITUDE_INDEX_NAME).write_text(
        json.dumps(index, indent=2, sort_keys=True)
    )
    return DownloadResult(
        mission=source.mission,
        n_ck=sum(len(c["ck_files"]) for c in craft),
        n_total_files=len(all_files),
        total_bytes=sum(p.stat().st_size for p in all_files),
        new_bytes=new_bytes,
        skipped_reason="cap reached mid-CK (partial coverage)" if truncated else None,
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
        patterns = patterns_for(source.mission)
        if not patterns:
            continue
        # Dedupe — BepiColombo / JUICE show up at both NAIF and ESA mirrors
        # but the patterns table is keyed by mission, so the second source
        # would re-download the same files. Skip the second occurrence.
        if any(s.mission == source.mission for _, s in targets):
            continue
        est_mib = sum(p.estimated_total_mib for p in patterns)
        targets.append((est_mib, source))

    targets.sort(key=lambda t: t[0])

    results: list[DownloadResult] = []
    total_new_mib = 0.0
    cap = max_total_mib
    for est_mib, source in targets:
        # Hard cap: once the running total has hit the budget, skip the
        # rest entirely. No predictive check anymore — that was unreliable
        # when estimates undershot (e.g. ORX at 2 GiB estimated, 260 GiB
        # actual). Instead we let the per-file cap below stop a runaway
        # mid-mission and check the running total here on entry.
        if cap is not None and total_new_mib >= cap:
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
        remaining_mib = (cap - total_new_mib) if cap is not None else None
        logger.info(
            "attitude: %s (est %d MiB) — running total %.1f / %s MiB",
            source.mission,
            est_mib,
            total_new_mib,
            f"{cap:.0f}" if cap is not None else "∞",
        )
        # Pass remaining budget to CK loop so a single mission can't blow
        # past the cap. Convert MiB → bytes for the per-file accumulator.
        max_new_bytes = (
            int(remaining_mib * 1024 * 1024) if remaining_mib is not None else None
        )
        result = download_attitude_for(client, source, max_new_bytes=max_new_bytes)
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
    max_new_bytes: int | None = None,
) -> tuple[list[Path], int, bool]:
    """List `url`, download files matching `glob` into `dest_dir`.

    Returns `(local_paths, bytes_newly_downloaded, truncated)`. `paths`
    covers both cached and freshly-downloaded files. The byte count only
    sums the network spend. `truncated=True` means `max_new_bytes` cut us
    off before we'd processed every match.

    `take_all=True` → download every match (used for CK — every bus file
    contributes attitude coverage). `take_all=False` → download just the
    lex-last match (used for FK + SCLK — we want the latest revision).
    """
    try:
        hrefs = list_naif_dir(client, url)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return [], 0, False
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
        return [], 0, False
    if not take_all:
        matches = [matches[-1]]

    out: list[Path] = []
    new_bytes = 0
    truncated = False
    for i, name in enumerate(matches):
        # Per-file cap check: stop before fetching another file once we've
        # already spent the budget. Cached files are free, so an existing
        # local file is still added to `out` even after the cap is hit.
        if max_new_bytes is not None and new_bytes >= max_new_bytes:
            logger.info(
                "download cap hit at %.1f MiB new (%d of %d files), stopping listing of %s",
                new_bytes / (1024 * 1024),
                i,
                len(matches),
                url,
            )
            truncated = True
            break
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
    return out, new_bytes, truncated
