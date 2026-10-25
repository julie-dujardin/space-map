"""Download the XP metallicities of Andrae, Rix & Chandra (2023).

XGBoost gives [M/H], Teff and log g from the Gaia DR3 XP spectra, CatWISE
photometry and the parallax. APOGEE DR17 and very metal-poor stars are the
training set. Table 1 has 174,922,161 stars and no quality cut. Table 2 is a
vetted sample of 17,558,141 red giants with the same values, so this provider
keeps only its membership, as `in_vetted_rgb_sample`.

The authors' advice (Sect. 3.5, 3.7 and 4.3): [M/H] is not valid for OBA
stars. On the main sequence it is unbiased for 0.5 < BP - RP < 1.5, about
0.15 dex too low for 1.5 < BP - RP < 2.5, and not valid outside that. Stars
with G > 17.65 are out of the training range. Teff cannot mark a hot star,
because its values stay near the training range: 2975 K to 7076 K in Table 1.
To remove the OBA stars they name the Gaia DR3 golden sample of OBA stars
(Gaia Collaboration, Creevey et al. 2023), so its membership is kept too, as
`in_oba_golden_sample`.

A reduction reads the deposit: the two Zenodo tables and the golden sample
file. The deposit is fetched only when a chunk needs a reduction, into
zenodo/, which holds nothing else. It is removed when every chunk is written,
as gaia_source never keeps its ECSV. Each output file holds the rows of the
stars that one gaia_source chunk kept. A run with a record limit reduces
nothing. Table 1 is one file, so any part of the table needs the whole deposit.

Writes, below sources/stars/gaia/gdr3/andrae2023_xgboost/:
- XgboostParameters_<pixels>.parquet   the kept rows of one gaia_source chunk
- columns.json                         type, unit and description of each column
- metadata.json                        with the MD5 of each deposit file
- zenodo/                              the deposit, only while chunks are missing

Licence: CC BY 4.0. Cite Andrae, Rix & Chandra 2023, ApJS 267, 8. The values
derive from Gaia, CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC. The golden sample is
Gaia DR3 data, CC BY-NC 3.0 IGO.
"""

import json
import logging
import shutil
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import httpx
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.catalogues.fetch import md5_of
from space_map_data.download.providers.stars import gaia_bulk, gaia_source
from space_map_data.download.providers.stars.gaia_bulk import (
    ARROW_TYPES,
    BULK_URL,
    CHUNK_SUFFIX,
    MD5_FILE,
    STATS_KEY,
    ChunkedTableDownloader,
    Column,
    fetch_md5sums,
    read_table,
)
from space_map_data.download.providers.three_d.resumable import download_resumable
from space_map_data.utils.arrays import find_sorted
from space_map_data.utils.files import SYNC_BYTES, write_parquet

logger = logging.getLogger(__name__)

RECORD = 7945154
RECORD_URL = f"https://zenodo.org/api/records/{RECORD}"
TABLE_PATH = f"{gaia_source.RELEASE}/andrae2023_xgboost"
CHUNK_PREFIX = "XgboostParameters_"
DEPOSIT_DIR = "zenodo"
ALL_STARS = "table_1_catwise.csv.gz"
VETTED_RGB = "table_2_catwise.csv.gz"
VETTED = "in_vetted_rgb_sample"
OBA_URL = (
    f"{BULK_URL}/{gaia_source.RELEASE}/Performance_verification/gold_sample_oba_stars/"
)
OBA_FILE = "GoldSampleObaStars.csv.gz"
OBA = "in_oba_golden_sample"
# Type, unit and description of each column, from the paper's data model.
COLUMNS: dict[str, tuple[pa.DataType, str | None, str]] = {
    "source_id": (pa.int64(), None, "Gaia DR3 source_id"),
    "mh_xgboost": (pa.float32(), "dex", "XGBoost estimate of [M/H]"),
    "teff_xgboost": (pa.float32(), "K", "XGBoost estimate of Teff"),
    "logg_xgboost": (pa.float32(), "log(cm.s**-2)", "XGBoost estimate of log g"),
    "catwise_w1": (pa.float32(), "mag", "CatWISE2020 W1 magnitude (Vega)"),
    "catwise_w2": (pa.float32(), "mag", "CatWISE2020 W2 magnitude (Vega)"),
    "in_training_sample": (
        pa.bool_(),
        None,
        "True for a star of the XGBoost training sample",
    ),
    VETTED: (
        pa.bool_(),
        None,
        "True for a star of Table 2, the vetted red-giant sample",
    ),
    OBA: (
        pa.bool_(),
        None,
        "True for a star of the Gaia DR3 golden sample of OBA stars",
    ),
}
DATATYPES = {kind: name for name, kind in ARROW_TYPES.items()}
SCHEMA = pa.schema([(name, kind) for name, (kind, _, _) in COLUMNS.items()])
TABLE_COLUMNS = [name for name in SCHEMA.names if name not in (VETTED, OBA)]
WORKERS = 8
# The Zenodo files as Zenodo stores them, for the MD5 check.
_AS_STORED = {"Accept-Encoding": "identity"}


def open_table(path: Path, names: list[str]) -> pcsv.CSVStreamingReader:
    return pcsv.open_csv(
        path,
        read_options=pcsv.ReadOptions(block_size=64 << 20),
        convert_options=pcsv.ConvertOptions(
            include_columns=names,
            column_types={name: COLUMNS[name][0] for name in names},
        ),
    )


def read_ids(path: Path) -> np.ndarray:
    """The sorted source ids of a table."""
    parts = [
        batch.column("source_id").to_numpy()
        for batch in open_table(path, ["source_id"])
    ]
    ids = np.concatenate(parts) if parts else np.zeros(0, np.int64)
    if np.any(np.diff(ids) <= 0):
        raise DownloadError(f"{path.name} is not sorted by source_id")
    return ids


class GaiaXpMetallicityDownloader(ChunkedTableDownloader):
    """One file per gaia_source chunk, from the two tables of the deposit.

    Table 1 is sorted by source_id, so one pass over it fills the chunks in
    order. This class has its own `download` and `chunk_path`.
    """

    name = PROVIDERS.GAIA_XP_METALLICITY
    table_path = TABLE_PATH

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.source_dir = gaia_bulk.OUT_DIR / gaia_source.TABLE_PATH
        self.deposit_dir = self.out_dir / DEPOSIT_DIR

    def selection(self) -> dict[str, object]:
        return {
            "columns": SCHEMA.names,
            "min_parallax_over_error": gaia_source.MIN_PARALLAX_OVER_ERROR,
            "zenodo_record": RECORD,
            "oba_golden_sample": OBA_URL + OBA_FILE,
        }

    def is_current(self, stats: dict) -> bool:
        return (
            stats["min_parallax_over_error"] == gaia_source.MIN_PARALLAX_OVER_ERROR
            and stats["zenodo_record"] == RECORD
        )

    def chunk_path(self, chunk: str) -> Path:
        pixels = chunk.removeprefix(gaia_source.CHUNK_PREFIX).removesuffix(CHUNK_SUFFIX)
        return self.out_dir / f"{CHUNK_PREFIX}{pixels}.parquet"

    def source_path(self, chunk: str) -> Path:
        return self.source_dir / (chunk.removesuffix(CHUNK_SUFFIX) + ".parquet")

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        md5_file = self.source_dir / MD5_FILE
        if not md5_file.exists():
            raise DownloadError(f"{md5_file} is missing: run gaia_source first")
        chunks = sorted(
            name for name in md5_file.read_text().split() if name.endswith(CHUNK_SUFFIX)
        )
        self._describe_columns()
        done = self._written(chunks, SCHEMA.names)
        todo = {
            chunk
            for chunk in chunks
            if chunk not in done and self.source_path(chunk).exists()
        }
        logger.info(
            "%s: %d chunks, %d written, %d to reduce, %d wait for gaia_source",
            self.name,
            len(chunks),
            len(done),
            len(todo),
            len(chunks) - len(done) - len(todo),
        )
        sums = self._recorded_files()
        if todo and limit is not None:
            logger.info("%s: a run with a record limit fetches no deposit", self.name)
        elif todo:
            sums = self._fetch_deposit()
            self._reduce_table(chunks, todo, done)
        totals = {
            key: sum(stats[key] for stats in done.values())
            for key in (
                "rows_kept",
                "rows_in",
                "stars",
                "stars_without_row",
                "vetted",
                "oba",
            )
        }
        complete = len(done) == len(chunks)
        self._save_metadata(
            RECORD_URL,
            totals.pop("rows_kept"),
            complete=complete,
            chunks=len(done),
            chunks_total=len(chunks),
            selection=self.selection(),
            files=sums,
            **totals,
        )
        if complete and self.deposit_dir.exists():
            shutil.rmtree(self.deposit_dir)
            logger.info("%s: every chunk is written, deposit removed", self.name)

    def _recorded_files(self) -> dict[str, str]:
        """The deposit MD5s of the last run that reduced a chunk."""
        if not self.metadata_file.exists():
            return {}
        return json.loads(self.metadata_file.read_text()).get("files", {})

    def _fetch_deposit(self) -> dict[str, str]:
        """Fetch the deposit files that the disk lacks. Returns their MD5."""
        response = self.client.get(RECORD_URL)
        response.raise_for_status()
        try:
            files = {entry["key"]: entry for entry in response.json()["files"]}
            wanted = {
                name: (
                    files[name]["links"]["self"],
                    files[name]["checksum"].removeprefix("md5:"),
                )
                for name in (ALL_STARS, VETTED_RGB)
            }
        except (ValueError, KeyError, TypeError) as error:
            raise DownloadError(
                f"Zenodo {RECORD}: unexpected record, {error!r}"
            ) from error
        self.deposit_dir.mkdir(exist_ok=True)
        (self.deposit_dir / "record.json").write_bytes(response.content)
        oba_sums = fetch_md5sums(self.client, OBA_URL, self.deposit_dir)
        if OBA_FILE not in oba_sums:
            raise DownloadError(f"{OBA_URL}{MD5_FILE} does not list {OBA_FILE}")
        wanted[OBA_FILE] = (OBA_URL + OBA_FILE, oba_sums[OBA_FILE])
        for name, (url, md5) in wanted.items():
            dest = self.deposit_dir / name
            # A file takes its name only after its MD5 check.
            if dest.exists():
                continue

            def check(path: Path, md5: str = md5) -> None:
                found = md5_of(path)
                if found != md5:
                    raise DownloadError(f"{path.name}: MD5 {found}, expected {md5}")

            if not download_resumable(
                self.client,
                url,
                dest,
                headers=_AS_STORED,
                check=check,
                sync_bytes=SYNC_BYTES,
            ):
                raise DownloadError(f"{url}: the fetch failed")
        return {name: md5 for name, (_, md5) in wanted.items()}

    def _describe_columns(self) -> None:
        columns = [
            Column(name, DATATYPES[kind], unit, description)
            for name, (kind, unit, description) in COLUMNS.items()
        ]
        (self.out_dir / "columns.json").write_text(
            json.dumps([asdict(c) for c in columns], indent=2, ensure_ascii=False)
            + "\n"
        )

    def _reduce_table(
        self,
        chunks: list[str],
        todo: set[str],
        done: dict[str, dict],
    ) -> None:
        """Write the chunks of `todo` in one pass over Table 1."""
        vetted = read_ids(self.deposit_dir / VETTED_RGB)
        oba = np.sort(
            read_table((self.deposit_dir / OBA_FILE).read_bytes(), ["source_id"])[
                "source_id"
            ].to_numpy()
        )
        ranges = np.array([gaia_source.pixel_range(c) for c in chunks], np.int64)
        if np.any(ranges[1:, 0] != ranges[:-1, 1] + 1):
            raise DownloadError("the gaia_source chunks leave a gap between pixels")
        starts = ranges[:, 0] << gaia_source.PIXEL_SHIFT
        end = (ranges[-1, 1] + 1) << gaia_source.PIXEL_SHIFT
        pending: deque[tuple[str, Future[dict]]] = deque()
        parts: list[pa.Table] = []
        current = 0
        last_id = -1
        started = time.monotonic()
        empty = pa.schema([SCHEMA.field(name) for name in TABLE_COLUMNS]).empty_table()

        with ThreadPoolExecutor(WORKERS) as pool:

            def collect(wait_all: bool) -> None:
                while pending and (wait_all or len(pending) > 2 * WORKERS):
                    chunk, future = pending.popleft()
                    stats = future.result()
                    done[chunk] = stats
                    logger.info(
                        "%s: kept %d of %d, %d vetted, %.1f min",
                        chunk,
                        stats["rows_kept"],
                        stats["rows_in"],
                        stats["vetted"],
                        (time.monotonic() - started) / 60,
                    )

            def close_until(index: int) -> None:
                """Write the chunks before `index`, with the rows read so far."""
                nonlocal current, parts
                while current < index:
                    chunk = chunks[current]
                    if chunk in todo:
                        rows = pa.concat_tables(parts) if parts else empty
                        future = pool.submit(
                            self._write_chunk, chunk, rows, vetted, oba
                        )
                        pending.append((chunk, future))
                        collect(wait_all=False)
                    parts = []
                    current += 1

            for batch in open_table(self.deposit_dir / ALL_STARS, TABLE_COLUMNS):
                table = pa.Table.from_batches([batch])
                ids = table["source_id"].to_numpy()
                if not ids.size:
                    continue
                if ids[0] <= last_id or np.any(np.diff(ids) <= 0):
                    raise DownloadError(f"{ALL_STARS} is not sorted by source_id")
                if ids[0] < starts[0] or ids[-1] >= end:
                    raise DownloadError(f"{ALL_STARS} has a star outside the chunks")
                last_id = int(ids[-1])
                which = np.searchsorted(starts, ids, "right") - 1
                cuts = np.flatnonzero(np.diff(which)) + 1
                for low, high in zip(np.r_[0, cuts], np.r_[cuts, ids.size]):
                    close_until(int(which[low]))
                    parts.append(table.slice(low, high - low))
            close_until(len(chunks))
            collect(wait_all=True)

    def _write_chunk(
        self, chunk: str, rows: pa.Table, vetted: np.ndarray, oba: np.ndarray
    ) -> dict:
        """Write the rows of the stars that one gaia_source chunk kept."""
        stars = pq.read_table(self.source_path(chunk), columns=["source_id"])
        selection = json.loads(stars.schema.metadata[STATS_KEY])
        if selection["min_parallax_over_error"] != gaia_source.MIN_PARALLAX_OVER_ERROR:
            raise DownloadError(f"{chunk} is from another threshold: run gaia_source")
        kept = rows.filter(
            pc.is_in(rows["source_id"], value_set=stars["source_id"].combine_chunks())
        )
        ids = kept["source_id"].to_numpy()
        flag = find_sorted(vetted, ids) >= 0
        hot = find_sorted(oba, ids) >= 0
        kept = kept.append_column(VETTED, pa.array(flag))
        kept = kept.append_column(OBA, pa.array(hot))
        stats: dict[str, object] = {
            "source": chunk,
            "zenodo_record": RECORD,
            "rows_in": rows.num_rows,
            "stars": stars.num_rows,
            "stars_without_row": stars.num_rows - kept.num_rows,
            "vetted": int(flag.sum()),
            "oba": int(hot.sum()),
            "min_parallax_over_error": selection["min_parallax_over_error"],
            "rows_kept": kept.num_rows,
        }
        write_parquet(
            kept.cast(SCHEMA).replace_schema_metadata(
                {STATS_KEY: json.dumps(stats).encode()}
            ),
            self.chunk_path(chunk),
            sync=True,
            level=9,
        )
        return stats
