"""Durable record of the bot's posts, under ``sources/activity/dsn-bot/``.

``events/<date>.jsonl.gz``
    One line per post, read into fields: which spacecraft, which dish, what
    rate. The posts themselves are not kept — the account serves its whole
    history in one request, so re-reading them is a refetch away, and a copy
    of someone else's record is not ours to hold.
``state.json``
    Per-code roll-up — first and last downlink the bot saw.

The repository is cumulative, so a refetch is a superset of the last one and
only posts newer than the last import are folded in.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from space_map_data.tracking.dailylog import DailyLog
from space_map_data.constants.tracking import DSN_OBJECT_IDS
from space_map_data.tracking.dsn.feed import SpacecraftInfo, codes_by_name
from space_map_data.tracking.dsnbot.repo import Post, parse_event, when
from space_map_data.utils.paths import SOURCES_DIR

logger = logging.getLogger(__name__)

BOT_DIR = SOURCES_DIR / "activity" / "dsn-bot"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class BotState:
    """Roll-up for one DSN code as the bot reported it."""

    code: str
    name: str = ""
    first_event: str = ""
    last_event: str = ""
    last_dish: str = ""
    last_data_rate: float | None = None
    events: int = 0


class BotStore:
    def __init__(self, root: Path = BOT_DIR) -> None:
        self.root = root
        self.events = DailyLog(root / "events")
        self.state_file = root / "state.json"

        self.posts = 0
        self.last_imported = ""
        self.codes: dict[str, BotState] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        data = json.loads(self.state_file.read_text())
        self.posts = data.get("posts", 0)
        self.last_imported = data.get("last_imported", "")
        self.codes = {
            code: BotState(**entry) for code, entry in data.get("codes", {}).items()
        }
        logger.info("Loaded %d bot-seen codes from %s", len(self.codes), self.root)

    def record(self, posts: list[Post], config: dict[str, SpacecraftInfo]) -> list[str]:
        """Fold in every post we have not seen. Returns codes new to this store.

        The feed's own dictionary does the naming both ways: the first three
        days of posts print a spacecraft's friendly name, every day after that
        prints its code.
        """
        names = codes_by_name(config)
        new: list[str] = []
        for post in posts:
            if post.created_at <= self.last_imported:
                continue
            self.posts += 1
            self.last_imported = post.created_at
            event = parse_event(post.text)
            if event is None:
                # Kept verbatim, because a line we cannot read is the one thing
                # a refetch will not explain on its own.
                logger.warning("Unreadable post: %s", post.text)
                self.events.append(
                    when(post), {"t": post.created_at, "text": post.text}
                )
                continue

            code = _code_for(event.craft, names)
            self.events.append(
                when(post),
                {
                    "t": post.created_at,
                    "c": code,
                    "d": event.dish,
                    "rate": event.data_rate,
                },
            )
            state = self.codes.get(code)
            if state is None:
                state = BotState(code=code, first_event=post.created_at)
                self.codes[code] = state
                new.append(code)
            info = config.get(code)
            state.name = info.friendly_name if info else ""
            state.last_event = post.created_at
            state.last_dish = event.dish
            state.last_data_rate = event.data_rate
            state.events += 1
        self._flush()
        return new

    def _flush(self) -> None:
        state = {
            "updated_at": _now(),
            "posts": self.posts,
            "last_imported": self.last_imported,
            "codes": {code: asdict(s) for code, s in sorted(self.codes.items())},
        }
        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, self.state_file)


def _code_for(craft: str, names: dict[str, tuple[str, ...]]) -> str:
    """The DSN code a post meant, or the text it used if that is not decidable.

    Posts print the code, except in the first days when they printed the
    friendly name. Where two codes share a name, the one we hold an object for
    wins — the other is the variant nothing in our record ever refers to.
    """
    craft = craft.upper()
    candidates = names.get(craft, ())
    if len(candidates) == 1:
        return candidates[0]
    known = [code for code in candidates if code in DSN_OBJECT_IDS]
    return known[0] if len(known) == 1 else craft
