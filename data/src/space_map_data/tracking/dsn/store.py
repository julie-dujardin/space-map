"""Durable record of what the DSN has been talking to.

Everything lands under ``sources/activity/dsn/`` in the downloads tree rather
than the database: the record is only worth anything once it spans months, and
an ingest run rebuilds DB tables from scratch.

Four kinds of output, because they answer different questions:

``state.json``
    Current roll-up, one entry per DSN code — the "last activity" lookup.
``contacts.jsonl``
    Append-only closed contacts: the pass pattern, without reading every poll.
``raw/<date>.jsonl.gz``
    Every poll's document, verbatim. The archive of record: parsing keeps only
    the fields we understand today, and the feed publishes no history, so
    anything dropped here is unrecoverable.
``observations/<date>.jsonl.gz``
    The same polls parsed into one row per tracked spacecraft — the convenient
    view, rebuildable from ``raw/`` if the parser changes.
``snapshots/<code>/``
    The first sighting of a code, verbatim. DSN codes map to nothing we hold,
    so this is the evidence an unknown one gets linked to an object from.
"""

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeIs

from space_map_data.tracking.dailylog import DailyLog
from space_map_data.tracking.dsn.feed import (
    DSN_XML_URL,
    Dish,
    FeedSnapshot,
    Signal,
    SpacecraftInfo,
    Target,
)
from space_map_data.utils.paths import SOURCES_DIR

logger = logging.getLogger(__name__)

DSN_DIR = SOURCES_DIR / "activity" / "dsn"

# A spacecraft drops off the feed between passes and during MSPA handovers.
# Anything shorter than this is the same contact, not a new one.
CONTACT_GAP = timedelta(minutes=30)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _age(iso: str) -> timedelta:
    return datetime.now(UTC) - datetime.fromisoformat(iso)


@dataclass
class SpacecraftState:
    """Roll-up for one DSN code."""

    code: str
    # Filled in by hand once a code is researched — nothing derives it.
    object_id: str | None = None
    friendly_name: str = ""
    explorer_name: str = ""
    friendly_acronym: str | None = None
    first_seen: str = ""
    last_target_at: str = ""
    last_signal_at: str | None = None
    last_dish: str = ""
    last_station: str = ""
    last_band: str | None = None
    last_data_rate: float | None = None
    last_rtlt: float | None = None
    last_downleg_range: float | None = None
    target_polls: int = 0
    signal_polls: int = 0
    contacts: int = 0


@dataclass
class OpenContact:
    """A contact still in progress, kept across restarts so it isn't split."""

    code: str
    dish: str
    station: str
    start: str
    end: str
    polls: int = 0
    signal_polls: int = 0
    bands: list[str] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)
    max_data_rate: float | None = None
    min_rtlt: float | None = None


class ActivityStore:
    def __init__(self, root: Path = DSN_DIR) -> None:
        self.root = root
        self.snapshots_dir = root / "snapshots"
        self.observations = DailyLog(root / "observations")
        self.raw = DailyLog(root / "raw")
        self.state_file = root / "state.json"
        self.open_file = root / "contacts-open.json"
        self.contacts_file = root / "contacts.jsonl"
        self.config_file = root / "config.xml"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        self.polls = 0
        self.spacecraft: dict[str, SpacecraftState] = {}
        self.open: dict[str, OpenContact] = {}
        self._load()

    def _load(self) -> None:
        if self.state_file.exists():
            data = json.loads(self.state_file.read_text())
            self.polls = data.get("polls", 0)
            self.spacecraft = {
                code: SpacecraftState(**entry)
                for code, entry in data.get("spacecraft", {}).items()
            }
        if self.open_file.exists():
            self.open = {
                key: OpenContact(**entry)
                for key, entry in json.loads(self.open_file.read_text()).items()
            }
        logger.info(
            "Loaded %d spacecraft, %d open contacts from %s",
            len(self.spacecraft),
            len(self.open),
            self.root,
        )

    def record(
        self, snapshot: FeedSnapshot, config: dict[str, SpacecraftInfo]
    ) -> list[str]:
        """Fold one poll into the record. Returns codes seen for the first time."""
        self.polls += 1
        observed = snapshot.fetched_at.isoformat(timespec="seconds")
        new_codes: list[str] = []
        rows: list[dict] = []

        for code, (dish, target) in snapshot.active_targets().items():
            info = config.get(code)
            state = self.spacecraft.get(code)
            if state is None:
                state = SpacecraftState(code=code, first_seen=observed)
                self.spacecraft[code] = state
                new_codes.append(code)
                self._write_snapshot(code, observed, dish, info)
                logger.info(
                    "New DSN code %s (%s) on %s",
                    code,
                    info.friendly_name if info else "unknown to config.xml",
                    dish.name,
                )
            if info is not None:
                state.friendly_name = info.friendly_name
                state.explorer_name = info.explorer_name
                state.friendly_acronym = info.friendly_acronym
            self._update_state(state, observed, dish, target)
            self._update_contact(state, observed, dish, target)
            rows.append(_observation(dish, target))

        # One line per poll either way, including a poll that saw nothing: the
        # network sat idle for five hours on the first day of recording, and
        # that was only legible because the empty samples were there to count.
        at = snapshot.fetched_at
        self.raw.append(at, {"t": observed, "xml": snapshot.raw})
        self.observations.append(at, {"t": observed, "targets": rows})
        self._close_stale()
        self._flush()
        return new_codes

    def _update_state(
        self, state: SpacecraftState, observed: str, dish: Dish, target: Target
    ) -> None:
        state.last_target_at = observed
        state.last_dish = dish.name
        state.last_station = dish.station
        state.target_polls += 1
        # -1 is the feed's "no value", carried on most passes. Keeping the last
        # real reading makes these the last known range, not the last sentinel.
        if _measured(target.rtlt):
            state.last_rtlt = target.rtlt
        if _measured(target.downleg_range):
            state.last_downleg_range = target.downleg_range
        signal = _signal_for(dish, state.code)
        if signal is None:
            return
        state.last_signal_at = observed
        state.signal_polls += 1
        state.last_band = signal.band
        state.last_data_rate = signal.data_rate

    def _update_contact(
        self, state: SpacecraftState, observed: str, dish: Dish, target: Target
    ) -> None:
        key = f"{state.code}|{dish.name}"
        contact = self.open.get(key)
        if contact is None:
            contact = OpenContact(
                code=state.code,
                dish=dish.name,
                station=dish.station,
                start=observed,
                end=observed,
            )
            self.open[key] = contact
        contact.end = observed
        contact.polls += 1
        if _measured(target.rtlt):
            contact.min_rtlt = (
                target.rtlt
                if contact.min_rtlt is None
                else min(contact.min_rtlt, target.rtlt)
            )
        # Every link counts here, unlike the roll-up's single latest signal:
        # a contact is worth knowing used both directions and both bands.
        signals = _signals_for(dish, state.code)
        if not signals:
            return
        contact.signal_polls += 1
        for signal in signals:
            if signal.band and signal.band not in contact.bands:
                contact.bands.append(signal.band)
            if signal.direction not in contact.directions:
                contact.directions.append(signal.direction)
            if signal.data_rate is not None:
                contact.max_data_rate = (
                    signal.data_rate
                    if contact.max_data_rate is None
                    else max(contact.max_data_rate, signal.data_rate)
                )

    def _close_stale(self) -> None:
        stale = [key for key, c in self.open.items() if _age(c.end) > CONTACT_GAP]
        if not stale:
            return
        with self.contacts_file.open("a") as f:
            for key in stale:
                contact = self.open.pop(key)
                f.write(json.dumps(asdict(contact)) + "\n")
                state = self.spacecraft.get(contact.code)
                if state is not None:
                    state.contacts += 1
            f.flush()
        logger.info("Closed %d contact(s)", len(stale))

    def _write_snapshot(
        self, code: str, observed: str, dish: Dish, info: SpacecraftInfo | None
    ) -> None:
        """Keep the feed and dictionary entries a first sighting was made of."""
        out_dir = self.snapshots_dir / code
        out_dir.mkdir(parents=True, exist_ok=True)
        parts = [
            f'<dsn-sighting code="{code}" observed="{observed}" source="{DSN_XML_URL}">',
            info.raw if info is not None else "<spacecraft-unknown/>",
            dish.raw,
            "</dsn-sighting>",
        ]
        (out_dir / f"{_stamp()}.xml").write_text("\n".join(parts))

    def store_config(self, xml_text: str) -> None:
        """Keep the current dictionary, and a dated copy whenever it changes.

        Codes get added and renamed upstream; without the dated copies an
        earlier sighting's name is silently rewritten.
        """
        if self.config_file.exists():
            previous = self.config_file.read_bytes()
            if (
                hashlib.sha256(previous).digest()
                == hashlib.sha256(xml_text.encode()).digest()
            ):
                return
            logger.info("config.xml changed upstream, archiving previous copy")
        _atomic_write(self.root / f"config-{_stamp()}.xml", xml_text)
        _atomic_write(self.config_file, xml_text)

    def _flush(self) -> None:
        state = {
            "updated_at": _now(),
            "polls": self.polls,
            "spacecraft": {
                code: asdict(s) for code, s in sorted(self.spacecraft.items())
            },
        }
        _atomic_write(self.state_file, json.dumps(state, indent=2))
        _atomic_write(
            self.open_file,
            json.dumps({k: asdict(v) for k, v in self.open.items()}, indent=2),
        )


def _observation(dish: Dish, target: Target) -> dict:
    """One spacecraft as this poll saw it. Keys are short — there are ~17k a day."""
    signal = _signal_for(dish, target.code)
    return {
        "c": target.code,
        "d": dish.name,
        "act": dish.activity,
        "band": signal.band if signal else None,
        "rate": signal.data_rate if signal else None,
        "dir": [s.direction for s in _signals_for(dish, target.code)],
        "dl": target.downleg_range if _measured(target.downleg_range) else None,
        "rtlt": target.rtlt if _measured(target.rtlt) else None,
    }


def _measured(value: float | None) -> TypeIs[float]:
    """The feed writes -1 for a range or light time it does not have."""
    return value is not None and value > 0


def _signals_for(dish: Dish, code: str) -> list[Signal]:
    """The dish's active signals for this spacecraft.

    A dish carries signals for every spacecraft it serves under MSPA, so the
    spacecraft attribute — not the dish — decides which ones are ours.
    """
    return [s for s in dish.signals if s.spacecraft == code]


def _signal_for(dish: Dish, code: str) -> Signal | None:
    """The one signal that stands for the contact — downlink is the telemetry."""
    signals = _signals_for(dish, code)
    for signal in signals:
        if signal.direction == "down":
            return signal
    return signals[0] if signals else None


def _atomic_write(path: Path, text: str) -> None:
    """Rename over the target so a kill mid-write can't truncate the record."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
