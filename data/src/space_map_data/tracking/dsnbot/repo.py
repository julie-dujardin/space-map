"""Fetch the bot's repository and read the posts out of it.

``com.atproto.sync.getRepo`` returns every record the account has ever written
as one CAR file — 8 MB for 31k posts — so there is no paging and no rate limit
to work around. The host to ask is whichever PDS the DID document currently
names, which is why that is resolved rather than hardcoded.

The posts themselves are prose, and the grammar has been stable since the third
day: ``<site> DSS <n> receiving data from <spacecraft> at <rate>.`` The rate
occasionally comes out empty upstream, which is the one variant worth handling.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime

import cbor2
import httpx

logger = logging.getLogger(__name__)

BOT_DID = "did:plc:szn6zrt3kifgyxdaf2w6f2uw"
BOT_HANDLE = "dsn-status.bot.country"
PLC_URL = f"https://plc.directory/{BOT_DID}"
POST_TYPE = "app.bsky.feed.post"

# "Canberra DSS 34 receiving data from RST at 354.5 kb/s." The site prefix is
# missing from the first three days, the rate from 0.5% of posts.
EVENT = re.compile(
    r"^(?:(?P<site>\w+) )?DSS (?P<dish>\d+) receiving data from (?P<craft>.+?)"
    r"(?: at (?P<rate>[\d.]* ?[kMG]?b/s)?)?\.$"
)
RATE_UNITS = {"b/s": 1, "kb/s": 1e3, "Mb/s": 1e6, "Gb/s": 1e9}


class BotError(Exception):
    """The repository could not be fetched or read this run."""


@dataclass(frozen=True)
class Post:
    """One post, as written."""

    created_at: str
    text: str


@dataclass(frozen=True)
class Event:
    """A post read as what it describes."""

    craft: str
    dish: str
    site: str | None
    data_rate: float | None


def fetch_repo(client: httpx.Client) -> bytes:
    """Download the account's whole repository as a CAR file."""
    try:
        document = client.get(PLC_URL).raise_for_status().json()
        service = next(
            s["serviceEndpoint"]
            for s in document["service"]
            if s["type"] == "AtprotoPersonalDataServer"
        )
        response = client.get(
            f"{service}/xrpc/com.atproto.sync.getRepo", params={"did": BOT_DID}
        )
        response.raise_for_status()
    except (httpx.HTTPError, KeyError, StopIteration, ValueError) as e:
        raise BotError(f"could not fetch {BOT_HANDLE}'s repository: {e}") from e
    logger.info("Fetched %s: %d bytes", BOT_HANDLE, len(response.content))
    return response.content


def parse_posts(car: bytes) -> list[Post]:
    """Every post in a CAR file, oldest first.

    Blocks are read individually rather than by walking the repository's merkle
    tree: we want all of one record type, not a consistent view of the account.
    """
    posts = []
    for block in _blocks(car):
        try:
            record = cbor2.loads(block)
        except Exception:
            continue
        if not isinstance(record, dict) or record.get("$type") != POST_TYPE:
            continue
        created_at, text = record.get("createdAt"), record.get("text")
        if isinstance(created_at, str) and isinstance(text, str):
            posts.append(Post(created_at=created_at, text=text))
    if not posts:
        raise BotError("no posts in the repository — has the format changed?")
    return sorted(posts, key=lambda p: p.created_at)


def parse_event(text: str) -> Event | None:
    """Read one post, or None if it is not a downlink line."""
    match = EVENT.match(text)
    if match is None:
        return None
    return Event(
        craft=match["craft"].strip(),
        dish=f"DSS{match['dish']}",
        site=match["site"],
        data_rate=_rate(match["rate"]),
    )


def when(post: Post) -> datetime:
    """When the bot saw it, which is not when the feed changed."""
    return datetime.fromisoformat(post.created_at)


def _rate(raw: str | None) -> float | None:
    """Bits per second. The space before the unit came in later; both appear."""
    match = re.fullmatch(r"([\d.]+) ?([kMG]?b/s)", raw.strip()) if raw else None
    if match is None:
        return None
    try:
        return float(match[1]) * RATE_UNITS[match[2]]
    except ValueError:
        return None


def _blocks(car: bytes):
    """Yield each block's payload, skipping the header and every CID."""
    header_length, offset = _varint(car, 0)
    offset += header_length
    while offset < len(car):
        length, offset = _varint(car, offset)
        end = offset + length
        yield car[offset + _cid_length(car, offset) : end]
        offset = end


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = buf[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7


def _cid_length(buf: bytes, i: int) -> int:
    """CIDv1 is version, codec, hash function and digest length, then digest."""
    if buf[i] == 0x12 and buf[i + 1] == 0x20:
        return 34  # CIDv0 is a bare sha-256 multihash.
    j = i + 1
    _, j = _varint(buf, j)
    _, j = _varint(buf, j)
    digest_length, j = _varint(buf, j)
    return j + digest_length - i
