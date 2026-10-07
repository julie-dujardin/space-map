"""Tests for the Gaia bulk-repository providers."""

import gzip
import hashlib
import json
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import gaia_bulk
from space_map_data.download.providers.stars.gaia_astrophysical_parameters import (
    GaiaAstrophysicalParametersDownloader,
)
from space_map_data.download.providers.stars.gaia_bulk import (
    BULK_URL,
    STATS_KEY,
    ChunkedTableDownloader,
    ChunkJob,
    fetch_note,
    read_chunk_record,
    read_header,
    read_table,
    reduce_chunk,
)
from space_map_data.download.providers.stars.gaia_source import (
    COLUMNS,
    GaiaSourceDownloader,
)

HEADER = """# %ECSV 1.0
# ---
# delimiter: ','
# meta: !!omap
# - RELEASE: Gaia DR3
# datatype:
# -
#   name: solution_id
#   datatype: int64
#   description: Solution Identifier
# -
#   name: source_id
#   datatype: int64
#   description: Unique source identifier
# -
#   name: parallax
#   datatype: float64
#   unit: mas
#   description: Parallax
# -
#   name: parallax_over_error
#   datatype: float32
#   description: Parallax divided by its standard error
# -
#   name: duplicated_source
#   datatype: bool
#   description: Source with multiple source identifiers
# -
#   name: libname_gspphot
#   datatype: string
#   description: Name of the best library
# -
#   name: mass_flame
#   datatype: float32
#   unit: solMass
#   description: Mass of the star from FLAME
"""
NAMES = (
    "solution_id,source_id,parallax,parallax_over_error,duplicated_source,"
    "libname_gspphot,mass_flame"
)


def _ecsv(*rows: str) -> bytes:
    text = HEADER + NAMES + "\n" + "".join(row + "\n" for row in rows)
    return gzip.compress(text.encode())


ROWS = (
    '1,10,2.5,25.0,"False","MARCS",1.5',
    '1,11,0.4,4.0,"True",null,null',
    '1,12,null,null,"False",null,null',
    '1,13,1.0,5.5,"False","PHOENIX",0.75',
)


def _keep_strong(table: pa.Table, job: ChunkJob) -> tuple[pa.Table, dict[str, float]]:
    import pyarrow.compute as pc

    kept = table.filter(pc.field("parallax_over_error") > 5.0)
    return kept, {"rows_without_parallax": table["parallax"].null_count}


class _InlinePool:
    """Runs each submitted call at once, in this process."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> "_InlinePool":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def submit(self, fn, *args) -> Future:
        future: Future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as error:
            future.set_exception(error)
        return future


class _Table(ChunkedTableDownloader):
    name = "test_table"
    table_path = "gdr3/test_table"
    columns = ("source_id", "parallax", "parallax_over_error")
    count_keys = ("rows_without_parallax",)
    select = staticmethod(_keep_strong)


class TestEcsv:
    """Reading the ECSV header and the rows below it."""

    def test_header_is_the_leading_comment_lines(self):
        columns, lines = read_header(_ecsv(*ROWS))
        assert lines == HEADER.count("\n")
        assert [c.name for c in columns] == NAMES.split(",")

    def test_header_that_does_not_end_fails(self, monkeypatch):
        monkeypatch.setattr(gaia_bulk, "HEADER_BYTES", 40)
        with pytest.raises(DownloadError, match="header is longer"):
            read_header(_ecsv(*ROWS))

    def test_columns_carry_type_unit_and_description(self):
        columns = {c.name: c for c in read_header(_ecsv(*ROWS))[0]}
        assert columns["parallax"].unit == "mas"
        assert columns["parallax"].datatype == "float64"
        assert columns["source_id"].unit is None
        assert columns["source_id"].description == "Unique source identifier"

    def test_table_takes_the_declared_types(self):
        table = read_table(_ecsv(*ROWS), None)
        assert table.schema.field("parallax").type == pa.float64()
        assert table.schema.field("parallax_over_error").type == pa.float32()
        assert table.schema.field("duplicated_source").type == pa.bool_()
        assert table["duplicated_source"].to_pylist() == [False, True, False, False]

    def test_null_reads_as_missing_in_every_type(self):
        table = read_table(_ecsv(*ROWS), None)
        assert table["parallax"].to_pylist()[2] is None
        assert table["libname_gspphot"].to_pylist() == ["MARCS", None, None, "PHOENIX"]

    def test_exclude_drops_columns_when_all_are_read(self):
        table = read_table(_ecsv(*ROWS), None, exclude=("solution_id",))
        assert table.column_names == NAMES.split(",")[1:]

    def test_columns_selects_and_orders(self):
        table = read_table(_ecsv(*ROWS), ("parallax", "source_id"))
        assert table.column_names == ["parallax", "source_id"]


class TestReduceChunk:
    """One chunk, from gzip ECSV to Parquet."""

    def test_writes_the_selected_rows_and_the_record(self, tmp_path):
        out = tmp_path / "Chunk_0-1.parquet"
        job = ChunkJob("https://x.test/c.csv.gz", "abc", out, "ua", _keep_strong)
        stats = reduce_chunk(_ecsv(*ROWS), job)

        assert pq.read_table(out)["source_id"].to_pylist() == [10, 13]
        assert stats == {
            "source": "https://x.test/c.csv.gz",
            "md5": "abc",
            "rows_in": 4,
            "rows_without_parallax": 1,
            "rows_kept": 2,
        }
        assert read_chunk_record(out)[1] == stats
        assert not list(tmp_path.glob("*.part"))


class TestChunkedTableDownloader:
    """Which chunks a run reduces, and what it records."""

    CHUNKS = {
        "Chunk_0-1.csv.gz": _ecsv(*ROWS),
        "Chunk_2-3.csv.gz": _ecsv('1,20,3.0,30.0,"False","A",2.0'),
    }

    @pytest.fixture
    def table(self, tmp_path, monkeypatch):
        table_url = f"{BULK_URL}/{_Table.table_path}/"
        self.md5sums = "".join(
            f"{hashlib.md5(raw).hexdigest()}  {name}\n"
            for name, raw in self.CHUNKS.items()
        )
        self.requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            name = str(request.url).removeprefix(table_url)
            self.requested.append(name)
            if name == "_MD5SUM.txt":
                return httpx.Response(200, text=self.md5sums)
            return httpx.Response(200, content=self.CHUNKS[name])

        client = httpx.Client(
            transport=httpx.MockTransport(handler), headers={"User-Agent": "test"}
        )

        def run_inline(job: ChunkJob) -> dict[str, object]:
            raw = gaia_bulk.fetch_verified(client, job.url, job.md5)
            return reduce_chunk(raw, job)

        monkeypatch.setattr(gaia_bulk, "OUT_DIR", tmp_path)
        monkeypatch.setattr(gaia_bulk, "ProcessPoolExecutor", _InlinePool)
        monkeypatch.setattr(gaia_bulk, "run_chunk", run_inline)
        return _Table(client)

    def _metadata(self, table: _Table) -> dict:
        return json.loads(table.metadata_file.read_text())

    def test_full_run_is_complete_with_summed_counts(self, table):
        table.download()
        meta = self._metadata(table)
        assert meta["complete"] is True
        assert meta["record_count"] == 3
        assert (meta["rows_in"], meta["rows_without_parallax"]) == (5, 1)
        assert (meta["chunks"], meta["chunks_total"]) == (2, 2)
        assert table.is_complete(limit=None)

    def test_columns_file_describes_the_kept_columns(self, table):
        table.download()
        columns = json.loads((table.out_dir / "columns.json").read_text())
        assert [c["name"] for c in columns] == list(_Table.columns)
        assert columns[1]["unit"] == "mas"

    def test_limit_stops_early_and_the_next_run_continues(self, table, monkeypatch):
        monkeypatch.setattr(gaia_bulk, "MAX_WORKERS", 1)
        table.download(limit=1)
        meta = self._metadata(table)
        assert (meta["complete"], meta["chunks"]) == (False, 1)
        assert table.is_complete(limit=1) and not table.is_complete(limit=None)

        self.requested.clear()
        table.download()
        assert self._metadata(table)["complete"] is True
        assert "Chunk_0-1.csv.gz" not in self.requested[2:]

    def test_chunk_with_other_columns_is_reduced_again(self, table):
        table.download()
        stale = table.chunk_path("Chunk_2-3.csv.gz")
        record = pq.read_schema(stale).metadata
        pq.write_table(
            pa.table({"source_id": [20]}).replace_schema_metadata(record), stale
        )
        table.download()
        assert pq.read_schema(stale).names == list(_Table.columns)

    def test_chunk_without_its_companion_waits(self, table, tmp_path, monkeypatch):
        present = tmp_path / "companion.parquet"
        present.touch()
        monkeypatch.setattr(
            table,
            "companion",
            lambda chunk: present if chunk.startswith("Chunk_0") else tmp_path / "no",
        )
        table.download()
        meta = self._metadata(table)
        assert (meta["complete"], meta["chunks"]) == (False, 1)
        assert "Chunk_2-3.csv.gz" not in self.requested

    def test_changed_selection_makes_a_complete_table_incomplete(
        self, table, monkeypatch
    ):
        table.download()
        assert table.is_complete(limit=None)
        wider = (*_Table.columns, "mass_flame")
        monkeypatch.setattr(_Table, "columns", wider)
        assert not table.is_complete(limit=None)

        table.download()
        assert table.is_complete(limit=None)
        written = pq.read_schema(table.chunk_path("Chunk_0-1.csv.gz")).names
        assert written == list(wider)

    def test_changed_exclude_list_reduces_every_chunk_again(self, table, monkeypatch):
        monkeypatch.setattr(_Table, "columns", None)
        monkeypatch.setattr(_Table, "exclude", ("solution_id",))
        table.download()
        monkeypatch.setattr(_Table, "exclude", ("solution_id", "mass_flame"))
        table.download()
        names = pq.read_schema(table.chunk_path("Chunk_2-3.csv.gz")).names
        assert "mass_flame" not in names and "libname_gspphot" in names

    def test_dead_worker_fails_the_run_and_still_records_it(self, table, monkeypatch):
        class _BreaksAfterOne(_InlinePool):
            submitted = 0

            def submit(self, fn, *args) -> Future:
                type(self).submitted += 1
                if type(self).submitted > 1:
                    raise BrokenProcessPool("A child process terminated abruptly")
                return super().submit(fn, *args)

        monkeypatch.setattr(gaia_bulk, "ProcessPoolExecutor", _BreaksAfterOne)
        with pytest.raises(DownloadError, match="1 chunks failed"):
            table.download()
        meta = self._metadata(table)
        assert (meta["complete"], meta["chunks"]) == (False, 1)

    def test_unreadable_chunk_list_fails_and_keeps_the_old_copy(self, table):
        table.download()
        good = (table.out_dir / "_MD5SUM.txt").read_text()
        self.md5sums = "<html><body>Sign in to the network</body></html>"
        with pytest.raises(DownloadError, match="unreadable line"):
            table.download()
        assert (table.out_dir / "_MD5SUM.txt").read_text() == good

    def test_damaged_chunk_fails_the_run_and_leaves_it_incomplete(
        self, table, monkeypatch
    ):
        monkeypatch.setattr(gaia_bulk, "RETRY_WAIT_SECONDS", 0.0)
        monkeypatch.setitem(self.CHUNKS, "Chunk_2-3.csv.gz", b"damaged")
        with pytest.raises(DownloadError, match="1 chunks failed"):
            table.download()
        meta = self._metadata(table)
        assert (meta["complete"], meta["chunks"]) == (False, 1)


class TestGaiaProviders:
    """The two tables that share the chunk reducer."""

    def test_source_columns_are_unique(self):
        assert len(set(COLUMNS)) == len(COLUMNS)

    def test_source_chunk_from_another_threshold_is_not_current(self):
        downloader = GaiaSourceDownloader.__new__(GaiaSourceDownloader)
        assert downloader.is_current({"min_parallax_over_error": 5.0})
        assert not downloader.is_current({"min_parallax_over_error": 10.0})

    def test_parameters_keep_the_stars_of_the_source_chunk(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gaia_bulk, "OUT_DIR", tmp_path)
        downloader = GaiaAstrophysicalParametersDownloader.__new__(
            GaiaAstrophysicalParametersDownloader
        )
        companion = downloader.companion("AstrophysicalParameters_000000-003111.csv.gz")
        assert companion == (
            tmp_path / "gdr3/gaia_source/GaiaSource_000000-003111.parquet"
        )

        companion.parent.mkdir(parents=True)
        record = json.dumps({"min_parallax_over_error": 5.0}).encode()
        stars = pa.table({"source_id": pa.array([10, 13, 99], pa.int64())})
        pq.write_table(stars.replace_schema_metadata({STATS_KEY: record}), companion)

        out = tmp_path / "out.parquet"
        job = ChunkJob(
            "https://x.test/c.csv.gz",
            "abc",
            out,
            "ua",
            GaiaAstrophysicalParametersDownloader.select,
            exclude=GaiaAstrophysicalParametersDownloader.exclude,
            companion=companion,
        )
        stats = reduce_chunk(_ecsv(*ROWS), job)

        kept = pq.read_table(out)
        assert kept["source_id"].to_pylist() == [10, 13]
        # Every other column of the chunk is one that gaia_source keeps.
        assert kept.column_names == ["source_id", "mass_flame"]
        assert kept["mass_flame"].to_pylist() == [1.5, 0.75]
        assert (stats["stars"], stats["stars_without_row"]) == (3, 1)
        assert downloader.is_current(stats)

        other = json.dumps({"min_parallax_over_error": 3.0}).encode()
        pq.write_table(stars.replace_schema_metadata({STATS_KEY: other}), companion)
        with pytest.raises(DownloadError, match="another threshold"):
            reduce_chunk(_ecsv(*ROWS), job)

    def test_html_in_place_of_a_note_fails(self):
        page = httpx.Response(200, html="<html>Sign in</html>")
        client = httpx.Client(transport=httpx.MockTransport(lambda request: page))
        with pytest.raises(DownloadError, match="HTML page"):
            fetch_note(client, "https://x.test/_license.txt")
