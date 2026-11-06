"""The record of a Zenodo deposit: its files, their MD5, sizes and licence.

A caller reads only the fields it uses, so a record that lacks a size or states its
licence in another form fails only the callers that check them.
"""

from dataclasses import dataclass

import httpx

from space_map_data.download.downloader import DownloadError

ZENODO_URL = "https://zenodo.org/api/records"


@dataclass(frozen=True)
class ZenodoFile:
    name: str
    url: str
    md5: str


@dataclass(frozen=True)
class ZenodoRecord:
    number: int
    # The entry of each file by name, as received.
    entries: dict[str, dict]
    metadata: dict
    # The answer of Zenodo as received.
    raw: bytes

    def file(self, name: str) -> ZenodoFile:
        if name not in self.entries:
            raise DownloadError(f"Zenodo {self.number}: no file {name}")
        entry = self.entries[name]
        try:
            md5 = entry["checksum"].removeprefix("md5:")
            return ZenodoFile(name, entry["links"]["self"], md5)
        except (KeyError, TypeError, AttributeError) as error:
            raise DownloadError(f"Zenodo {self.number}: unexpected {name}") from error

    def sizes(self) -> dict[str, int]:
        """The size of every file. A record without them is refused."""
        try:
            return {name: int(entry["size"]) for name, entry in self.entries.items()}
        except (KeyError, TypeError, ValueError) as error:
            raise DownloadError(f"Zenodo {self.number}: unexpected sizes") from error

    def license(self) -> str | None:
        """The id of the licence that the record states, such as `cc-by-4.0`. A
        licence in another form is refused."""
        try:
            stated = self.metadata.get("license")
            return stated["id"] if stated is not None else None
        except (KeyError, TypeError, AttributeError) as error:
            raise DownloadError(f"Zenodo {self.number}: unexpected licence") from error


def fetch_record(client: httpx.Client, number: int) -> ZenodoRecord:
    response = client.get(f"{ZENODO_URL}/{number}", timeout=120.0)
    if response.status_code != 200:
        raise DownloadError(f"HTTP {response.status_code} for Zenodo {number}")
    try:
        body = response.json()
        entries = {entry["key"]: entry for entry in body["files"]}
        metadata = body.get("metadata") or {}
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise DownloadError(f"Zenodo {number}: unexpected record") from error
    return ZenodoRecord(number, entries, metadata, response.content)
