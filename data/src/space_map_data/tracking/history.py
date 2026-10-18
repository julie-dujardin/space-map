"""The curated record of last contacts, ``sources/activity/history/last-contact.json``.

For craft that no network we watch hears any more: the last time a signal
from them was received, as their mission records state it. One object keyed
by object id; ``last_contact`` is in one of the events files' date forms, at
the precision the record supports, or null with a ``reason`` where the
research found none, so that it is not done twice. ``source``, ``note`` and
``confidence`` are for the curator.

Read whole at every publish, so a new copy takes effect without a restart.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from space_map_data.probes.events import DatePrecision, date_precision
from space_map_data.utils.paths import SOURCES_DIR

logger = logging.getLogger(__name__)

HISTORY_FILE = SOURCES_DIR / "activity" / "history" / "last-contact.json"


@dataclass(frozen=True)
class LastContact:
    """One craft's last signal, as the record states it."""

    last_contact: str
    precision: DatePrecision


def load(path: Path = HISTORY_FILE) -> dict[str, LastContact]:
    """Every entry with a legal date. A bad one is left out rather than
    stopping the publish, which carries the live networks too."""
    if not path.exists():
        logger.warning("No curated last contacts at %s", path)
        return {}
    record: dict[str, LastContact] = {}
    for object_id, entry in json.loads(path.read_text()).items():
        if entry["last_contact"] is None:
            continue
        precision = date_precision(entry["last_contact"])
        if precision is None:
            logger.warning(
                "%s: %r is not an events-file date, left out",
                object_id,
                entry["last_contact"],
            )
            continue
        record[object_id] = LastContact(entry["last_contact"], precision)
    return record
