"""Survey SPK segment data types across ALL kernels the app loads.

Walks the same kernel tree the runtime furnshes (`DOWNLOAD_DIR/spice/kernels`)
covering: generic planet/satellite/asteroid SPKs, mission probe SPKs, and
landed-mission SPKs. For each SPK segment we read the *data type* (the
integer SPK subtype: 2/3 = Chebyshev, 9 = Lagrange, 10 = SGP4/TLE,
13 = Hermite, 21 = Extended-MDA, …) and group results by body category.

Run from data/:
    uv run python scripts/diag_spk_types.py
"""

import datetime as _dt
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

import spiceypy  # noqa: E402

from space_map_data.download.providers.spice.probes import (  # noqa: E402
    LANDED_MISSIONS_DIR,
    MISSIONS_DIR,
)
from space_map_data.utils.paths import DOWNLOAD_DIR  # noqa: E402

KERNELS_ROOT = DOWNLOAD_DIR / "spice" / "kernels"

# Human-readable name for each SPK data type. Numbers and descriptions per
# NAIF "SPK Required Reading"; only the ones we might actually encounter
# are spelled out — anything else falls back to "type N".
_SPK_TYPE_NAMES: dict[int, str] = {
    1: "Modified Difference Arrays",
    2: "Chebyshev (position only, equal-step)",
    3: "Chebyshev (position+velocity, equal-step)",
    5: "Discrete states (two-body propagation)",
    8: "Lagrange interpolation, equal-step",
    9: "Lagrange interpolation, unequal-step",
    10: "Space Command TLE / SGP4–SDP4",
    12: "Hermite interpolation, equal-step",
    13: "Hermite interpolation, unequal-step",
    14: "Chebyshev (pos+vel, unequal-step)",
    15: "Precessing-conic propagation",
    17: "Equinoctial elements",
    18: "ESOC/DDID Hermite/Lagrange",
    19: "ESOC/DDID piecewise interpolation",
    20: "Chebyshev (velocity only)",
    21: "Extended Modified Difference Arrays",
}


def _type_label(t: int) -> str:
    return f"type {t:>2} — {_SPK_TYPE_NAMES.get(t, 'unknown')}"


def _classify_naif(naif: int) -> str:
    """Coarse bucket for a NAIF target ID."""
    if naif == 0:
        return "ssb"
    if naif == 10:
        return "sun"
    if 1 <= naif <= 9:
        return "planet_barycenter"
    if naif in (199, 299, 399, 499, 599, 699, 799, 899, 999):
        return "planet_body"
    if 100 <= naif <= 999:
        return "moon"
    if -999 <= naif <= -1:
        return "spacecraft"
    if -1_000_000 < naif < -1000:
        return "spacecraft_extended"
    if naif >= 2_000_000:
        return "asteroid_sbdb"
    if naif >= 1_000_000:
        return "comet_sbdb"
    return "other"


_CATEGORY_ORDER = (
    "sun",
    "planet_barycenter",
    "planet_body",
    "moon",
    "asteroid_sbdb",
    "comet_sbdb",
    "spacecraft",
    "spacecraft_extended",
    "ssb",
    "other",
)


def _et_to_iso(et: float) -> str:
    return (_dt.datetime(2000, 1, 1, 12, 0, 0) + _dt.timedelta(seconds=et)).strftime(
        "%Y-%m-%d"
    )


def _body_name(naif: int) -> str:
    """Best-effort name lookup via SPICE; returns '' if unknown."""
    try:
        return spiceypy.bodc2n(naif)
    except spiceypy.exceptions.SpiceyError:
        return ""


def _segments(kernel: Path) -> list[tuple[int, int, float, float]]:
    """Per-segment (target_naif, seg_type, start_et, end_et) for `kernel`."""
    out: list[tuple[int, int, float, float]] = []
    try:
        handle = spiceypy.dafopr(str(kernel))
    except spiceypy.exceptions.SpiceyError:
        return out
    try:
        spiceypy.dafbfs(handle)
        while spiceypy.daffna():
            summ = spiceypy.dafgs(n=8)  # SPK summary: 2 doubles + 6 ints
            dc, ic = spiceypy.dafus(summ, 2, 6)
            out.append(
                (int(ic[0]), int(ic[3]), float(dc[0]), float(dc[1])),
            )
    finally:
        spiceypy.dafcls(handle)
    return out


def _gather_kernels() -> list[tuple[str, Path]]:
    """Return (source_label, kernel_path) for every .bsp the app would furnsh."""
    out: list[tuple[str, Path]] = []
    if not KERNELS_ROOT.exists():
        return out

    for sub in ("planets", "satellites", "asteroids"):
        d = KERNELS_ROOT / "spk" / sub
        if d.exists():
            for k in sorted(d.glob("*.bsp")):
                out.append((f"generic/{sub}", k))

    for label, root in (("missions", MISSIONS_DIR), ("landed", LANDED_MISSIONS_DIR)):
        if not root.exists():
            continue
        for mdir in sorted(root.iterdir()):
            if not mdir.is_dir():
                continue
            for k in sorted(list(mdir.glob("*.bsp")) + list(mdir.glob("*.BSP"))):
                out.append((f"{label}/{mdir.name}", k))
    return out


def _furnsh_naming() -> None:
    """Load LSK + PCK so `bodc2n` resolves human names. SPKs aren't needed
    for name lookups (SPICE has the major-body table built in)."""
    for ext, sub in ((".tls", "lsk"), (".tpc", "pck")):
        d = KERNELS_ROOT / sub
        if not d.exists():
            continue
        for p in sorted(d.glob(f"*{ext}")):
            try:
                spiceypy.furnsh(str(p))
            except spiceypy.exceptions.SpiceyError:
                pass


def main() -> int:
    _furnsh_naming()

    # (category, naif, type) → list of (source, kernel, span_days)
    by_cat_type: defaultdict[tuple[str, int], list[tuple[int, str, str, float]]] = (
        defaultdict(list)
    )
    overall: Counter[int] = Counter()
    per_category: defaultdict[str, Counter[int]] = defaultdict(Counter)
    kernels = _gather_kernels()
    print(f"Scanning {len(kernels)} SPK kernels under {KERNELS_ROOT}\n")

    for source, kernel in kernels:
        for naif, seg_type, s, e in _segments(kernel):
            cat = _classify_naif(naif)
            overall[seg_type] += 1
            per_category[cat][seg_type] += 1
            by_cat_type[(cat, seg_type)].append(
                (naif, source, kernel.name, (e - s) / 86400.0)
            )

    print("=== Overall segment-type histogram ===")
    for t, c in sorted(overall.items()):
        print(f"  {_type_label(t):<55}  {c:>6} segments")
    print()

    print("=== Segment types per object category ===")
    for cat in _CATEGORY_ORDER:
        if cat not in per_category:
            continue
        types = per_category[cat]
        total = sum(types.values())
        type_summary = ", ".join(
            f"type {t}={c}" for t, c in sorted(types.items(), key=lambda x: -x[1])
        )
        print(f"  {cat:<22} {total:>6} segments  ({type_summary})")
    print()

    print("=== Per (category, type) detail — distinct NAIF targets ===")
    for cat in _CATEGORY_ORDER:
        cat_keys = [k for k in by_cat_type if k[0] == cat]
        if not cat_keys:
            continue
        print(f"\n--- {cat} ---")
        for _, seg_type in sorted(cat_keys, key=lambda x: x[1]):
            rows = by_cat_type[(cat, seg_type)]
            per_naif: defaultdict[int, float] = defaultdict(float)
            sources: defaultdict[int, set[str]] = defaultdict(set)
            for naif, source, _kname, span_d in rows:
                per_naif[naif] += span_d
                sources[naif].add(source)
            print(f"  {_type_label(seg_type)}  — {len(per_naif)} distinct targets")
            shown = sorted(per_naif.items(), key=lambda x: -x[1])[:20]
            for naif, span_d in shown:
                name = _body_name(naif) or "?"
                srcs = ", ".join(sorted(sources[naif]))
                print(
                    f"    NAIF={naif:>8}  {name:<28}  "
                    f"{span_d / 365.25:>7.1f} yr total  [{srcs}]"
                )
            if len(per_naif) > 20:
                print(f"    ... +{len(per_naif) - 20} more targets")
    spiceypy.kclear()
    return 0


if __name__ == "__main__":
    sys.exit(main())
