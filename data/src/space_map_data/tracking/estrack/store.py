"""Durable record of ESTRACK activity, under ``sources/activity/estrack/``.

``state.json``
    Per-mission roll-up — the last month that carried service volume, which is
    the ESA answer to "when was this last talked to".
``months/<YYYY-MM>.json``
    Each month's figures as fetched. Kept per month because the current one
    keeps growing, and because the backend only publishes a three-month window:
    once a month falls out of it, our copy is the only one left.
``live/<date>.jsonl.gz``
    One row per live poll, holding both payloads whole. The flags have read
    false for every mission since we started watching, and a file full of empty
    polls is what makes that a finding rather than an absence of looking.
``missions.json`` / ``stations.json``
    Reference data, with a dated copy kept whenever it changes.
"""

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from space_map_data.tracking.dailylog import DailyLog
from space_map_data.tracking.estrack.api import MonthStats
from space_map_data.utils.paths import SOURCES_DIR

logger = logging.getLogger(__name__)

ESTRACK_DIR = SOURCES_DIR / "activity" / "estrack"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


@dataclass
class MissionState:
    """Roll-up for one ESTRACK mission code."""

    code: str
    # Filled in by hand once researched — nothing derives it.
    object_id: str | None = None
    name: str = ""
    first_seen: str = ""
    # The newest month carrying service volume. Null means listed but silent
    # across every month we hold, which is how a retired mission reads.
    last_active_month: str | None = None
    last_volume: float = 0.0
    volume_by_month: dict[str, float] = field(default_factory=dict)
    last_live_at: str | None = None
    live_polls: int = 0


class EstrackStore:
    def __init__(self, root: Path = ESTRACK_DIR) -> None:
        self.root = root
        self.months_dir = root / "months"
        self.state_file = root / "state.json"
        self.live = DailyLog(root / "live")
        self.months_dir.mkdir(parents=True, exist_ok=True)

        self.live_polls = 0
        self.missions: dict[str, MissionState] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        data = json.loads(self.state_file.read_text())
        self.live_polls = data.get("live_polls", 0)
        self.missions = {
            code: MissionState(**entry)
            for code, entry in data.get("missions", {}).items()
        }
        logger.info("Loaded %d ESTRACK missions from %s", len(self.missions), self.root)

    def record_month(self, stats: MonthStats, names: dict[str, str]) -> list[str]:
        """Fold one month's figures in. Returns mission codes seen for the first time."""
        _atomic_write(
            self.months_dir / f"{stats.month}.json",
            json.dumps(
                {
                    "fetched_at": _now(),
                    "month": stats.month,
                    "network": stats.network,
                    "missions": stats.missions,
                    "stations": stats.stations,
                },
                indent=2,
            ),
        )

        new: list[str] = []
        for code, entry in stats.missions.items():
            state = self.missions.get(code)
            if state is None:
                state = MissionState(code=code, first_seen=_now())
                self.missions[code] = state
                new.append(code)
            if code in names:
                state.name = names[code]
            volume = float(entry.get("serviceVolume") or 0)
            state.volume_by_month[stats.month] = volume
            # A month can still be filling in, so recompute from the whole
            # record rather than trusting this fetch to be the newest.
            active = sorted(m for m, v in state.volume_by_month.items() if v > 0)
            state.last_active_month = active[-1] if active else None
            state.last_volume = (
                state.volume_by_month[state.last_active_month]
                if state.last_active_month
                else 0.0
            )
        self._flush()
        return new

    def record_live(self, missions: dict, stations: dict) -> list[str]:
        """Note a live poll. Returns the mission codes reported live, if any."""
        self.live_polls += 1
        observed = _now()
        live = sorted(c for c, e in missions.items() if e.get("live"))
        live_stations = sorted(c for c, e in stations.items() if e.get("live"))
        for code in live:
            state = self.missions.get(code)
            if state is None:
                state = MissionState(code=code, first_seen=observed)
                self.missions[code] = state
            state.last_live_at = observed
            state.live_polls += 1
        self.live.append(
            datetime.now(UTC),
            {
                "observed": observed,
                "live_missions": live,
                "live_stations": live_stations,
                "missions": missions,
                "stations": stations,
            },
        )
        self._flush()
        return live

    def store_reference(self, missions: list, stations: list) -> dict[str, str]:
        """Keep the descriptions, and return the code → name map they carry."""
        for name, payload in (("missions", missions), ("stations", stations)):
            self._store_if_changed(name, json.dumps(payload, indent=2))
        return {
            m["code"]: m.get("name", "")
            for m in missions
            if isinstance(m, dict) and m.get("code")
        }

    def _store_if_changed(self, name: str, text: str) -> None:
        path = self.root / f"{name}.json"
        if path.exists():
            if (
                hashlib.sha256(path.read_bytes()).digest()
                == hashlib.sha256(text.encode()).digest()
            ):
                return
            logger.info("ESTRACK %s changed upstream, archiving previous copy", name)
        _atomic_write(self.root / f"{name}-{_stamp()}.json", text)
        _atomic_write(path, text)

    def _flush(self) -> None:
        _atomic_write(
            self.state_file,
            json.dumps(
                {
                    "updated_at": _now(),
                    "live_polls": self.live_polls,
                    "missions": {
                        code: asdict(m) for code, m in sorted(self.missions.items())
                    },
                },
                indent=2,
            ),
        )


def _atomic_write(path: Path, text: str) -> None:
    """Rename over the target so a kill mid-write can't truncate the record."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
