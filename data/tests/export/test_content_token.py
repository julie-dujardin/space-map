"""Tests for `_content_token`, the per-class cache-busting hash.

The versioning scheme rests on one property: the token changes iff a file's
relative path or bytes change. These pin determinism (so a no-op re-export
keeps the client's cache) and sensitivity (so any real change busts it).
"""

from pathlib import Path

from space_map_data.export.pipeline.orchestrator import _content_token


def _write(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class TestContentToken:
    """Content-hash token over every file under a class directory."""

    def test_missing_dir_is_zero(self, tmp_path: Path) -> None:
        assert _content_token(tmp_path / "absent") == "0"

    def test_empty_dir_is_zero(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        assert _content_token(tmp_path / "empty") == "0"

    def test_deterministic_across_identical_trees(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a", tmp_path / "b"
        for root in (a, b):
            _write(root, "x/0.bin", b"hello")
            _write(root, "y/1.bin", b"world")
        assert _content_token(a) == _content_token(b)

    def test_content_change_busts_token(self, tmp_path: Path) -> None:
        root = tmp_path / "c"
        _write(root, "x/0.bin", b"hello")
        before = _content_token(root)
        _write(root, "x/0.bin", b"hell0")  # same length, one byte differs
        assert _content_token(root) != before

    def test_path_change_busts_token(self, tmp_path: Path) -> None:
        root1, root2 = tmp_path / "d1", tmp_path / "d2"
        _write(root1, "x/0.bin", b"hello")
        _write(root2, "x/1.bin", b"hello")  # same bytes, different path
        assert _content_token(root1) != _content_token(root2)

    def test_new_file_busts_token(self, tmp_path: Path) -> None:
        root = tmp_path / "e"
        _write(root, "x/0.bin", b"hello")
        before = _content_token(root)
        _write(root, "x/1.bin", b"")  # even an empty new file changes the set
        assert _content_token(root) != before

    def test_token_is_16_hex(self, tmp_path: Path) -> None:
        _write(tmp_path / "f", "x/0.bin", b"hello")
        token = _content_token(tmp_path / "f")
        assert len(token) == 16
        assert all(ch in "0123456789abcdef" for ch in token)
