"""A model bundle on disk: ``models/{slug}/{tier}.glb``, each GLB carrying the
bundle's metadata in ``asset.extras.spacemap``.

The deploy is capped at 100k files, so a bundle ships its GLBs and nothing
else. Every tier carries the whole payload: a client reads it off whichever
tier it loaded.
"""

import json
import logging
import os
from pathlib import Path

from space_map_data.ingest.providers.models.metadata import (
    GLB_CHUNK,
    GLB_HEADER,
    GLB_JSON_CHUNK,
    GLB_MAGIC,
    read_json_chunk,
)

log = logging.getLogger(__name__)

PAYLOAD_KEY = "spacemap"
# The one payload field that changes on every write. A bundle whose payload
# and meshes are otherwise unchanged keeps the stamp it has, so its GLBs keep
# their bytes and a deploy doesn't upload them again.
_STAMP_KEY = "processed_at"


def write_bundle(out_dir: Path, sources: dict[str, Path], payload: dict) -> None:
    """Write each tier's GLB from ``sources`` with ``payload`` embedded, one
    ``processed_at`` across them, and drop every other file in ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    old = read_payload(out_dir / "high.glb")
    if old is not None and _unstamped(old) == _unstamped(payload):
        kept = {**payload, _STAMP_KEY: old.get(_STAMP_KEY)}
        built = {tier: embed_payload(src, kept) for tier, src in sources.items()}
        if all(_holds(out_dir / f"{tier}.glb", data) for tier, data in built.items()):
            prune_bundle_dir(out_dir, sources)
            return
    for tier, src in sources.items():
        _replace(out_dir / f"{tier}.glb", embed_payload(src, payload))
    prune_bundle_dir(out_dir, sources)


def is_intact(out_dir: Path, tiers) -> bool:
    """Whether ``out_dir`` holds exactly the GLBs of ``tiers``, each carrying a
    payload."""
    names = {f"{tier}.glb" for tier in tiers}
    if not out_dir.is_dir() or {p.name for p in out_dir.iterdir()} != names:
        return False
    return all(read_payload(out_dir / name) is not None for name in names)


def prune_bundle_dir(out_dir: Path, tiers) -> None:
    """Delete what a bundle no longer ships: a tier it dropped, or anything that
    isn't a tier GLB."""
    keep = {f"{tier}.glb" for tier in tiers}
    for path in out_dir.iterdir():
        if path.name not in keep and path.is_file():
            path.unlink()


def embed_payload(src: Path, payload: dict) -> bytes:
    """``src``'s bytes with ``payload`` under ``asset.extras``."""
    with src.open("rb") as f:
        gltf = read_json_chunk(f)
        rest = f.read()
    if gltf is None:
        raise ValueError(f"{src}: not a glTF 2 binary")
    asset = gltf.setdefault("asset", {})
    extras = asset.get("extras")
    asset["extras"] = {
        **(extras if isinstance(extras, dict) else {}),
        PAYLOAD_KEY: payload,
    }
    return _join(gltf, rest)


def _holds(path: Path, data: bytes) -> bool:
    return (
        path.exists() and path.stat().st_size == len(data) and path.read_bytes() == data
    )


def _replace(dst: Path, data: bytes) -> None:
    """Write ``data`` as a new file renamed into place, so a ``dst`` sharing
    its inode with a cached GLB never changes the cache."""
    tmp = dst.with_name(f".{dst.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dst)


def asset_extras(payload: dict) -> dict:
    """The ``asset.extras`` of a GLB written from scratch."""
    return {PAYLOAD_KEY: payload}


def read_payload(glb: Path) -> dict | None:
    """The payload a GLB carries, reading its header and JSON chunk only.
    None when the file is missing, not glTF 2 binary, or carries none."""
    try:
        with glb.open("rb") as f:
            gltf = read_json_chunk(f)
    except OSError:
        return None
    asset = (gltf or {}).get("asset")
    extras = asset.get("extras") if isinstance(asset, dict) else None
    payload = extras.get(PAYLOAD_KEY) if isinstance(extras, dict) else None
    return payload if isinstance(payload, dict) else None


def read_bundle(slug_dir: Path) -> dict | None:
    """A bundle's payload with each shipped tier's ``size_bytes``, which a file
    can't carry about itself; a tier whose file is missing is left out. None,
    with a warning, when the high tier carries no payload."""
    payload = read_payload(slug_dir / "high.glb")
    if payload is None:
        log.warning("model bundle %s: high.glb carries no payload", slug_dir.name)
        return None
    exports = {}
    for tier, record in (payload.get("exports") or {}).items():
        glb = slug_dir / f"{tier}.glb"
        if glb.exists():
            exports[tier] = {**record, "size_bytes": glb.stat().st_size}
    payload["exports"] = exports
    payload["tiers"] = [t for t in payload.get("tiers") or [] if t in exports]
    return payload


def _unstamped(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k != _STAMP_KEY}


def _join(gltf: dict, rest: bytes) -> bytes:
    body = json.dumps(gltf, separators=(",", ":")).encode()
    body += b" " * (-len(body) % 4)  # JSON chunks pad with spaces
    total = GLB_HEADER.size + GLB_CHUNK.size + len(body) + len(rest)
    return (
        GLB_HEADER.pack(GLB_MAGIC, 2, total)
        + GLB_CHUNK.pack(len(body), GLB_JSON_CHUNK)
        + body
        + rest
    )
