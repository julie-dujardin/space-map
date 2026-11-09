"""File helpers for the registry and the tables."""

import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
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


def with_computed(
    rows: pa.Table,
    regions: tuple[int, ...],
    directory: Path,
    columns: list[str] | None = None,
    *,
    schema: pa.Schema | None = None,
) -> pa.Table:
    """`rows` with the computed `columns` (default: all) of their IDs, from
    the scratch files of `regions` in `directory`. A region with no rows has
    no file; when none of `regions` has one, `schema`, that of the files,
    types the columns."""
    read = None if columns is None else ["id", *columns]
    paths = [region_file(directory, r) for r in regions]
    parts = [pq.read_table(path, columns=read) for path in paths if path.exists()]
    if parts:
        found = pa.concat_tables(parts)
    elif schema is not None:
        found = schema.empty_table().select(read or schema.names)
    else:
        raise FileNotFoundError(f"{directory}: no scratch file of regions {regions}")
    at = pc.index_in(rows["id"], value_set=found["id"])
    if at.null_count:
        raise ValueError(f"{directory}: {at.null_count} rows have no computed values")
    taken = found.take(at)
    for field_ in found.schema:
        if field_.name != "id":
            rows = rows.append_column(field_, taken[field_.name])
    return rows


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
