"""Range-resume file download shared by the shape-model providers.

Sized for the slow backup uplink: kill-safe (``.part`` + Range), sequential
callers, generous retries on transient errors.
"""

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CHUNK = 1 << 16
RETRIES = 5
RETRY_WAIT_SECONDS = 30.0


def download_resumable(client: httpx.Client, url: str, dest: Path) -> bool:
    """Fetch ``url`` → ``dest``. Returns False on a non-retryable failure."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    part = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Validator sidecar: resuming across a server-side regeneration of the
    # same URL stitches two file generations together (observed with DAMIT's
    # monthly dump). If-Range makes the server send the full body instead.
    meta = part.with_suffix(part.suffix + ".meta")

    for attempt in range(1, RETRIES + 1):
        offset = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        if offset and meta.exists():
            headers["If-Range"] = meta.read_text().strip()
        try:
            with client.stream("GET", url, headers=headers, timeout=120.0) as resp:
                if resp.status_code == 416:  # past EOF: we already have every byte
                    break
                resp.raise_for_status()
                # Routers intercept dead uplinks with a 200 text/html error
                # page; no model file is HTML, so retry rather than save it.
                ctype = resp.headers.get("content-type", "")
                if "text/html" in ctype:
                    raise httpx.TransportError(
                        f"text/html response (captive portal?): {ctype}"
                    )
                if resp.status_code != 206:
                    offset = (
                        0  # full body: no Range, server ignored it, or file changed
                    )
                validator = resp.headers.get("etag") or resp.headers.get(
                    "last-modified"
                )
                if validator and not offset:
                    meta.write_text(validator)
                done = offset
                started = time.monotonic()
                with part.open("ab" if offset else "wb") as fh:
                    for chunk in resp.iter_bytes(CHUNK):
                        fh.write(chunk)
                        done += len(chunk)
                rate = (done - offset) / max(time.monotonic() - started, 0.01) / 1024
                logger.info(
                    "got %s (%.1f MiB, %.0f KiB/s)", dest.name, done / 2**20, rate
                )
            break
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403, 404):
                logger.error(
                    "FAILED %s: HTTP %s — source URL needs fixing",
                    url,
                    e.response.status_code,
                )
                return False
            logger.warning("attempt %d/%d failed for %s: %s", attempt, RETRIES, url, e)
        except httpx.HTTPError as e:
            logger.warning("attempt %d/%d failed for %s: %s", attempt, RETRIES, url, e)
        if attempt == RETRIES:
            logger.error("FAILED %s after %d attempts", url, RETRIES)
            return False
        time.sleep(RETRY_WAIT_SECONDS)

    if part.exists():
        part.rename(dest)
    meta.unlink(missing_ok=True)
    return True
