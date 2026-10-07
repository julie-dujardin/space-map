"""Fetch the texture source files that the manifests give a link for.

Most maps are staged by hand from a browser. The multi-gigabyte mosaics carry
their direct link instead, so a fresh machine can rebuild the tile pyramids
and a dropped connection resumes rather than restarts. A link may also be a zip
archive that holds the file, as for the 3,960 quads of the Mars CTX mosaic.

Writes to the entry's own source directory:
    sources/textures/<manifest dir>/<file>
    sources/textures/files-metadata.json
"""

import json
import logging
import os
import threading
import time
import zipfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO

import httpx

from space_map_data.constants.manifests.textures import (
    MANIFESTS_DIR,
    layer_files,
    load_entries,
    source_layers,
)
from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import (
    DownloadError,
    Downloader,
    user_agent_without_bot,
)
from space_map_data.utils.paths import CACHE_DIR, SOURCES_TEXTURES_DIR

logger = logging.getLogger(__name__)

CHUNK_BYTES = 8 << 20
MAX_ATTEMPTS = 8
RETRY_DELAY_SECONDS = 10.0
# Each host tried so far serves about 25 MB/s per connection, whatever the
# count, so this is the speed-up; more would lean on one university server.
WORKERS = 4
# Files between two saves of the record, so a long run killed midway keeps it.
SAVE_EVERY = 25
# Bytes written between two flushes to disk.
SYNC_BYTES = 64 << 20

# Archives land on local disk first. On the downloads mount each one would
# cross the network three times: written, read back to unpack, written again.
ARCHIVE_DIR = CACHE_DIR / "texture-archives"


def write_synced(chunks: Iterable[bytes], out: BinaryIO) -> int:
    """Write ``chunks``, flushing to disk as it goes; return the byte count.

    Nothing slows a writer that outruns a network mount: the unwritten data
    piles up in memory, by gigabytes for a file this size, and a run under a
    memory cap is killed for it. Flushed pages are also dropped from the
    cache, since nothing here reads them back.
    """
    written = pending = 0
    for chunk in chunks:
        out.write(chunk)
        written += len(chunk)
        pending += len(chunk)
        if pending >= SYNC_BYTES:
            out.flush()
            os.fdatasync(out.fileno())
            os.posix_fadvise(out.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
            pending = 0
    return written


class TextureFilesDownloader(Downloader):
    name = PROVIDERS.TEXTURE_FILES
    # sources/textures/ also holds the hand-staged trees; keep clear of them.
    metadata_name = "files-metadata.json"

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_TEXTURES_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)
        # NASA's PDS file host answers 403 to a User-Agent that contains "bot".
        self._headers = {"User-Agent": user_agent_without_bot(client)}

    def _targets(self) -> list[tuple[str, Path]]:
        return [
            (url, entry["_source_dir"] / name)
            for entry in load_entries(self.out_dir)
            if not entry.get("skip")
            for layer in source_layers(entry)
            for name, url in layer_files(layer)
            if url
        ]

    def _key(self, path: Path) -> str:
        return str(path.relative_to(self.out_dir))

    def _recorded(self) -> dict[str, int]:
        if not self.metadata_file.exists():
            return {}
        return json.loads(self.metadata_file.read_text()).get("files") or {}

    def is_complete(self, limit: int | None) -> bool:
        # Keyed on the manifest rather than a past run's flag, so a link added
        # later is still fetched.
        sizes = self._recorded()
        return bool(sizes) and all(
            self._key(path) in sizes and path.exists() for _, path in self._targets()
        )

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        targets = self._targets()
        sizes = self._recorded()
        failed: list[str] = []
        lock = threading.Lock()

        def fetch(target: tuple[str, Path]) -> None:
            url, path = target
            key = self._key(path)
            try:
                # A file is only ever renamed into place whole, so one already
                # recorded needs no request.
                if not (key in sizes and path.exists()):
                    size = self._fetch(url, path)
                    with lock:
                        sizes[key] = size
                        if len(sizes) % SAVE_EVERY == 0:
                            self._save(sizes)
            except (httpx.HTTPError, DownloadError, zipfile.BadZipFile, OSError) as e:
                logger.error("%s: %s", path.name, e)
                with lock:
                    failed.append(path.name)

        with ThreadPoolExecutor(WORKERS) as pool:
            list(pool.map(fetch, targets))
        self._save(sizes)
        if failed:
            shown = ", ".join(failed[:10])
            raise DownloadError(
                f"{len(failed)} of {len(targets)} texture files not fetched: {shown}"
            )

    def _save(self, sizes: dict[str, int]) -> None:
        self._save_metadata(str(MANIFESTS_DIR), len(sizes), files=dict(sizes))

    def _fetch(self, url: str, path: Path) -> int:
        """Bring ``path`` up to the remote file; return its size in bytes."""
        if url.endswith(".zip") and path.suffix != ".zip":
            return self._fetch_from_archive(url, path)
        return self._download(url, path)

    def _fetch_from_archive(self, url: str, path: Path) -> int:
        """Unpack ``path`` from the zip archive at ``url``, then drop the
        archive."""
        if path.exists():
            return path.stat().st_size
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        archive_path = ARCHIVE_DIR / url.rsplit("/", 1)[-1]
        self._download(url, archive_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        with zipfile.ZipFile(archive_path) as archive:
            member = next(
                (m for m in archive.namelist() if m.rsplit("/", 1)[-1] == path.name),
                None,
            )
            if member is None:
                raise DownloadError(f"{archive_path.name} holds no {path.name}")
            with archive.open(member) as src, part.open("wb") as dst:
                write_synced(iter(lambda: src.read(CHUNK_BYTES), b""), dst)
        part.rename(path)
        archive_path.unlink()
        logger.info("Unpacked %s (%.2f GiB)", path.name, path.stat().st_size / 2**30)
        return path.stat().st_size

    def _download(self, url: str, path: Path) -> int:
        """Fetch ``url`` to ``path``, resuming a partial file."""
        head = self._head(url)
        length = head.headers.get("Content-Length")
        if length is None:
            # Without a size a cut-off file cannot be told from a whole one.
            raise DownloadError(f"{path.name}: the host states no size")
        total = int(length)
        validator = head.headers.get("ETag") or head.headers.get("Last-Modified")

        if path.exists():
            if path.stat().st_size != total:
                # Never overwrite gigabytes on a size mismatch alone.
                logger.warning(
                    "%s is %d bytes locally, %d upstream; delete it to re-fetch",
                    path.name,
                    path.stat().st_size,
                    total,
                )
            return path.stat().st_size

        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        stamp = path.with_name(path.name + ".part.validator")
        # A partial file from another upstream version cannot be resumed.
        if part.exists() and (
            not validator or not stamp.exists() or stamp.read_text() != validator
        ):
            part.unlink()
        if validator:
            stamp.write_text(validator)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                self._stream(url, part, total, validator)
            except httpx.TransportError as e:
                if attempt == MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "%s: %s, resuming (attempt %d)", path.name, e, attempt + 1
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            break

        if part.stat().st_size != total:
            raise DownloadError(
                f"{path.name}: got {part.stat().st_size} of {total} bytes"
            )
        part.rename(path)
        stamp.unlink(missing_ok=True)
        logger.info("Fetched %s (%.2f GiB)", path.name, total / 2**30)
        return total

    def _head(self, url: str) -> httpx.Response:
        """A dropped connection on this one request must not cost the file its
        turn: over thousands of files a few always drop."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                head = self.client.head(url, headers=self._headers)
                head.raise_for_status()
                return head
            except httpx.TransportError:
                if attempt == MAX_ATTEMPTS:
                    raise
                time.sleep(RETRY_DELAY_SECONDS)
        raise AssertionError("unreachable")

    def _stream(self, url: str, part: Path, total: int, validator: str | None) -> None:
        have = part.stat().st_size if part.exists() else 0
        if have >= total:
            return
        headers = dict(self._headers)
        if have:
            headers["Range"] = f"bytes={have}-"
            if validator:
                headers["If-Range"] = validator
        with self.client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            # A 200 answers the whole file: the range was refused or stale.
            resumed = resp.status_code == 206
            if have:
                logger.info(
                    "%s: %s at %.2f of %.2f GiB",
                    part.name,
                    "resuming" if resumed else "restarting",
                    have / 2**30 if resumed else 0.0,
                    total / 2**30,
                )
            with part.open("ab" if resumed else "wb") as f:
                write_synced(resp.iter_bytes(CHUNK_BYTES), f)
