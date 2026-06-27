"""Generate moon geometric albedos from JPL Horizons OBJ_DATA.

JPL's static "Planetary Satellite Physical Parameters" table dropped albedo in
its 2021 site redesign (it now lists only GM / mean radius / mean density), but
Horizons still prints a ``Geometric Albedo`` line in each body's OBJ_DATA block.
We harvest it per moon to feed the neutral-grey "albedo" colour tier in
``export/small_body_color.py``: a moon TrueColorTools never measured (most
irregular satellites) then gets a physically-correct *brightness* — a dark P-type
captured grey vs a bright icy grey — instead of one flat generic tint.

Only planetary satellites carry a Horizons albedo, so we query the moons whose
NAIF id is a classical satellite number (< 1000); the 5-digit provisional-name
moons (recent discoveries) have no published albedo and are skipped.

Emits ``constants/moon_albedos.json``: ``{"<naif>": <geometric_albedo>, ...}``.

One-off generator, regenerated when Horizons refreshes. NOT on the export hot
path. Run under the project venv (needs httpx + the DB):

    uv run python scripts/generate_moon_albedos.py
"""

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx

from space_map_data.download.providers.spice.synth.horizons_api import fetch_obj_data

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB = _REPO_ROOT.parent / "space-map-downloads" / "db" / "space-map.db"
_OUT = (
    _REPO_ROOT / "data" / "src" / "space_map_data" / "constants" / "moon_albedos.json"
)

# Classical satellite NAIF ids are planet_digit*100 + number (< 1000); 5-digit
# ids are provisional-name moons Horizons has no albedo for.
_MAX_PLANETARY_NAIF = 1000

# Horizons prints the line a few ways: "Geometric Albedo=  0.081 +- 0.002",
# "Geometric Albedo    =  0.04", "Geometric albedo ~ 0.5". Grab the first float.
_ALBEDO_RE = re.compile(r"Geometric\s+[Aa]lbedo\s*[=~:]?\s*([0-9]*\.?[0-9]+)")


def _moon_naif_ids(db_path: Path) -> list[int]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT naif_id FROM objects "
            "WHERE object_type = 'moon' AND naif_id IS NOT NULL AND naif_id < ? "
            "ORDER BY naif_id",
            (_MAX_PLANETARY_NAIF,),
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _parse_albedo(raw: str) -> float | None:
    m = _ALBEDO_RE.search(raw)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    # Reject implausible parses (a stray "0" from an unrelated field, >1 albedo).
    if not (0.0 < val <= 1.0):
        logger.warning("  naif %s: implausible albedo %.3f — skipped", "?", val)
        return None
    return val


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=_OUT)
    ap.add_argument(
        "--delay", type=float, default=0.7, help="seconds between Horizons calls"
    )
    args = ap.parse_args()

    naif_ids = _moon_naif_ids(args.db.resolve())
    logger.info("Querying Horizons for %d planetary satellites ...", len(naif_ids))

    albedos: dict[str, float] = {}
    no_albedo = 0
    errors = 0
    with httpx.Client() as client:
        for i, naif in enumerate(naif_ids):
            if i and i % 25 == 0:
                logger.info(
                    "  ...%d/%d (%d with albedo)", i, len(naif_ids), len(albedos)
                )
            try:
                obj = fetch_obj_data(client, naif)
            except httpx.HTTPError as e:
                errors += 1
                logger.warning("  naif %s: Horizons error %s", naif, e)
                continue
            albedo = _parse_albedo(obj.raw)
            if albedo is None:
                no_albedo += 1
            else:
                albedos[str(naif)] = round(albedo, 4)
            time.sleep(args.delay)

    out = dict(sorted(albedos.items(), key=lambda kv: int(kv[0])))
    args.out.resolve().write_text(json.dumps(out, indent=2) + "\n", encoding="UTF-8")
    logger.info(
        "\nwrote %s\n  %d moons with albedo, %d without, %d errors (of %d queried)",
        args.out,
        len(albedos),
        no_albedo,
        errors,
        len(naif_ids),
    )


if __name__ == "__main__":
    main()
