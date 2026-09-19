"""Content stamps for cache signatures.

A stamp is `{size, digest}` and never carries an mtime, so copying, moving or
re-downloading identical bytes leaves every cache that embeds it warm. mtime
only keys the local digest memo in CACHE_DIR, which makes the common run
stat-only; a moved tree re-reads its files once and never re-exports.

Files above `_FULL_HASH_LIMIT` are digested from fixed samples (head, tail,
two interior blocks) plus their size. Every input this covers — SPICE
kernels, zips, npz, CSV snapshots — changes its size or its head/tail on any
real update, and hashing 500 GB of kernels per mount move is not an option.
"""

import atexit
import hashlib
import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from space_map_data.utils.paths import CACHE_DIR

logger = logging.getLogger(__name__)

# Bump when the digest recipe changes; every stamp then recomputes once.
_RECIPE_VERSION = 1
_FULL_HASH_LIMIT = 1 << 20
_EDGE_BYTES = 256 << 10
_INNER_BYTES = 64 << 10
_INNER_FRACTIONS = (1 / 3, 2 / 3)
# NAS reads are latency-bound (~8 ms per cold small read), so a tree walk
# digests misses concurrently.
_THREADS = 32
_FLUSH_EVERY = 256

_MEMO_PATH = CACHE_DIR / "content_stamps.json"

_memo: dict[str, list] | None = None
_memo_pid: int | None = None
_dirty = 0
_lock = Lock()


def content_stamp(path: Path) -> dict | None:
    """`{size, digest}` for `path`, or None when it is missing."""
    try:
        st = path.stat()
    except OSError:
        return None
    return {"size": st.st_size, "digest": _digest(path, st)}


def content_stamps(paths: list[Path]) -> dict[Path, dict | None]:
    """`content_stamp` for many paths, digesting the memo misses in parallel."""
    stats: dict[Path, os.stat_result] = {}
    for p in paths:
        try:
            stats[p] = p.stat()
        except OSError:
            pass
    misses = [(p, st) for p, st in stats.items() if _memo_get(p, st) is None]
    if misses:
        with ThreadPoolExecutor(max_workers=min(_THREADS, len(misses))) as ex:
            list(ex.map(lambda ps: _digest(*ps), misses))
    return {
        p: None
        if p not in stats
        else {"size": stats[p].st_size, "digest": _digest(p, stats[p])}
        for p in paths
    }


def _digest(path: Path, st: os.stat_result) -> str:
    memoised = _memo_get(path, st)
    if memoised is not None:
        return memoised
    with path.open("rb") as f:
        if st.st_size <= _FULL_HASH_LIMIT:
            h = hashlib.file_digest(f, lambda: hashlib.blake2b(digest_size=16))
        else:
            h = hashlib.blake2b(digest_size=16)
            h.update(str(st.st_size).encode())
            offsets = [0, *(int(st.st_size * frac) for frac in _INNER_FRACTIONS)]
            sizes = [_EDGE_BYTES, *([_INNER_BYTES] * len(_INNER_FRACTIONS))]
            for offset, size in zip(offsets, sizes, strict=True):
                f.seek(offset)
                h.update(f.read(size))
            f.seek(max(0, st.st_size - _EDGE_BYTES))
            h.update(f.read(_EDGE_BYTES))
    digest = h.hexdigest()
    _memo_put(path, st, digest)
    return digest


def _key(path: Path) -> str:
    return os.path.abspath(path)


def _memo_get(path: Path, st: os.stat_result) -> str | None:
    memo = _load_memo()
    entry = memo.get(_key(path))
    if entry and entry[0] == st.st_size and entry[1] == st.st_mtime_ns:
        return entry[2]
    return None


def _memo_put(path: Path, st: os.stat_result, digest: str) -> None:
    global _dirty
    with _lock:
        _load_memo()[_key(path)] = [st.st_size, st.st_mtime_ns, digest]
        _dirty += 1
        flush = _dirty >= _FLUSH_EVERY
    if flush:
        flush_memo()


def _load_memo() -> dict[str, list]:
    global _memo, _memo_pid
    if _memo is not None:
        return _memo
    _memo = _read_memo_file()
    # Only the process that loaded the memo flushes at exit; a forked child
    # inherits the dict but must not race the parent on the file.
    _memo_pid = os.getpid()
    atexit.register(_flush_at_exit)
    return _memo


def _read_memo_file() -> dict[str, list]:
    try:
        data = json.loads(_MEMO_PATH.read_bytes())
    except (OSError, json.JSONDecodeError):
        return {}
    if data.get("recipe") != _RECIPE_VERSION:
        return {}
    return data.get("files", {})


def _flush_at_exit() -> None:
    if os.getpid() == _memo_pid:
        flush_memo()


def flush_memo() -> None:
    """Merge this process's new digests into the memo file.

    Merging (rather than overwriting) keeps entries another process wrote in
    the meantime; a lost race costs one re-digest, never a wrong stamp.
    """
    global _dirty
    with _lock:
        if _memo is None or _dirty == 0:
            return
        merged = _read_memo_file()
        merged.update(_memo)
        _dirty = 0
    payload = json.dumps({"recipe": _RECIPE_VERSION, "files": merged}).encode()
    try:
        _MEMO_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=f".{_MEMO_PATH.name}.", suffix=".tmp", dir=_MEMO_PATH.parent
        )
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp, _MEMO_PATH)
    except OSError as exc:
        logger.warning("content stamp memo not saved to %s: %s", _MEMO_PATH, exc)
