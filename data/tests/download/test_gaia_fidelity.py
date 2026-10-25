"""Tests for the Gaia astrometric fidelity provider."""

import json
import re
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import gaia_bulk, gaia_fidelity
from space_map_data.download.providers.stars.gaia_bulk import STATS_KEY
from space_map_data.download.providers.stars.gaia_fidelity import (
    GaiaFidelityDownloader,
)

CHUNKS = ("GaiaSource_000000-000001.csv.gz", "GaiaSource_000002-000005.csv.gz")
HEADER = "source_id,fidelity_v2,norm_dg\n"
# The rows the archive has. Star 12 has none.
TABLE = {10: "1.0,-20.5", 11: "0.25,", 20: "0.9,-3.0"}
TIMEOUT = (
    '<VOTABLE><INFO name="QUERY_STATUS" value="ERROR">'
    "Job timeout/aborted.</INFO></VOTABLE>"
)


def _source_chunk(path: Path, ids: list[int], threshold: float = 5.0) -> None:
    record = json.dumps({"min_parallax_over_error": threshold}).encode()
    table = pa.table({"source_id": pa.array(ids, pa.int64())})
    pq.write_table(table.replace_schema_metadata({STATS_KEY: record}), path)


class TestGaiaFidelityDownloader:
    """What a run asks for and what it records."""

    @pytest.fixture
    def downloader(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gaia_bulk, "OUT_DIR", tmp_path)
        self.source = tmp_path / "gdr3/gaia_source"
        self.source.mkdir(parents=True)
        listed = (*CHUNKS, "_readme.txt")
        (self.source / "_MD5SUM.txt").write_text(
            "".join(f"{'0' * 32}  {name}\n" for name in listed)
        )
        _source_chunk(self.source / "GaiaSource_000000-000001.parquet", [10, 11, 12])
        _source_chunk(self.source / "GaiaSource_000002-000005.parquet", [20])
        self.asked: list[list[int]] = []
        self.cut = False
        self.failing: set[int] = set()

        def handler(request: httpx.Request) -> httpx.Response:
            ids = [int(i) for i in re.findall(rb"<TD>(\d+)</TD>", request.content)]
            self.asked.append(ids)
            if self.failing & set(ids):
                return httpx.Response(200, text=TIMEOUT)
            found = [i for i in ids if i in TABLE]
            if self.cut and len(found) > 1:
                self.cut = False
                found = found[:1]
            rows = "".join(f"{i},{TABLE[i]}\n" for i in found)
            return httpx.Response(200, text=HEADER + rows)

        client = httpx.Client(
            transport=httpx.MockTransport(handler), headers={"User-Agent": "test"}
        )
        return GaiaFidelityDownloader(client)

    def _metadata(self, downloader: GaiaFidelityDownloader) -> dict:
        return json.loads(downloader.metadata_file.read_text())

    def _rows(self, downloader: GaiaFidelityDownloader) -> dict:
        return pq.read_table(downloader.chunk_path(CHUNKS[0])).to_pydict()

    def test_full_run_writes_each_chunk_and_is_complete(self, downloader):
        downloader.download()

        assert self._rows(downloader) == {
            "source_id": [10, 11],
            "fidelity_v2": [1.0, 0.25],
            "norm_dg": [-20.5, None],
        }
        meta = self._metadata(downloader)
        assert meta["complete"] and meta["chunks"] == 2
        assert (meta["record_count"], meta["stars"], meta["stars_without_row"]) == (
            3,
            4,
            1,
        )
        assert downloader.is_complete(None)

    def test_a_query_sends_at_most_a_piece_of_ids(self, downloader, monkeypatch):
        monkeypatch.setattr(gaia_fidelity, "PIECE", 2)
        downloader.download()
        assert max(len(ids) for ids in self.asked) == 2
        assert self._rows(downloader)["source_id"] == [10, 11]

    def test_cut_answer_is_completed(self, downloader, monkeypatch):
        # One row is an answer at the row limit.
        monkeypatch.setattr(gaia_fidelity, "DEFAULT_ROWS", 1)
        self.cut = True
        downloader.download()
        assert self._rows(downloader)["source_id"] == [10, 11]
        assert self._metadata(downloader)["stars_without_row"] == 1

    def test_a_complete_answer_is_not_asked_again(self, downloader):
        downloader.download()
        assert sorted(self.asked) == [[10, 11, 12], [20]]

    def test_failed_query_fails_only_its_chunk(self, downloader):
        self.failing = {10}
        with pytest.raises(DownloadError, match="1 chunks failed"):
            downloader.download()
        assert not downloader.chunk_path(CHUNKS[0]).exists()
        assert downloader.chunk_path(CHUNKS[1]).exists()
        assert not self._metadata(downloader)["complete"]

    def test_written_chunk_is_not_fetched_again(self, downloader):
        downloader.download()
        queries = len(self.asked)
        downloader.download()
        assert len(self.asked) == queries

    def test_chunk_from_another_threshold_is_fetched_again(self, downloader):
        downloader.download()
        path = downloader.chunk_path(CHUNKS[0])
        written = pq.read_table(path)
        record = json.loads(written.schema.metadata[STATS_KEY])
        record["min_parallax_over_error"] = 3.0
        pq.write_table(
            written.replace_schema_metadata({STATS_KEY: json.dumps(record).encode()}),
            path,
        )
        self.asked.clear()
        downloader.download()
        assert self.asked == [[10, 11, 12]]
        assert downloader.is_complete(None)

    def test_chunk_waits_for_gaia_source(self, downloader):
        (self.source / "GaiaSource_000002-000005.parquet").unlink()
        downloader.download()
        assert [20] not in self.asked
        assert not self._metadata(downloader)["complete"]

    def test_source_chunk_from_another_threshold_fails(self, downloader):
        _source_chunk(self.source / "GaiaSource_000000-000001.parquet", [10], 3.0)
        with pytest.raises(DownloadError, match="1 chunks failed"):
            downloader.download()
        assert not downloader.chunk_path(CHUNKS[0]).exists()

    def test_changed_selection_makes_a_complete_table_incomplete(self, downloader):
        downloader.download()
        meta = self._metadata(downloader)
        meta["selection"]["columns"] = ["source_id", "fidelity_v2"]
        downloader.metadata_file.write_text(json.dumps(meta))
        assert not downloader.is_complete(None)

    def test_missing_chunk_list_fails(self, downloader):
        (self.source / "_MD5SUM.txt").unlink()
        with pytest.raises(DownloadError, match="run gaia_source first"):
            downloader.download()


class TestCutAnswers:
    """The row counts of an answer that the archive can have cut."""

    @pytest.mark.parametrize(
        ("rows", "cut"),
        [
            (0, False),
            (1, False),
            (8192, False),
            (8193, True),
            (16385, True),
            (20_000, False),
            (49_999, False),
            (50_000, True),
        ],
    )
    def test_can_be_cut(self, rows, cut):
        assert gaia_fidelity.can_be_cut(rows) is cut
