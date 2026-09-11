"""Tests for the Earth cloud downloader's mirror backfill."""

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.images import earth_clouds
from space_map_data.download.providers.images.earth_clouds import (
    MIRROR_RELEASES_URL,
    SOURCE_URL,
    EarthCloudsDownloader,
)

PAGE_2_URL = "https://api.github.com/repositories/1/releases?per_page=100&page=2"


def _release(tag: str, *asset_names: str) -> dict:
    return {
        "tag_name": tag,
        "assets": [
            {"name": n, "browser_download_url": f"https://assets.test/{n}"}
            for n in asset_names
        ],
    }


PAGES = {
    MIRROR_RELEASES_URL: [
        _release("maps-20260911_1800", "clouds_alpha_20260911_1800.png"),
        _release("maps-20260911_1500", "clouds_alpha_20260911_1500.png"),
    ],
    PAGE_2_URL: [
        _release("maps-20260910_0300", "clouds_20260910_0300.jpg"),
        _release("archive-2026-W31", "clouds_alpha_2K_2026-W31.zip"),
    ],
}


def _downloader(tmp_path, monkeypatch, fail: frozenset[str] = frozenset()):
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url in PAGES:
            headers = (
                {"Link": f'<{PAGE_2_URL}>; rel="next"'}
                if url == MIRROR_RELEASES_URL
                else {}
            )
            return httpx.Response(200, json=PAGES[url], headers=headers)
        if url in fail:
            return httpx.Response(404)
        return httpx.Response(200, content=url.encode())

    monkeypatch.setattr(earth_clouds, "SOURCES_TEXTURES_DIR", tmp_path)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return EarthCloudsDownloader(client), requested


def test_backfill_fills_missing_slots_only(tmp_path, monkeypatch):
    dl, requested = _downloader(tmp_path, monkeypatch)
    existing = dl.out_dir / "2026/09/11/15.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"live")

    dl._backfill()

    assert (dl.out_dir / "2026/09/11/18.png").read_bytes() == (
        b"https://assets.test/clouds_alpha_20260911_1800.png"
    )
    assert existing.read_bytes() == b"live"
    assert not (dl.out_dir / "2026/09/10/03.png").exists()
    assert requested == [
        MIRROR_RELEASES_URL,
        PAGE_2_URL,
        "https://assets.test/clouds_alpha_20260911_1800.png",
    ]


def test_backfill_continues_past_failures_then_raises(tmp_path, monkeypatch):
    dl, _ = _downloader(
        tmp_path,
        monkeypatch,
        fail=frozenset({"https://assets.test/clouds_alpha_20260911_1800.png"}),
    )

    with pytest.raises(DownloadError, match="1 of 2"):
        dl._backfill()

    assert (dl.out_dir / "2026/09/11/15.png").exists()


def test_download_saves_live_slot_before_backfill(tmp_path, monkeypatch):
    dl, requested = _downloader(tmp_path, monkeypatch)

    dl.download()

    assert requested[0] == SOURCE_URL
    assert dl.is_complete(limit=None)
    assert dl.metadata_file.exists()
