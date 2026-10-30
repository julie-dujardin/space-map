"""Control of the glibc heap: the arena count and the return of free pages.

glibc gives each thread an arena, and an arena keeps the memory that its
threads free. A run with many threads then holds memory that no object uses.
Without glibc these calls do nothing.
"""

import ctypes
import gc
import logging

logger = logging.getLogger(__name__)

# From malloc.h.
_M_ARENA_MAX = -8

_LIBC = ctypes.CDLL(None)
_MALLOPT = getattr(_LIBC, "mallopt", None)
_MALLOC_TRIM = getattr(_LIBC, "malloc_trim", None)


def limit_arenas(count: int) -> None:
    """Let at most `count` arenas serve all threads.

    glibc sets its own limit when it has more than 8 arenas. After that, this
    call has no effect.
    """
    if _MALLOPT is not None:
        _MALLOPT(_M_ARENA_MAX, count)


def release_free_memory(step: str) -> None:
    """Collect garbage, give the free heap pages back, and log the anon size."""
    gc.collect()
    if _MALLOC_TRIM is None:
        return
    before = _rss_anon_gb()
    _MALLOC_TRIM(0)
    logger.info("memory after %s: anon %.1f -> %.1f GB", step, before, _rss_anon_gb())


def _rss_anon_gb() -> float:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("RssAnon:"):
                return int(line.split()[1]) / 1024**2
    return 0.0
