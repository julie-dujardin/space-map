"""File writes that survive a crash and do not fill the memory.

A writer that outruns a network mount keeps the unwritten data in memory,
and a run under a memory cap is then killed. A flush writes the data to disk
and drops its pages from the cache, because nothing reads them back.
"""

import os
from pathlib import Path
from typing import BinaryIO

import pyarrow as pa
import pyarrow.parquet as pq

# Bytes written to a network mount between two flushes to disk.
SYNC_BYTES = 64 << 20


def flush_to_disk(out: BinaryIO) -> None:
    """Write `out` to disk and drop its pages from the cache."""
    out.flush()
    os.fdatasync(out.fileno())
    os.posix_fadvise(out.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)


def write_parquet(table: pa.Table, path: Path, sync: bool = False) -> None:
    """Write `table` through a temporary file. `sync` flushes it to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    pq.write_table(table, part, compression="zstd")
    if sync:
        with part.open("rb+") as handle:
            os.fsync(handle.fileno())
    part.replace(path)
