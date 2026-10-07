"""Download the published catalogues that a manifest lists.

One provider covers one object class. Its manifest is
`constants/manifests/catalogues/<group>.yaml`, and that file records the reuse
terms of each catalogue.

Writes, below sources/catalogues/<group>/:
- <key>/<file>        the files of one catalogue, as published
- <key>/ReadMe        the CDS description, for a catalogue in the CDS archive
- <key>/record.json   the Zenodo record, for a Zenodo deposit
- metadata.json       the files, their URLs and the fetch date of each catalogue

A file is checked before it takes its name. An empty file fails. A CDS data
file is checked against the record count in its ReadMe. A Zenodo file is
checked against the MD5 in its record. CDS answers 403 to a User-Agent that
contains "bot".

A file is fetched again when its URL in the manifest changes. A file that the
manifest no longer names is deleted.

One failed catalogue does not stop the others. The provider then stays
incomplete and names the failed catalogues.
"""

import json
import logging
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from space_map_data.constants.manifests.catalogues import (
    Catalogue,
    CdsFiles,
    ZenodoFiles,
    load_catalogues,
)
from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.cds import CDS_URL, README, count_records, record_counts
from space_map_data.download.downloader import (
    DownloadError,
    Downloader,
    user_agent_without_bot,
)
from space_map_data.download.providers.catalogues.fetch import md5_of
from space_map_data.download.providers.three_d.resumable import download_resumable
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR

logger = logging.getLogger(__name__)

ZENODO_URL = "https://zenodo.org/api/records"
RECORD = "record.json"

_HTML_NAMES = (".html", ".htm")
# A byte range needs the file as the server stores it.
_AS_STORED = {"Accept-Encoding": "identity"}


@dataclass(frozen=True)
class Fetch:
    """One file to fetch, and the check that accepts it."""

    name: str
    url: str
    method: str = "GET"
    data: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    check: Callable[[Path], None] | None = None


class CatalogueDownloader(Downloader):
    group: str

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = SOURCES_CATALOGUES_DIR / self.group
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._cds_headers = {**_AS_STORED, "User-Agent": user_agent_without_bot(client)}

    def is_complete(self, limit: int | None) -> bool:
        if not super().is_complete(limit):
            return False
        fetched = self._fetched()
        return not any(
            _is_due(catalogue, fetched) for catalogue in load_catalogues(self.group)
        )

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        catalogues = load_catalogues(self.group)
        fetched = self._fetched()
        due = [catalogue for catalogue in catalogues if _is_due(catalogue, fetched)]
        # Nothing is due on a forced run. Then every catalogue is checked
        # against the disk.
        selected = due or catalogues
        records = {
            catalogue.key: fetched[catalogue.key]
            for catalogue in catalogues
            if catalogue.key in fetched
        }
        failed: list[str] = []
        for catalogue in selected:
            previous = fetched.get(catalogue.key)
            again = previous is not None and _has_lapsed(catalogue, previous)
            try:
                records[catalogue.key] = self._fetch_catalogue(
                    catalogue, previous, again
                )
            except (DownloadError, httpx.HTTPError) as exc:
                logger.error("%s/%s failed: %s", self.group, catalogue.key, exc)
                failed.append(catalogue.key)

        self._save_metadata(
            f"manifests/catalogues/{self.group}.yaml",
            len(catalogues) - len(failed),
            complete=not failed,
            catalogues=records,
        )
        if failed:
            raise DownloadError(
                f"{len(failed)} of {len(catalogues)} catalogues failed: "
                + ", ".join(failed)
            )

    def _fetched(self) -> dict[str, dict]:
        """The catalogue records of the last run."""
        if not self.metadata_file.exists():
            return {}
        return json.loads(self.metadata_file.read_text()).get("catalogues", {})

    def _fetch_catalogue(
        self, catalogue: Catalogue, previous: dict | None, again: bool
    ) -> dict:
        directory = self.out_dir / catalogue.key
        directory.mkdir(parents=True, exist_ok=True)
        known = previous["files"] if previous else {}
        items = self._fetches(catalogue, directory)
        wanted = [
            item
            for item in items
            if again
            or not (directory / item.name).exists()
            or known.get(item.name, {}).get("url") != item.url
        ]
        # A form answer and the files it makes share one session.
        if wanted and any(item.method == "POST" for item in items):
            wanted = items
        for item in wanted:
            self._fetch_file(item, directory / item.name)
        files = {
            item.name: {
                "url": item.url,
                "bytes": (directory / item.name).stat().st_size,
            }
            for item in items
        }
        _prune(directory, files)
        record: dict[str, object] = {
            "fetched_at": (
                previous["fetched_at"]
                if previous and not wanted
                else datetime.now(timezone.utc).isoformat()
            ),
            "files": files,
        }
        if catalogue.zenodo is not None:
            record["zenodo"] = catalogue.zenodo.record
        return record

    def _fetch_file(self, item: Fetch, dest: Path) -> None:
        fetched = download_resumable(
            self.client,
            item.url,
            dest,
            method=item.method,
            data=item.data or None,
            headers=item.headers or _AS_STORED,
            replace=True,
            html=item.name.endswith(_HTML_NAMES),
            check=_accept(item),
        )
        if not fetched:
            raise DownloadError(f"{item.url}: the fetch failed")

    def _fetches(self, catalogue: Catalogue, directory: Path) -> list[Fetch]:
        items: list[Fetch] = []
        if catalogue.cds is not None:
            items += self._cds_fetches(catalogue.cds, directory)
        if catalogue.zenodo is not None:
            items += self._zenodo_fetches(catalogue.zenodo, directory)
        items += [
            Fetch(remote.name, remote.url, remote.method, dict(remote.data))
            for remote in catalogue.urls
        ]
        return items

    def _cds_fetches(self, cds: CdsFiles, directory: Path) -> list[Fetch]:
        base = f"{CDS_URL}/{cds.catalogue}"
        self._fetch_file(
            Fetch(README, f"{base}/{README}", headers=self._cds_headers),
            directory / README,
        )
        listed = record_counts(
            (directory / README).read_text(encoding="utf-8", errors="replace")
        )
        items: list[Fetch] = []
        for name in cds.files:
            expected = listed.get(name.removesuffix(".gz"))
            # Only the fixed-width data files are one record for each line.
            if expected is None or not name.removesuffix(".gz").endswith(".dat"):
                logger.debug("%s/%s: no record count to check", cds.catalogue, name)
                check = None
            else:
                check = _records_check(name, expected)
            items.append(
                Fetch(name, f"{base}/{name}", headers=self._cds_headers, check=check)
            )
        return items

    def _zenodo_fetches(self, zenodo: ZenodoFiles, directory: Path) -> list[Fetch]:
        response = self.client.get(f"{ZENODO_URL}/{zenodo.record}")
        if response.status_code in (403, 404, 410):
            raise DownloadError(
                f"HTTP {response.status_code} for Zenodo {zenodo.record}"
            )
        response.raise_for_status()
        try:
            files = {entry["key"]: entry for entry in response.json()["files"]}
            wanted = zenodo.files or tuple(files)
            items = [
                Fetch(
                    name,
                    files[name]["links"]["self"],
                    check=_md5_check(files[name]["checksum"].removeprefix("md5:")),
                )
                for name in wanted
            ]
        except (ValueError, KeyError, TypeError) as exc:
            raise DownloadError(
                f"Zenodo {zenodo.record}: unexpected record, {exc!r}"
            ) from exc
        (directory / RECORD).write_bytes(response.content)
        return items


def _is_due(catalogue: Catalogue, fetched: dict[str, dict]) -> bool:
    """True when a catalogue is new, changed in the manifest, or lapsed."""
    record = fetched.get(catalogue.key)
    if record is None:
        return True
    files = record["files"]
    for name, url in _named_urls(catalogue).items():
        if name not in files or url not in (None, files[name]["url"]):
            return True
    if catalogue.zenodo is not None and record.get("zenodo") != catalogue.zenodo.record:
        return True
    return _has_lapsed(catalogue, record)


def _named_urls(catalogue: Catalogue) -> dict[str, str | None]:
    """The URL of each file the entry names. Zenodo gives its URLs later."""
    urls: dict[str, str | None] = {remote.name: remote.url for remote in catalogue.urls}
    if catalogue.cds is not None:
        base = f"{CDS_URL}/{catalogue.cds.catalogue}"
        urls.update({name: f"{base}/{name}" for name in catalogue.cds.files})
    if catalogue.zenodo is not None:
        urls.update(dict.fromkeys(catalogue.zenodo.files))
    return urls


def _has_lapsed(catalogue: Catalogue, record: dict) -> bool:
    if catalogue.refresh_days is None:
        return False
    age = datetime.now(timezone.utc) - datetime.fromisoformat(record["fetched_at"])
    return age >= timedelta(days=catalogue.refresh_days)


def _prune(directory: Path, files: dict[str, dict]) -> None:
    """Delete the files of a catalogue that its manifest entry no longer names."""
    kept = {README, RECORD, *files}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.relative_to(directory).as_posix() not in kept:
            logger.info("Deleting %s, the manifest no longer names it", path)
            path.unlink()


def _accept(item: Fetch) -> Callable[[Path], None]:
    """The check of one file, with an unreadable file turned into a failure."""

    def check(path: Path) -> None:
        if path.stat().st_size == 0:
            raise DownloadError(f"{item.name}: the file is empty")
        if item.check is None:
            return
        try:
            item.check(path)
        except (OSError, EOFError, zlib.error) as exc:
            raise DownloadError(f"{item.name}: cannot read the file, {exc}") from exc

    return check


def _records_check(name: str, expected: int) -> Callable[[Path], None]:
    def check(path: Path) -> None:
        found = count_records(path, name)
        if found == expected:
            return
        # Some ReadMes do not count the headlines and the blank lines.
        if count_records(path, name, data_only=True) != expected:
            raise DownloadError(f"{name}: {found} records, the ReadMe lists {expected}")

    return check


def _md5_check(expected: str) -> Callable[[Path], None]:
    def check(path: Path) -> None:
        found = md5_of(path)
        if found != expected:
            raise DownloadError(f"MD5 {found}, Zenodo lists {expected}")

    return check


class GalaxyCataloguesDownloader(CatalogueDownloader):
    name = PROVIDERS.GALAXY_CATALOGUES
    group = "galaxies"


class StarClusterCataloguesDownloader(CatalogueDownloader):
    name = PROVIDERS.STAR_CLUSTER_CATALOGUES
    group = "star-clusters"


class NebulaCataloguesDownloader(CatalogueDownloader):
    name = PROVIDERS.NEBULA_CATALOGUES
    group = "nebulae"


class StellarRemnantCataloguesDownloader(CatalogueDownloader):
    name = PROVIDERS.STELLAR_REMNANT_CATALOGUES
    group = "stellar-remnants"


class BlackHoleCataloguesDownloader(CatalogueDownloader):
    name = PROVIDERS.BLACK_HOLE_CATALOGUES
    group = "black-holes"


class TransientCataloguesDownloader(CatalogueDownloader):
    name = PROVIDERS.TRANSIENT_CATALOGUES
    group = "transients"
