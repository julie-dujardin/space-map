"""Generate physically-derived small-body sRGB colours from TrueColorTools.

Replaces the hand-tuned frontend taxonomy heuristic with TCT's "natural colour
as-is" (geometric-albedo–scaled, gamma-corrected, brightness *not* maximized).
Emits ``constants/small_body_colors.json`` consumed by the export resolver:

    {
      "neutral_linear": [r, g, b],   # reflectance=1 linear RGB (luminance 1),
                                     # the hue-less chroma for the albedo-grey tier
      "by_taxon": {"S": [r, g, b], ...},   # Bus-DeMeo class chroma (linear,
                                     # luminance-normalized) — hue only
      "by_spkid": {                  # per-body, grouped by derivation method
        "spectrum":   {"20000004": "#rrggbb", ...},  # measured reflectance
        "photometry": {"20000433": "#rrggbb", ...},  # SBDB B-V/U-B indices
      }
    }

The export scales a chroma (``neutral_linear`` or a ``by_taxon`` entry) by a
body's geometric albedo and sRGB-encodes it, so per-class/grey brightness always
comes from the body's own measured albedo. ``by_spkid`` are final per-body
colours (full natural TCT colour, brightness from that body's own data).

This is a one-off generator, regenerated when SBDB or TCT refreshes. It is NOT
on the export hot path — TCT's numpy/scipy/astropy deps never enter the project.

Run under TrueColorTools' own venv (it reads the DB via stdlib sqlite3 only):

    cd <truecolortools clone>
    . .venv-tct/bin/activate
    python <repo>/data/scripts/generate_small_body_colors.py \
        --tct-root . --db <downloads>/db/space-map.db
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# TCT's per-body spectrum reconstruction solves tiny linear systems; multithreaded
# BLAS oversubscribes and thrashes on them. Pin to one thread *before* numpy loads.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

# DB-derived sibling of the repo checkout, mirroring utils/paths.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB = _REPO_ROOT.parent / "space-map-downloads" / "db" / "space-map.db"
_DEFAULT_TCT = _REPO_ROOT.parent / "space-map-downloads" / "truecolortools"
_OUT = (
    _REPO_ROOT
    / "data"
    / "src"
    / "space_map_data"
    / "constants"
    / "small_body_colors.json"
)

# Numbered minor planets get SPK-ID = 20_000_000 + number (matches SBDB/Horizons).
_SPKID_ASTEROID_OFFSET = 20_000_000


def _load_tct(tct_root: Path):
    """Import TCT's core/database from the clone. Must chdir into the root —
    TCT resolves ``spectra/`` and filter profiles relative to the cwd."""
    sys.path.insert(0, str(tct_root))
    os.chdir(tct_root)
    import src.database as db  # noqa: E402  # ty: ignore[unresolved-import]  # TCT clone, not a project dep
    from src.core import (  # noqa: E402  # ty: ignore[unresolved-import]  # TCT clone, not a project dep
        ColorPoint,
        ColorSystem,
        ObjectName,
        Spectrum,
        database_parser,
    )

    return db, database_parser, ColorPoint, ColorSystem, ObjectName, Spectrum


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tct-root", type=Path, default=_DEFAULT_TCT)
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=_OUT)
    args = ap.parse_args()

    out_path = args.out.resolve()  # resolve before chdir into the TCT root
    db_path = args.db.resolve()

    db, database_parser, ColorPoint, ColorSystem, ObjectName, Spectrum = _load_tct(
        args.tct_root.resolve()
    )
    import numpy as np

    srgb = ColorSystem("sRGB")

    def colour_of(body) -> str | None:
        """Natural geometric-albedo colour as ``#rrggbb``; None if unscalable."""
        spectrum, estimated = body.get_spectrum("geometric")
        c = ColorPoint.from_spectral_data(spectrum).to_color_system(srgb)
        c.gamma_correction = True
        # Brightness maximization only when albedo can't scale the spectrum —
        # otherwise we keep the true (dark) reflectance the user asked for.
        c.maximize_brightness = estimated is None
        return c.to_html()

    def colour_of_entry(name, entry) -> str | None:
        return colour_of(database_parser(name, entry))

    objs, _refs = db.import_DBs(["spectra"])

    def luminance(linear) -> float:
        """sRGB/Rec.709 relative luminance of a linear-light RGB triple."""
        r, g, b = linear
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def chroma(linear) -> list[float]:
        """Normalize a linear colour to luminance 1 — hue only, brightness
        re-applied per body via its albedo. Falls back to neutral grey if black."""
        lin = np.asarray(linear, dtype=float)
        y = luminance(lin)
        if y <= 0:
            return [1.0, 1.0, 1.0]
        return [round(float(v), 6) for v in lin / y]

    # --- neutral chroma: flat reflectance = 1 (the reflectance-1 white point) ---
    nm = np.arange(380, 781, 5)
    flat = Spectrum(nm, np.ones_like(nm, dtype=float), name=ObjectName("neutral"))
    neutral = ColorPoint.from_spectral_data(flat).to_color_system(srgb)
    neutral.gamma_correction = False  # linear; the export applies sRGB OETF
    neutral_linear = chroma(neutral.to_array())

    # --- by_taxon: Bus-DeMeo class spectra (the taxonomy SBDB spec_B uses) ---
    # Two entries per class (distinct sources); average in linear light.
    taxon_linear: dict[str, list] = {}
    for name, entry in objs.items():
        tags = entry.get("tags", [])
        if not any(t.endswith("Bus-DeMeo taxonomy") for t in tags):
            continue
        m = re.match(r"([A-Za-z]+)-type", str(name))
        if not m:
            continue
        cls = m.group(1)
        try:
            body = database_parser(name, entry)
            spectrum, estimated = body.get_spectrum("geometric")
            c = ColorPoint.from_spectral_data(spectrum).to_color_system(srgb)
            c.gamma_correction = False
            taxon_linear.setdefault(cls, []).append(np.asarray(c.to_array()))
        except Exception as e:  # noqa: BLE001
            print(f"  skip taxon {name}: {e}", file=sys.stderr)

    # Average each class in linear light, then keep only its hue (luminance 1);
    # the export re-applies brightness from each body's measured albedo.
    by_taxon = {
        cls: chroma(np.mean(arrs, axis=0)) for cls, arrs in taxon_linear.items()
    }

    # Per-body colours are grouped by derivation method so the export can credit
    # each: `spectrum` = a measured reflectance spectrum, `photometry` = SBDB
    # broadband B-V/U-B colour indices. Both run through TrueColorTools' engine.
    def sort_by_spkid(d: dict[str, str]) -> dict[str, str]:
        return dict(sorted(d.items(), key=lambda kv: int(kv[0])))

    # --- spectrum: individually-measured named bodies in TCT ---
    # Keys look like "4 Vesta [refs]" / "134340 Pluto [refs]". Skip sub-region
    # entries ("4 Vesta: Bright areas", "Ahuna Mons (Ceres)").
    by_spectrum: dict[str, str] = {}
    skipped_named = 0
    for name, entry in objs.items():
        s = str(name)
        if ":" in s or "(" in s:
            continue
        m = re.match(r"(\d+)\s+\S", s)
        if not m:
            continue
        if not any(t.startswith("minor body") for t in entry.get("tags", [])):
            continue
        spkid = str(_SPKID_ASTEROID_OFFSET + int(m.group(1)))
        try:
            hexcol = colour_of_entry(name, entry)
            if hexcol:
                by_spectrum[spkid] = hexcol
        except Exception as e:  # noqa: BLE001
            skipped_named += 1
            print(f"  skip named {name}: {e}", file=sys.stderr)

    # --- photometry: SBDB B-V + U-B colour indices through the TCT engine ---
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT spkid, BV, UB, albedo FROM sbdb WHERE BV IS NOT NULL AND UB IS NOT NULL"
    ).fetchall()
    con.close()
    print(
        f"  photometry: {len(rows)} candidate bodies ...", file=sys.stderr, flush=True
    )
    by_photometry: dict[str, str] = {}
    bv_skipped = 0
    for i, (spkid, bv, ub, albedo) in enumerate(rows):
        if i and i % 100 == 0:
            print(f"    ...{i}/{len(rows)}", file=sys.stderr, flush=True)
        if spkid is None or spkid in by_spectrum:  # a measured spectrum wins
            continue
        entry: dict[str, object] = {
            "photometric_system": "Generic_Bessell",
            "color_indices": {"U-B": float(ub), "B-V": float(bv)},
            "calibration_system": "Vega",
        }
        if albedo is not None:
            entry["geometric_albedo"] = ["Generic_Bessell.V", [float(albedo), 0.0]]
        try:
            hexcol = colour_of_entry(ObjectName(f"sbdb-{spkid}"), entry)
            if hexcol:
                by_photometry[str(spkid)] = hexcol
        except Exception as e:  # noqa: BLE001
            bv_skipped += 1
            print(f"  skip BV/UB {spkid}: {e}", file=sys.stderr)

    out = {
        "neutral_linear": neutral_linear,
        "by_taxon": dict(sorted(by_taxon.items())),
        "by_spkid": {
            "spectrum": sort_by_spkid(by_spectrum),
            "photometry": sort_by_spkid(by_photometry),
        },
    }
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="UTF-8")

    print(
        f"\nwrote {out_path}\n"
        f"  neutral_linear = {neutral_linear}\n"
        f"  by_taxon       = {len(by_taxon)} classes\n"
        f"  by_spkid       = {len(by_spectrum)} spectrum + {len(by_photometry)} photometry "
        f"(skipped {skipped_named}+{bv_skipped})"
    )


if __name__ == "__main__":
    main()
