"""The published answer: when was each object last talked to.

One small file, rewritten whenever the poller learns something, served from a
deployment of its own (``infrastructure/live``) because it changes every few
minutes and the catalogue export does not.

Two things a reader needs and cannot reconstruct from the dates alone:

* ``sources`` — who saw it, how precisely, and since when. A missing object
  means "not seen since that source started", never "last heard from before
  that", and one of the three sources is someone else's work.
* ``precision`` — the DSN resolves a pass to the second, the bot's posts to the
  minute, ESTRACK only to the month that carried traffic. All three are "last
  contact"; only two are a time.
"""

import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from space_map_data.constants.tracking import (
    DSN_NON_SPACECRAFT,
    DSN_OBJECT_IDS,
    ESTRACK_OBJECT_IDS,
)
from space_map_data.tracking.dsn.store import ActivityStore
from space_map_data.tracking.dsnbot.repo import BOT_HANDLE
from space_map_data.tracking.dsnbot.store import BotStore
from space_map_data.tracking.estrack.store import EstrackStore
from space_map_data.utils.paths import LIVE_DIR

logger = logging.getLogger(__name__)

ACTIVITY_FILE = LIVE_DIR / "v1" / "activity.json"

# Where each date comes from and what it is worth. Published with the dates
# because two of these are narrower than they look and one is not ours.
SOURCES = {
    "dsn": {
        "network": "NASA Deep Space Network",
        "measures": "a pass, while the antenna is pointed at the spacecraft",
        "precision": "second",
        "via": "https://eyes.nasa.gov/dsn/",
    },
    "dsn-bot": {
        "network": "NASA Deep Space Network",
        "measures": "a downlink reaching data lock; carrier-only passes are absent",
        "precision": "minute",
        "via": f"https://bsky.app/profile/{BOT_HANDLE}",
        "credit": "Russ Garrett, pydsn (MIT)",
    },
    "estrack": {
        "network": "ESA ESTRACK",
        "measures": "service volume booked in a calendar month",
        "precision": "month",
        "via": "https://estracknow.esa.int/",
    },
}
# Ties go to the source that saw the most: a month and a timestamp inside it
# compare as "2026-09" < "2026-09-17T...", which is already the order we want.
RANK = {"dsn": 3, "dsn-bot": 2, "estrack": 1}


@dataclass(frozen=True)
class Sighting:
    """One network's last contact with one object."""

    network: str
    code: str
    name: str
    last_contact: str
    precision: str


def build(dsn: ActivityStore, estrack: EstrackStore, bot: BotStore) -> dict:
    """The published document, from the three stores as they currently stand."""
    sightings: dict[str, list[Sighting]] = {}
    unresolved: list[dict] = []

    for code, state in sorted(dsn.spacecraft.items()):
        if code in DSN_NON_SPACECRAFT or not state.last_target_at:
            continue
        sighting = Sighting(
            network="dsn",
            code=code,
            name=state.friendly_name,
            last_contact=state.last_target_at,
            precision="second",
        )
        _place(sightings, unresolved, DSN_OBJECT_IDS.get(code), sighting)

    for code, state in sorted(bot.codes.items()):
        if code in DSN_NON_SPACECRAFT:
            continue
        sighting = Sighting(
            network="dsn-bot",
            code=code,
            name=state.name,
            last_contact=state.last_event,
            precision="minute",
        )
        _place(sightings, unresolved, DSN_OBJECT_IDS.get(code), sighting)

    for code, state in sorted(estrack.missions.items()):
        if not state.last_active_month:
            continue
        sighting = Sighting(
            network="estrack",
            code=code,
            name=state.name,
            last_contact=state.last_active_month,
            precision="month",
        )
        _place(sightings, unresolved, ESTRACK_OBJECT_IDS.get(code), sighting)

    since = {
        "dsn": _earliest(s.first_seen for s in dsn.spacecraft.values()),
        "dsn-bot": _earliest(s.first_event for s in bot.codes.values()),
        "estrack": _earliest(s.first_seen for s in estrack.missions.values()),
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": {
            name: source | {"since": since[name]} for name, source in SOURCES.items()
        },
        "objects": {
            object_id: _entry(found) for object_id, found in sorted(sightings.items())
        },
        "unresolved": unresolved,
    }


def _place(
    sightings: dict[str, list[Sighting]],
    unresolved: list[dict],
    object_id: str | None,
    sighting: Sighting,
) -> None:
    if object_id is None:
        unresolved.append(
            {
                "network": sighting.network,
                "code": sighting.code,
                "name": sighting.name,
                "last_contact": sighting.last_contact,
            }
        )
        return
    sightings.setdefault(object_id, []).append(sighting)


def _entry(found: list[Sighting]) -> dict:
    """Every source's view, plus the one that answers "how long ago".

    The most recent sighting leads and the others are kept beside it rather
    than dropped, so a reader can see that three sources disagree by hours
    because they are measuring three different things.
    """
    lead = max(found, key=lambda s: (s.last_contact, RANK[s.network]))
    return {
        "last_contact": lead.last_contact,
        "precision": lead.precision,
        "network": lead.network,
        "seen": {
            s.network: {"code": s.code, "last_contact": s.last_contact} for s in found
        },
    }


def _earliest(values: Iterable[str]) -> str | None:
    stamps = sorted(v for v in values if v)
    return stamps[0] if stamps else None


def write(document: dict, path: Path = ACTIVITY_FILE) -> bool:
    """Write the document, unless only its timestamp would change.

    Returns whether anything was published. The poller rebuilds this far more
    often than the networks produce news, and an unchanged file that keeps a
    new mtime makes every deploy look like it carried something.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, indent=1)
    if path.exists():
        previous = json.loads(path.read_text())
        previous["generated_at"] = document["generated_at"]
        if previous == document:
            return False
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
    logger.info(
        "Published %d object(s), %d unresolved code(s) to %s",
        len(document["objects"]),
        len(document["unresolved"]),
        path,
    )
    return True
