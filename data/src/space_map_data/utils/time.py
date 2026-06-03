"""JD↔ET helpers and time constants shared across pipelines."""

import datetime

J2000_JD = 2451545.0
S_PER_DAY = 86400.0
DAYS_PER_YEAR = 365.25


def jd_to_et(jd: float) -> float:
    """JD (TDB) → seconds past J2000 (ET)."""
    return (jd - J2000_JD) * S_PER_DAY


def et_to_jd(et: float) -> float:
    """ET (TDB seconds past J2000) → Julian Date TDB."""
    return J2000_JD + et / S_PER_DAY


def year_to_jd(year: int) -> float:
    """Civil-year start (Jan 1 00:00) → Julian Date (proleptic Gregorian)."""
    return datetime.date(year, 1, 1).toordinal() + 1721424.5
