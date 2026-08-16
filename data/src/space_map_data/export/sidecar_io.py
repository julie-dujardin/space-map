"""Atomic write + read helpers shared by per-zone export sidecars.

A sidecar is a small JSON file recording what inputs produced a chunk, so the
next export can skip unchanged work. Zone-specific signature shapes live in
each zone's `sidecar.py`; the IO primitives are here.
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

    Build-only metadata is kept out of EXPORT_DIR so it doesn't eat into
    Cloudflare Pages' 20k-file cap. Paths outside EXPORT_DIR pass through
    unchanged, so test fixtures stay colocated.
    """
    try:
        rel = path.relative_to(EXPORT_DIR)
    except ValueError:
        return path
    return EXPORT_METADATA_DIR / rel


def write_atomic(path: Path, content: bytes) -> None:
    """Tempfile + rename in the destination dir — crash-safe.

    `mkstemp` creates the temp file 0o600, and `os.replace` preserves that mode,
    so we chmod 0o644 or the published binaries 403 for anyone but the export user.
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
