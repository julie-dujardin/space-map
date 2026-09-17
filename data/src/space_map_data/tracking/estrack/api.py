"""Fetch the ESTRACKnow JSON routes.

Route shapes, read off the app bundle:

``/status``
    Backend heartbeat.
``/missions``, ``/stations``
    Reference data — mission and antenna descriptions.
``/missions/{YYYY-MM}``, ``/stations/{YYYY-MM}``, ``/statistics/{YYYY-MM}``
    Service volume and performance for that month.
``/missions/live``, ``/stations/live``
    Per-entity live flag.

``/missions/{anything}`` falls back to the live map rather than erroring, and a
month outside the published range answers 200 with every volume zeroed, so a
reply is never proof the month was real — :func:`fetch_month` checks the dates
list first.
"""

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://estracknow.esa.int"
LIVE_PATH = "live"


class EstrackError(Exception):
    """A route could not be fetched or did not answer with what it should."""


@dataclass(frozen=True)
class MonthStats:
    """One month of service volume, per mission and per antenna."""

    month: str
    network: dict
    missions: dict[str, dict]
    stations: dict[str, dict]

    def active_missions(self) -> dict[str, float]:
        """Missions with service volume this month — the activity signal."""
        return {
            code: entry["serviceVolume"]
            for code, entry in self.missions.items()
            if entry.get("serviceVolume")
        }


def _get(client: httpx.Client, path: str) -> object:
    url = f"{BASE_URL}/{path}"
    try:
        response = client.get(url)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        raise EstrackError(f"{url}: {type(e).__name__}: {e}") from e
    except ValueError as e:
        raise EstrackError(f"{url}: reply was not JSON: {e}") from e


def _expect_dict(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        raise EstrackError(f"/{path}: expected an object, got {type(value).__name__}")
    return value


def _expect_list(value: object, path: str) -> list:
    if not isinstance(value, list):
        raise EstrackError(f"/{path}: expected a list, got {type(value).__name__}")
    return value


def fetch_status(client: httpx.Client) -> dict:
    return _expect_dict(_get(client, "status"), "status")


def fetch_reference(client: httpx.Client) -> tuple[list, list]:
    """Mission and antenna descriptions. Slow-moving, worth diffing not polling."""
    missions = _expect_list(_get(client, "missions"), "missions")
    stations = _expect_list(_get(client, "stations"), "stations")
    return missions, stations


def fetch_months(client: httpx.Client) -> list[str]:
    """The months the backend actually holds, newest first."""
    dates = _expect_list(_get(client, "statistics/dates"), "statistics/dates")
    return [d for d in dates if isinstance(d, str)]


def fetch_month(client: httpx.Client, month: str) -> MonthStats:
    return MonthStats(
        month=month,
        network=_expect_dict(
            _get(client, f"statistics/{month}"), f"statistics/{month}"
        ),
        missions=_expect_dict(_get(client, f"missions/{month}"), f"missions/{month}"),
        stations=_expect_dict(_get(client, f"stations/{month}"), f"stations/{month}"),
    )


def fetch_live(client: httpx.Client) -> tuple[dict, dict]:
    """Per-mission and per-antenna live flags."""
    missions = _expect_dict(_get(client, f"missions/{LIVE_PATH}"), "missions/live")
    stations = _expect_dict(_get(client, f"stations/{LIVE_PATH}"), "stations/live")
    return missions, stations


def live_codes(entries: dict) -> list[str]:
    return sorted(code for code, entry in entries.items() if entry.get("live"))
