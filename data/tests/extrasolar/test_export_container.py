import gzip
import struct

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.export.extrasolar import container
from space_map_data.export.extrasolar.container import Column
from space_map_data.export.extrasolar.tiles import ROOTS, Split, units
from space_map_data.extrasolar.ids import CELL_COUNT, CELL_LEVEL
from space_map_data.extrasolar.tables import CROSS_ID


def _sample() -> list[Column]:
    cross = pa.array(
        [
            [{"catalogue": "gaia", "release": "dr3", "catalogue_id": "123"}],
            None,
            [
                {"catalogue": "hip", "release": "2007", "catalogue_id": "7"},
                {"catalogue": "iau", "release": "wgsn", "catalogue_id": "Sîrius"},
            ],
        ],
        pa.list_(CROSS_ID),
    )
    return [
        Column("id", "id", pa.array([1, 2**53 - 1, 33554432], pa.int64())),
        Column("ra", "float64", pa.array([1.5, None, -3.25])),
        Column("mag", "float32", pa.array([1.0, 2.0, None], pa.float32())),
        Column("n", "int16", pa.array([None, -5, 7], pa.int16())),
        Column("ok", "bool", pa.array([True, None, False])),
        Column("mask", "uint32", pa.array([2, 0, 4294967295], pa.uint32())),
        Column("name", "string", pa.array(["α Cen", None, ""])),
        Column("source", "dict", pa.array(["gaia-dr3", "hipparcos-2007", None])),
        Column("cross_ids", "cross_ids", cross),
    ]


class TestContainer:
    """The payload layout, its round trip and the token patch."""

    def test_round_trip(self):
        columns = _sample()
        payload = container.encode(container.KIND_TILE, 3, columns, b"\1" * 8)
        out = container.decode(payload)
        assert out.kind == container.KIND_TILE and out.rows == 3
        assert out.info == b"\1" * 8
        for column in columns:
            kind, values = out.columns[column.name]
            assert kind == column.kind
            assert isinstance(column.values, pa.Array)
            assert values.to_pylist() == column.values.to_pylist(), column.name
        assert np.isnan(out.numpy("ra")[1])

    def test_buffers_are_aligned_views(self):
        payload = container.encode(container.KIND_TILE, 3, _sample())
        magic, _, _, _, _, rows, count, info = container.HEADER.unpack_from(payload)
        assert magic == b"SMXS" and rows == 3 and count == 9
        at = container.HEADER.size + info
        for _ in range(count):
            code, _, nbuf, size = struct.unpack_from("<BBBB", payload, at)
            at += 4 + size
            for i in range(nbuf):
                offset, length = struct.unpack_from("<II", payload, at + 8 * i)
                assert offset % 8 == 0 and offset + length <= len(payload)
            if container.TYPE_NAMES[code] == "id":
                offset, _ = struct.unpack_from("<II", payload, at + 8 * (nbuf - 1))
                values = np.frombuffer(payload, np.float64, 3, offset)
                assert values.tolist() == [1, 2**53 - 1, 33554432]
            at += 8 * nbuf

    def test_empty_and_bits(self):
        columns = [
            Column("id", "id", pa.array([], pa.int64())),
            Column("name", "string", pa.array([], pa.string())),
            Column("cross_ids", "cross_ids", pa.array([], pa.list_(CROSS_ID))),
        ]
        out = container.decode(container.encode(container.KIND_TILE, 0, columns))
        assert out.rows == 0 and out.table().num_rows == 0
        bits = np.array([True, False, True] * 7)
        out = container.decode(
            container.encode(container.KIND_SPLIT, 21, [Column("split", "bits", bits)])
        )
        assert out.numpy("split").tolist() == bits.tolist()

    def test_ids_past_2_53_are_refused(self):
        with pytest.raises(container.FormatError):
            container.encode(
                container.KIND_IDS,
                1,
                [Column("id", "id", pa.array([2**53], pa.int64()))],
            )

    def test_gzip_is_deterministic_and_patchable(self, tmp_path):
        payload = container.encode(container.KIND_TILE, 3, _sample())
        assert container.gzip_payload(payload) == container.gzip_payload(payload)
        written = container.write(tmp_path, "a/b.bin.gz", payload)
        path = tmp_path / "a" / "b.bin.gz"
        assert gzip.decompress(path.read_bytes()) == payload
        container.patch_token(path, "0123456789abcdef")
        patched = gzip.decompress(path.read_bytes())
        assert patched[8:24] == b"0123456789abcdef"
        assert patched[24:] == payload[24:]
        assert container.read(path).token == "0123456789abcdef"
        with pytest.raises(container.FormatError):
            container.patch_token(path, "fedcba9876543210")
        assert written.rows == 3

    def test_token_ignores_order_and_follows_bytes(self, tmp_path):
        one = container.write(tmp_path, "x", container.encode(1, 0, []))
        two = container.write(tmp_path, "y", container.encode(2, 0, []))
        assert container.token_of([one, two]) == container.token_of([two, one])
        other = container.write(tmp_path, "y", container.encode(3, 0, []))
        assert container.token_of([one, two]) != container.token_of([one, other])


class TestSplit:
    """The tile tree: the split rule, the bit order and the leaves."""

    def test_split_rule_and_bits(self):
        counts = np.zeros(CELL_COUNT, np.int64)
        counts[:5] = 3  # 15 rows in the first five cells
        counts[CELL_COUNT - 1] = 2
        split = Split.build(counts, max_rows=4)
        first = split.first
        ends = np.r_[first[1:], CELL_COUNT]
        assert first[0] == 0 and np.all(first[1:] > first[:-1])
        assert np.all(ends - first == 4 ** (CELL_LEVEL - split.level.astype(np.int64)))
        sums = np.add.reduceat(counts, first)
        assert np.all((sums <= 4) | (split.level == CELL_LEVEL))
        # Root 0 and its first descendant down to level 9 split; nothing else.
        assert split.bits[:10].all() and not split.bits[10]
        assert split.bits.sum() == 10
        again = Split.from_bits(split.bits, "split")
        assert np.array_equal(again.level, split.level)
        assert np.array_equal(again.pixel, split.pixel)
        assert split.leaf_of(np.array([0, 4, CELL_COUNT - 1])).tolist() == [
            0,
            4,
            split.level.size - 1,
        ]

    def test_bits_left_over_are_refused(self):
        with pytest.raises(container.FormatError, match="a/split.bin.gz"):
            Split.from_bits(np.zeros(ROOTS + 1, bool), "a/split.bin.gz")

    def test_a_short_split_table_is_refused(self):
        # Root 0 splits into four leaves; roots 1 to 11 have no bit.
        bits = np.array([True, False, False, False, False])
        with pytest.raises(container.FormatError, match="a/split.bin.gz"):
            Split.from_bits(bits, "a/split.bin.gz")

    def test_units_cover_large_leaves(self):
        counts = np.zeros(CELL_COUNT, np.int64)
        counts[123456] = 50
        split = Split.build(counts, max_rows=10)
        found = units(split)
        regions = [r for unit in found for r in unit.regions]
        assert sorted(regions) == list(range(768))
        assert sum(unit.level.size for unit in found) == split.level.size
