"""Shared code for the providers that read the Gaia bulk repository.

The repository holds each table as gzip ECSV chunks, listed in `_MD5SUM.txt`.
A chunk covers a range of HEALPix level-8 pixels, and every source table uses
the same ranges.

`ChunkedTableDownloader` streams one table. For each chunk it keeps the rows
that the provider selects and writes them as one Parquet file. The ECSV is not
kept: `gaia_source` alone is 757 GB.

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC.
https://www.cosmos.esa.int/web/gaia-users/license
"""

import hashlib
import json
import logging
import multiprocessing
import os
import re
import time
import zlib
from collections.abc import Callable, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    wait,
)
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.csv as pcsv
import pyarrow.parquet as pq
import yaml

from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

BULK_URL = "https://cdn.gea.esac.esa.int/Gaia"
OUT_DIR = SOURCES_STARS_DIR / "gaia"
MD5_FILE = "_MD5SUM.txt"
CHUNK_SUFFIX = ".csv.gz"

# Key of the per-chunk record in the Parquet footer.
STATS_KEY = b"space_map_reduction"

ATTEMPTS = 6
RETRY_WAIT_SECONDS = 10.0
# A chunk needs about 1.2 GB while it is parsed.
MAX_WORKERS = 12
# The longest ECSV header is about 150 kB compressed.
HEADER_BYTES = 1 << 20

_MD5_LINE = re.compile(r"([0-9a-f]{32})\s+(\S+)")

ARROW_TYPES: dict[str, pa.DataType] = {
    "int8": pa.int8(),
    "int16": pa.int16(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "float32": pa.float32(),
    "float64": pa.float64(),
    "bool": pa.bool_(),
    "string": pa.string(),
}


@dataclass(frozen=True)
class Column:
    """One column of a table, as its ECSV header declares it."""

    name: str
    datatype: str
    unit: str | None
    description: str


def fetch_md5sums(
    client: httpx.Client, table_url: str, out_dir: Path
) -> dict[str, str]:
    """The files of a table and their MD5. Keeps a copy of the list."""
    response = client.get(table_url + MD5_FILE)
    response.raise_for_status()
    sums: dict[str, str] = {}
    for line in response.text.splitlines():
        match = _MD5_LINE.fullmatch(line.strip())
        if match is None:
            raise DownloadError(f"{table_url}{MD5_FILE}: unreadable line {line[:80]!r}")
        sums[match[2]] = match[1]
    (out_dir / MD5_FILE).write_bytes(response.content)
    return sums


def fetch_note(client: httpx.Client, url: str) -> bytes:
    """Fetch a plain-text note. A dead uplink can answer 200 with an HTML page."""
    response = client.get(url)
    response.raise_for_status()
    if "text/html" in response.headers.get("content-type", ""):
        raise DownloadError(f"{url}: got an HTML page")
    return response.content


def fetch_verified(client: httpx.Client, url: str, md5: str) -> bytes:
    """Fetch `url` and check its MD5. A failed or damaged transfer is tried again."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = client.get(url, timeout=300.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            if error.response.status_code in (403, 404):
                raise DownloadError(
                    f"HTTP {error.response.status_code} for {url}"
                ) from error
            logger.warning("%s: attempt %d/%d: %s", url, attempt, ATTEMPTS, error)
        except httpx.HTTPError as error:
            logger.warning("%s: attempt %d/%d: %r", url, attempt, ATTEMPTS, error)
        else:
            if hashlib.md5(response.content).hexdigest() == md5:
                return response.content
            logger.warning(
                "%s: attempt %d/%d: MD5 mismatch on %d bytes",
                url,
                attempt,
                ATTEMPTS,
                len(response.content),
            )
        if attempt < ATTEMPTS:
            time.sleep(RETRY_WAIT_SECONDS * attempt)
    raise DownloadError(f"{url}: no valid download after {ATTEMPTS} attempts")


def parse_header(header: bytes) -> list[Column]:
    # The first line is the `%ECSV` marker, which YAML reads as a directive.
    lines = header.decode().splitlines()[1:]
    spec = yaml.safe_load("\n".join(line[2:] for line in lines))
    return [
        Column(c["name"], c["datatype"], c.get("unit"), c.get("description", ""))
        for c in spec["datatype"]
    ]


def read_header(compressed: bytes) -> tuple[list[Column], int]:
    """The columns of a gzip ECSV chunk, and how many lines its header has.

    The header is the leading `#` lines. Only the start of `compressed` is
    read, so the start of a chunk is enough.
    """
    data = zlib.decompressobj(wbits=31).decompress(compressed[:HEADER_BYTES])
    end = lines = 0
    while data.startswith(b"#", end):
        newline = data.find(b"\n", end)
        if newline < 0:
            break
        end = newline + 1
        lines += 1
    if data.startswith(b"#", end) or end == len(data):
        raise DownloadError(f"ECSV header is longer than {HEADER_BYTES} bytes")
    return parse_header(data[:end]), lines


def fetch_header(client: httpx.Client, url: str) -> list[Column]:
    """The columns of a chunk, read from the first bytes of the file."""
    response = client.get(url, headers={"Range": f"bytes=0-{HEADER_BYTES - 1}"})
    response.raise_for_status()
    return read_header(response.content)[0]


def kept_columns(
    header: list[Column], columns: Sequence[str] | None, exclude: Sequence[str]
) -> list[Column]:
    """`columns` in that order, or every column that `exclude` does not name."""
    if columns is None:
        return [column for column in header if column.name not in exclude]
    by_name = {column.name: column for column in header}
    return [by_name[name] for name in columns]


def read_table(
    compressed: bytes, columns: Sequence[str] | None, exclude: Sequence[str] = ()
) -> pa.Table:
    """Parse a gzip ECSV chunk with the types its header declares.

    The text is decompressed block by block, so it is never whole in memory.
    """
    header, header_lines = read_header(compressed)
    kept = kept_columns(header, columns, exclude)
    return pcsv.read_csv(
        pa.CompressedInputStream(pa.BufferReader(compressed), "gzip"),
        read_options=pcsv.ReadOptions(
            use_threads=False, block_size=64 << 20, skip_rows=header_lines
        ),
        convert_options=pcsv.ConvertOptions(
            include_columns=[column.name for column in kept],
            column_types={c.name: ARROW_TYPES[c.datatype] for c in kept},
            null_values=["null", ""],
            strings_can_be_null=True,
        ),
    )


@dataclass(frozen=True)
class ChunkJob:
    """One chunk to reduce. It crosses the process boundary."""

    url: str
    md5: str
    out: Path
    user_agent: str
    select: "Select"
    columns: tuple[str, ...] | None = None
    exclude: tuple[str, ...] = ()
    # A file that `select` reads, for a table that joins on another.
    companion: Path | None = None


# Returns the kept rows and the counts to record for the chunk.
Select = Callable[[pa.Table, ChunkJob], tuple[pa.Table, dict[str, float]]]


def reduce_chunk(raw: bytes, job: ChunkJob) -> dict[str, object]:
    """Write the selected rows of one ECSV chunk to `job.out`."""
    table = read_table(raw, job.columns, job.exclude)
    kept, detail = job.select(table, job)
    stats: dict[str, object] = {
        "source": job.url,
        "md5": job.md5,
        "rows_in": table.num_rows,
        **detail,
        "rows_kept": kept.num_rows,
    }
    part = job.out.with_suffix(".parquet.part")
    pq.write_table(
        kept.replace_schema_metadata({STATS_KEY: json.dumps(stats).encode()}),
        part,
        compression="zstd",
        compression_level=9,
    )
    part.replace(job.out)
    return stats


def run_chunk(job: ChunkJob) -> dict[str, object]:
    """Worker entry point: fetch one chunk and reduce it."""
    with httpx.Client(
        headers={"User-Agent": job.user_agent}, follow_redirects=True
    ) as client:
        raw = fetch_verified(client, job.url, job.md5)
    return reduce_chunk(raw, job)


def read_chunk_record(path: Path) -> tuple[list[str], dict]:
    """The column names of a written chunk and the record in its footer."""
    schema = pq.read_schema(path)
    return schema.names, json.loads(schema.metadata[STATS_KEY])


class ChunkedTableDownloader(Downloader):
    """Reduce one chunked table of the Gaia bulk repository to Parquet.

    `limit` stops the run once that many rows are kept. A later run continues
    from the chunks on disk.
    """

    # Path of the table below BULK_URL, and of its output below OUT_DIR.
    table_path: str
    select: Select
    columns: tuple[str, ...] | None = None
    exclude: tuple[str, ...] = ()
    # The integer counts that `select` reports, summed into metadata.json.
    count_keys: tuple[str, ...] = ()

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR / self.table_path
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.table_url = f"{BULK_URL}/{self.table_path}/"

    def companion(self, chunk: str) -> Path | None:
        """The file that `select` needs for this chunk, if any."""
        return None

    def selection(self) -> dict[str, object]:
        """The settings that decide what a chunk holds.

        metadata.json records them. A table written with other settings is not
        complete.
        """
        return {"columns": self.columns, "exclude": self.exclude}

    def is_current(self, stats: dict) -> bool:
        """False when a written chunk comes from other selection settings."""
        return True

    def is_complete(self, limit: int | None) -> bool:
        if not super().is_complete(limit):
            return False
        recorded = json.loads(self.metadata_file.read_text()).get("selection")
        return recorded == json.loads(json.dumps(self.selection()))

    def chunk_path(self, chunk: str) -> Path:
        return self.out_dir / (chunk.removesuffix(CHUNK_SUFFIX) + ".parquet")

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        sums = {
            name: md5
            for name, md5 in fetch_md5sums(
                self.client, self.table_url, self.out_dir
            ).items()
            if name.endswith(CHUNK_SUFFIX)
        }
        chunks = sorted(sums)
        if not chunks:
            raise DownloadError(f"{self.table_url}: no chunk in {MD5_FILE}")
        names = self._write_columns(chunks[0])

        done = self._written(chunks, names)
        todo = []
        waiting = 0
        for chunk in chunks:
            if chunk in done:
                continue
            companion = self.companion(chunk)
            if companion is not None and not companion.exists():
                waiting += 1
                continue
            todo.append(chunk)
        logger.info(
            "%s: %d chunks, %d written, %d to reduce, %d wait for the table they join",
            self.name,
            len(chunks),
            len(done),
            len(todo),
            waiting,
        )

        failed = self._reduce(todo, sums, done, limit)
        totals = {
            key: sum(stats[key] for stats in done.values())
            for key in ("rows_in", "rows_kept", *self.count_keys)
        }
        rows_kept = totals.pop("rows_kept")
        self._save_metadata(
            self.table_url,
            rows_kept,
            complete=len(done) == len(chunks),
            chunks=len(done),
            chunks_total=len(chunks),
            selection=self.selection(),
            **totals,
        )
        if failed:
            raise DownloadError(f"{len(failed)} chunks failed: {', '.join(failed)}")

    def _written(self, chunks: list[str], names: list[str]) -> dict[str, dict]:
        """The footer record of each chunk that is on disk and current."""
        present = [chunk for chunk in chunks if self.chunk_path(chunk).exists()]
        with ThreadPoolExecutor(32) as pool:
            records = pool.map(
                read_chunk_record, [self.chunk_path(chunk) for chunk in present]
            )
        done: dict[str, dict] = {}
        for chunk, (written_names, stats) in zip(present, records):
            if written_names != names or not self.is_current(stats):
                logger.info("%s: written with other settings, reducing again", chunk)
                continue
            done[chunk] = stats
        return done

    def _reduce(
        self,
        todo: list[str],
        sums: dict[str, str],
        done: dict[str, dict],
        limit: int | None,
    ) -> list[str]:
        """Reduce `todo` in worker processes. Returns the chunks that failed."""
        user_agent = self.client.headers["User-Agent"]
        workers = min(MAX_WORKERS, os.cpu_count() or 1)
        kept = sum(stats["rows_kept"] for stats in done.values())
        queue = iter(todo)
        pending: dict[Future, str] = {}
        failed: list[str] = []
        finished = 0
        pool_broke = False
        started = time.monotonic()

        # spawn: the parent holds an HTTP client and Arrow threads.
        with ProcessPoolExecutor(
            workers, mp_context=multiprocessing.get_context("spawn")
        ) as pool:
            while True:
                while (
                    not pool_broke
                    and len(pending) < workers
                    and (limit is None or kept < limit)
                    and (chunk := next(queue, None)) is not None
                ):
                    job = ChunkJob(
                        url=self.table_url + chunk,
                        md5=sums[chunk],
                        out=self.chunk_path(chunk),
                        user_agent=user_agent,
                        select=type(self).select,
                        columns=self.columns,
                        exclude=self.exclude,
                        companion=self.companion(chunk),
                    )
                    try:
                        pending[pool.submit(run_chunk, job)] = chunk
                    except BrokenProcessPool:
                        pool_broke = True
                        failed.append(chunk)
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
                    counts = {key: stats[key] for key in ("rows_in", *self.count_keys)}
                    minutes = (time.monotonic() - started) / 60
                    logger.info(
                        "[%d/%d] %s: kept %d %s, %.1f min",
                        finished,
                        len(todo),
                        chunk,
                        stats["rows_kept"],
                        counts,
                        minutes,
                    )
        if pool_broke:
            logger.error(
                "A worker process died, most likely out of memory. "
                "The chunks not started stay for the next run."
            )
        return failed

    def _write_columns(self, chunk: str) -> list[str]:
        """Record the type, unit and description of each kept column.

        Returns the column names that a current chunk has.
        """
        header = fetch_header(self.client, self.table_url + chunk)
        kept = kept_columns(header, self.columns, self.exclude)
        (self.out_dir / "columns.json").write_text(
            json.dumps([asdict(c) for c in kept], indent=2, ensure_ascii=False) + "\n"
        )
        return [column.name for column in kept]
