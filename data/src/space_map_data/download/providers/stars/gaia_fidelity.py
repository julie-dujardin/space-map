"""Download the astrometric fidelity of the positionable Gaia DR3 stars.

Rybizki et al. (2022) trained a classifier that tells a real astrometric
solution from a spurious one. A spurious solution is most often a blend in a
crowded field, which gives a far star a large parallax and puts it close to
the Sun. `fidelity_v2` below 0.5 marks a star whose distance is likely wrong.
`norm_dg` tells how much a brighter neighbour can spoil its photometry. The
classifier ran on Gaia EDR3, which has the same sources and astrometry as DR3.

ESA serves the table only through its TAP service, so this provider uploads
the ids of the stars that `gaia_source` kept, one of its chunks at a time.

Writes, below sources/stars/gaia/gedr3/external/gaiaedr3_spurious/:
- Fidelity_<pixels>.parquet   the rows of the stars of one gaia_source chunk
- metadata.json

No licence is stated. Cite Rybizki et al. 2022, MNRAS 510, 2597. The values
derive from Gaia, CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC.
https://www.cosmos.esa.int/web/gaia-users/license
"""

import json
import logging
import time
from collections.abc import Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.exoplanets.tap import tap_sync, votable
from space_map_data.download.providers.stars import gaia_bulk, gaia_source
from space_map_data.download.providers.stars.gaia_bulk import (
    CHUNK_SUFFIX,
    MD5_FILE,
    STATS_KEY,
    ChunkedTableDownloader,
)

logger = logging.getLogger(__name__)

TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
TABLE_PATH = "gedr3/external/gaiaedr3_spurious"
CHUNK_PREFIX = "Fidelity_"
COLUMNS: dict[str, pa.DataType] = {
    "source_id": pa.int64(),
    "fidelity_v2": pa.float32(),
    "norm_dg": pa.float32(),
}
QUERY = (
    f"select {', '.join(f's.{column}' for column in COLUMNS)}"
    " from TAP_UPLOAD.sent as u"
    " join external.gaiaedr3_spurious as s on s.source_id = u.source_id"
)
# Ids per query: one takes about 12 s, and the answer stays below the 50,000
# rows the archive sends by default.
PIECE = 20_000
WORKERS = 4
# A cut answer comes with no error. It has DEFAULT_ROWS rows, or k·CUT_ROWS + 1
# rows when the query runs too long.
DEFAULT_ROWS = 50_000
CUT_ROWS = 8192


def read_rows(body: str, types: dict[str, pa.DataType]) -> pa.Table:
    return pcsv.read_csv(
        pa.py_buffer(body.encode()),
        convert_options=pcsv.ConvertOptions(
            column_types=types,
            include_columns=list(types),
            null_values=["", "null"],
            strings_can_be_null=True,
        ),
    )


def can_be_cut(rows: int) -> bool:
    """Whether an answer of `rows` rows can be one that the archive cut."""
    return rows >= DEFAULT_ROWS or (rows > CUT_ROWS and rows % CUT_ROWS == 1)


def ask_ids(
    client: httpx.Client,
    query: str,
    ids: Sequence[int],
    types: dict[str, pa.DataType],
) -> pa.Table:
    """The rows that `query` gives for `ids`, uploaded as `source_id`, PIECE
    ids at a time.

    A piece whose answer can be cut is asked again for its ids without a row,
    until an answer adds none.
    """
    found = [pa.schema(types).empty_table()]
    pieces = [list(ids[i : i + PIECE]) for i in range(0, len(ids), PIECE)]
    while pieces:
        again = []
        for piece in pieces:
            upload = votable("source_id", "long", piece)
            rows = read_rows(tap_sync(client, TAP_URL, query, upload=upload), types)
            found.append(rows)
            if can_be_cut(rows.num_rows):
                got = set(rows["source_id"].to_pylist())
                again.append([i for i in piece if i not in got])
        pieces = [piece for piece in again if piece]
    return pa.concat_tables(found)


class GaiaFidelityDownloader(ChunkedTableDownloader):
    """One file per gaia_source chunk, with the record of the bulk tables.

    The rows come from the TAP service of the archive. So this class has its
    own `download` and `chunk_path`.
    """

    name = PROVIDERS.GAIA_FIDELITY
    table_path = TABLE_PATH

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.source_dir = gaia_bulk.OUT_DIR / gaia_source.TABLE_PATH

    def selection(self) -> dict[str, object]:
        return {
            "columns": list(COLUMNS),
            "min_parallax_over_error": gaia_source.MIN_PARALLAX_OVER_ERROR,
        }

    def is_current(self, stats: dict) -> bool:
        return stats["min_parallax_over_error"] == gaia_source.MIN_PARALLAX_OVER_ERROR

    def chunk_path(self, chunk: str) -> Path:
        pixels = chunk.removeprefix(gaia_source.CHUNK_PREFIX).removesuffix(CHUNK_SUFFIX)
        return self.out_dir / f"{CHUNK_PREFIX}{pixels}.parquet"

    def source_path(self, chunk: str) -> Path:
        return self.source_dir / (chunk.removesuffix(CHUNK_SUFFIX) + ".parquet")

    def fetch_chunk(self, chunk: str) -> dict[str, object]:
        """Write the rows of the stars that one gaia_source chunk kept."""
        stars = pq.read_table(self.source_path(chunk), columns=["source_id"])
        selection = json.loads(stars.schema.metadata[STATS_KEY])
        if selection["min_parallax_over_error"] != gaia_source.MIN_PARALLAX_OVER_ERROR:
            raise DownloadError(f"{chunk} is from another threshold: run gaia_source")
        rows = ask_ids(self.client, QUERY, stars["source_id"].to_pylist(), COLUMNS)
        stats: dict[str, object] = {
            "source": chunk,
            "stars": stars.num_rows,
            "stars_without_row": stars.num_rows - rows.num_rows,
            "min_parallax_over_error": selection["min_parallax_over_error"],
            "rows_kept": rows.num_rows,
        }
        out = self.chunk_path(chunk)
        part = out.with_suffix(".parquet.part")
        pq.write_table(
            rows.replace_schema_metadata({STATS_KEY: json.dumps(stats).encode()}),
            part,
            compression="zstd",
            compression_level=9,
        )
        part.replace(out)
        return stats

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        md5_file = self.source_dir / MD5_FILE
        if not md5_file.exists():
            raise DownloadError(f"{md5_file} is missing: run gaia_source first")
        chunks = sorted(
            name for name in md5_file.read_text().split() if name.endswith(CHUNK_SUFFIX)
        )

        done = self._written(chunks, list(COLUMNS))
        todo = [
            chunk
            for chunk in chunks
            if chunk not in done and self.source_path(chunk).exists()
        ]
        logger.info(
            "%s: %d chunks, %d written, %d to fetch, %d wait for gaia_source",
            self.name,
            len(chunks),
            len(done),
            len(todo),
            len(chunks) - len(done) - len(todo),
        )

        failed = self._fetch(todo, done, limit)
        totals = {
            key: sum(stats[key] for stats in done.values())
            for key in ("rows_kept", "stars", "stars_without_row")
        }
        self._save_metadata(
            TAP_URL,
            totals.pop("rows_kept"),
            complete=len(done) == len(chunks),
            chunks=len(done),
            chunks_total=len(chunks),
            selection=self.selection(),
            **totals,
        )
        if failed:
            raise DownloadError(f"{len(failed)} chunks failed: {', '.join(failed)}")

    def _fetch(
        self, todo: list[str], done: dict[str, dict], limit: int | None
    ) -> list[str]:
        """Fetch `todo`. Returns the chunks that failed."""
        kept = sum(stats["rows_kept"] for stats in done.values())
        queue = iter(todo)
        pending: dict[Future, str] = {}
        failed: list[str] = []
        finished = 0
        started = time.monotonic()
        with ThreadPoolExecutor(WORKERS) as pool:
            while True:
                while (
                    len(pending) < WORKERS
                    and (limit is None or kept < limit)
                    and (chunk := next(queue, None)) is not None
                ):
                    pending[pool.submit(self.fetch_chunk, chunk)] = chunk
                if not pending:
                    break
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    chunk = pending.pop(future)
                    finished += 1
                    try:
                        stats = future.result()
                    except Exception as error:
                        failed.append(chunk)
                        logger.error("%s: %r", chunk, error)
                        continue
                    done[chunk] = stats
                    kept += stats["rows_kept"]
                    logger.info(
                        "[%d/%d] %s: %d rows, %d stars without one, %.1f min",
                        finished,
                        len(todo),
                        chunk,
                        stats["rows_kept"],
                        stats["stars_without_row"],
                        (time.monotonic() - started) / 60,
                    )
        return failed
