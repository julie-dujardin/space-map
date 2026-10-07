"""Edits to an export that is already written.

Shared by the ``space-map-export --only`` sections that change what the
object bundles say without running the whole export.
"""

import gzip
import hashlib
from collections.abc import Callable
from pathlib import Path

import orjson

from space_map_data.export.sidecar_io import write_atomic


def content_token(root: Path) -> str:
    """Stable 16-hex token over every file under `root` (path + bytes).

    Changes iff a file's relative path or contents change, so a deterministic
    re-export keeps the token (and the client's cached copy). Returns "0" when
    the directory is missing or holds no files. Nondeterministic contents only
    weaken caching (the token churns), never correctness.
    """
    if not root.is_dir():
        return "0"
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        return "0"
    digest = hashlib.sha256()
    for path in files:
        file_hash = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                file_hash.update(block)
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(file_hash.digest())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def patch_global_bundles(out_dir: Path, patch: Callable[[str, dict], bool]) -> int:
    """Run ``patch(body_id, data)`` on every body of the global object
    bundles. It edits ``data`` and returns whether it did. Returns how many
    bundle files changed."""
    rewritten = 0
    for bucket_path in sorted((out_dir / "objects" / "__global__").glob("*.json.gz")):
        bundle = orjson.loads(gzip.decompress(bucket_path.read_bytes()))
        # A list, not a generator: every body is patched, also after a change.
        if any([patch(body_id, data) for body_id, data in bundle.items()]):
            write_atomic(bucket_path, gzip.compress(orjson.dumps(bundle), mtime=0))
            rewritten += 1
    return rewritten


def refresh_versions(out_dir: Path, *classes: str) -> None:
    """Restate the cache token of each of ``classes`` in metadata.json. A
    client caches a class by its token, so the token must follow the bytes."""
    metadata_path = out_dir / "metadata.json"
    metadata = orjson.loads(metadata_path.read_bytes())
    for cls in classes:
        metadata["versions"][cls] = content_token(out_dir / cls)
    metadata_path.write_bytes(orjson.dumps(metadata, option=orjson.OPT_INDENT_2))
