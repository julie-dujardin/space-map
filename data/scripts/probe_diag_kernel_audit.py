"""Audit every mission for the writer/benchmark kernel-set divergence.

The writer loads only the kernels listed in `_index.json`'s `files` list.
The benchmark calls `_mission_kernels(mdir)` which globs the directory.
Any .bsp present in the dir but absent from _index.json that covers the
probe's NAIF id will override the writer's truth at benchmark eval time,
inflating reported errors.

Outputs a per-mission report of:
  - .bsp files only in dir (not in _index.json)
  - which of those cover any -1..-999 NAIF id, and what time window

Run from data/:
    uv run python scripts/probe_diag_kernel_audit.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

import spiceypy  # noqa: E402

from space_map_data.download.providers.spice.probes import MISSIONS_DIR  # noqa: E402
from space_map_data.export.position.probes.writer import (  # noqa: E402
    _STATIONARY_PATTERNS,
    _collect_generic_kernels,
)
from space_map_data.utils.paths import DOWNLOAD_DIR  # noqa: E402


def _index_files(mdir: Path) -> set[str]:
    idx_path = mdir / "_index.json"
    if not idx_path.exists():
        return set()
    idx = json.loads(idx_path.read_text())
    return {f["name"] for f in idx.get("files", [])}


def _all_bsps(mdir: Path) -> list[Path]:
    return [
        k
        for k in (sorted(mdir.glob("*.bsp")) + sorted(mdir.glob("*.BSP")))
        if not any(p in k.name for p in _STATIONARY_PATTERNS)
    ]


def _et_to_date(et: float) -> str:
    import datetime

    return (
        datetime.datetime(2000, 1, 1, 12, 0, 0) + datetime.timedelta(seconds=et)
    ).strftime("%Y-%m-%d")


def _spacecraft_coverage(kernel: Path) -> dict[int, list[tuple[float, float]]]:
    """All -1..-999 NAIF ids covered by `kernel`, with their windows."""
    out: dict[int, list[tuple[float, float]]] = {}
    try:
        cell_ids = spiceypy.cell_int(2000)
        spiceypy.spkobj(str(kernel), cell_ids)
        ids = sorted(cell_ids[i] for i in range(spiceypy.card(cell_ids)))
    except spiceypy.exceptions.SpiceyError:
        return out
    for naif in ids:
        if not (-999 <= naif <= -1):
            continue
        try:
            cell = spiceypy.cell_double(2000)
            spiceypy.spkcov(str(kernel), naif, cell)
            ivals = []
            for i in range(spiceypy.wncard(cell)):
                s, e = spiceypy.wnfetd(cell, i)
                ivals.append((s, e))
            if ivals:
                out[naif] = ivals
        except spiceypy.exceptions.SpiceyError:
            continue
    return out


def main() -> int:
    KR = DOWNLOAD_DIR / "spice" / "kernels"
    lsk_pck, generic_spk = _collect_generic_kernels(KR)
    for p in lsk_pck:
        spiceypy.furnsh(str(p))

    rows: list[dict] = []
    for mdir in sorted(MISSIONS_DIR.iterdir()):
        if not mdir.is_dir():
            continue
        index_set = _index_files(mdir)
        if not index_set:
            continue
        all_bsps = _all_bsps(mdir)
        extras = [k for k in all_bsps if k.name not in index_set]
        if not extras:
            continue
        # Per-extra: which spacecraft NAIFs does it cover?
        for k in extras:
            cov = _spacecraft_coverage(k)
            if not cov:
                rows.append({"mission": mdir.name, "kernel": k.name, "naif": None})
                continue
            for naif, ivals in cov.items():
                s = min(iv[0] for iv in ivals)
                e = max(iv[1] for iv in ivals)
                rows.append(
                    {
                        "mission": mdir.name,
                        "kernel": k.name,
                        "naif": naif,
                        "start": _et_to_date(s),
                        "end": _et_to_date(e),
                    }
                )
    print(
        f"\n{'Mission':<22} {'Extra kernel (not in _index.json)':<44} {'NAIF':>5} {'Coverage':<24}"
    )
    print("-" * 100)
    for r in rows:
        cov = (
            f"{r.get('start', '')} → {r.get('end', '')}"
            if r["naif"] is not None
            else "(no -1..-999 coverage)"
        )
        print(f"{r['mission']:<22} {r['kernel']:<44} {str(r['naif']):>5} {cov:<24}")
    print(f"\nTotal extra-kernel rows: {len(rows)}")
    print(
        f"  with spacecraft coverage: {sum(1 for r in rows if r['naif'] is not None)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
