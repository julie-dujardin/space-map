"""Content stamps: mtime-blind, content-sensitive, memoised."""

import os

from space_map_data.utils import content_stamp
from space_map_data.utils.content_stamp import content_stamps, content_stamp as stamp


def _touch(path, mtime_ns):
    os.utime(path, ns=(mtime_ns, mtime_ns))


class TestSmallFiles:
    """Files under the full-hash limit are digested whole."""

    def test_mtime_change_keeps_the_stamp(self, tmp_path):
        f = tmp_path / "a.tls"
        f.write_bytes(b"leapseconds")
        before = stamp(f)
        _touch(f, 1_000_000_000_000_000_000)
        assert stamp(f) == before

    def test_copy_has_the_same_stamp(self, tmp_path):
        a = tmp_path / "a.bc"
        b = tmp_path / "moved" / "a.bc"
        a.write_bytes(b"kernel bytes")
        b.parent.mkdir()
        b.write_bytes(a.read_bytes())
        assert stamp(a) == stamp(b)

    def test_content_change_moves_the_stamp(self, tmp_path):
        f = tmp_path / "a.bc"
        f.write_bytes(b"one")
        before = stamp(f)
        f.write_bytes(b"two")
        after = stamp(f)
        assert after is not None and after != before
        assert after["size"] == 3

    def test_missing_file_is_none(self, tmp_path):
        assert stamp(tmp_path / "nope") is None


class TestSampledFiles:
    """Files over the limit hash size + head + tail + interior blocks."""

    def test_edges_and_interior_are_sampled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(content_stamp, "_FULL_HASH_LIMIT", 64)
        monkeypatch.setattr(content_stamp, "_EDGE_BYTES", 8)
        monkeypatch.setattr(content_stamp, "_INNER_BYTES", 4)
        f = tmp_path / "big.bsp"
        base = bytearray(b"x" * 300)
        f.write_bytes(base)
        before = stamp(f)
        for offset in (0, 100, 200, 299):
            data = bytearray(base)
            data[offset] = ord("y")
            f.write_bytes(data)
            assert stamp(f) != before, offset

    def test_untouched_middle_is_not_seen(self, tmp_path, monkeypatch):
        monkeypatch.setattr(content_stamp, "_FULL_HASH_LIMIT", 64)
        monkeypatch.setattr(content_stamp, "_EDGE_BYTES", 8)
        monkeypatch.setattr(content_stamp, "_INNER_BYTES", 4)
        f = tmp_path / "big.bsp"
        base = bytearray(b"x" * 300)
        f.write_bytes(base)
        before = stamp(f)
        base[50] = ord("y")
        f.write_bytes(base)
        assert stamp(f) == before


class TestMemo:
    """Digests are reused while size and mtime hold, and survive a restart."""

    def test_memo_short_circuits_on_stat(self, tmp_path):
        f = tmp_path / "a.bc"
        f.write_bytes(b"abc")
        before = stamp(f)
        mtime = f.stat().st_mtime_ns
        f.write_bytes(b"xyz")
        _touch(f, mtime)
        assert stamp(f) == before

    def test_memo_persists_across_processes(self, tmp_path):
        f = tmp_path / "a.bc"
        f.write_bytes(b"abc")
        before = stamp(f)
        mtime = f.stat().st_mtime_ns
        content_stamp.flush_memo()
        content_stamp._memo = None  # a fresh process reloads the memo file
        f.write_bytes(b"xyz")
        _touch(f, mtime)
        assert stamp(f) == before

    def test_batch_matches_single_and_keeps_missing(self, tmp_path):
        a = tmp_path / "a"
        a.write_bytes(b"a")
        missing = tmp_path / "missing"
        out = content_stamps([a, missing])
        assert out[a] == stamp(a)
        assert out[missing] is None
