"""Atomic write + read helpers shared by per-zone export sidecars.

A sidecar is a small JSON file living next to a binary chunk that records
what inputs produced that chunk, so the next export can skip work whose
inputs haven't changed. The zone-specific signature shape lives in each
zone's `sidecar.py` (probes, elements/earth); the IO primitives are here.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

from space_map_data.utils.paths import EXPORT_DIR, EXPORT_METADATA_DIR

logger = logging.getLogger(__name__)


def mirror_path(path: Path) -> Path:
    """Map an EXPORT_DIR path to its EXPORT_METADATA_DIR counterpart.

    Build-only sidecar metadata (incremental sidecars, texture/ring
    metadata.json) is written under EXPORT_METADATA_DIR with the same
    relative layout so EXPORT_DIR can be deployed to Cloudflare Pages
    (20k-file cap) without the sidecars eating the budget.

    Paths outside EXPORT_DIR (e.g. pytest tmp_path) pass through
    unchanged — callers writing data and metadata to a test fixture
    end up colocated, matching pre-split behaviour.
    """
    try:
        rel = path.relative_to(EXPORT_DIR)
    except ValueError:
        return path
    return EXPORT_METADATA_DIR / rel


def write_atomic(path: Path, content: bytes) -> None:
    """Tempfile + rename in the destination dir — crash-safe.

    `tempfile.mkstemp` creates the temp file with mode 0o600 (owner-only) for
    security, and `os.replace` preserves that mode — so without an explicit
    chmod the published binaries would be unreadable to anyone except the
    export user, manifesting as nginx/CDN 403s on otherwise-existing files.
    Force 0o644 to match what a plain `open(..., 'wb')` under the typical
    0o022 umask produces.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_sidecar(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Sidecar %s unreadable (%s); treating as missing", path, e)
        return None


def matches(path: Path, expected: dict) -> bool:
    """True iff the on-disk sidecar equals `expected`."""
    return read_sidecar(path) == expected


def write_sidecar(path: Path, signature: dict) -> None:
    write_atomic(path, json.dumps(signature, sort_keys=True, indent=2).encode())
