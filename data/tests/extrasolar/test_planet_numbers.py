"""Tests for planet numbers: the registry's Planets part across ingests."""

import pyarrow as pa
import pytest

from space_map_data.extrasolar.exoplanets.numbering import (
    Incoming,
    PartState,
    Previous,
    assign,
)
from space_map_data.extrasolar.registry import (
    ALIAS,
    LIVE,
    PLANETS,
    RETIRED,
    RegistryError,
)

H1, H2 = 16_777_217, 33_554_433
ARCHIVE = ("nasa-exoplanet-archive", "pscomppars")
EU = ("exoplanet-eu", "catalog")


def planet(index, host, *ids, year=2010, letter="b", name=None, period=10.0):
    return Incoming(
        index,
        host,
        tuple(ids),
        year,
        letter,
        name or f"P{index}",
        period,
    )


def archive(n: int) -> tuple[str, str, str]:
    return (*ARCHIVE, f"3.{n}")


def eu(name: str) -> tuple[str, str, str]:
    return (*EU, name)


class Ingests:
    """The part across ingests, as the extension feeds it."""

    def __init__(self) -> None:
        self.records = PLANETS.empty_table()
        self.previous = Previous()
        self.ingest = 0

    def run(self, planets, complete=True, max_retired=None):
        self.ingest += 1
        state = PartState.build(self.records)
        result = assign(
            planets, state, self.previous, self.ingest, complete, max_retired
        )
        self.records = pa.concat_tables([self.records, result.records])
        by_index = {p.index: p for p in planets}
        for index, number in result.number.items():
            self.previous.letter[number] = by_index[index].letter
            self.previous.period[number] = by_index[index].period
        return result

    def statuses(self):
        state = PartState.build(self.records)
        return dict(state.status)


class TestFirstIngest:
    def test_numbers_by_year_then_letter(self):
        part = Ingests()
        result = part.run(
            [
                planet(0, H1, archive(1), year=2015, letter="b"),
                planet(1, H1, archive(2), year=2009, letter="c"),
                planet(2, H1, archive(3), year=2015, letter="d"),
                planet(3, H2, archive(4), year=2020),
            ]
        )
        assert result.number == {
            1: (H1, 1),
            0: (H1, 2),
            2: (H1, 3),
            3: (H2, 1),
        }
        assert result.new == 4 and result.unreviewed == 0
        assert part.records.num_rows == 4
        assert set(part.records["status"].to_pylist()) == {LIVE}


class TestLaterIngests:
    def first(self) -> Ingests:
        part = Ingests()
        part.run(
            [
                planet(0, H1, archive(1), eu("A b"), letter="b"),
                planet(1, H1, archive(2), eu("A c"), letter="c", period=30.0),
            ]
        )
        return part

    def test_ids_keep_numbers_and_new_planets_take_the_next(self):
        part = self.first()
        result = part.run(
            [
                planet(5, H1, archive(2), letter="c", period=30.0),
                planet(6, H1, archive(9), year=2001, letter="d"),
                planet(7, H1, eu("A b"), letter="b"),
            ]
        )
        assert result.number == {5: (H1, 2), 7: (H1, 1), 6: (H1, 3)}
        assert result.kept == 2 and result.new == 1

    def test_a_dropped_planet_retires_and_its_number_stays_used(self):
        part = self.first()
        result = part.run([planet(0, H1, archive(1))])
        assert result.events["retired"] == [f"{H1}/b/2"]
        assert part.statuses()[(H1, 2)] == RETIRED
        again = part.run(
            [planet(0, H1, archive(1)), planet(1, H1, archive(2), letter="c")]
        )
        # The retired number is never given again, even to its old ids.
        assert again.number[1] == (H1, 3)
        assert again.events["retired hit"]

    def test_a_partial_input_retires_nothing(self):
        part = self.first()
        result = part.run([planet(0, H1, archive(1))], complete=False)
        assert "retired" not in result.events
        assert result.events["not seen, kept (partial input)"] == [f"{H1}/b/2"]

    def test_the_retire_cap(self):
        part = self.first()
        with pytest.raises(RegistryError, match="retire 2 planets"):
            part.run([], max_retired=1)

    def test_a_renamed_planet_finds_its_number_by_letter_and_period(self):
        part = self.first()
        result = part.run(
            [
                planet(0, H1, archive(1), eu("A b")),
                planet(1, H1, eu("A new name"), letter="c", period=31.0),
            ]
        )
        assert result.number[1] == (H1, 2)
        assert result.events["found by letter and period"]
        assert result.new == 0

    def test_a_merge_makes_an_alias(self):
        part = self.first()
        result = part.run([planet(0, H1, archive(1), eu("A c"))])
        assert result.number[0] == (H1, 1)
        assert part.statuses()[(H1, 2)] == ALIAS
        assert result.events["merged"] and result.unreviewed == 1
        # The alias leads to the survivor at the next ingest.
        later = part.run([planet(0, H1, archive(2))])
        assert later.number[0] == (H1, 1)

    def test_a_new_host_gives_a_new_number_and_an_alias(self):
        # The host of planet 0 merged into H2, or a catalogue moved it there.
        part = self.first()
        result = part.run(
            [planet(0, H2, archive(1)), planet(1, H1, archive(2), letter="c")]
        )
        assert result.number[0] == (H2, 1)
        assert result.events["host changed"] and result.unreviewed == 1
        assert (result.new, result.kept, result.moved) == (0, 1, 1)
        state = PartState.build(part.records)
        # The old URL redirects to the planet on its new host.
        assert state.status[(H1, 1)] == ALIAS
        assert state.alias_target[(H1, 1)] == (H2, 1)
        assert state.live_end((H1, 1)) == (H2, 1)
        # The next ingest keeps the new number.
        later = part.run(
            [planet(0, H2, archive(1)), planet(1, H1, archive(2), letter="c")]
        )
        assert later.number[0] == (H2, 1) and not later.events["host changed"]

    def test_a_planet_on_a_new_host_can_take_a_free_number_there(self):
        part = Ingests()
        part.run([planet(0, H1, archive(1)), planet(1, H2, eu("B b"))])
        # Planet 0 is now on H2 and its letter and period find (H2, 1).
        result = part.run(
            [planet(0, H2, archive(1)), planet(2, H2, archive(7), letter="c")]
        )
        assert result.number == {0: (H2, 1), 2: (H2, 2)}
        assert result.events["found by letter and period"]
        assert (result.new, result.kept, result.moved) == (1, 0, 1)

    def test_a_merge_across_hosts_keeps_the_number_on_the_host(self):
        part = Ingests()
        part.run([planet(0, H1, archive(1)), planet(1, H2, eu("B b"))])
        result = part.run([planet(0, H2, archive(1), eu("B b"))])
        assert result.number[0] == (H2, 1)
        state = PartState.build(part.records)
        assert state.alias_target[(H1, 1)] == (H2, 1)

    def test_a_merged_number_is_not_free(self):
        # Planet 0 holds the ids of (H1, 1) and (H1, 2): (H1, 2) becomes its
        # alias, so planet 9 with c's letter and period must not take it.
        part = self.first()
        result = part.run(
            [
                planet(0, H1, archive(1), eu("A c")),
                planet(9, H1, eu("A c bis"), letter="c", period=30.0),
            ]
        )
        assert result.number[0] == (H1, 1)
        assert result.number[9] == (H1, 3)
        assert part.statuses()[(H1, 2)] == ALIAS
        assert not result.events["found by letter and period"]

    def test_a_split_keeps_the_number_with_most_ids(self):
        part = self.first()
        result = part.run(
            [
                planet(0, H1, archive(1)),
                planet(1, H1, eu("A b"), archive(2), letter="c"),
                planet(2, H1, eu("A c"), letter="x", period=99.0),
            ]
        )
        assert result.number[0] == (H1, 1)
        assert result.number[1] == (H1, 2)
        assert result.number[2] == (H1, 3)
        assert len(result.events["split"]) == 2
