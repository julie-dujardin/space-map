"""The binary container of every extrasolar file.

A file is gzip around one payload. The payload is little-endian:

    0   char[4]   magic "SMXS"
    4   uint16    format version
    6   uint8     kind (KIND_*)
    7   uint8     0
    8   char[16]  token of the tree or table, ASCII hex
    24  uint32    row count n
    28  uint16    column count
    30  uint16    info length h, a multiple of 8
    32  info      h bytes that the kind defines
    32+h          column directory, then the buffers

A directory entry is uint8 type, uint8 flags, uint8 buffer count b, uint8
name length, the UTF-8 name, then b pairs of uint32 (offset, length). Offsets
count from the start of the payload, and each buffer starts at a multiple of
8, so a browser reads it as a typed array without a copy. Flag bit 0: the
first buffer is a validity bitmap (bit i of byte i >> 3 is 1 when row i has a
value). A null float is also NaN, and a null integer is 0.

The first 32 bytes are a stored deflate block, so the token sits at a fixed
place in the gzip file. A file is written with a zero token, which the
payload hash of the token leaves out, and the token is written in afterwards.
"""

import gzip
import hashlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.extrasolar.ids import MAX_ID
from space_map_data.extrasolar.tables import CROSS_ID

MAGIC = b"SMXS"
VERSION = 1
HEADER = struct.Struct("<4sHBB16sIHH")
TOKEN_AT = 8
TOKEN_SIZE = 16
ZERO_TOKEN = b"\0" * TOKEN_SIZE

KIND_TILE = 1
KIND_SPLIT = 2
KIND_NODE = 3
KIND_IDS = 4

LEVEL = 9
# Gzip header with mtime 0 and no file name, so the bytes are deterministic.
GZIP_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"
# Not the last block, stored, 32 bytes.
STORED_BLOCK = b"\x00" + struct.pack("<HH", HEADER.size, 0xFFFF ^ HEADER.size)
TOKEN_IN_FILE = len(GZIP_HEADER) + len(STORED_BLOCK) + TOKEN_AT

HAS_VALIDITY = 1

# Type codes. "id" is an integer ID below 2^53 in a float64, so a browser
# gets an exact number without BigInt.
TYPES = {
    "bool": 1,
    "int8": 2,
    "int16": 3,
    "int32": 4,
    "uint8": 5,
    "uint16": 6,
    "uint32": 7,
    "float32": 8,
    "float64": 9,
    "id": 10,
    "string": 11,
    "dict": 12,
    "cross_ids": 13,
    "bits": 14,
}
TYPE_NAMES = {code: name for name, code in TYPES.items()}
NUMPY = {
    "bool": np.uint8,
    "int8": np.int8,
    "int16": np.int16,
    "int32": np.int32,
    "uint8": np.uint8,
    "uint16": np.uint16,
    "uint32": np.uint32,
    "float32": np.float32,
    "float64": np.float64,
    "id": np.float64,
}
ARROW = {
    "bool": pa.bool_(),
    "int8": pa.int8(),
    "int16": pa.int16(),
    "int32": pa.int32(),
    "uint8": pa.uint8(),
    "uint16": pa.uint16(),
    "uint32": pa.uint32(),
    "float32": pa.float32(),
    "float64": pa.float64(),
    "id": pa.int64(),
    "string": pa.string(),
    "dict": pa.string(),
    "cross_ids": pa.list_(CROSS_ID),
    "bits": pa.bool_(),
}
_FROM_ARROW = {
    pa.bool_(): "bool",
    pa.int8(): "int8",
    pa.int16(): "int16",
    pa.int32(): "int32",
    pa.uint8(): "uint8",
    pa.uint16(): "uint16",
    pa.uint32(): "uint32",
    pa.float32(): "float32",
    pa.float64(): "float64",
    pa.int64(): "id",
    pa.string(): "string",
}


class FormatError(Exception):
    pass


def column_type(field: pa.Field, dictionary: frozenset[str] = frozenset()) -> str:
    """The container type of an Arrow field. `dictionary` names string columns
    with few distinct values."""
    kind = _FROM_ARROW.get(field.type)
    if pa.types.is_list(field.type) and field.type.value_type == CROSS_ID:
        kind = "cross_ids"
    if kind is None:
        raise FormatError(f"{field.name}: no container type for {field.type}")
    if kind == "string" and field.name in dictionary:
        return "dict"
    return kind


@dataclass(frozen=True)
class Column:
    name: str
    kind: str
    # The values. Arrow for every type but "bits", which takes a numpy bool array.
    values: pa.Array | np.ndarray


def _validity(array: pa.Array) -> bytes | None:
    if not array.null_count:
        return None
    valid = array.is_valid().to_numpy(zero_copy_only=False)
    return np.packbits(valid, bitorder="little").tobytes()


def _strings(array: pa.Array) -> list[bytes]:
    """Offsets (uint32, n + 1) and UTF-8 bytes of a string array."""
    array = array.cast(pa.string())
    if not len(array):
        return [np.zeros(1, np.uint32).tobytes(), b""]
    _, offset_buffer, data = array.buffers()
    offsets = np.frombuffer(
        offset_buffer, np.int32, len(array) + 1, 4 * array.offset
    ).astype(np.int64)
    payload = b"" if data is None else data.to_pybytes()[offsets[0] : offsets[-1]]
    return [(offsets - offsets[0]).astype(np.uint32).tobytes(), payload]


def _dictionary(array: pa.Array) -> tuple[np.ndarray, pa.Array]:
    """uint16 codes in order of first use, and the distinct values."""
    encoded = pc.dictionary_encode(array)
    if len(encoded.dictionary) > 0xFFFF:
        raise FormatError("a dictionary column holds over 65,535 values")
    codes = encoded.indices.fill_null(0).to_numpy().astype(np.uint16)
    return codes, encoded.dictionary


def _buffers(column: Column, rows: int) -> tuple[int, list[bytes]]:
    """The flags and buffers of one column."""
    if column.kind == "bits":
        values = np.asarray(column.values, bool)
        return 0, [np.packbits(values, bitorder="little").tobytes()]
    array = column.values
    if isinstance(array, pa.ChunkedArray):
        array = array.combine_chunks()
    if len(array) != rows:
        raise FormatError(f"{column.name}: {len(array)} values for {rows} rows")
    validity = _validity(array)
    flags = HAS_VALIDITY if validity is not None else 0
    out = [validity] if validity is not None else []
    kind = column.kind
    if kind in NUMPY:
        if kind == "id":
            ints = array.fill_null(0).to_numpy()
            if ints.size and (ints.min() < 0 or ints.max() > MAX_ID):
                raise FormatError(f"{column.name}: an ID outside 0..2^53")
            data = ints.astype(np.float64)
        elif pa.types.is_floating(array.type):
            data = array.fill_null(np.nan).to_numpy(zero_copy_only=False)
        elif kind == "bool":
            data = array.fill_null(False).to_numpy(zero_copy_only=False)
        else:
            data = array.fill_null(0).to_numpy(zero_copy_only=False)
        out.append(np.ascontiguousarray(data, NUMPY[kind]).tobytes())
    elif kind == "string":
        out += _strings(array)
    elif kind == "dict":
        codes, values = _dictionary(array)
        out += [codes.tobytes(), *_strings(values)]
    elif kind == "cross_ids":
        offsets = array.offsets.to_numpy().astype(np.int64)
        items = array.values.slice(offsets[0], offsets[-1] - offsets[0])
        pairs = pc.binary_join_element_wise(
            items.field("catalogue"), items.field("release"), "\0"
        )
        codes, values = _dictionary(pairs)
        split = pc.split_pattern(values, "\0")
        flat = pc.list_flatten(split)
        out += [
            (offsets - offsets[0]).astype(np.uint32).tobytes(),
            codes.tobytes(),
            *_strings(items.field("catalogue_id")),
            *_strings(flat),
        ]
    else:
        raise FormatError(f"{column.name}: unknown type {kind}")
    return flags, out


def _pad(size: int) -> int:
    return -size % 8


def encode(
    kind: int,
    rows: int,
    columns: list[Column],
    info: bytes = b"",
    token: bytes = ZERO_TOKEN,
) -> bytes:
    """The payload of one file."""
    if len(info) % 8:
        raise FormatError("the info block must be a multiple of 8 bytes")
    encoded = [(column, *_buffers(column, rows)) for column in columns]
    names = [column.name.encode() for column in columns]
    directory = sum(
        4 + len(name) + 8 * len(bufs) for name, (_, _, bufs) in zip(names, encoded)
    )
    at = HEADER.size + len(info) + directory
    at += _pad(at)
    places: list[list[tuple[int, int]]] = []
    for _, _, bufs in encoded:
        place = []
        for buf in bufs:
            place.append((at, len(buf)))
            at += len(buf) + _pad(len(buf))
        places.append(place)

    out = bytearray(
        HEADER.pack(MAGIC, VERSION, kind, 0, token, rows, len(columns), len(info))
    )
    out += info
    for name, (column, flags, bufs), place in zip(names, encoded, places):
        out += struct.pack("<BBBB", TYPES[column.kind], flags, len(bufs), len(name))
        out += name
        for offset, length in place:
            out += struct.pack("<II", offset, length)
    out += b"\0" * _pad(len(out))
    for _, _, bufs in encoded:
        for buf in bufs:
            out += buf
            out += b"\0" * _pad(len(buf))
    return bytes(out)


def gzip_payload(payload: bytes, level: int = LEVEL) -> bytes:
    """Gzip with the 32-byte header in a stored block of its own."""
    deflate = zlib.compressobj(level, zlib.DEFLATED, -15, 9)
    body = deflate.compress(payload[HEADER.size :]) + deflate.flush()
    trailer = struct.pack("<II", zlib.crc32(payload), len(payload) & 0xFFFFFFFF)
    return GZIP_HEADER + STORED_BLOCK + payload[: HEADER.size] + body + trailer


@dataclass(frozen=True)
class Written:
    """A file written with a zero token."""

    path: str
    digest: bytes
    rows: int
    size: int


def write(root: Path, path: str, payload: bytes) -> Written:
    """Write `payload` at `root / path` and return its hash for the token."""
    if payload[TOKEN_AT : TOKEN_AT + TOKEN_SIZE] != ZERO_TOKEN:
        raise FormatError(f"{path}: a payload is written with a zero token")
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    data = gzip_payload(payload)
    target.write_bytes(data)
    rows = HEADER.unpack_from(payload)[5]
    return Written(path, hashlib.sha256(payload).digest(), rows, len(data))


def token_of(files: list[Written]) -> str:
    """16 hex digits over the paths and payload hashes of a tree or table."""
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda f: f.path):
        digest.update(item.path.encode() + b"\0" + item.digest)
    return digest.hexdigest()[:TOKEN_SIZE]


def patch_token(path: Path, token: str) -> None:
    """Write `token` into a file that has a zero token.

    CRC-32 is affine, so the new CRC is the old one xor the CRC of the change
    xor the CRC of zeros of the same length.
    """
    new = token.encode()
    with path.open("r+b") as handle:
        handle.seek(TOKEN_IN_FILE)
        if handle.read(TOKEN_SIZE) != ZERO_TOKEN:
            raise FormatError(f"{path} already has a token")
        handle.seek(-8, 2)
        crc, size = struct.unpack("<II", handle.read(8))
        tail = bytes(size - TOKEN_AT - TOKEN_SIZE)
        change = zlib.crc32(tail, zlib.crc32(bytes(TOKEN_AT) + new))
        zeros = zlib.crc32(tail, zlib.crc32(bytes(TOKEN_AT + TOKEN_SIZE)))
        handle.seek(TOKEN_IN_FILE)
        handle.write(new)
        handle.seek(-8, 2)
        handle.write(struct.pack("<I", crc ^ change ^ zeros))


# Reading


@dataclass
class Container:
    kind: int
    token: str
    rows: int
    info: bytes
    columns: dict[str, tuple[str, pa.Array]]

    def column(self, name: str) -> pa.Array:
        return self.columns[name][1]

    def numpy(self, name: str) -> np.ndarray:
        """A column without nulls as numpy, or with NaN for null floats."""
        return np.asarray(self.column(name).to_numpy(zero_copy_only=False))

    def table(self) -> pa.Table:
        return pa.table({name: values for name, (_, values) in self.columns.items()})


def _view(data: bytes, place: tuple[int, int], dtype) -> np.ndarray:
    offset, length = place
    return np.frombuffer(data, dtype, length // np.dtype(dtype).itemsize, offset)


def _string_array(
    data: bytes,
    offsets: tuple[int, int],
    values: tuple[int, int],
    n: int,
    validity: pa.Buffer | None,
) -> pa.Array:
    offs = _view(data, offsets, np.uint32).astype(np.int32)
    raw = data[values[0] : values[0] + values[1]]
    return pa.StringArray.from_buffers(
        n, pa.py_buffer(offs.tobytes()), pa.py_buffer(raw), validity
    )


def _decode(
    data: bytes, kind: str, flags: int, places: list[tuple[int, int]], n: int
) -> pa.Array:
    if kind == "bits":
        bits = _view(data, places[0], np.uint8)
        return pa.array(np.unpackbits(bits, bitorder="little")[:n].astype(bool))
    validity = None
    mask = None
    if flags & HAS_VALIDITY:
        offset, length = places[0]
        validity = pa.py_buffer(data[offset : offset + length])
        bits = np.unpackbits(_view(data, places[0], np.uint8), bitorder="little")[:n]
        mask = bits == 0
        places = places[1:]
    if kind in NUMPY:
        values = _view(data, places[0], NUMPY[kind])
        if kind == "id":
            values = values.astype(np.int64)
        elif kind == "bool":
            values = values.astype(bool)
        return pa.array(values, ARROW[kind], mask=mask)
    if kind == "string":
        return _string_array(data, places[0], places[1], n, validity)
    if kind == "dict":
        codes = _view(data, places[0], np.uint16)
        values = _string_array(
            data,
            places[1],
            places[2],
            int(len(_view(data, places[1], np.uint32)) - 1),
            None,
        )
        return values.take(pa.array(codes.astype(np.int32), mask=mask))
    if kind == "cross_ids":
        list_offsets = _view(data, places[0], np.uint32).astype(np.int32)
        codes = _view(data, places[1], np.uint16).astype(np.int32)
        m = len(codes)
        ids = _string_array(data, places[2], places[3], m, None)
        k2 = len(_view(data, places[4], np.uint32)) - 1
        pairs = _string_array(data, places[4], places[5], k2, None)
        catalogue = pairs.take(pa.array(2 * codes))
        release = pairs.take(pa.array(2 * codes + 1))
        items = pa.StructArray.from_arrays(
            [catalogue, release, ids], fields=list(CROSS_ID)
        )
        return pa.ListArray.from_arrays(
            pa.array(list_offsets),
            items,
            type=pa.list_(CROSS_ID),
            mask=None if mask is None else pa.array(mask),
        )
    raise FormatError(f"unknown type {kind}")


def decode(payload: bytes) -> Container:
    magic, version, kind, _, token, rows, count, info_size = HEADER.unpack_from(payload)
    if magic != MAGIC:
        raise FormatError("not an extrasolar file")
    if version != VERSION:
        raise FormatError(f"format version {version}, this code reads {VERSION}")
    at = HEADER.size
    info = payload[at : at + info_size]
    at += info_size
    columns: dict[str, tuple[str, pa.Array | np.ndarray]] = {}
    for _ in range(count):
        code, flags, nbuf, name_size = struct.unpack_from("<BBBB", payload, at)
        at += 4
        name = payload[at : at + name_size].decode()
        at += name_size
        places = [struct.unpack_from("<II", payload, at + 8 * i) for i in range(nbuf)]
        at += 8 * nbuf
        type_name = TYPE_NAMES[code]
        columns[name] = (type_name, _decode(payload, type_name, flags, places, rows))
    return Container(kind, token.decode(), rows, info, columns)


def read(path: Path) -> Container:
    return decode(gzip.decompress(path.read_bytes()))
