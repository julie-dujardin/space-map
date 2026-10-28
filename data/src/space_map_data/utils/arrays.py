"""Array helpers."""

import numpy as np
import pyarrow as pa


def floats(table: pa.Table, name: str) -> np.ndarray:
    """A column as float64, NaN where null."""
    return table[name].cast(pa.float64()).fill_null(np.nan).to_numpy()


def find_sorted(sorted_keys: np.ndarray, keys: np.ndarray) -> np.ndarray:
    """The position of each of `keys` in `sorted_keys`, -1 where missing."""
    if not sorted_keys.size:
        return np.full(len(keys), -1, np.int64)
    at = np.minimum(np.searchsorted(sorted_keys, keys), sorted_keys.size - 1)
    return np.where(sorted_keys[at] == keys, at, -1)


def map_sorted(
    sorted_keys: np.ndarray,
    values: np.ndarray,
    keys: np.ndarray,
    missing: float | np.ndarray,
) -> np.ndarray:
    """The value of each of `keys`, by its position in `sorted_keys`.

    `missing` is the result where a key is not in `sorted_keys`, a scalar or
    one value per key.
    """
    at = find_sorted(sorted_keys, keys)
    found = values[at] if values.size else np.zeros(len(keys), values.dtype)
    return np.where(at >= 0, found, missing)
