"""Shared HTTP + SPK helpers used by both `bodies/` and `probes/`."""

import asyncio
import logging
import re
import time
from pathlib import Path

import httpx
import spiceypy

logger = logging.getLogger(__name__)

_HREF_RE = re.compile(r'href="([^"?/][^"]*)"')


def list_naif_dir(client: httpx.Client, url: str, *, retry: bool = True) -> list[str]:
    """List Apache-style directory hrefs at `url`.

    NAIF and ESA both occasionally serve a 404 for a directory that succeeds
    on immediate retry (server-side cache miss / index regeneration). A single
    1-second retry catches these without masking persistently-missing dirs.
    Returns [] on persistent failure with a warning.
    """
    last_exc: httpx.HTTPError | None = None
    attempts = 2 if retry else 1
    for attempt in range(attempts):
        try:
            resp = client.get(url, timeout=60.0)
            resp.raise_for_status()
            return [h for h in _HREF_RE.findall(resp.text) if h not in {"..", "."}]
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(1.0)
    logger.warning("listing failed for %s: %s", url, last_exc)
    return []


def stream_to(
    client: httpx.Client, url: str, dest: Path, expected_size: int = 0
) -> None:
    """Stream `url` to `dest` atomically via `.part` rename.

    Skips the download when the file already exists with the expected size.
    """
    if dest.exists() and expected_size and dest.stat().st_size == expected_size:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url, timeout=600.0) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)
    tmp.replace(dest)


def head_sizes_async(urls: list[str], *, concurrency: int = 16) -> list[int]:
    """Fan out HEAD requests to fetch content-length for many URLs at once.

    Returns 0 for any URL whose HEAD fails. Spins up its own AsyncClient
    rather than borrowing the caller's sync client, since httpx clients
    aren't shared across loops.
    """
    if not urls:
        return []

    async def _run() -> list[int]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as ac:
            sem = asyncio.Semaphore(concurrency)

            async def one(url: str) -> int:
                async with sem:
                    try:
                        r = await ac.head(url)
                        r.raise_for_status()
                        return int(r.headers.get("content-length", 0))
                    except httpx.HTTPError:
                        return 0

            return await asyncio.gather(*(one(u) for u in urls))

    return asyncio.run(_run())


def spk_targets(path: Path) -> set[int]:
    """Unique NAIF target IDs in `path`.

    Uses spiceypy.spkobj rather than jplephem because the latter only handles
    SPK types 2/3/13; older missions (Viking, Helios, early Mariners, some
    Pioneer files) use type 1 modified-difference arrays which jplephem reads
    as damaged. Returns an empty set on read failure.
    """
    try:
        ids = spiceypy.spkobj(str(path))
    except spiceypy.exceptions.SpiceyError as exc:
        logger.warning("SPK open failed for %s: %s", path.name, exc)
        return set()
    return {int(naif) for naif in ids}
