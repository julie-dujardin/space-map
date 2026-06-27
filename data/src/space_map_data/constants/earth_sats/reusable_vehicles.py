"""Individual reusable vehicles (orbiters, boosters) behind an lv- family.

GCAT has no per-vehicle catalog, so each family parses its own identity out of a
launchlog row: the Shuttle orbiter from the payload name, a Falcon core serial
from the flight id. Drives the top-N reusable-vehicle breakdown on lv- pages.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ReusableVehicle:
    """One vehicle flown by a launch. ``id`` is the display label; cores have no QID."""

    id: str
    qid: str | None = None


# Shuttle orbiter → Wikidata entity (each has its own Wikipedia article).
_ORBITER_QID = {
    "Columbia": "Q54383",
    "Challenger": "Q54382",
    "Discovery": "Q54384",
    "Atlantis": "Q54381",
    "Endeavour": "Q182508",
}
_ORBITER_RE = re.compile(r"^([A-Za-z]+)\s*\(STS")
_CORE_RE = re.compile(r"B(\d{4})")


def _shuttle(flight_id: str | None, name: str | None) -> list[ReusableVehicle]:
    m = _ORBITER_RE.match(name or "")
    if not m:
        return []
    orbiter = m.group(1)
    return [ReusableVehicle(orbiter, _ORBITER_QID.get(orbiter))]


def _falcon(flight_id: str | None, name: str | None) -> list[ReusableVehicle]:
    # GCAT records the core serial(s) in the flight id; early v1.0 flights have none.
    return [
        ReusableVehicle(f"B{c}") for c in sorted(set(_CORE_RE.findall(flight_id or "")))
    ]


# Family slug → extractor (returns every reusable vehicle on one launch).
REUSABLE_VEHICLE_EXTRACTORS: dict[
    str, Callable[[str | None, str | None], list[ReusableVehicle]]
] = {
    "space-shuttle": _shuttle,
    "falcon": _falcon,
}

REUSABLE_VEHICLE_QIDS: frozenset[str] = frozenset(_ORBITER_QID.values())
