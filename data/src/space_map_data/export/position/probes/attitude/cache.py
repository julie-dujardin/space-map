"""Files of the probe attitude cache, in the export metadata mirror.

Per probe, under `attitude/<probe>/`:
- `_attitude_cache.json`: the spin plan, keyed on the full kernel signature,
  and the manifest of the last chunk write, keyed on the shard signatures.
- `shards/<k>-<sig>.npz`: the keyframes of shard k (`ets`, `quats`, `seg`).
  The name holds the signature, so a file is never rewritten in place and a
  crash leaves only whole files.

Per craft, `attitude/_coverage/<frame>.json` holds the SEGMENT-level coverage
of each CK, and whether its segments need positions to resolve, keyed on its
content stamp.
"""

import json
import os
from pathlib import Path

import numpy as np

from space_map_data.export.sidecar_io import read_sidecar, write_atomic

# The probe cache file and the shard signatures: a bump extracts every shard.
CACHE_VERSION = 6
# The coverage entries: a bump reads every CK again.
COVERAGE_VERSION = 5
# The spin plan: a bump plans every probe again.
SPIN_VERSION = 5
CACHE_NAME = "_attitude_cache.json"
SHARD_DIR = "shards"
COVERAGE_DIR = "_coverage"


def load_probe_cache(meta_dir: Path) -> dict:
    data = read_sidecar(meta_dir / CACHE_NAME)
    if data is None or data.get("version") != CACHE_VERSION:
        return {"version": CACHE_VERSION, "spin": None, "output": None}
    return data


def save_probe_cache(meta_dir: Path, cache: dict) -> None:
    write_atomic(meta_dir / CACHE_NAME, json.dumps(cache, sort_keys=True).encode())


def shard_name(k: int, sig: str) -> str:
    return f"{k}-{sig}.npz"


def list_shards(meta_dir: Path) -> set[str]:
    try:
        return set(os.listdir(meta_dir / SHARD_DIR))
    except FileNotFoundError:
        return set()


def save_shard(path: Path, ets: np.ndarray, quats: np.ndarray, seg: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("wb") as f:
        np.savez(f, ets=ets, quats=quats, seg=seg)
        # A name on disk must mean whole content, also after a power loss.
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_shard(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with np.load(path) as data:
        return data["ets"], data["quats"], data["seg"]


def coverage_path(attitude_meta_dir: Path, frame: str) -> Path:
    return attitude_meta_dir / COVERAGE_DIR / f"{frame}.json"


def load_coverage(path: Path, key: dict) -> dict[str, dict]:
    """`{ck name: {"stamp", "cover", "ephemeris"}}` when the file was written
    under `key` (coverage version and LSK, FK and SCLK stamps), else empty."""
    data = read_sidecar(path)
    if data is None or data.get("key") != key:
        return {}
    return data["cks"]


def save_coverage(path: Path, key: dict, cks: dict[str, dict]) -> None:
    write_atomic(path, json.dumps({"key": key, "cks": cks}, sort_keys=True).encode())
