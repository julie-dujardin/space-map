"""Tests for the download of the O'Brien et al. 2024 white dwarfs."""

import json

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import obrien_white_dwarfs
from space_map_data.download.providers.stars.obrien_white_dwarfs import (
    ObrienWhiteDwarfsDownloader,
)

HEADER = ",".join(
    ["WDJ_Name", obrien_white_dwarfs.ID_COLUMN, *obrien_white_dwarfs.FIT_COLUMNS]
)
CSV = f"{HEADER}\nWDJ0415-0739,3195919254111315712,16265,278,7.916,.021,.568,.012\n"


class TestObrienWhiteDwarfs:
    """Table A1 as published, checked for the columns that the ingest reads."""

    def make(self, tmp_path, monkeypatch, body: str) -> ObrienWhiteDwarfsDownloader:
        monkeypatch.setattr(obrien_white_dwarfs, "OUT_DIR", tmp_path / "out")
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=body)
            )
        )
        return ObrienWhiteDwarfsDownloader(client)

    def test_writes_the_table(self, tmp_path, monkeypatch):
        downloader = self.make(tmp_path, monkeypatch, CSV)
        downloader.download()
        out = obrien_white_dwarfs.OUT_DIR / obrien_white_dwarfs.TABLE_FILE
        assert out.read_text() == CSV
        meta = json.loads(downloader.metadata_file.read_text())
        assert meta["record_count"] == 1
        assert meta["terms"]["license"].startswith("CC BY 4.0")
        assert downloader.is_complete(None)

    def test_a_table_without_the_fit_writes_nothing(self, tmp_path, monkeypatch):
        downloader = self.make(tmp_path, monkeypatch, "WDJ_Name,DR3_source_id\n")
        with pytest.raises(DownloadError, match="gaia_teff"):
            downloader.download()
        assert not (
            obrien_white_dwarfs.OUT_DIR / obrien_white_dwarfs.TABLE_FILE
        ).exists()
