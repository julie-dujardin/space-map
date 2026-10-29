"""Mean heliocentric orbital elements for the major planets, from JPL Horizons.

The planets have no SBDB row, so the Solar System minimap and the planet
family rules read their semi-major axis, inclination, eccentricity and
sidereal period from here. Each value is the mean of the Horizons osculating
elements over one orbital period, which removes the periodic terms. The
export loads the JSON like a static table. The frame is heliocentric
(CENTER=Sun), the ecliptic (REF_PLANE=ECLIPTIC) of J2000.
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


# Output key → Horizons ELEMENTS column: a [AU], i [deg], e, sidereal period [d].
_COLUMNS = {"a": "A", "i": "IN", "e": "EC", "period": "PR"}


def _mean_elements(text: str) -> tuple[dict[str, float], int]:
    """The mean of each of `_COLUMNS` over the ELEMENTS rows in a Horizons CSV
    reply, and the number of rows."""
    header = next(
        line for line in text[: text.index("$$SOE")].splitlines() if "JDTDB" in line
    )
    cols = [c.strip() for c in header.split(",")]
    index = {key: cols.index(col) for key, col in _COLUMNS.items()}
    block = text[text.index("$$SOE") + 5 : text.index("$$EOE")]
    values: dict[str, list[float]] = {key: [] for key in _COLUMNS}
    for row in csv.reader(io.StringIO(block)):
        cells = [c.strip() for c in row]
        if len(cells) <= max(index.values()) or not cells[index["a"]]:
            continue
        for key, i in index.items():
            values[key].append(float(cells[i]))
    if not values["a"]:
        raise ValueError("no element rows in Horizons reply")
    means = {key: statistics.fmean(found) for key, found in values.items()}
    return means, len(values["a"])


def fetch_planet_elements(client: httpx.Client, out_dir: Path) -> None:
    """Bake mean planet elements to ``<out_dir>/planet_elements.json``.

    Shape: ``{"199": {"a": <AU>, "i": <deg>, "e": <1>, "period": <d>}, …}``
    keyed by NAIF id.
    """
    elements: dict[str, dict[str, float]] = {}
    for naif_id, (command, period_yr) in _PLANETS.items():
        try:
            text = _fetch_elements(client, command, period_yr)
            means, n = _mean_elements(text)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Horizons elements for %d failed: %s", naif_id, exc)
            continue
        elements[str(naif_id)] = {
            "a": round(means["a"], 6),
            "i": round(means["i"], 4),
            "e": round(means["e"], 6),
            "period": round(means["period"], 4),
        }
        logger.info("Horizons mean elements %d: %s (n=%d)", naif_id, means, n)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "planet_elements.json"
    path.write_bytes(orjson.dumps(elements, option=orjson.OPT_INDENT_2))
    logger.info("Wrote %d planet elements → %s", len(elements), path)
