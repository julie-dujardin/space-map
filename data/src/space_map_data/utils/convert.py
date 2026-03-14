from datetime import date, datetime


def date_to_julian(value: date | str) -> float | None:
    """Convert a date or ISO 8601 datetime string to a Julian Date."""
    if isinstance(value, date):
        return value.toordinal() + 1721424.5
    if not value or not value.strip():
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.timestamp() / 86400.0 + 2440587.5
