"""CSV value conversion helpers.

Raise errors for invalid values, and convert empty/whitespace-only strings to None.
"""

import calendar
import datetime
import math
from pathlib import Path

GM_EARTH = 398600.4418  # km^3/s^2

_GCAT_MONTHS = {abbr: i for i, abbr in enumerate(calendar.month_abbr) if abbr}


def count_csv_rows(path: Path) -> int:
    """Count data rows in a CSV file (excludes header)."""
    with open(path) as f:
        return sum(1 for _ in f) - 1


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


def gcat_date_to_iso(val: str | None) -> str | None:
    """Convert a GCAT "Vague Date" to a partial ISO 8601 string at its precision.

    ``1958 Jul 25`` → ``1958-07-25``; ``2022 Jan 6 2149`` → ``2022-01-06T21:49``;
    ``1957 Oct 4 1928:34`` → ``1957-10-04T19:28:34``; ``1961`` → ``1961``;
    ``1961 Apr`` → ``1961-04``. Times are UTC (implied, like satcat's
    ``launch_date``); the trailing ``?`` uncertainty marker is dropped — the
    raw string keeps it. Returns None for empty values or forms GCAT doesn't
    use here (centiday, hour-suffix, BC, century descriptors).
    """
    if not val or not val.strip():
        return None
    parts = val.strip().rstrip("?").split()
    if not parts or not parts[0].isdigit():
        return None
    iso = f"{int(parts[0]):04d}"
    if len(parts) >= 2:
        month = _GCAT_MONTHS.get(parts[1])
        if month is None:
            return iso  # quarter (Q1-Q4) or unknown token — keep year
        iso += f"-{month:02d}"
    if len(parts) >= 3:
        if not parts[2].isdigit():
            return iso
        iso += f"-{int(parts[2]):02d}"
    if len(parts) >= 4:
        clock, _, sec = parts[3].partition(":")
        if len(clock) != 4 or not clock.isdigit():
            return iso  # hour-suffix / centiday — keep date precision
        iso += f"T{clock[:2]}:{clock[2:]}"
        if sec:
            try:
                iso += f":{int(float(sec)):02d}"
            except ValueError:
                pass
    return iso


def mean_motion_to_a_km(mean_motion_rev_per_day: float) -> float:
    """Derive semi-major axis in km from mean motion in rev/day."""
    n_rad_s = mean_motion_rev_per_day * 2.0 * math.pi / 86400.0
    return (GM_EARTH / (n_rad_s * n_rad_s)) ** (1.0 / 3.0)
