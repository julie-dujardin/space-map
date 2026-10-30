"""Per-object bundle dicts held as JSON bytes until something touches them.

The export accumulates one global dict per object (1.6M of them) plus one
per language for the QID-bearing ones, and keeps them all until the bundles
are sealed. As Python dicts that is ~6 KB each, ~10 GB in total; as orjson
bytes it is under a tenth of that.
"""

from collections.abc import Iterator, MutableMapping

import orjson


def _encode(value: dict) -> bytes:
    """JSON bytes of exact size.

    The bytes from orjson keep about 4 KB of unused room. The copy holds only
    the JSON.
    """
    return bytes(memoryview(orjson.dumps(value)))


class CompactMap(MutableMapping[str, dict]):
    """``{id: dict}`` whose values live as JSON bytes.

    ``map[k]`` (and ``.get``) decode the entry and keep the decoded dict, so
    in-place mutation of the returned dict persists. ``items()`` and
    ``values()`` yield throwaway decoded copies: mutate ``map[k]`` instead of
    the yielded dict. ``raw(k)`` hands the bundle writer the bytes.
    """

    __slots__ = ("_data",)

    def __init__(self) -> None:
        self._data: dict[str, bytes | dict] = {}

    def __getitem__(self, key: str) -> dict:
        value = self._data[key]
        if isinstance(value, bytes):
            value = orjson.loads(value)
            self._data[key] = value
        return value

    def __setitem__(self, key: str, value: dict) -> None:
        self._data[key] = _encode(value)

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def items(self):
        for key, value in self._data.items():
            yield key, (orjson.loads(value) if isinstance(value, bytes) else value)

    def values(self):
        for value in self._data.values():
            yield orjson.loads(value) if isinstance(value, bytes) else value

    def update(self, other=(), /, **kwargs) -> None:
        if isinstance(other, CompactMap):
            self._data.update(other._data)
        else:
            super().update(other, **kwargs)

    def raw(self, key: str) -> bytes:
        """One entry as JSON bytes, encoding it again if it was decoded."""
        value = self._data[key]
        return value if isinstance(value, bytes) else orjson.dumps(value)
