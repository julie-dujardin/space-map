import numpy as np
import pyarrow as pa

from space_map_data.utils.arrays import find_sorted, floats, map_sorted

SORTED = np.array([3, 7, 9], np.int64)


class TestSorted:
    """Lookups in sorted keys: misses below, between and past the keys."""

    def test_find(self):
        keys = np.array([9, 1, 7, 8, 12, 3], np.int64)
        assert find_sorted(SORTED, keys).tolist() == [2, -1, 1, -1, -1, 0]
        assert find_sorted(SORTED[:0], keys).tolist() == [-1] * 6

    def test_map(self):
        values = np.array([30, 70, 90], np.int64)
        keys = np.array([7, 8, 12, 3], np.int64)
        assert map_sorted(SORTED, values, keys, 0).tolist() == [70, 0, 0, 30]
        assert map_sorted(SORTED, values, keys, keys).tolist() == [70, 8, 12, 30]
        empty = SORTED[:0]
        assert map_sorted(empty, empty, keys, keys).tolist() == keys.tolist()
        assert map_sorted(empty, empty, keys, 0).tolist() == [0] * 4


def test_floats_fill_nulls_with_nan():
    table = pa.table({"x": pa.array([1.5, None], pa.float32())})
    result = floats(table, "x")
    assert result.dtype == np.float64
    assert result[0] == 1.5 and np.isnan(result[1])
