"""Fetch and parse the two DSN Now XML documents.

``dsn.xml`` is the live state, rewritten every ~5 seconds. ``config.xml`` is
the dictionary: it maps each short DSN code to a human name, so it is the only
thing that makes a sighting interpretable.

Attribute names follow the DSN Now client's own parser
(``eyes.nasa.gov/apps/dsn-now/javascripts/sites.js``); the feed is undocumented,
so every field is read defensively and a missing one is never fatal.
"""

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

DSN_XML_URL = "https://eyes.nasa.gov/dsn/data/dsn.xml"
CONFIG_XML_URL = "https://eyes.nasa.gov/apps/dsn-now/config.xml"

# Targets that are the network testing against itself, not a spacecraft.
NON_SPACECRAFT_TARGETS = frozenset({"DSN", "DSS", "TEST"})


class FeedError(Exception):
    """The feed could not be fetched or parsed this poll."""


@dataclass(frozen=True)
class Signal:
    direction: str
    spacecraft: str | None
    band: str | None
    data_rate: float | None
    power: float | None


@dataclass(frozen=True)
class Target:
    code: str
    dsn_id: str | None
    upleg_range: float | None
    downleg_range: float | None
    rtlt: float | None


@dataclass(frozen=True)
class Dish:
    name: str
    station: str
    activity: str | None
    targets: tuple[Target, ...]
    signals: tuple[Signal, ...]
    # The element verbatim, kept so a first sighting can be snapshotted with
    # every field the feed carried rather than only the ones parsed here.
    raw: str


@dataclass(frozen=True)
class FeedSnapshot:
    fetched_at: datetime
    feed_time: datetime | None
    dishes: tuple[Dish, ...]
    # The document as fetched. Parsing keeps only the fields we understand, and
    # the feed publishes no history, so the archive has to hold the original.
    raw: str = ""

    def active_targets(self) -> dict[str, tuple[Dish, Target]]:
        """Spacecraft codes currently pointed at, keyed by uppercase code.

        A code on two dishes at once (MSPA, arraying) keeps the first — the
        pair only feeds contact grouping, and the sighting is the same either
        way.
        """
        found: dict[str, tuple[Dish, Target]] = {}
        for dish in self.dishes:
            for target in dish.targets:
                if target.code in NON_SPACECRAFT_TARGETS:
                    continue
                found.setdefault(target.code, (dish, target))
        return found


@dataclass(frozen=True)
class SpacecraftInfo:
    """One ``<spacecraft>`` entry of ``config.xml``'s spacecraft map."""

    code: str
    friendly_name: str
    explorer_name: str
    friendly_acronym: str | None
    raw: str


def _float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_signal(node: ET.Element, direction: str) -> Signal | None:
    """Return the signal only when the feed marks it active."""
    if node.get("active") != "true":
        return None
    return Signal(
        direction=direction,
        spacecraft=(node.get("spacecraft") or "").upper() or None,
        band=node.get("band") or None,
        data_rate=_float(node.get("dataRate")),
        power=_float(node.get("power")),
    )


def _parse_dish(node: ET.Element, station: str) -> Dish:
    targets: list[Target] = []
    signals: list[Signal] = []
    for child in node:
        if child.tag == "target":
            name = (child.get("name") or "").strip().upper()
            if not name:
                continue
            targets.append(
                Target(
                    code=name,
                    dsn_id=child.get("id"),
                    upleg_range=_float(child.get("uplegRange")),
                    downleg_range=_float(child.get("downlegRange")),
                    rtlt=_float(child.get("rtlt")),
                )
            )
        elif child.tag in ("upSignal", "downSignal"):
            signal = _parse_signal(child, "up" if child.tag == "upSignal" else "down")
            if signal is not None:
                signals.append(signal)
    return Dish(
        name=node.get("name") or "",
        station=station,
        activity=node.get("activity") or None,
        targets=tuple(targets),
        signals=tuple(signals),
        raw=ET.tostring(node, encoding="unicode"),
    )


def parse_feed(xml_text: str, fetched_at: datetime) -> FeedSnapshot:
    """Parse ``dsn.xml``.

    ``<station>`` and ``<dish>`` are siblings, each dish belonging to the
    station that precedes it, so document order carries the association.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise FeedError(f"dsn.xml did not parse: {e}") from e

    dishes: list[Dish] = []
    feed_time: datetime | None = None
    station = ""
    for node in root:
        if node.tag == "station":
            station = node.get("friendlyName") or node.get("name") or ""
            if feed_time is None:
                feed_time = _feed_time(node.get("timeUTC"))
        elif node.tag == "dish":
            dishes.append(_parse_dish(node, station))
    return FeedSnapshot(
        fetched_at=fetched_at,
        feed_time=feed_time,
        dishes=tuple(dishes),
        raw=xml_text,
    )


def _feed_time(raw: str | None) -> datetime | None:
    """Station clocks are epoch milliseconds."""
    if not raw:
        return None
    try:
        return datetime.fromtimestamp(int(raw) / 1000, tz=UTC)
    except ValueError:
        return None


def parse_config(xml_text: str) -> dict[str, SpacecraftInfo]:
    """Parse ``config.xml``'s spacecraft map, keyed by uppercase code."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise FeedError(f"config.xml did not parse: {e}") from e

    out: dict[str, SpacecraftInfo] = {}
    for node in root.iter("spacecraft"):
        name = (node.get("name") or "").strip()
        if not name:
            continue
        out[name.upper()] = SpacecraftInfo(
            code=name.upper(),
            friendly_name=node.get("friendlyName") or "",
            explorer_name=node.get("explorerName") or "",
            friendly_acronym=node.get("friendlyAcronym"),
            raw=ET.tostring(node, encoding="unicode"),
        )
    return out


def fetch_feed(client: httpx.Client) -> FeedSnapshot:
    """Fetch and parse ``dsn.xml``.

    The cache-busting query parameter matches the DSN Now client's own: the
    document sits behind CloudFront with a one-hour max-age it does not honour
    for itself.
    """
    url = f"{DSN_XML_URL}?r={int(time.time() // 5)}"
    return parse_feed(_get(client, url), datetime.now(UTC))


def fetch_config(client: httpx.Client) -> tuple[str, dict[str, SpacecraftInfo]]:
    text = _get(client, CONFIG_XML_URL)
    return text, parse_config(text)


def _get(client: httpx.Client, url: str) -> str:
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise FeedError(f"{url}: {type(e).__name__}: {e}") from e
    return response.text
