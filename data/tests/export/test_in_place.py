"""Tests for the edits to an export that is already written.

The content token must change iff a file's path or bytes change: these pin both
determinism (no-op re-export keeps the cache) and sensitivity (any change busts it).
"""

import gzip
from pathlib import Path

import orjson

from space_map_data.export.in_place import (
    content_token,
    patch_global_bundles,
    refresh_versions,
)


def _write(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class TestContentToken:
    """Content-hash token over every file under a class directory."""

    def test_missing_dir_is_zero(self, tmp_path: Path) -> None:
        assert content_token(tmp_path / "absent") == "0"

    def test_empty_dir_is_zero(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        assert content_token(tmp_path / "empty") == "0"

    def test_deterministic_across_identical_trees(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a", tmp_path / "b"
        for root in (a, b):
            _write(root, "x/0.bin", b"hello")
            _write(root, "y/1.bin", b"world")
        assert content_token(a) == content_token(b)

    def test_content_change_busts_token(self, tmp_path: Path) -> None:
        root = tmp_path / "c"
        _write(root, "x/0.bin", b"hello")
        before = content_token(root)
        _write(root, "x/0.bin", b"hell0")  # same length, one byte differs
        assert content_token(root) != before

    def test_path_change_busts_token(self, tmp_path: Path) -> None:
        root1, root2 = tmp_path / "d1", tmp_path / "d2"
        _write(root1, "x/0.bin", b"hello")
        _write(root2, "x/1.bin", b"hello")  # same bytes, different path
        assert content_token(root1) != content_token(root2)

    def test_new_file_busts_token(self, tmp_path: Path) -> None:
        root = tmp_path / "e"
        _write(root, "x/0.bin", b"hello")
        before = content_token(root)
        _write(root, "x/1.bin", b"")  # even an empty new file changes the set
        assert content_token(root) != before

    def test_token_is_16_hex(self, tmp_path: Path) -> None:
        _write(tmp_path / "f", "x/0.bin", b"hello")
        token = content_token(tmp_path / "f")
        assert len(token) == 16
        assert all(ch in "0123456789abcdef" for ch in token)


class TestPatchGlobalBundles:
    """One pass over the global object bundles, for the `--only` sections."""

    @staticmethod
    def _bundle(out_dir: Path, name: str, bodies: dict) -> Path:
        path = out_dir / "objects" / "__global__" / f"{name}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(orjson.dumps(bodies)))
        return path

    def test_rewrites_only_the_files_a_patch_changed(self, tmp_path):
        kept = self._bundle(tmp_path, "0", {"a": {}})
        changed = self._bundle(tmp_path, "1", {"b": {}, "c": {}})
        before = kept.read_bytes()

        def patch(body_id: str, data: dict) -> bool:
            if body_id == "a":
                return False
            data["seen"] = True
            return True

        assert patch_global_bundles(tmp_path, patch) == 1
        assert kept.read_bytes() == before
        # Every body of the file, not only up to the first change.
        assert orjson.loads(gzip.decompress(changed.read_bytes())) == {
            "b": {"seen": True},
            "c": {"seen": True},
        }


class TestRefreshVersions:
    def test_restates_the_named_classes_and_keeps_the_rest(self, tmp_path):
        (tmp_path / "objects").mkdir()
        (tmp_path / "objects" / "a.json").write_text("{}")
        metadata = tmp_path / "metadata.json"
        metadata.write_bytes(
            orjson.dumps({"versions": {"objects": "0", "images": "kept"}})
        )

        refresh_versions(tmp_path, "objects")

        assert orjson.loads(metadata.read_bytes())["versions"] == {
            "objects": content_token(tmp_path / "objects"),
            "images": "kept",
        }
