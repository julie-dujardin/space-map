"""Planet numbers: the registry's Planets part.

A planet is (host, number). The number counts from 1 within its host. At the
first ingest the planets of a host take their numbers by discovery year, then
letter, then designation; a later planet takes the next free number. A number
is never given twice.

Each record of the part is either a link, (host, number) ← a catalogue id with
status live, or a status change of (host, number): alias of another planet,
(alias_host, alias_target), or retired. The latest record wins.

A planet of a later ingest finds its number by any of its catalogue ids. A
planet that no id finds tries the free numbers of its host by letter and by a
period within 20%, which finds an exoplanet.eu planet with a new name. The
host of a number is the star the planet orbits, so a planet whose host is
now another ID (its star merged, or a catalogue moved it) takes a number on
the new host, and its old number becomes an alias of it: the old URL
redirects. A planet that two numbers claim joins them: the number on its
host, else the older one, survives and the other becomes its alias. A number
that no planet takes retires: its URL then 404s.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar.exoplanets.catalogues import close
from space_map_data.extrasolar.ids import cell_of
from space_map_data.extrasolar.registry import (
    ALIAS,
    LIVE,
    PLANETS,
    RETIRED,
    Registry,
    RegistryError,
)

logger = logging.getLogger(__name__)

PART = "planets"
LETTER_PERIOD_TOLERANCE = 0.2
# Share of the live planets that one ingest may retire.
MAX_RETIRED_SHARE = 0.05
MIN_RETIRED_CAP = 10

Number = tuple[int, int]
CatalogueId = tuple[str, str, str]


@dataclass(frozen=True)
class Incoming:
    """A planet of this ingest, with its host ID and its catalogue ids."""

    index: int
    host: int
    ids: tuple[CatalogueId, ...]
    year: int | None
    letter: str | None
    designation: str
    period: float | None


@dataclass
class PartState:
    """The Planets part as the earlier ingests left it."""

    status: dict[Number, str] = field(default_factory=dict)
    alias_target: dict[Number, Number] = field(default_factory=dict)
    first_ingest: dict[Number, int] = field(default_factory=dict)
    link: dict[CatalogueId, Number] = field(default_factory=dict)
    top: dict[int, int] = field(default_factory=dict)

    @classmethod
    def build(cls, records: pa.Table) -> PartState:
        state = cls()
        rows = sorted(records.to_pylist(), key=lambda r: r["ingest"])
        for row in rows:
            number = (row["host"], row["number"])
            state.first_ingest.setdefault(number, row["ingest"])
            state.top[row["host"]] = max(state.top.get(row["host"], 0), row["number"])
            if row["status"] == LIVE and row["catalogue"] is not None:
                state.link[(row["catalogue"], row["release"], row["catalogue_id"])] = (
                    number
                )
                state.status.setdefault(number, LIVE)
            else:
                state.status[number] = row["status"]
                if row["status"] == ALIAS:
                    state.alias_target[number] = (
                        row["alias_host"],
                        row["alias_target"],
                    )
        return state

    def live_end(self, number: Number) -> Number | None:
        """The live planet at the end of an alias chain, None when there is
        none."""
        seen = set()
        while self.status.get(number) == ALIAS and number not in seen:
            seen.add(number)
            number = self.alias_target[number]
        return number if self.status.get(number) == LIVE else None


def read_state(registry: Registry) -> PartState:
    tables = [
        registry.read_part(PART, region) for region in registry.part_regions(PART)
    ]
    records = pa.concat_tables(tables) if tables else PLANETS.empty_table()
    return PartState.build(records)


@dataclass
class Previous:
    """Letters and periods of the numbers in the last planets table."""

    letter: dict[Number, str | None] = field(default_factory=dict)
    period: dict[Number, float | None] = field(default_factory=dict)


@dataclass
class Assignment:
    number: dict[int, Number]
    records: pa.Table
    # The incoming planets by what they get: a new number, their number
    # again, or a number on a new host. The three add up to all of them.
    new: int = 0
    kept: int = 0
    moved: int = 0
    events: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    @property
    def unreviewed(self) -> int:
        return sum(len(self.events[k]) for k in ("merged", "host changed", "split"))


def _text(number: Number) -> str:
    return f"{number[0]}/b/{number[1]}"


def assign(
    incoming: list[Incoming],
    state: PartState,
    previous: Previous,
    ingest: int,
    complete: bool,
    max_retired: int | None = None,
) -> Assignment:
    """Numbers for the planets of this ingest, and the records to add."""
    events: dict[str, list[str]] = defaultdict(list)
    records: list[dict] = []

    def record(
        number: Number,
        status: str,
        target: Number | None = None,
        cid: CatalogueId | None = None,
    ) -> None:
        catalogue, release, catalogue_id = cid or (None, None, None)
        records.append(
            {
                "host": number[0],
                "number": number[1],
                "status": status,
                "alias_target": None if target is None else target[1],
                "alias_host": None if target is None else target[0],
                "catalogue": catalogue,
                "release": release,
                "catalogue_id": catalogue_id,
                "ingest": ingest,
            }
        )

    # Live numbers that the catalogue ids of each planet find.
    found: dict[int, list[Number]] = {}
    for planet in incoming:
        hits: list[Number] = []
        for cid in planet.ids:
            number = state.link.get(cid)
            if number is None:
                continue
            end = state.live_end(number)
            if end is None:
                events["retired hit"].append(
                    f"{'/'.join(cid)} named {_text(number)}, which is retired"
                )
            elif end not in hits:
                hits.append(end)
        found[planet.index] = hits

    # A number that several planets find goes to the one with most ids on it.
    claimants: dict[Number, list[tuple[int, int]]] = defaultdict(list)
    for planet in incoming:
        for number in found[planet.index]:
            on_it = sum(1 for cid in planet.ids if state.link.get(cid) == number)
            claimants[number].append((-on_it, planet.index))
    designations = {p.index: p.designation for p in incoming}
    for number, wanted in sorted(claimants.items()):
        wanted.sort()
        for _, other in wanted[1:]:
            found[other].remove(number)
            events["split"].append(
                f"{_text(number)} stays with {designations[wanted[0][1]]};"
                f" {designations[other]} also names it"
            )

    number_of: dict[int, Number] = {}
    # Planets whose numbers are on another host, by planet: those numbers.
    moved: dict[int, list[Number]] = {}
    for planet in incoming:
        hits = found[planet.index]
        if not hits:
            continue
        survivor = min(
            hits,
            key=lambda n: (n[0] != planet.host, state.first_ingest.get(n, ingest), n),
        )
        if survivor[0] != planet.host:
            moved[planet.index] = hits
            continue
        number_of[planet.index] = survivor
        for loser in hits:
            if loser != survivor:
                record(loser, ALIAS, target=survivor)
                events["merged"].append(
                    f"{_text(loser)} is now an alias of {_text(survivor)}:"
                    f" {planet.designation} holds the ids of both"
                )

    # A planet that no id finds tries the free numbers of its host. A number
    # that any planet's ids find is not free, even when it merges away.
    found_now = {number for hits in found.values() for number in hits}
    free: dict[int, list[Number]] = defaultdict(list)
    for number, status in sorted(state.status.items()):
        if status == LIVE and number not in found_now:
            free[number[0]].append(number)
    for planet in incoming:
        if planet.index in number_of:
            continue
        options = [
            n
            for n in free.get(planet.host, [])
            if planet.letter
            and previous.letter.get(n) == planet.letter
            and close(previous.period.get(n), planet.period, LETTER_PERIOD_TOLERANCE)
        ]
        if len(options) == 1:
            number_of[planet.index] = options[0]
            free[planet.host].remove(options[0])
            events["found by letter and period"].append(
                f"{planet.designation} takes {_text(options[0])}"
            )

    # New planets take the next numbers of their host.
    new = [p for p in incoming if p.index not in number_of]
    new.sort(
        key=lambda p: (p.host, p.year or 9999, p.letter or "~", p.designation, p.index)
    )
    top = dict(state.top)
    for planet in new:
        top[planet.host] = top.get(planet.host, 0) + 1
        number_of[planet.index] = (planet.host, top[planet.host])

    # The old numbers of a planet on a new host point to its number there.
    for planet in incoming:
        for old in moved.get(planet.index, []):
            now = number_of[planet.index]
            record(old, ALIAS, target=now)
            events["host changed"].append(
                f"{_text(old)} is now an alias of {_text(now)}: the host of"
                f" {planet.designation} is now {planet.host}"
            )

    # Links that the part does not hold yet.
    by_index = {p.index: p for p in incoming}
    for index, number in sorted(number_of.items(), key=lambda t: t[1]):
        for cid in by_index[index].ids:
            if state.link.get(cid) != number:
                record(number, LIVE, cid=cid)

    # Live numbers that no planet takes retire.
    taken_now = set(number_of.values())
    merged_away = {(r["host"], r["number"]) for r in records if r["status"] != LIVE}
    live = [
        n for n, s in sorted(state.status.items()) if s == LIVE and n not in merged_away
    ]
    leaving = [n for n in live if n not in taken_now]
    if leaving and complete:
        cap = max_retired
        if cap is None:
            cap = max(MIN_RETIRED_CAP, int(len(live) * MAX_RETIRED_SHARE))
        if len(leaving) > cap:
            raise RegistryError(
                f"the ingest would retire {len(leaving)} planets, over the cap of {cap}"
            )
        for number in leaving:
            record(number, RETIRED)
            events["retired"].append(_text(number))
    elif leaving:
        events["not seen, kept (partial input)"] += [_text(n) for n in leaving]

    for kind, texts in events.items():
        level = logging.WARNING if kind in ("merged", "host changed") else logging.INFO
        for text in texts:
            logger.log(level, "planet %s: %s", kind, text)
    table = pa.Table.from_pylist(records, schema=PLANETS)
    # A planet on a new host can take a free number there, so it is not
    # always in `new`.
    fresh = sum(1 for p in new if p.index not in moved)
    return Assignment(
        number_of,
        sort_records(table),
        new=fresh,
        kept=len(incoming) - fresh - len(moved),
        moved=len(moved),
        events=events,
    )


def sort_records(table: pa.Table) -> pa.Table:
    """Records sorted by the cell of their host, then host and number."""
    if not table.num_rows:
        return table
    host = table["host"].to_numpy()
    order = np.lexsort((table["number"].to_numpy(), host, cell_of(host)))
    return table.take(order)
