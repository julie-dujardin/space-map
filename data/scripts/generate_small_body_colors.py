"""Generate the surface hues of small bodies and moons from TrueColorTools.

TCT gives each body a colour from a measured reflectance spectrum, scaled to
the geometric albedo of the database entry. Those albedos do not share one
definition: an entry can be one hemisphere, exclude the opposition surge, or
have no albedo (TCT then makes the brightest channel 1). So this script keeps
only the hue from TCT. The export (``export/small_body_color.py``) sets the
brightness from a V-band geometric albedo of one definition.

Emits ``constants/small_body_colors.json``:

    {
      "neutral_linear": [1, 1, 1],   # hue of a flat spectrum: grey
      "by_taxon": {"S": [r, g, b], ...},   # Bus-DeMeo class hue, luminance 1
      "by_spkid": {                  # asteroids and comets, by derivation
        "spectrum":   {"20000004": {"chroma": [r, g, b], "albedo": 0.38}, ...},
        "photometry": {"20000433": {"chroma": [r, g, b]}, ...},
      },
      "by_naif": {                   # natural satellites, keyed by NAIF id
        "spectrum":   {"607": {"chroma": [r, g, b], "albedo": 0.25}, ...},
      }
    }

``chroma`` is linear sRGB at luminance 1. ``albedo`` is the V-band value of
the entry's geometric albedo spectrum, absent where TCT has none. The export
uses it only for a body with no albedo from a better source.

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

# TCT names carry the IAU Roman-numeral satellite designation, e.g. "Europa
# (J II)". NAIF satellite ids are planet_digit*100 + designation number, so the
# mapping is exact (J II → 502, S LIII → 653 Aegaeon). TCT uses M for Mars.
_PLANET_DIGIT = {"E": 3, "M": 4, "J": 5, "S": 6, "U": 7, "N": 8, "P": 9}
_DESIGNATION = re.compile(r"\(([EMJSUNP]) ([IVXLC]+)\)")
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman_to_int(s: str) -> int:
    total = prev = 0
    for ch in reversed(s):
        v = _ROMAN[ch]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def _naif_of(name: str) -> int | None:
    """NAIF id from a TCT satellite name, or None if it carries no designation."""
    m = _DESIGNATION.search(name)
    if not m:
        return None
    return _PLANET_DIGIT[m.group(1)] * 100 + _roman_to_int(m.group(2))


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
        get_filter,
    )

    return (
        db,
        database_parser,
        ColorPoint,
        ColorSystem,
        ObjectName,
        Spectrum,
        get_filter,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tct-root", type=Path, default=_DEFAULT_TCT)
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=_OUT)
    args = ap.parse_args()

    out_path = args.out.resolve()  # resolve before chdir into the TCT root
    db_path = args.db.resolve()

    (
        db,
        database_parser,
        ColorPoint,
        ColorSystem,
        ObjectName,
        Spectrum,
        get_filter,
    ) = _load_tct(args.tct_root.resolve())
    import numpy as np

    # A reflectance spectrum is the colour of the surface in sunlight, with the
    # sunlight shown white. Its white is the flat spectrum, Illuminant E, so
    # the Bradford adaptation from E to the D65 of sRGB (TCT's own default)
    # makes a grey surface grey.
    srgb = ColorSystem("sRGB", "Illuminant E")
    v_band = get_filter("Generic_Bessell.V")

    def luminance(linear) -> float:
        """sRGB/Rec.709 relative luminance of a linear-light RGB triple."""
        r, g, b = linear
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def chroma(linear) -> list[float]:
        """Normalize a linear colour to luminance 1. Falls back to neutral grey
        if black."""
        lin = np.asarray(linear, dtype=float)
        y = luminance(lin)
        if y <= 0:
            return [1.0, 1.0, 1.0]
        return [round(float(v), 6) for v in lin / y]

    def linear_of(spectrum) -> np.ndarray:
        """Linear sRGB of a spectrum, desaturated into the gamut by TCT."""
        c = ColorPoint.from_spectral_data(spectrum).to_color_system(srgb)
        c.gamma_correction = False
        return np.asarray(c.to_array())

    def entry_of(name, entry) -> dict:
        """Hue of a database entry, and its V-band geometric albedo if TCT has one."""
        spectrum, estimated = database_parser(name, entry).get_spectrum("geometric")
        out: dict = {"chroma": chroma(linear_of(spectrum))}
        if estimated is not None:
            out["albedo"] = round(float((spectrum @ v_band)[0]), 4)
        return out

    objs, _refs = db.import_DBs(["spectra"])

    # --- neutral chroma: flat reflectance = 1 (the reflectance-1 white point) ---
    nm = np.arange(380, 781, 5)
    flat = Spectrum(nm, np.ones_like(nm, dtype=float), name=ObjectName("neutral"))
    neutral_linear = chroma(linear_of(flat))
    if max(neutral_linear) - min(neutral_linear) > 1e-5:
        raise SystemExit(f"a flat spectrum is not grey: {neutral_linear}")

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
            spectrum, _ = database_parser(name, entry).get_spectrum("geometric")
            taxon_linear.setdefault(cls, []).append(linear_of(spectrum))
        except Exception as e:  # noqa: BLE001
            print(f"  skip taxon {name}: {e}", file=sys.stderr)

    by_taxon = {
        cls: chroma(np.mean(arrs, axis=0)) for cls, arrs in taxon_linear.items()
    }

    # Per-body hues are grouped by derivation method so the export can credit
    # each: `spectrum` = a measured reflectance spectrum, `photometry` = SBDB
    # broadband B-V/U-B colour indices. Both run through TrueColorTools' engine.
    def sort_by_id(d: dict[str, dict]) -> dict[str, dict]:
        return dict(sorted(d.items(), key=lambda kv: int(kv[0])))

    # --- spectrum: individually-measured named bodies in TCT ---
    # Keys look like "4 Vesta [refs]" / "134340 Pluto [refs]". Skip sub-region
    # entries ("4 Vesta: Bright areas", "Ahuna Mons (Ceres)").
    by_spectrum: dict[str, dict] = {}
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
            by_spectrum[spkid] = entry_of(name, entry)
        except Exception as e:  # noqa: BLE001
            skipped_named += 1
            print(f"  skip named {name}: {e}", file=sys.stderr)

    # --- photometry: SBDB B-V + U-B colour indices through the TCT engine ---
    # Hue only: the export takes the albedo from SBDB itself.
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT spkid, BV, UB FROM sbdb WHERE BV IS NOT NULL AND UB IS NOT NULL"
    ).fetchall()
    con.close()
    print(
        f"  photometry: {len(rows)} candidate bodies ...", file=sys.stderr, flush=True
    )
    by_photometry: dict[str, dict] = {}
    bv_skipped = 0
    for i, (spkid, bv, ub) in enumerate(rows):
        if i and i % 100 == 0:
            print(f"    ...{i}/{len(rows)}", file=sys.stderr, flush=True)
        if spkid is None or str(spkid) in by_spectrum:  # a measured spectrum wins
            continue
        entry: dict[str, object] = {
            "photometric_system": "Generic_Bessell",
            "color_indices": {"U-B": float(ub), "B-V": float(bv)},
            "calibration_system": "Vega",
        }
        try:
            spectrum, _ = database_parser(
                ObjectName(f"sbdb-{spkid}"), entry
            ).get_spectrum("geometric")
            by_photometry[str(spkid)] = {"chroma": chroma(linear_of(spectrum))}
        except Exception as e:  # noqa: BLE001
            bv_skipped += 1
            print(f"  skip BV/UB {spkid}: {e}", file=sys.stderr)

    # --- by_naif: moons/natural satellites in TCT, keyed by NAIF id ---
    # The `natural satellite/...` tag excludes rings, aurorae and surface
    # features. Each body keeps one entry. The order of preference is: the disk
    # entry that TCT features, then any disk entry or featured hemisphere entry
    # (the Moon has only hemisphere entries), then any hemisphere entry. An entry
    # for one region only ("Bright areas") is not used. Ties break on the name.
    naif_cands: dict[int, list[tuple[int, str, object, object]]] = {}
    for name, entry in objs.items():
        tags = entry.get("tags", [])
        if not any(str(t).startswith("natural satellite") for t in tags):
            continue
        s = str(name)
        naif = _naif_of(s)
        if naif is None:
            continue
        base = s.split(" | ")[0]
        if ":" not in base:
            rank = 0 if "featured" in tags else 1
        elif re.search(r"hemisphere|side", base, re.IGNORECASE):
            rank = 2 if "featured" not in tags else 1
        else:
            rank = 3  # material/region only — last resort
        naif_cands.setdefault(naif, []).append((rank, s, name, entry))

    by_naif: dict[str, dict] = {}
    naif_skipped = 0
    for naif, cands in naif_cands.items():
        cands.sort(key=lambda c: (c[0], c[1]))
        best_rank, best_label, best_name, best_entry = cands[0]
        if best_rank == 3:
            naif_skipped += 1
            print(
                f"  skip moon {naif}: only sub-region data ({best_label})",
                file=sys.stderr,
            )
            continue
        try:
            by_naif[str(naif)] = entry_of(best_name, best_entry)
        except Exception as e:  # noqa: BLE001
            naif_skipped += 1
            print(f"  skip moon {naif} ({best_label}): {e}", file=sys.stderr)

    out = {
        "neutral_linear": neutral_linear,
        "by_taxon": dict(sorted(by_taxon.items())),
        "by_spkid": {
            "spectrum": sort_by_id(by_spectrum),
            "photometry": sort_by_id(by_photometry),
        },
        "by_naif": {
            "spectrum": sort_by_id(by_naif),
        },
    }
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="UTF-8")

    print(
        f"\nwrote {out_path}\n"
        f"  neutral_linear = {neutral_linear}\n"
        f"  by_taxon       = {len(by_taxon)} classes\n"
        f"  by_spkid       = {len(by_spectrum)} spectrum + {len(by_photometry)} photometry "
        f"(skipped {skipped_named}+{bv_skipped})\n"
        f"  by_naif        = {len(by_naif)} moons (skipped {naif_skipped})"
    )


if __name__ == "__main__":
    main()
