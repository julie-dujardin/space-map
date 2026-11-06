"""Shared code for the dust-map downloads.

A map is a few large files of a Zenodo record, a Dataverse dataset or a plain
server. `DustMapDownloader` lists the files of the host, fetches the wanted
ones as published and checks the size and the MD5 before a file takes its name.
A file on disk stays when it has the listed size and the listed MD5. A normal
run takes the MD5 from the last run, so it reads no large file. A forced run
hashes the disk, and so repairs damaged bytes. A host with no MD5, such as the
Planck server, gives the size only. A file that the provider no longer names is
deleted.

Writes, below the out_dir of the provider:
- the wanted files, under the name of the host
- record.json  the listing of the host, when it has one
- metadata.json  the files with size and MD5, the sources, the licence the host
  states, TERMS

A run with a record limit fetches no file and ends as skipped. The first fill
comes from the CLI.
"""

import json
import logging
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TypedDict

import httpx

from space_map_data.download.downloader import (
    Downloader,
    DownloadError,
    DownloadSkipped,
)
from space_map_data.download.providers.catalogues.fetch import md5_check, md5_of
from space_map_data.download.providers.three_d.resumable import (
    AS_STORED,
    download_resumable,
)
from space_map_data.download.zenodo import fetch_record
from space_map_data.utils.files import SYNC_BYTES

logger = logging.getLogger(__name__)

DATAVERSE_URL = "https://dataverse.harvard.edu/api"
RECORD = "record.json"


class Quote(TypedDict):
    url: str
    text: str


class Terms(TypedDict):
    """The reuse terms of a map, as the other providers record them."""

    license: str | None
    terms_url: str
    distribution: str
    note: str
    quotes: list[Quote]


@dataclass(frozen=True)
class RemoteFile:
    name: str
    url: str
    size: int
    md5: str | None


@dataclass(frozen=True)
class Listing:
    """The files of a host by name, the licence it states and its own records."""

    files: dict[str, RemoteFile]
    license: str | None
    # The answers of the host, by the path below the out_dir that keeps them.
    records: dict[str, bytes] = field(default_factory=dict)


def zenodo_listing(client: httpx.Client, number: int) -> Listing:
    record = fetch_record(client, number)
    sizes = record.sizes()
    files = [record.file(name) for name in record.entries]
    return Listing(
        {f.name: RemoteFile(f.name, f.url, sizes[f.name], f.md5) for f in files},
        record.license(),
        {RECORD: record.raw},
    )


def dataverse_url(doi: str) -> str:
    """The API address of the latest published version of a dataset."""
    path = f"{DATAVERSE_URL}/datasets/:persistentId/versions/:latest-published"
    return str(httpx.URL(path, params={"persistentId": f"doi:{doi}"}))


def dataverse_listing(client: httpx.Client, doi: str) -> Listing:
    response = client.get(dataverse_url(doi), timeout=120.0)
    if response.status_code != 200:
        raise DownloadError(f"HTTP {response.status_code} for Dataverse {doi}")
    try:
        body = response.json()["data"]
        files = {}
        for f in body["files"]:
            data = f["dataFile"]
            checksum = data.get("checksum") or {}
            md5 = data.get("md5") or (
                checksum["value"] if checksum.get("type") == "MD5" else None
            )
            files[f["label"]] = RemoteFile(
                f["label"],
                f"{DATAVERSE_URL}/access/datafile/{data['id']}",
                int(data["filesize"]),
                md5,
            )
        stated = body.get("license")
        license = stated["name"] if stated is not None else None
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise DownloadError(f"Dataverse {doi}: unexpected record") from error
    return Listing(files, license, {RECORD: response.content})


def head_file(client: httpx.Client, url: str, name: str, md5: str | None) -> RemoteFile:
    """A file of a plain server. The server gives the size."""
    response = client.head(url, headers=AS_STORED, timeout=120.0)
    if response.status_code != 200:
        raise DownloadError(f"HTTP {response.status_code} for {url}")
    try:
        size = int(response.headers["content-length"])
    except (KeyError, ValueError) as error:
        raise DownloadError(f"{url}: no Content-Length") from error
    return RemoteFile(name, url, size, md5)


class DustMapDownloader(Downloader):
    """Fetches the `wanted` files of one map."""

    directory: Path
    page_url: str
    wanted: tuple[str, ...]
    # The addresses of the hosts that list the files. A change fetches again.
    sources: tuple[str, ...]
    # The licence text the host must state. A change stops the run.
    expected_license: str | None
    terms: Terms
    # Files below the directory that the host listing does not name.
    keep: frozenset[str] = frozenset()

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = self.directory
        self.out_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def listing(self) -> Listing: ...

    def is_complete(self, limit: int | None) -> bool:
        if not super().is_complete(limit):
            return False
        meta = json.loads(self.metadata_file.read_text())
        return all(meta.get(key) == value for key, value in self._identity().items())

    def download(
        self, limit: int | None = None, *, force: bool = False, **kwargs: object
    ) -> None:
        listing = self.listing()
        if listing.license != self.expected_license:
            raise DownloadError(
                f"{self.page_url}: the licence is {listing.license!r},"
                f" it was {self.expected_license!r}"
            )
        missing = sorted(set(self.wanted) - set(listing.files))
        if missing:
            raise DownloadError(f"{self.page_url}: no files {', '.join(missing)}")
        files = [listing.files[name] for name in self.wanted]
        recorded = self._recorded_md5s()
        todo = [file for file in files if not self._is_stored(file, recorded, force)]
        if todo and limit is not None:
            raise DownloadSkipped(
                f"{self.name}: {len(todo)} files to fetch, a run with a record limit"
                " fetches none"
            )
        for file in todo:
            self._fetch(file)
        self._prune(listing)
        for path, content in listing.records.items():
            (self.out_dir / path).write_bytes(content)
        self._save_metadata(
            self.page_url,
            len(self.wanted),
            complete=True,
            files=[asdict(file) for file in files],
            license_stated=listing.license,
            **self._identity(),
        )

    def _identity(self) -> dict[str, object]:
        """What the metadata records about the provider. A change fetches again."""
        return {
            "wanted": list(self.wanted),
            "sources": list(self.sources),
            "terms": self.terms,
        }

    def _recorded_md5s(self) -> dict[str, str | None]:
        """The MD5 of each file as the last run checked it."""
        if not self.metadata_file.exists():
            return {}
        files = json.loads(self.metadata_file.read_text()).get("files", [])
        return {file["name"]: file["md5"] for file in files}

    def _is_stored(
        self, file: RemoteFile, recorded: dict[str, str | None], force: bool
    ) -> bool:
        """Whether the disk holds the bytes that the host lists now."""
        dest = self.out_dir / file.name
        if not dest.exists() or dest.stat().st_size != file.size:
            return False
        if file.md5 is None:
            # Nothing to compare, so only a forced run can repair the bytes.
            stored = file.name in recorded and not force
            if stored:
                logger.info(
                    "%s: %s is stored, the host lists no MD5 and the size matches",
                    self.name,
                    file.name,
                )
            return stored
        if not force and recorded.get(file.name) == file.md5:
            logger.info("%s: %s is stored, as at the last run", self.name, file.name)
            return True
        if md5_of(dest) == file.md5:
            logger.info("%s: %s is stored, its MD5 matches", self.name, file.name)
            return True
        return False

    def _fetch(self, file: RemoteFile) -> None:
        dest = self.out_dir / file.name
        if not download_resumable(
            self.client,
            file.url,
            dest,
            headers=AS_STORED,
            replace=dest.exists(),
            check=_accept(file),
            sync_bytes=SYNC_BYTES,
        ):
            raise DownloadError(f"{file.url}: the fetch failed")

    def _prune(self, listing: Listing) -> None:
        """Delete the files that the provider no longer names."""
        kept = {*self.wanted, *listing.records, *self.keep, self.metadata_name}
        for path in sorted(self.out_dir.rglob("*")):
            if path.is_file() and path.relative_to(self.out_dir).as_posix() not in kept:
                logger.info("Deleting %s, the provider no longer names it", path)
                path.unlink()


def _accept(file: RemoteFile) -> Callable[[Path], None]:
    """The check of a fetched file: the listed size and, when listed, the MD5."""
    md5 = md5_check(file.name, file.md5) if file.md5 is not None else None

    def check(path: Path) -> None:
        if path.stat().st_size != file.size:
            raise DownloadError(
                f"{file.name}: {path.stat().st_size} bytes, the host lists {file.size}"
            )
        if md5 is not None:
            md5(path)

    return check
