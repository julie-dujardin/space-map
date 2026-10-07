"""Tests for the CDS star-catalogue downloader."""

import gzip
import json

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import cds
from space_map_data.download.providers.stars.cds import (
    CDS_URL,
    CDSStarCataloguesDownloader,
    count_records,
    record_counts,
)

README = """I/311               Hipparcos, the New Reduction       (van Leeuwen, 2007)
================================================================================
File Summary:
--------------------------------------------------------------------------------
 FileName   Lrecl  Records   Explanations
--------------------------------------------------------------------------------
ReadMe         80        .   This file
hip2.dat      276        3   The Astrometric Catalogue
                              (corrected version)
hip7p.dat     129        2   Seven-parameter solutions
notes.doc      97        1
--------------------------------------------------------------------------------

See also:
 I/239 : The Hipparcos and Tycho Catalogues (ESA 1997)

Byte-by-byte Description of file: hip2.dat
--------------------------------------------------------------------------------
   1-  6  I6    ---      HIP     Hipparcos identifier
"""

FILES = {
    "I/311/ReadMe": README.encode(),
    "I/311/hip2.dat.gz": gzip.compress(b"a\nb\nc\n"),
    "I/311/hip7p.dat": b"a\nb\n",
    "I/311/notes.doc.gz": gzip.compress(b"free text\n"),
}


@pytest.fixture
def downloader(tmp_path, monkeypatch):
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert "bot" not in request.headers["User-Agent"]
        path = str(request.url).removeprefix(CDS_URL + "/")
        requested.append(path)
        if path not in FILES:
            return httpx.Response(404)
        return httpx.Response(200, content=FILES[path])

    monkeypatch.setattr(cds, "OUT_DIR", tmp_path)
    monkeypatch.setattr(
        cds, "CATALOGUES", {"I/311": ("hip2.dat.gz", "hip7p.dat", "notes.doc.gz")}
    )
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": "space-map-bot/0.1 (a@b.test)"},
    )
    return CDSStarCataloguesDownloader(client), requested


class TestReadMe:
    """Record counts from the `File Summary` block."""

    def test_counts_only_the_summary_rows(self):
        assert record_counts(README) == {"hip2.dat": 3, "hip7p.dat": 2, "notes.doc": 1}

    def test_counts_records_in_plain_and_gzip_files(self):
        assert count_records(b"a\nb\n", "a.dat") == 2
        assert count_records(gzip.compress(b"a\nb\nc\n"), "a.dat.gz") == 3


class TestDownload:
    """Files land under the catalogue path, checked against the ReadMe."""

    def test_mirrors_the_catalogue_path(self, downloader, tmp_path):
        dl, _ = downloader
        dl.download()
        assert (tmp_path / "I/311/hip2.dat.gz").read_bytes() == FILES[
            "I/311/hip2.dat.gz"
        ]
        assert (tmp_path / "I/311/ReadMe").exists()
        meta = json.loads(dl.metadata_file.read_text())
        assert meta["record_count"] == 3
        assert meta["records"] == {
            "I/311": {"hip2.dat.gz": 3, "hip7p.dat": 2, "notes.doc.gz": 1}
        }

    def test_keeps_files_already_on_disk(self, downloader):
        dl, requested = downloader
        dl.download()
        requested.clear()
        dl.download()
        assert requested == ["I/311/ReadMe"]

    def test_short_file_fails_and_is_not_kept(self, downloader, tmp_path, monkeypatch):
        dl, _ = downloader
        monkeypatch.setitem(FILES, "I/311/hip7p.dat", b"a\n")
        with pytest.raises(DownloadError, match="1 records, the ReadMe lists 2"):
            dl.download()
        assert not list((tmp_path / "I/311").glob("hip7p.dat*"))

    def test_missing_file_fails(self, downloader, monkeypatch):
        dl, _ = downloader
        monkeypatch.delitem(FILES, "I/311/hip7p.dat")
        with pytest.raises(DownloadError, match="HTTP 404"):
            dl.download()

    def test_file_without_a_listed_count_fails_before_anything_is_written(
        self, downloader, tmp_path, monkeypatch
    ):
        dl, _ = downloader
        monkeypatch.setitem(FILES, "I/311/ReadMe", b"<html>Sign in</html>")
        with pytest.raises(DownloadError, match="no record count for hip2.dat.gz"):
            dl.download()
        assert not list((tmp_path / "I/311").iterdir())

    def test_file_that_no_longer_matches_the_readme_is_fetched_again(
        self, downloader, tmp_path, monkeypatch
    ):
        dl, requested = downloader
        dl.download()
        monkeypatch.setitem(
            FILES,
            "I/311/ReadMe",
            README.replace("129        2", "129        3").encode(),
        )
        monkeypatch.setitem(FILES, "I/311/hip7p.dat", b"a\nb\nc\n")
        requested.clear()
        dl.download()
        assert requested == ["I/311/ReadMe", "I/311/hip7p.dat"]
        assert (tmp_path / "I/311/hip7p.dat").read_bytes() == b"a\nb\nc\n"

    def test_server_error_is_tried_again(self, tmp_path, monkeypatch):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = str(request.url).removeprefix(CDS_URL + "/")
            calls.append(path)
            if calls.count(path) == 1 and path.endswith("hip7p.dat"):
                return httpx.Response(503)
            return httpx.Response(200, content=FILES[path])

        monkeypatch.setattr(cds, "OUT_DIR", tmp_path)
        monkeypatch.setattr(cds, "RETRY_WAIT_SECONDS", 0.0)
        monkeypatch.setattr(cds, "CATALOGUES", {"I/311": ("hip7p.dat",)})
        client = httpx.Client(transport=httpx.MockTransport(handler))
        CDSStarCataloguesDownloader(client).download()
        assert calls.count("I/311/hip7p.dat") == 2
