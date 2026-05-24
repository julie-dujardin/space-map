"""Per-mission SPK + PCK listing with include/skip filters applied.

Trajectory kernels go under `MISSIONS_DIR/<mission>/`; landed kernels under
`LANDED_MISSIONS_DIR/<mission>/`. A file is routed to one bucket only —
LANDED_INCLUDE wins over MISSION_INCLUDE so a surface kernel can't
accidentally end up in the trajectory tree even if MISSION_INCLUDE is too
permissive.
"""

import logging
import re
from dataclasses import dataclass

import httpx

from ..naif_http import head_sizes_async, list_naif_dir
from .mission_patterns import (
    LANDED_INCLUDE,
    MISSION_INCLUDE,
    MISSION_LATEST_ONLY,
    SKIP_PATTERNS,
)
from .sources import MissionSource

logger = logging.getLogger(__name__)

_GENERIC_PCK_SNAPSHOT_RE = re.compile(r"^pck\d+\.tpc$", re.IGNORECASE)
_VERSIONED_PCK_RE = re.compile(r"^(?P<stem>.+)_v(?P<ver>\d+)\.tpc$", re.IGNORECASE)


@dataclass(frozen=True)
class FileEntry:
    name: str
    url: str
    size_bytes: int


@dataclass(frozen=True)
class MissionFiles:
    trajectory: list[FileEntry]
    landed: list[FileEntry]


def apply_mission_filter(
    hrefs: list[str],
    include: dict[str, tuple[str, ...]],
    mission: str,
    use_latest_only: bool,
) -> list[str]:
    """Filter `hrefs` against `include[mission]` patterns.

    Returns [] when the mission has an entry in `include` but no files match
    (caller logs). Returns the input unchanged when the mission has no entry
    (accept-all).
    """
    if mission not in include:
        return list(hrefs)
    patterns = include[mission]
    if not patterns:
        return []
    compiled = tuple(re.compile(p, re.IGNORECASE) for p in patterns)
    if use_latest_only:
        kept: list[str] = []
        for pat in compiled:
            matches = sorted(h for h in hrefs if pat.match(h))
            if matches:
                kept.append(matches[-1])
        return kept
    return [h for h in hrefs if any(p.match(h) for p in compiled)]


def filter_pck_listing(hrefs: list[str]) -> list[str]:
    """Filter raw .tpc directory listings down to the canonical per-body files.

    Two filters:
    * Drop `pck\\d+.tpc` — generic-kernel snapshots bundled into mission dirs
      (e.g. ORX/kernels/pck/pck00010.tpc). The current pck00011 from
      `generic_kernels/pck/` supersedes them; loading the snapshot adds bytes
      and slows furnsh without contributing anything generic doesn't already.
    * For `<body>_v<n>.tpc` series, keep the highest version per body. NAIF
      mission archives keep older revisions for traceability; the latest is
      the canonical pick (same convention as `_LATEST_VERSION_KERNELS` in
      bodies/kernels.py).
    """
    versioned: dict[str, tuple[int, str]] = {}
    unversioned: list[str] = []
    for h in hrefs:
        if _GENERIC_PCK_SNAPSHOT_RE.match(h):
            continue
        m = _VERSIONED_PCK_RE.match(h)
        if m:
            stem = m.group("stem").lower()
            ver = int(m.group("ver"))
            prev = versioned.get(stem)
            if prev is None or ver > prev[0]:
                versioned[stem] = (ver, h)
        else:
            unversioned.append(h)
    return sorted([entry[1] for entry in versioned.values()] + unversioned)


def list_mission_spks(client: httpx.Client, source: MissionSource) -> MissionFiles:
    """Return kept (size-known) SPK entries for `source`, split by bucket.

    One upstream listing + one HEAD batch are shared between both buckets.
    Files matching `LANDED_INCLUDE` are routed to `landed` and excluded
    from `trajectory` even if `MISSION_INCLUDE` would also have matched
    them (LANDED wins).
    """
    raw = [
        h for h in list_naif_dir(client, source.spk_url) if h.lower().endswith(".bsp")
    ]
    hrefs = [h for h in raw if not any(p.match(h) for p in SKIP_PATTERNS)]
    pre_filter = len(hrefs)

    # LANDED is opt-in: missions without an explicit entry route everything
    # to trajectory. (`apply_mission_filter` returns accept-all when the
    # mission is absent — fine for MISSION_INCLUDE, wrong for LANDED_INCLUDE
    # since it would dump all of CASSINI/BEPICOLOMBO/etc. into landed_missions/.)
    landed_hrefs = (
        apply_mission_filter(
            hrefs, LANDED_INCLUDE, source.mission, use_latest_only=False
        )
        if source.mission in LANDED_INCLUDE
        else []
    )
    trajectory_pool = [h for h in hrefs if h not in set(landed_hrefs)]
    trajectory_hrefs = apply_mission_filter(
        trajectory_pool,
        MISSION_INCLUDE,
        source.mission,
        use_latest_only=source.mission in MISSION_LATEST_ONLY,
    )

    # Catches the M01/SOLAR-ORBITER-style bug where a hardcoded version
    # number in the regex drifts past the latest published kernel and
    # silently matches zero files. Only logs when MISSION_INCLUDE had an
    # entry but post-filter is empty — accept-all (no entry) is fine.
    if (
        source.mission in MISSION_INCLUDE
        and MISSION_INCLUDE[source.mission]
        and pre_filter
        and not trajectory_hrefs
    ):
        logger.warning(
            "%s/%s: MISSION_INCLUDE matched 0 of %d candidate .bsp "
            "files — pattern likely stale",
            source.server,
            source.mission,
            pre_filter,
        )

    all_hrefs = trajectory_hrefs + landed_hrefs
    if not all_hrefs:
        return MissionFiles(trajectory=[], landed=[])

    sizes = head_sizes_async([f"{source.spk_url}{h}" for h in all_hrefs])
    sized = {
        h: FileEntry(name=h, url=f"{source.spk_url}{h}", size_bytes=s)
        for h, s in zip(all_hrefs, sizes, strict=True)
    }
    return MissionFiles(
        trajectory=[sized[h] for h in trajectory_hrefs],
        landed=[sized[h] for h in landed_hrefs],
    )


def list_mission_pcks(client: httpx.Client, source: MissionSource) -> list[FileEntry]:
    """Return sized text-PCK entries from `<mission>/kernels/pck/`.

    Most missions don't publish a PCK directory — listing failures are silent
    by design. Filtered to `.tpc` (text PCKs) only: `.bpc` files are
    high-frequency Earth-orientation snapshots and don't contribute body
    shape/orientation/GM constants; `.fk` frame kernels define rotation
    frames but no scalar constants.

    No per-mission whitelist: PCKs are KB-scale and the bodies/ downloader's
    generic-wins furnish order (mission first, generic last) prevents any
    cross-body regression from incidental planet entries in mission PCKs.
    """
    pck_url = source.spk_url.replace("/spk/", "/pck/")
    listed = [h for h in list_naif_dir(client, pck_url) if h.lower().endswith(".tpc")]
    raw = filter_pck_listing(listed)
    if not raw:
        return []
    sizes = head_sizes_async([f"{pck_url}{h}" for h in raw])
    return [
        FileEntry(name=h, url=f"{pck_url}{h}", size_bytes=s)
        for h, s in zip(raw, sizes, strict=True)
    ]
