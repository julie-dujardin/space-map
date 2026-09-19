"""Local mirror of the small-file metadata trees under DOWNLOAD_DIR.

DOWNLOAD_DIR sits on a network mount. Reading one per-QID JSON there costs a
disk seek on the NAS (~8 ms, ~1100/s even with 32 threads), so a pass over
the 550k Wikidata/Wikipedia/Commons metadata files takes minutes however the
caller is written, and ingest and export together make several such passes.
Syncing those trees to local disk once per run (stat compare, parallel copy
of what changed) turns every later read into a page-cache hit.

Readers call `local(path)` on a DOWNLOAD_DIR path; it maps into the mirror
when the path lies under a synced tree and returns the path unchanged
otherwise, so code paths that never called `sync_all` keep reading the
source. Nothing is mirrored when DOWNLOAD_DIR is already on a local
filesystem.
"""

import logging
import os
import shutil
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from space_map_data.utils.paths import CACHE_DIR, DOWNLOAD_DIR

logger = logging.getLogger(__name__)

MIRROR_DIR = CACHE_DIR / "mirror"

_NETWORK_FS = frozenset(
    {"nfs", "nfs4", "cifs", "smb3", "fuse.sshfs", "fuse.rclone", "9p", "afs"}
)
_COPY_THREADS = 32

Selector = Callable[[Path], bool]


def _not_image_source(rel: Path) -> bool:
    return not rel.name.startswith("source.")


# (tree relative to DOWNLOAD_DIR, file filter). Commons keeps the picture
# bytes on the mount; only the per-image metadata beside them is mirrored.
TREES: tuple[tuple[str, Selector | None], ...] = (
    ("sources/metadata/wikidata", None),
    ("sources/metadata/wikipedia", None),
    ("sources/metadata/wikipedia_sections", None),
    ("sources/images/commons", _not_image_source),
)

_synced_roots: list[tuple[Path, Path]] = []


def is_network_mount(path: Path) -> bool:
    """True when `path` resolves onto a network filesystem, per mountinfo."""
    try:
        target = str(path.resolve())
        best_len, best_type = -1, ""
        with open("/proc/self/mountinfo") as f:
            for line in f:
                fields = line.split()
                mount_point = fields[4].replace("\\040", " ")
                # Later lines stack on earlier ones (autofs stub, then the
                # real mount), so ties go to the last entry.
                if len(mount_point) >= best_len and (
                    target == mount_point
                    or target.startswith(mount_point.rstrip("/") + "/")
                ):
                    best_len = len(mount_point)
                    best_type = fields[fields.index("-") + 1]
    except OSError, ValueError, IndexError:
        return False
    return best_type in _NETWORK_FS


def local(path: Path) -> Path:
    """Mirror path for `path` when its tree has been synced, else `path`."""
    for src_root, dst_root in _synced_roots:
        if path.is_relative_to(src_root):
            return dst_root / path.relative_to(src_root)
    return path


def sync_all() -> None:
    """Bring every tree in TREES up to date and register it for `local`."""
    if not is_network_mount(DOWNLOAD_DIR):
        return
    for rel, select in TREES:
        sync_tree(rel, select)


def sync_tree(rel: str, select: Selector | None = None) -> None:
    src_root = DOWNLOAD_DIR / rel
    dst_root = MIRROR_DIR / rel
    if not src_root.is_dir():
        logger.info("mirror: %s absent on the mount; nothing to sync", rel)
        return
    t0 = time.perf_counter()
    src = _scan(src_root, select)
    dst = _scan(dst_root, None) if dst_root.is_dir() else {}
    changed = [r for r, st in src.items() if dst.get(r) != st]
    stale = [r for r in dst if r not in src]
    for r in stale:
        (dst_root / r).unlink(missing_ok=True)
    dirs = {(dst_root / r).parent for r in changed}
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(_COPY_THREADS) as ex:
        list(ex.map(lambda r: _copy(src_root / r, dst_root / r, src[r]), changed))
    for r in stale:
        _prune_empty(dst_root / r, dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)
    logger.info(
        "mirror: %s — %d files, %d copied, %d removed in %.1fs",
        rel,
        len(src),
        len(changed),
        len(stale),
        time.perf_counter() - t0,
    )
    _synced_roots.append((src_root, dst_root))


def _scan(root: Path, select: Selector | None) -> dict[Path, tuple[int, int]]:
    """{relative path: (size, mtime_ns)} for every selected file under root."""
    out: dict[Path, tuple[int, int]] = {}
    stack = [root]
    while stack:
        d = stack.pop()
        with os.scandir(d) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False):
                    stack.append(Path(e.path))
                    continue
                if not e.is_file(follow_symlinks=False):
                    continue
                rel = Path(e.path).relative_to(root)
                if select is not None and not select(rel):
                    continue
                st = e.stat(follow_symlinks=False)
                out[rel] = (st.st_size, st.st_mtime_ns)
    return out


def _copy(src: Path, dst: Path, stamp: tuple[int, int]) -> None:
    tmp = dst.with_name(f".{dst.name}.tmp")
    shutil.copyfile(src, tmp)
    os.utime(tmp, ns=(stamp[1], stamp[1]))
    os.replace(tmp, dst)


def _prune_empty(path: Path, stop: Path) -> None:
    """Remove now-empty parents of a deleted file, up to (excluding) `stop`."""
    d = path.parent
    while d != stop:
        try:
            d.rmdir()
        except OSError:
            return
        d = d.parent
