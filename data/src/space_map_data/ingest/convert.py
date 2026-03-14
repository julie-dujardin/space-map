"""CSV value conversion helpers."""

import math

GM_EARTH = 398600.4418  # km^3/s^2


def float_or_none(val: str) -> float | None:
    if not val or not val.strip():
        return None
    return float(val)


def bool_or_none(val: str) -> bool | None:
    """Convert Y/N flag to bool."""
    v = val.strip().upper() if val else ""
    if v.lower() in ("y", "t", "true", "yes"):
        return True
    if v.lower() in ("n", "f", "false", "no"):
        return False
    if v is None or v == "":
        return None
    raise ValueError(f"Cannot convert '{val}' to bool")


def int_or_none(val: str) -> int | None:
    """Convert string to int, treating empty or whitespace-only strings as None.

    Raise an error otherwise.
    """
    if not val or not val.strip():
        return None
    return int(val)


def mean_motion_to_a_km(mean_motion_rev_per_day: float) -> float:
    """Derive semi-major axis in km from mean motion in rev/day."""
    n_rad_s = mean_motion_rev_per_day * 2.0 * math.pi / 86400.0
    return (GM_EARTH / (n_rad_s * n_rad_s)) ** (1.0 / 3.0)
