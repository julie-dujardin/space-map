"""Tests for the resumable texture source downloader."""

import io
import json
import zipfile

import glymur
import httpx
import numpy as np
import pytest
import tifffile
from glymur.jp2box import UUIDBox

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

    def test_file_named_by_two_entries_is_fetched_once(self, tmp_path, monkeypatch):
        """Two maps of one body share a detail layer."""
        downloader, requests = _downloader(tmp_path, monkeypatch)
        layer = {"file": "detail.tif", "download_url": URL}
        entries = [
            {"file": name, "_source_dir": tmp_path / "surfaces", "brightness": [layer]}
            for name in ("best.tif", "second.tif")
        ]
        monkeypatch.setattr(texture_files, "load_entries", lambda _dir: entries)
        downloader.download()

        assert (tmp_path / "surfaces" / "detail.tif").read_bytes() == BODY
        assert sum(r.method == "GET" for r in requests) == 1

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

    def test_host_that_states_no_size_fails_that_file_alone(
        self, tmp_path, monkeypatch
    ):
        downloader, _ = _downloader(tmp_path, monkeypatch)
        downloader.client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        )
        with pytest.raises(DownloadError, match="1 of 1 texture files not fetched"):
            downloader.download()
        assert downloader.metadata_file.exists()

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
        downloader, _requests = _downloader(tmp_path, monkeypatch)
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


def _geojp2(path, pixels: np.ndarray) -> None:
    """A JPEG 2000 image placed like the Opportunity mosaic: 25 cm pixels from
    a corner at 333 km west and 112 km south."""
    geo = io.BytesIO()
    keys = (1, 1, 0, 4, 1024, 0, 1, 1, 1025, 0, 1, 1, 2057, 34736, 1, 0, 3075, 0, 1, 17)
    tifffile.imwrite(
        geo,
        np.zeros((1, 1), np.uint8),
        extratags=[
            (33550, "d", 3, (0.25, 0.25, 0.0), True),
            (33922, "d", 6, (0.0, 0.0, 0.0, -333000.0, -112000.0, 0.0), True),
            (34735, "H", len(keys), keys, True),
            (34736, "d", 1, (3396190.0,), True),
        ],
        metadata=None,
    )
    plain = path.with_suffix(".plain.jp2")
    glymur.Jp2k(str(plain), data=pixels, tilesize=(128, 128))
    box = UUIDBox(texture_files.GEOJP2_UUID, geo.getvalue())
    boxes = glymur.Jp2k(str(plain)).box
    glymur.Jp2k(str(plain)).wrap(str(path), boxes=[*boxes[:-1], box, boxes[-1]])
    plain.unlink()


class TestJpeg2000:
    """A JPEG 2000 mosaic the builds cannot read in parts becomes a GeoTIFF."""

    def test_pixels_and_placement_carry_over(self, tmp_path, monkeypatch):
        monkeypatch.setattr(texture_files, "JPEG2000_BAND_ROWS", 512)
        monkeypatch.setattr(texture_files, "GEOTIFF_TILE", 256)
        pixels = np.random.default_rng(1).integers(1, 255, (700, 1100), np.uint8)
        _geojp2(tmp_path / "mosaic.jp2", pixels)
        texture_files.jpeg2000_to_geotiff(
            tmp_path / "mosaic.jp2", tmp_path / "mosaic.tif"
        )

        with tifffile.TiffFile(tmp_path / "mosaic.tif") as tif:
            page = tif.pages[0]
            assert isinstance(page, tifffile.TiffPage)
            assert page.is_tiled and page.chunks == (256, 256)
            assert np.array_equal(page.asarray(), pixels)
            geo = page.geotiff_tags
        assert geo is not None
        assert geo["ModelTiepoint"][3:5] == [-333000.0, -112000.0]
        assert geo["ProjCoordTransGeoKey"] == 17

    def test_image_with_no_geojp2_box_is_refused(self, tmp_path):
        glymur.Jp2k(str(tmp_path / "plain.jp2"), data=np.ones((64, 64), np.uint8))
        with pytest.raises(ValueError, match="no GeoJP2 box"):
            texture_files.jpeg2000_to_geotiff(
                tmp_path / "plain.jp2", tmp_path / "plain.tif"
            )

    def test_linked_image_is_converted_and_dropped(self, tmp_path, monkeypatch):
        pixels = np.full((300, 200), 90, np.uint8)
        _geojp2(tmp_path / "source.jp2", pixels)
        body = (tmp_path / "source.jp2").read_bytes()
        downloader, _ = _downloader(tmp_path, monkeypatch, body=body)
        monkeypatch.setattr(texture_files, "ARCHIVE_DIR", tmp_path / "archives")
        monkeypatch.setattr(
            texture_files,
            "load_entries",
            lambda _dir: [
                {
                    "file": "base.tif",
                    "_source_dir": tmp_path / "surfaces",
                    "patches": [
                        {
                            "id": "site",
                            "files": [
                                {
                                    "file": "mosaic.tif",
                                    "dir": "sites",
                                    "download_url": "https://maps.test/mosaic.jp2",
                                }
                            ],
                        }
                    ],
                }
            ],
        )
        downloader.download()

        target = tmp_path / "surfaces" / "sites" / "mosaic.tif"
        assert np.array_equal(tifffile.imread(target), pixels)
        assert list((tmp_path / "archives").iterdir()) == []
        assert [p.name for p in target.parent.iterdir()] == ["mosaic.tif"]
