"""Body origin dates → the `visible_from_days` render gate.

Shared by the elements and chebyshev position writers so a body's discovery /
launch date gates its rendering identically regardless of which ephemeris
backs it.
"""

from datetime import date

from space_map_data.export.position.format import MISSING_FLOAT32
from space_map_data.models.object import Object, OrbitalSource
from space_map_data.utils.convert import date_to_julian
from space_map_data.utils.time import J2000_JD, year_to_jd


def _iso_date_to_jd(value: str) -> float | None:
    """Parse a `YYYY-MM-DD` or bare `YYYY` date string to a JD."""
    s = value.strip()
    try:
        return date_to_julian(date.fromisoformat(s))
    except ValueError:
        pass
    try:
        return year_to_jd(int(s))
    except ValueError:
        return None


def origin_date(o: Object) -> str | None:
    """Origin date as an ISO date or bare year: discovery for small bodies and
    their moons, natural-moon `discovery_year`, launch for Earth sats. Gated
    on a scalar column first — a bare relation access would lazy-load in a
    worker thread.
    """
    if o.spkid is not None and o.sbdb is not None:
        return o.sbdb.first_obs
    if o.satcat_norad_cat_id is not None and o.satcat is not None:
        return o.satcat.launch_date
    if o.orbital_source == OrbitalSource.sbdb_moon and o.sbdb_moon is not None:
        year = o.sbdb_moon.year
        return str(year) if year is not None else None
    if o.discovery_year is not None:
        return str(o.discovery_year)
    return None


def visible_from_days(o: Object, start_jd: float) -> float:
    """Days from J2000 to when `o` first exists, or NaN ("always visible").

    NaN means no gating: missing/unparseable date, or one at/before `start_jd`
    (already existed when the chunk opens). The compare only bites bounded
    chunks (Earth sats, moon zones); unbounded SBDB files pass -inf.
    """
    origin = origin_date(o)
    if origin is None:
        return MISSING_FLOAT32
    jd = _iso_date_to_jd(origin)
    if jd is None or jd <= start_jd:
        return MISSING_FLOAT32
    return jd - J2000_JD
