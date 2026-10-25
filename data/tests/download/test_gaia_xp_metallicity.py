"""Tests for the XP metallicity provider (Andrae, Rix & Chandra 2023)."""

import gzip
import hashlib
import json
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import gaia_bulk, gaia_xp_metallicity
from space_map_data.download.providers.stars.gaia_bulk import STATS_KEY
from space_map_data.download.providers.stars.gaia_xp_metallicity import (
    ALL_STARS,
    OBA_FILE,
    OBA_URL,
    RECORD_URL,
    VETTED_RGB,
    GaiaXpMetallicityDownloader,
)
from space_map_data.download.providers.three_d import resumable

CHUNKS = (
    "GaiaSource_000000-000001.csv.gz",
    "GaiaSource_000002-000005.csv.gz",
    "GaiaSource_000006-786431.csv.gz",
)
HEADER = (
    "source_id,catwise_w1,catwise_w2,in_training_sample,"
    "mh_xgboost,teff_xgboost,logg_xgboost\n"
)


def sid(pixel: int, k: int) -> int:
    """A source id in a level-8 pixel."""
    return (pixel << 43) + k


# Stars the gaia_source chunks kept. Star (0, 12) and (7, 30) have no row in
# Table 1, and (0, 13) is in Table 1 but not kept.
KEPT = ([sid(0, 10), sid(1, 11), sid(0, 12)], [sid(2, 20), sid(3, 21)], [sid(7, 30)])
TABLE_1 = {
    sid(0, 10): "12.1,12.2,False,-0.256,5991.6,4.551",
    sid(0, 13): "11.0,11.1,True,0.1,5000.0,4.0",
    sid(1, 11): "9.5,9.6,True,-1.5,4500.0,1.9",
    sid(3, 21): "14.0,14.1,False,0.3,3500.0,4.8",
}
TABLE_2 = (sid(1, 11),)
OBA = (sid(3, 21), sid(5, 99))
# The golden sample file is ECSV, with its column types in a YAML header.
OBA_HEADER = (
    "# %ECSV 1.0\n# ---\n# datatype:\n"
    "# - {name: source_id, datatype: int64}\n"
    "# - {name: vtan_flag, datatype: int8}\n"
)


def gz_csv(header: str, rows: list[str]) -> bytes:
    return gzip.compress((header + "".join(f"{row}\n" for row in rows)).encode())


def table_1(order: list[int] | None = None) -> bytes:
    ids = order or sorted(TABLE_1)
    return gz_csv(HEADER, [f"{i},{TABLE_1[i]}" for i in ids])


def source_chunk(path: Path, ids: list[int], threshold: float = 5.0) -> None:
    record = json.dumps({"min_parallax_over_error": threshold}).encode()
    table = pa.table({"source_id": pa.array(ids, pa.int64())})
    pq.write_table(table.replace_schema_metadata({STATS_KEY: record}), path)


class TestGaiaXpMetallicityDownloader:
    """What a run fetches, what it writes and what it records."""

    @pytest.fixture
    def downloader(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gaia_bulk, "OUT_DIR", tmp_path)
        monkeypatch.setattr(resumable, "RETRY_WAIT_SECONDS", 0)
        self.source = tmp_path / "gdr3/gaia_source"
        self.source.mkdir(parents=True)
        listed = (*CHUNKS, "_readme.txt")
        (self.source / "_MD5SUM.txt").write_text(
            "".join(f"{'0' * 32}  {name}\n" for name in listed)
        )
        for chunk, ids in zip(CHUNKS, KEPT):
            source_chunk(self.source / chunk.replace(".csv.gz", ".parquet"), ids)
        self.files = {
            ALL_STARS: table_1(),
            VETTED_RGB: gz_csv("source_id,mh_xgboost\n", [f"{i},0" for i in TABLE_2]),
        }
        oba = gz_csv(OBA_HEADER + "source_id,vtan_flag\n", [f"{i},0" for i in OBA])
        self.listed_md5: dict[str, str] = {}
        self.fetched: list[str] = []
        self.requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            self.requests.append(url)
            if url == OBA_URL + "_MD5SUM.txt":
                return httpx.Response(
                    200, text=f"{hashlib.md5(oba).hexdigest()}  {OBA_FILE}\n"
                )
            if url == OBA_URL + OBA_FILE:
                self.fetched.append(OBA_FILE)
                return httpx.Response(200, content=oba)
            if url == RECORD_URL:
                files = [
                    {
                        "key": name,
                        "checksum": "md5:"
                        + self.listed_md5.get(name, hashlib.md5(body).hexdigest()),
                        "links": {"self": f"https://zenodo.test/{name}"},
                    }
                    for name, body in self.files.items()
                ]
                return httpx.Response(200, json={"files": files})
            name = url.rsplit("/", 1)[1]
            self.fetched.append(name)
            return httpx.Response(200, content=self.files[name])

        client = httpx.Client(
            transport=httpx.MockTransport(handler), headers={"User-Agent": "test"}
        )
        return GaiaXpMetallicityDownloader(client)

    def _rows(self, downloader: GaiaXpMetallicityDownloader, index: int) -> dict:
        return pq.read_table(downloader.chunk_path(CHUNKS[index])).to_pydict()

    def _metadata(self, downloader: GaiaXpMetallicityDownloader) -> dict:
        return json.loads(downloader.metadata_file.read_text())

    def test_full_run_writes_each_chunk_and_is_complete(self, downloader):
        downloader.download()

        rows = self._rows(downloader, 0)
        assert rows["source_id"] == [sid(0, 10), sid(1, 11)]
        assert rows["mh_xgboost"] == pytest.approx([-0.256, -1.5])
        assert rows["teff_xgboost"] == pytest.approx([5991.6, 4500.0])
        assert rows["catwise_w2"] == pytest.approx([12.2, 9.6])
        assert rows["in_training_sample"] == [False, True]
        assert rows["in_vetted_rgb_sample"] == [False, True]
        assert rows["in_oba_golden_sample"] == [False, False]
        assert self._rows(downloader, 1)["source_id"] == [sid(3, 21)]
        assert self._rows(downloader, 1)["in_oba_golden_sample"] == [True]
        # A chunk with no row in Table 1 still has its file.
        assert self._rows(downloader, 2)["source_id"] == []
        schema = pq.read_schema(downloader.chunk_path(CHUNKS[2]))
        assert schema.names == gaia_xp_metallicity.SCHEMA.names

        meta = self._metadata(downloader)
        assert meta["complete"] and meta["chunks"] == 3
        assert (meta["record_count"], meta["rows_in"], meta["vetted"]) == (3, 4, 1)
        assert (meta["stars"], meta["stars_without_row"], meta["oba"]) == (6, 3, 1)
        assert sorted(meta["files"]) == sorted([ALL_STARS, VETTED_RGB, OBA_FILE])
        assert downloader.is_complete(None)
        # Every chunk is written, so the deposit is gone.
        assert not downloader.deposit_dir.exists()
        columns = json.loads((downloader.out_dir / "columns.json").read_text())
        assert [c["datatype"] for c in columns][:2] == ["int64", "float32"]

    def test_second_run_asks_for_nothing_and_writes_nothing(self, downloader):
        downloader.download()
        assert self.fetched == [ALL_STARS, VETTED_RGB, OBA_FILE]
        written = downloader.chunk_path(CHUNKS[0]).stat().st_mtime_ns
        files = self._metadata(downloader)["files"]
        self.requests.clear()
        downloader.download()
        assert self.requests == []
        assert downloader.chunk_path(CHUNKS[0]).stat().st_mtime_ns == written
        assert self._metadata(downloader)["files"] == files
        assert not downloader.deposit_dir.exists()

    def test_a_partial_run_keeps_the_deposit_for_the_next(self, downloader):
        source = self.source / CHUNKS[1].replace(".csv.gz", ".parquet")
        source.unlink()
        downloader.download()
        assert (downloader.deposit_dir / ALL_STARS).exists()
        source_chunk(source, KEPT[1])
        downloader.download()
        # The files on disk are read again, not fetched.
        assert self.fetched == [ALL_STARS, VETTED_RGB, OBA_FILE]
        assert self._rows(downloader, 1)["source_id"] == [sid(3, 21)]
        assert self._metadata(downloader)["complete"]
        assert not downloader.deposit_dir.exists()

    def test_a_run_with_a_record_limit_fetches_no_deposit(self, downloader):
        downloader.download(limit=1)
        assert self.requests == []
        assert not downloader.deposit_dir.exists()
        assert not downloader.chunk_path(CHUNKS[0]).exists()
        assert not self._metadata(downloader)["complete"]

    def test_a_bad_md5_keeps_no_file(self, downloader):
        self.listed_md5[VETTED_RGB] = "0" * 32
        with pytest.raises(DownloadError, match="MD5"):
            downloader.download()
        assert not (downloader.deposit_dir / VETTED_RGB).exists()
        assert not downloader.chunk_path(CHUNKS[0]).exists()

    def test_chunk_waits_for_gaia_source(self, downloader):
        (self.source / CHUNKS[1].replace(".csv.gz", ".parquet")).unlink()
        downloader.download()
        assert not downloader.chunk_path(CHUNKS[1]).exists()
        assert self._rows(downloader, 2)["source_id"] == []
        assert not self._metadata(downloader)["complete"]

    def test_an_unsorted_table_fails(self, downloader):
        self.files[ALL_STARS] = table_1([sid(1, 11), sid(0, 10)])
        with pytest.raises(DownloadError, match="not sorted"):
            downloader.download()

    def test_source_chunk_from_another_threshold_fails(self, downloader):
        source_chunk(
            self.source / CHUNKS[0].replace(".csv.gz", ".parquet"), KEPT[0], 3.0
        )
        with pytest.raises(DownloadError, match="another threshold"):
            downloader.download()
