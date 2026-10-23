"""The ID of an object outside the solar system.

    id = serial·2^29 + table·2^24 + cell

- cell (bits 0–23): the HEALPix level-10 nested cell (ICRS) of the position at
  J2016.0 when the ID was minted, 0 to 12,582,911. It is never recomputed.
- table (bits 24–28): the home table, 1 to 30. 0 is never given, so no ID is 0.
  31 is kept to widen the field later.
- serial (bits 29 and up): the order of minting within its table and cell, from
  0. It is never reused.

An ID stays below 2^53, so a JavaScript number holds it exactly. The functions
take a Python int or a numpy int64 array.
"""

import re
from collections.abc import Collection
from typing import overload

import numpy as np

CELL_LEVEL = 10
CELL_COUNT = 12 * 4**CELL_LEVEL
CELL_BITS = 24
TABLE_BITS = 5
SERIAL_SHIFT = CELL_BITS + TABLE_BITS
CELL_MASK = (1 << CELL_BITS) - 1
TABLE_MASK = (1 << TABLE_BITS) - 1

FIRST_TABLE = 1
LAST_TABLE = 30
KEPT_TABLE = 31

MAX_ID = 2**53 - 1
MAX_SERIAL = MAX_ID >> SERIAL_SHIFT

# A bare decimal with no leading zero, short enough to stay under 2^53.
_URL_ID = re.compile(r"[1-9][0-9]{0,15}")


def _check(name: str, value: int | np.ndarray, low: int, high: int) -> None:
    if np.any(np.asarray(value) < low) or np.any(np.asarray(value) > high):
        raise ValueError(f"{name} outside {low}..{high}")


@overload
def encode(serial: int, table: int, cell: int) -> int: ...
@overload
def encode(
    serial: np.ndarray, table: int | np.ndarray, cell: np.ndarray
) -> np.ndarray: ...
def encode(serial, table, cell):
    _check("serial", serial, 0, MAX_SERIAL)
    _check("table", table, FIRST_TABLE, LAST_TABLE)
    _check("cell", cell, 0, CELL_COUNT - 1)
    if isinstance(serial, np.ndarray):
        serial = serial.astype(np.int64)
        table = np.asarray(table, np.int64)
        cell = np.asarray(cell, np.int64)
    return (serial << SERIAL_SHIFT) | (table << CELL_BITS) | cell


@overload
def cell_of(id_: int) -> int: ...
@overload
def cell_of(id_: np.ndarray) -> np.ndarray: ...
def cell_of(id_):
    return id_ & CELL_MASK


@overload
def table_of(id_: int) -> int: ...
@overload
def table_of(id_: np.ndarray) -> np.ndarray: ...
def table_of(id_):
    return (id_ >> CELL_BITS) & TABLE_MASK


@overload
def serial_of(id_: int) -> int: ...
@overload
def serial_of(id_: np.ndarray) -> np.ndarray: ...
def serial_of(id_):
    return id_ >> SERIAL_SHIFT


@overload
def decode(id_: int) -> tuple[int, int, int]: ...
@overload
def decode(id_: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]: ...
def decode(id_):
    """The (serial, table, cell) of `id_`."""
    return serial_of(id_), table_of(id_), cell_of(id_)


def parse(text: str, tables: Collection[int]) -> int | None:
    """The ID that a URL segment names, or None when the URL is a 404.

    `tables` are the table numbers that the export lists. The frontend has its
    own copy of this check.
    """
    if not _URL_ID.fullmatch(text):
        return None
    id_ = int(text)
    if id_ > MAX_ID or cell_of(id_) >= CELL_COUNT or table_of(id_) not in tables:
        return None
    return id_
