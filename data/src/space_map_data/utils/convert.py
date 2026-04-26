from datetime import date, datetime, timezone


def date_to_julian(value: date | str) -> float | None:
    """Convert a date or ISO 8601 datetime string to a Julian Date.

    Naive datetimes (e.g. CelesTrak's ``2026-04-25T14:51:50.576832``) are
    interpreted as UTC — otherwise ``timestamp()`` would treat them as local
    time and shift JDs by the host's offset.
    """
    if isinstance(value, date):
        return value.toordinal() + 1721424.5
    if not value or not value.strip():
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp() / 86400.0 + 2440587.5
