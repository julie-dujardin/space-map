"""CSV value conversion helpers.

Raise errors for invalid values, and convert empty/whitespace-only strings to None.
"""

import datetime
import math

GM_EARTH = 398600.4418  # km^3/s^2


def string_or_none(val: str | None) -> str | None:
    """Convert empty or whitespace-only strings to None."""
    if not val or not val.strip():
        return None
    return val.strip()


def float_or_none(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    return float(val)


def bool_or_none(val: str | None) -> bool | None:
    """Convert Y/N flag to bool."""
    if not val or not val.strip():
        return None
    v = val.strip().lower()
    if v in ("y", "t", "true", "yes"):
        return True
    if v in ("n", "f", "false", "no"):
        return False
    raise ValueError(f"Cannot convert '{val}' to bool")


def int_or_none(val: str | None) -> int | None:
    """Convert string to int, treating empty or whitespace-only strings as None.

    Raise an error otherwise.
    """
    if val is None or val.strip() == "":
        return None
    return int(val)


def normalize_partial_date(val: str) -> str | None:
    """Normalize a possibly-partial date: 'YYYY-MM-DD' stays as-is, 'YYYY-??-??' becomes 'YYYY'. Handle BCE dates."""
    if not val or not val.strip():
        return None
    val = val.strip()

    # Handle BCE dates
    if val.startswith("-"):
        bce = True
        val = val[1:]
    else:
        bce = False

    # Handle years
    if "?" in val:
        val = val.split("-")[0]

    if bce:
        val = "-" + val
    return val


def date_or_none(val: str) -> datetime.date | None:
    """Convert 'YYYY-MM-DD' to date."""
    if not val or not val.strip():
        return None
    return datetime.date.fromisoformat(val.strip())


def datetime_or_none(val: str) -> datetime.datetime | None:
    """Convert 'YYYY-MM-DD.DDDDDDD' (fractional day) to datetime (epoch_cal/tp_cal)."""
    if not val or not val.strip():
        return None
    val = val.strip()
    date_str, _, frac_str = val.partition(".")
    d = datetime.date.fromisoformat(date_str)
    if frac_str:
        frac_day = float("0." + frac_str)
        seconds = frac_day * 86400
        td = datetime.timedelta(seconds=seconds)
    else:
        td = datetime.timedelta()
    return datetime.datetime(d.year, d.month, d.day) + td


def mean_motion_to_a_km(mean_motion_rev_per_day: float) -> float:
    """Derive semi-major axis in km from mean motion in rev/day."""
    n_rad_s = mean_motion_rev_per_day * 2.0 * math.pi / 86400.0
    return (GM_EARTH / (n_rad_s * n_rad_s)) ** (1.0 / 3.0)
