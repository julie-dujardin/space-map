"""Mean heliocentric orbital elements for the major planets, from JPL Horizons.

The planets carry no SBDB row (they're SPICE-tracked), so the Solar System
minimap needs their semi-major axis + inclination from elsewhere. We average
Horizons osculating elements over one full orbital period — that cancels the
periodic wobble and yields clean mean values — and bake them to a JSON the
export loads like a static table. Inclination is referred to the ecliptic
(REF_PLANE=ECLIPTIC), heliocentric (CENTER=Sun), J2000.
"""

import csv
import datetime
import io
import logging
import statistics
from pathlib import Path

import httpx
import orjson

logger = logging.getLogger(__name__)

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"

# Planet NAIF id → (Horizons command for the system barycenter, sidereal period
# [yr]). The barycenter (1…9) gives the planet's heliocentric orbit; the period
# only sizes the averaging window, so rough values are fine.
_PLANETS: dict[int, tuple[str, float]] = {
    199: ("1", 0.2408467),
    299: ("2", 0.6151973),
    399: ("3", 1.0000174),  # Earth–Moon barycenter
    499: ("4", 1.8808476),
    599: ("5", 11.862615),
    699: ("6", 29.447498),
    799: ("7", 84.016846),
    899: ("8", 164.79132),
    999: ("9", 247.92065),
}

_SAMPLES = 360  # samples across one period; the mean is robust well below this


def _fetch_elements(client: httpx.Client, command: str, period_yr: float) -> str:
    """Horizons ELEMENTS ephemeris over exactly one orbital period (CSV)."""
    stop = datetime.date(2000, 1, 1) + datetime.timedelta(days=period_yr * 365.25)
    params = {
        "format": "text",
        "COMMAND": f"'{command}'",
        "OBJ_DATA": "NO",
        "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "ELEMENTS",
        "CENTER": "'500@10'",  # Sun body center → heliocentric
        "REF_PLANE": "ECLIPTIC",
        "REF_SYSTEM": "J2000",
        "OUT_UNITS": "AU-D",
        "CSV_FORMAT": "YES",
        "START_TIME": "2000-01-01",
        "STOP_TIME": stop.isoformat(),
        "STEP_SIZE": str(_SAMPLES),
    }
    resp = client.get(HORIZONS_URL, params=params, timeout=60)
    resp.raise_for_status()
    return resp.text


def _mean_a_i(text: str) -> tuple[float, float, int]:
    """Mean (a [AU], i [deg]) over the ELEMENTS rows in a Horizons CSV reply."""
    header = next(
        line for line in text[: text.index("$$SOE")].splitlines() if "JDTDB" in line
    )
    cols = [c.strip() for c in header.split(",")]
    i_a, i_in = cols.index("A"), cols.index("IN")
    block = text[text.index("$$SOE") + 5 : text.index("$$EOE")]
    a_vals: list[float] = []
    i_vals: list[float] = []
    for row in csv.reader(io.StringIO(block)):
        cells = [c.strip() for c in row]
        if len(cells) <= max(i_a, i_in) or not cells[i_a]:
            continue
        a_vals.append(float(cells[i_a]))
        i_vals.append(float(cells[i_in]))
    if not a_vals:
        raise ValueError("no element rows in Horizons reply")
    return statistics.fmean(a_vals), statistics.fmean(i_vals), len(a_vals)


def fetch_planet_elements(client: httpx.Client, out_dir: Path) -> None:
    """Bake mean planet elements to ``<out_dir>/planet_elements.json``.

    Shape: ``{"199": {"a": <AU>, "i": <deg>}, …}`` keyed by NAIF id.
    """
    elements: dict[str, dict[str, float]] = {}
    for naif_id, (command, period_yr) in _PLANETS.items():
        try:
            text = _fetch_elements(client, command, period_yr)
            a, i, n = _mean_a_i(text)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Horizons elements for %d failed: %s", naif_id, exc)
            continue
        elements[str(naif_id)] = {"a": round(a, 6), "i": round(i, 4)}
        logger.info(
            "Horizons mean elements %d: a=%.4f AU, i=%.4f deg (n=%d)", naif_id, a, i, n
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "planet_elements.json"
    path.write_bytes(orjson.dumps(elements, option=orjson.OPT_INDENT_2))
    logger.info("Wrote %d planet elements → %s", len(elements), path)
