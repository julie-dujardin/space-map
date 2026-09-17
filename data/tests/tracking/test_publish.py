"""What the published file says, and what it refuses to say.

The interesting cases are the ones where a source reports something we cannot
attribute: an unknown code, a network task that is not a spacecraft at all, and
a probe three sources saw at three different resolutions.
"""

import json

import pytest

from space_map_data.tracking import publish
from space_map_data.tracking.dsn.store import ActivityStore, SpacecraftState
from space_map_data.tracking.dsnbot.store import BotState, BotStore
from space_map_data.tracking.estrack.store import EstrackStore, MissionState

VOYAGER_1 = "probe-49065984"
MARS_EXPRESS = "probe-93536256"


@pytest.fixture
def dsn(tmp_path):
    return ActivityStore(root=tmp_path / "dsn")


@pytest.fixture
def estrack(tmp_path):
    return EstrackStore(root=tmp_path / "estrack")


@pytest.fixture
def bot(tmp_path):
    return BotStore(root=tmp_path / "bot")


def _posted(bot: BotStore, code: str, at: str, first: str = "") -> None:
    bot.codes[code] = BotState(
        code=code, name=code, first_event=first or at, last_event=at
    )


def _seen(dsn: ActivityStore, code: str, at: str, first: str = "") -> None:
    dsn.spacecraft[code] = SpacecraftState(
        code=code,
        friendly_name=code,
        first_seen=first or at,
        last_target_at=at,
    )


def _volume(
    estrack: EstrackStore, code: str, month: str | None, first: str = ""
) -> None:
    estrack.missions[code] = MissionState(
        code=code,
        name=code,
        first_seen=first or "2026-09-15T00:00:00+00:00",
        last_active_month=month,
    )


class TestObjects:
    """One entry per object we can name, and nothing for one we cannot."""

    def test_a_dsn_pass_is_reported_to_the_second(self, dsn, estrack, bot):
        _seen(dsn, "VGR1", "2026-09-17T08:44:22+00:00")
        entry = publish.build(dsn, estrack, bot)["objects"][VOYAGER_1]
        assert entry["last_contact"] == "2026-09-17T08:44:22+00:00"
        assert entry["precision"] == "second"
        assert entry["network"] == "dsn"

    def test_an_estrack_mission_is_reported_by_month(self, dsn, estrack, bot):
        _volume(estrack, "GAIA", "2026-07")
        entry = publish.build(dsn, estrack, bot)["objects"]["probe-103354368"]
        assert entry["last_contact"] == "2026-07"
        assert entry["precision"] == "month"

    def test_a_mission_with_no_active_month_is_left_out(self, dsn, estrack, bot):
        _volume(estrack, "GAIA", None)
        assert publish.build(dsn, estrack, bot)["objects"] == {}

    def test_an_unknown_code_is_reported_unresolved_rather_than_guessed(
        self, dsn, estrack, bot
    ):
        _seen(dsn, "ZZZZ", "2026-09-17T08:44:22+00:00")
        document = publish.build(dsn, estrack, bot)
        assert document["objects"] == {}
        assert document["unresolved"] == [
            {
                "network": "dsn",
                "code": "ZZZZ",
                "name": "ZZZZ",
                "last_contact": "2026-09-17T08:44:22+00:00",
            }
        ]

    def test_radio_astronomy_is_neither_published_nor_reported(self, dsn, estrack, bot):
        _seen(dsn, "GBRA", "2026-09-17T08:44:22+00:00")
        document = publish.build(dsn, estrack, bot)
        assert document["objects"] == {} and document["unresolved"] == []


class TestBothNetworks:
    """A probe both networks track keeps both readings, and leads with the pass."""

    def test_the_timestamped_sighting_leads(self, dsn, estrack, bot):
        _seen(dsn, "MEX", "2026-09-17T14:44:22+00:00")
        _volume(estrack, "MEX", "2026-09")
        entry = publish.build(dsn, estrack, bot)["objects"][MARS_EXPRESS]
        assert entry["precision"] == "second"
        assert entry["seen"]["estrack"] == {"code": "MEX", "last_contact": "2026-09"}
        assert entry["seen"]["dsn"]["last_contact"] == "2026-09-17T14:44:22+00:00"


class TestSources:
    """A missing object means unseen since a source started, so say when."""

    def test_each_source_carries_the_date_it_starts_from(self, dsn, estrack, bot):
        _seen(dsn, "VGR1", "2026-09-17T08:44:22+00:00", first="2026-09-16T00:00:00")
        _seen(dsn, "MEX", "2026-09-17T14:44:22+00:00", first="2026-09-15T00:00:00")
        _posted(bot, "MVN", "2026-03-18T22:21:45+00:00", first="2024-12-06T00:00:00")
        sources = publish.build(dsn, estrack, bot)["sources"]
        assert sources["dsn"]["since"] == "2026-09-15T00:00:00"
        assert sources["dsn-bot"]["since"] == "2024-12-06T00:00:00"
        assert sources["estrack"]["since"] is None

    def test_someone_else_s_record_says_whose_it_is(self, dsn, estrack, bot):
        source = publish.build(dsn, estrack, bot)["sources"]["dsn-bot"]
        assert "Russ Garrett" in source["credit"]
        assert source["via"].startswith("https://bsky.app/")
        assert "carrier" in source["measures"]


class TestTheBotsRecord:
    """It reaches back further than ours, and means less per sighting."""

    def test_a_probe_only_the_bot_saw_is_published_as_the_bot_s(
        self, dsn, estrack, bot
    ):
        _posted(bot, "MVN", "2026-03-18T22:21:45+00:00")
        entry = publish.build(dsn, estrack, bot)["objects"]["probe-120983552"]
        assert entry["network"] == "dsn-bot"
        assert entry["precision"] == "minute"
        assert entry["last_contact"] == "2026-03-18T22:21:45+00:00"

    def test_our_own_newer_sighting_leads_and_the_bot_s_is_kept(
        self, dsn, estrack, bot
    ):
        _seen(dsn, "VGR1", "2026-09-17T08:44:22+00:00")
        _posted(bot, "VGR1", "2026-09-17T03:41:21+00:00")
        entry = publish.build(dsn, estrack, bot)["objects"][VOYAGER_1]
        assert entry["network"] == "dsn"
        assert entry["seen"]["dsn-bot"]["last_contact"] == "2026-09-17T03:41:21+00:00"

    def test_the_most_recent_sighting_leads_whichever_source_it_is(
        self, dsn, estrack, bot
    ):
        _seen(dsn, "MEX", "2026-08-01T00:00:00+00:00")
        _volume(estrack, "MEX", "2026-09")
        entry = publish.build(dsn, estrack, bot)["objects"][MARS_EXPRESS]
        assert entry["network"] == "estrack" and entry["last_contact"] == "2026-09"


class TestWrite:
    """Republishing an unchanged document would make every deploy look like news."""

    def test_only_a_new_timestamp_is_not_a_change(self, dsn, estrack, bot, tmp_path):
        _seen(dsn, "VGR1", "2026-09-17T08:44:22+00:00")
        path = tmp_path / "activity.json"
        assert publish.write(publish.build(dsn, estrack, bot), path) is True
        assert publish.write(publish.build(dsn, estrack, bot), path) is False

    def test_a_later_pass_is_published(self, dsn, estrack, bot, tmp_path):
        _seen(dsn, "VGR1", "2026-09-17T08:44:22+00:00")
        path = tmp_path / "activity.json"
        publish.write(publish.build(dsn, estrack, bot), path)
        _seen(dsn, "VGR1", "2026-09-17T09:44:22+00:00")
        assert publish.write(publish.build(dsn, estrack, bot), path) is True
        written = json.loads(path.read_text())
        assert written["objects"][VOYAGER_1]["last_contact"].endswith("09:44:22+00:00")
