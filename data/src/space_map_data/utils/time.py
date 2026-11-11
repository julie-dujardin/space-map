"""JD↔ET helpers and time constants shared across pipelines."""

import datetime

import erfa

J2000_JD = 2451545.0
S_PER_DAY = 86400.0
DAYS_PER_YEAR = 365.25


def jd_to_et(jd: float) -> float:
    """JD (TDB) → seconds past J2000 (ET)."""
    return (jd - J2000_JD) * S_PER_DAY


def utc_jd_to_tdb(jd: float) -> float:
    """JD (UTC) → JD (TDB), with the leap seconds. TDB and TT differ by less
    than 2 ms, which is ignored."""
    tt1, tt2 = erfa.taitt(*erfa.utctai(jd, 0.0))
    return tt1 + tt2


def et_to_jd(et: float) -> float:
    """ET (TDB seconds past J2000) → Julian Date TDB."""
    return J2000_JD + et / S_PER_DAY


def year_to_jd(year: int) -> float:
    """Civil-year start (Jan 1 00:00) → Julian Date (proleptic Gregorian)."""
    return datetime.date(year, 1, 1).toordinal() + 1721424.5
