"""File helpers for the registry and the tables."""

import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from space_map_data.utils.files import SYNC_BYTES, flush_to_disk

COPY_BLOCK = 8 << 20


def region_file(directory: Path, region: int) -> Path:
    return directory / f"{region:03d}.parquet"


def fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_parquet(
    paths: list[Path], schema: pa.Schema, columns: list[str] | None = None
) -> pa.Table:
    """The rows of `paths` in order, or an empty table of `schema`."""
    if columns is not None:
        schema = pa.schema([schema.field(name) for name in columns])
    tables = [pq.read_table(path, columns=columns) for path in paths]
    return pa.concat_tables(tables) if tables else schema.empty_table()


def write_json(path: Path, data: object) -> None:
    """Replace `path` with `data` in one step that survives a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with part.open("w") as handle:
        json.dump(data, handle, indent=1)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    part.replace(path)
    fsync_dir(path.parent)


def copy_synced(source: Path, target: Path) -> None:
    """Copy a file and flush it to disk as it goes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = 0
    with source.open("rb") as inp, target.open("wb") as out:
        while block := inp.read(COPY_BLOCK):
            out.write(block)
            pending += len(block)
            if pending >= SYNC_BYTES:
                flush_to_disk(out)
                pending = 0
        flush_to_disk(out)
