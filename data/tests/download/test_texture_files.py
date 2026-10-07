"""Tests for the resumable texture source downloader."""

import io
import json
import zipfile

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.images import texture_files
from space_map_data.download.providers.images.texture_files import (
    TextureFilesDownloader,
)

URL = "https://maps.test/dem.tif"
BODY = bytes(range(256)) * 40
ETAG = '"v1"'


def _downloader(tmp_path, monkeypatch, *, etag: str = ETAG, body: bytes = BODY):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        headers = {"ETag": etag, "Content-Length": str(len(body))}
        if request.method == "HEAD":
            return httpx.Response(200, headers=headers)
        range_header = request.headers.get("Range")
        if range_header and request.headers.get("If-Range") == etag:
            start = int(range_header.removeprefix("bytes=").removesuffix("-"))
            return httpx.Response(206, content=body[start:], headers={"ETag": etag})
        return httpx.Response(200, content=body, headers={"ETag": etag})

    monkeypatch.setattr(texture_files, "SOURCES_TEXTURES_DIR", tmp_path)
    monkeypatch.setattr(
        texture_files,
        "load_entries",
        lambda _dir: [
            {
                "file": "base.tif",
                "_source_dir": tmp_path / "displacement" / "moon",
                "insets": [{"file": "dem.tif", "download_url": URL}],
            },
            {
                "file": "skipped.tif",
                "download_url": "https://maps.test/skipped.tif",
                "_source_dir": tmp_path / "surfaces",
                "skip": True,
            },
        ],
    )
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": "space-map-bot/0.1 (ops@maps.test)"},
    )
    return TextureFilesDownloader(client), requests


class TestTextureFilesDownloader:
    """Fetches the manifest's linked files, resuming a partial one."""

    def test_fetches_a_linked_inset_into_its_entry_directory(
        self, tmp_path, monkeypatch
    ):
        downloader, requests = _downloader(tmp_path, monkeypatch)
        downloader.download()

        target = tmp_path / "displacement" / "moon" / "dem.tif"
        assert target.read_bytes() == BODY
        assert not list(target.parent.glob("*.part*"))
        assert all("skipped" not in str(r.url) for r in requests)

    def test_requests_drop_the_bot_token_and_keep_the_contact(
        self, tmp_path, monkeypatch
    ):
        """NASA's file host refuses a User-Agent that names itself a bot."""
        downloader, requests = _downloader(tmp_path, monkeypatch)
        downloader.download()
        agents = {r.headers["User-Agent"] for r in requests}
        assert agents == {"space-map/0.1 (ops@maps.test)"}

    def test_resumes_from_the_bytes_already_on_disk(self, tmp_path, monkeypatch):
        downloader, requests = _downloader(tmp_path, monkeypatch)
        target = tmp_path / "displacement" / "moon" / "dem.tif"
        target.parent.mkdir(parents=True)
        (target.parent / "dem.tif.part").write_bytes(BODY[:1000])
        (target.parent / "dem.tif.part.validator").write_text(ETAG)
        downloader.download()

        assert target.read_bytes() == BODY
        assert requests[-1].headers["Range"] == "bytes=1000-"

    def test_partial_file_of_another_version_starts_over(self, tmp_path, monkeypatch):
        downloader, requests = _downloader(tmp_path, monkeypatch)
        target = tmp_path / "displacement" / "moon" / "dem.tif"
        target.parent.mkdir(parents=True)
        (target.parent / "dem.tif.part").write_bytes(b"x" * 1000)
        (target.parent / "dem.tif.part.validator").write_text('"v0"')
        downloader.download()

        assert target.read_bytes() == BODY
        assert "Range" not in requests[-1].headers

    def test_file_already_in_place_is_left_alone(self, tmp_path, monkeypatch):
        downloader, requests = _downloader(tmp_path, monkeypatch)
        target = tmp_path / "displacement" / "moon" / "dem.tif"
        target.parent.mkdir(parents=True)
        target.write_bytes(BODY)
        downloader.download()
        assert [r.method for r in requests] == ["HEAD"]

    def test_short_download_is_an_error_and_keeps_the_part(self, tmp_path, monkeypatch):
        downloader, _ = _downloader(tmp_path, monkeypatch)
        monkeypatch.setattr(downloader, "_stream", lambda *args: None)
        target = tmp_path / "displacement" / "moon" / "dem.tif"
        target.parent.mkdir(parents=True)
        (target.parent / "dem.tif.part").write_bytes(BODY[:1000])
        (target.parent / "dem.tif.part.validator").write_text(ETAG)

        with pytest.raises(DownloadError):
            downloader.download()
        assert not target.exists()
        assert (target.parent / "dem.tif.part").exists()

    def test_recorded_file_needs_no_request_on_the_next_run(
        self, tmp_path, monkeypatch
    ):
        """A run over thousands of files must restart without asking for each."""
        downloader, requests = _downloader(tmp_path, monkeypatch)
        downloader.download()
        del requests[:]
        downloader.download()
        assert requests == []

    def test_file_inside_a_zip_archive_is_unpacked(self, tmp_path, monkeypatch):
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("quad_E076_N16/readme.txt", "notes")
            archive.writestr("quad_E076_N16/mosaic.tif", BODY)
        downloader, _ = _downloader(tmp_path, monkeypatch, body=packed.getvalue())
        monkeypatch.setattr(texture_files, "ARCHIVE_DIR", tmp_path / "archives")
        monkeypatch.setattr(
            texture_files,
            "load_entries",
            lambda _dir: [
                {
                    "file": "base.tif",
                    "_source_dir": tmp_path / "surfaces",
                    "brightness": [
                        {
                            "dir": "ctx",
                            "file": "mosaic.tif",
                            "download_url": "https://maps.test/quad_E076_N16.zip",
                        }
                    ],
                }
            ],
        )
        downloader.download()

        target = tmp_path / "surfaces" / "ctx" / "mosaic.tif"
        assert target.read_bytes() == BODY
        assert list((tmp_path / "archives").iterdir()) == []
        assert [p.name for p in target.parent.iterdir()] == ["mosaic.tif"]

    def test_complete_only_while_every_linked_file_is_recorded(
        self, tmp_path, monkeypatch
    ):
        """A link added to the manifest later must still be fetched."""
        downloader, _ = _downloader(tmp_path, monkeypatch)
        assert not downloader.is_complete(None)
        downloader.download()
        assert downloader.is_complete(None)

        meta = json.loads(downloader.metadata_file.read_text())
        assert meta["files"] == {"displacement/moon/dem.tif": len(BODY)}
        (tmp_path / "displacement" / "moon" / "dem.tif").unlink()
        assert not downloader.is_complete(None)


class TestDroppedConnection:
    """Over thousands of files a few requests always drop."""

    def test_size_request_is_retried(self, tmp_path, monkeypatch):
        downloader, requests = _downloader(tmp_path, monkeypatch)
        monkeypatch.setattr(texture_files, "RETRY_DELAY_SECONDS", 0.0)
        send = downloader.client.head
        calls = []

        def flaky(url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise httpx.RemoteProtocolError("Server disconnected")
            return send(url, **kwargs)

        monkeypatch.setattr(downloader.client, "head", flaky)
        downloader.download()

        assert len(calls) == 2
        assert (tmp_path / "displacement" / "moon" / "dem.tif").read_bytes() == BODY


class TestWriteSynced:
    """Large files reach a network mount without piling up in memory."""

    def test_flushes_to_disk_every_few_megabytes(self, tmp_path, monkeypatch):
        flushed: list[int] = []
        monkeypatch.setattr(texture_files, "SYNC_BYTES", 1000)
        monkeypatch.setattr(
            texture_files.os, "fdatasync", lambda fd: flushed.append(fd)
        )
        with (tmp_path / "out.bin").open("wb") as out:
            written = texture_files.write_synced([b"x" * 400] * 6, out)

        assert written == 2400
        assert (tmp_path / "out.bin").read_bytes() == b"x" * 2400
        assert len(flushed) == 2
