"""Tests for the Bailer-Jones and UltracoolSheet downloads."""

import hashlib
import json
import re

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import bailer_jones, ultracoolsheet
from space_map_data.download.providers.stars.bailer_jones import (
    BailerJonesDistancesDownloader,
)
from space_map_data.download.providers.stars.ultracoolsheet import (
    UltracoolSheetDownloader,
)

# The archive's distances, by source_id.
DISTANCES = {11: "300.5,250.0,380.0,10033", 17: "9000.0,5000.0,15000.0,10011"}


class TestBailerJones:
    """The geometric distances of the gaia_named rows."""

    @pytest.fixture
    def downloader(self, tmp_path, monkeypatch):
        named = tmp_path / "named.parquet"
        pq.write_table(
            pa.table({"source_id": pa.array([17, 11, 12], pa.int64())}), named
        )
        monkeypatch.setattr(bailer_jones, "NAMED_FILE", named)
        monkeypatch.setattr(BailerJonesDistancesDownloader, "inputs", (named,))
        monkeypatch.setattr(bailer_jones, "OUT_DIR", tmp_path / "out")
        self.asked: list[list[int]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = request.content
            assert b"external.gaiaedr3_distance" in body
            ids = [int(i) for i in re.findall(rb"<TD>(\d+)</TD>", body)]
            self.asked.append(ids)
            lines = [f"{i},{DISTANCES[i]}" for i in ids if i in DISTANCES]
            text = "source_id,r_med_geo,r_lo_geo,r_hi_geo,flag\n" + "".join(
                f"{line}\n" for line in lines
            )
            return httpx.Response(200, text=text)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        return BailerJonesDistancesDownloader(client)

    def test_writes_the_distances(self, downloader):
        downloader.download()
        rows = pq.read_table(bailer_jones.OUT_DIR / bailer_jones.OUT_FILE)
        assert sorted(rows["source_id"].to_pylist()) == [11, 17]
        assert rows.schema.field("r_med_geo").type == pa.float32()
        assert rows["flag"].to_pylist()[0] in ("10033", "10011")
        # A complete answer is not asked again.
        assert self.asked == [[11, 12, 17]]
        meta = json.loads(downloader.metadata_file.read_text())
        assert (meta["record_count"], meta["ids_sent"]) == (2, 3)


CSV = b"name,exoplanet\nLuhman 16,N\n"


class TestUltracoolSheet:
    """The main table of one Zenodo release, checked by its MD5."""

    def make(self, tmp_path, monkeypatch, checksum: str) -> UltracoolSheetDownloader:
        monkeypatch.setattr(ultracoolsheet, "OUT_DIR", tmp_path / "out")
        record = {
            "files": [
                {
                    "key": ultracoolsheet.SOURCE_FILE,
                    "checksum": f"md5:{checksum}",
                    "links": {"self": "https://zenodo.test/main"},
                }
            ]
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith(str(ultracoolsheet.RECORD)):
                return httpx.Response(200, json=record)
            return httpx.Response(200, content=CSV)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        return UltracoolSheetDownloader(client)

    def test_writes_the_table(self, tmp_path, monkeypatch):
        downloader = self.make(tmp_path, monkeypatch, hashlib.md5(CSV).hexdigest())
        downloader.download()
        out = ultracoolsheet.OUT_DIR / ultracoolsheet.MAIN_FILE
        assert out.read_bytes() == CSV
        meta = json.loads(downloader.metadata_file.read_text())
        assert (meta["record_count"], meta["record"]) == (1, ultracoolsheet.RECORD)
        assert downloader.is_complete(None)

    def test_a_wrong_checksum_writes_nothing(self, tmp_path, monkeypatch):
        downloader = self.make(tmp_path, monkeypatch, "0" * 32)
        with pytest.raises(DownloadError, match="MD5"):
            downloader.download()
        assert not (ultracoolsheet.OUT_DIR / ultracoolsheet.MAIN_FILE).exists()
