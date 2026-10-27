"""Write the answer to one query to disk, count the answers of a QLever query,
and hash a file."""

import gzip
import hashlib
import logging
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from space_map_data.download.downloader import DownloadError

logger = logging.getLogger(__name__)

ATTEMPTS = 4
RETRY_WAIT_SECONDS = 30.0
CHUNK_BYTES = 1 << 20
# A slow server gets ten minutes between two chunks.
TIMEOUT = httpx.Timeout(60.0, read=600.0)
_RETRIED = (429, 500, 502, 503, 504)
QLEVER_URL = "https://qlever.dev/api/wikidata"
QLEVER_TSV = {"Accept": "text/tab-separated-values"}


def qlever_count(client: httpx.Client, query: str) -> int:
    """The number that a QLever query of one COUNT returns."""
    response = client.post(
        QLEVER_URL, data={"query": query}, headers=QLEVER_TSV, timeout=120.0
    )
    response.raise_for_status()
    return int(response.text.split()[1])


def download_item_list(
    client: httpx.Client,
    dest: Path,
    count_query: str,
    items_query: str,
    floor: int,
    read: Callable[[Path], object],
) -> int:
    """Write the rows of a QLever list of Wikidata items to `dest` and return
    their count. Fails when QLever counts fewer than `floor` items, when the
    rows are not as many as the count, or when `read` raises ValueError on
    them."""
    counted = qlever_count(client, count_query)
    if counted < floor:
        raise DownloadError(f"QLever counts {counted} items, at least {floor} expected")

    def check(part: Path, lines: int) -> None:
        if lines - 1 != counted:
            raise DownloadError(
                f"QLever returned {lines - 1} items and counts {counted}"
            )
        try:
            read(part)
        except ValueError as error:
            raise DownloadError(f"{part.name}: {error}") from error

    post_lines_gz(
        client,
        QLEVER_URL,
        dest,
        data={"query": items_query, "action": "tsv_export"},
        headers=QLEVER_TSV,
        check=check,
    )
    logger.info("%s: %d items", dest.name, counted)
    return counted


def post_lines_gz(
    client: httpx.Client,
    url: str,
    dest: Path,
    *,
    data: Mapping[str, str],
    headers: Mapping[str, str] | None = None,
    check: Callable[[Path, int], None],
) -> int:
    """POST a query and write the answer to `dest` with gzip.

    `check` gets the partial file and its line count before the file becomes
    `dest`. When it raises, the partial file is removed and `dest` stays as it
    was. Return the line count.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, ATTEMPTS + 1):
        try:
            lines = _stream_gz(client, url, part, data, headers)
            break
        except httpx.HTTPError as exc:
            logger.warning(
                "%s: %s, attempt %d of %d", url, type(exc).__name__, attempt, ATTEMPTS
            )
            if attempt < ATTEMPTS:
                time.sleep(RETRY_WAIT_SECONDS)
    else:
        raise DownloadError(f"{url}: no complete answer in {ATTEMPTS} attempts")
    try:
        check(part, lines)
    except DownloadError:
        part.unlink()
        raise
    part.replace(dest)
    return lines


def _stream_gz(
    client: httpx.Client,
    url: str,
    part: Path,
    data: Mapping[str, str],
    headers: Mapping[str, str] | None,
) -> int:
    lines = 0
    with client.stream(
        "POST", url, data=data, headers=headers, timeout=TIMEOUT
    ) as response:
        if response.status_code in _RETRIED:
            response.raise_for_status()
        if response.status_code >= 400:
            raise DownloadError(f"HTTP {response.status_code} for {url}")
        with gzip.open(part, "wb", compresslevel=6) as file:
            for chunk in response.iter_bytes(CHUNK_BYTES):
                file.write(chunk)
                lines += chunk.count(b"\n")
    return lines


def md5_of(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as file:
        while chunk := file.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
