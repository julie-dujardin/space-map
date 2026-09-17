"""Reading the DSN bot's posts back into a record.

The posts are prose written by someone else's program, so the tests are mostly
about the shapes it has actually produced: the first days that print a friendly
name instead of a code, the rate that occasionally comes out empty, and a
refetch that returns everything again.
"""

import gzip
import json

import pytest

from space_map_data.tracking.dsn.feed import SpacecraftInfo, codes_by_name
from space_map_data.tracking.dsnbot.repo import Event, Post, parse_event, parse_posts
from space_map_data.tracking.dsnbot.store import BotStore

CONFIG = {
    "VGR1": SpacecraftInfo("VGR1", "Voyager 1", "sc_voyager_1", "VGR1", ""),
    "MVN": SpacecraftInfo("MVN", "MAVEN", "sc_maven", None, ""),
    "M01O": SpacecraftInfo("M01O", "Mars Odyssey", "sc_m01o", None, ""),
    "M01S": SpacecraftInfo("M01S", "Mars Odyssey", "sc_m01s", None, ""),
}


def _event(text: str) -> Event:
    event = parse_event(text)
    assert event is not None
    return event


def _post(at: str, text: str) -> Post:
    return Post(created_at=f"2026-09-{at}+00:00", text=text)


@pytest.fixture
def store(tmp_path):
    return BotStore(root=tmp_path)


class TestReadingAPost:
    """One grammar, with two variations the bot has actually emitted."""

    def test_the_usual_line(self):
        event = _event("Canberra DSS 34 receiving data from RST at 354.5 kb/s.")
        assert (event.site, event.dish, event.craft) == ("Canberra", "DSS34", "RST")
        assert event.data_rate == 354500.0

    def test_the_first_days_carry_no_site_and_no_space_in_the_rate(self):
        event = _event("DSS 25 receiving data from Parker Solar Probe at 208.3kb/s.")
        assert event.site is None
        assert event.craft == "Parker Solar Probe"
        assert event.data_rate == 208300.0

    def test_an_empty_rate_is_still_a_contact(self):
        event = _event("Madrid DSS 63 receiving data from SOHO at .")
        assert event.craft == "SOHO" and event.data_rate is None

    def test_something_that_is_not_a_downlink_line_is_not_invented(self):
        assert parse_event("Goldstone DSS 14 carrier lock on VGR2") is None


class TestNaming:
    """A name is only resolved to a code when exactly one code claims it."""

    def test_a_friendly_name_resolves_to_its_code(self, store):
        store.record(
            [_post("01T00:00:00", "DSS 25 receiving data from MAVEN.")], CONFIG
        )
        assert "MVN" in store.codes

    def test_a_name_two_codes_share_goes_to_the_one_we_hold_an_object_for(self, store):
        store.record(
            [_post("01T00:00:00", "DSS 25 receiving data from Mars Odyssey.")], CONFIG
        )
        assert "M01O" in store.codes and "M01S" not in store.codes

    def test_a_name_that_settles_nothing_is_kept_as_written(self, store):
        config = CONFIG | {
            "TM": SpacecraftInfo("TM", "Team Miles", "sc_tm", None, ""),
            "TMM": SpacecraftInfo("TMM", "Team Miles", "sc_tmm", None, ""),
        }
        store.record(
            [_post("01T00:00:00", "DSS 25 receiving data from Team Miles.")], config
        )
        assert "TEAM MILES" in store.codes

    def test_the_reverse_map_keeps_every_candidate(self):
        names = codes_by_name(CONFIG)
        assert names["MAVEN"] == ("MVN",)
        assert set(names["MARS ODYSSEY"]) == {"M01O", "M01S"}


class TestImport:
    """The repository is cumulative, so importing it twice must not double."""

    def test_posts_are_recorded_once_per_code(self, store):
        posts = [
            _post(
                "01T00:00:00", "Canberra DSS 43 receiving data from VGR1 at 160 b/s."
            ),
            _post("02T00:00:00", "Madrid DSS 63 receiving data from VGR1 at 40 b/s."),
        ]
        assert store.record(posts, CONFIG) == ["VGR1"]
        state = store.codes["VGR1"]
        assert state.events == 2
        assert state.first_event.startswith("2026-09-01")
        assert state.last_event.startswith("2026-09-02")
        assert state.name == "Voyager 1"

    def test_a_refetch_adds_only_what_is_new(self, store):
        first = _post(
            "01T00:00:00", "Canberra DSS 43 receiving data from VGR1 at 1 b/s."
        )
        second = _post(
            "03T00:00:00", "Madrid DSS 63 receiving data from VGR1 at 2 b/s."
        )
        store.record([first], CONFIG)
        assert store.record([first, second], CONFIG) == []
        assert store.codes["VGR1"].events == 2 and store.posts == 2

    def test_only_the_reading_is_kept_not_the_post(self, store, tmp_path):
        text = "Canberra DSS 43 receiving data from VGR1 at 160 b/s."
        store.record([_post("01T00:00:00", text)], CONFIG)
        store.events.compress_closed_days("")
        packed = tmp_path / "events" / "2026-09-01.jsonl.gz"
        row = json.loads(gzip.decompress(packed.read_bytes()).decode())
        assert (row["c"], row["d"], row["rate"]) == ("VGR1", "DSS43", 160.0)
        assert "text" not in row

    def test_a_post_we_cannot_read_is_kept_as_written(self, store, tmp_path):
        store.record([_post("01T00:00:00", "DSS 43 doing something new.")], CONFIG)
        store.events.compress_closed_days("")
        packed = tmp_path / "events" / "2026-09-01.jsonl.gz"
        row = json.loads(gzip.decompress(packed.read_bytes()).decode())
        assert row["text"] == "DSS 43 doing something new."
        assert store.codes == {}

    def test_state_survives_a_restart(self, store, tmp_path):
        store.record(
            [
                _post(
                    "01T00:00:00", "Canberra DSS 43 receiving data from VGR1 at 1 b/s."
                )
            ],
            CONFIG,
        )
        assert BotStore(root=tmp_path).codes["VGR1"].events == 1


class TestCarFile:
    """The repository arrives as a CAR file, which nothing else here reads."""

    def test_a_repository_with_no_posts_is_an_error_not_an_empty_import(self):
        with pytest.raises(Exception):
            parse_posts(b"\x01\xa0")
