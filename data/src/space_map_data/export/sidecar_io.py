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

logger = logging.getLogger(__name__)


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
