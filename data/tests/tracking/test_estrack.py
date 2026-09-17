"""Monthly roll-up and live-flag handling for the ESTRACK poller.

Figures are shaped like the real replies: a month that is still filling in, a
mission listed but silent, and the live flags reading false for everyone.
"""

import json

import pytest

from space_map_data.tracking.estrack.api import MonthStats, live_codes
from space_map_data.tracking.estrack.store import EstrackStore

NAMES = {"JUIC": "Juice", "GAIA": "Gaia", "SOLO": "Solar Orbiter"}


def _month(month: str, volumes: dict[str, float]) -> MonthStats:
    return MonthStats(
        month=month,
        network={"servicePerformance": 99.3, "serviceVolume": sum(volumes.values())},
        missions={
            code: {"servicePerformance": 100.0, "serviceVolume": v, "live": False}
            for code, v in volumes.items()
        },
        stations={
            "CEB": {"servicePerformance": 100.0, "serviceVolume": 1, "live": False}
        },
    )


@pytest.fixture
def store(tmp_path):
    return EstrackStore(root=tmp_path)


def _only_live_line(store) -> str:
    (path,) = list(store.live.directory.glob("*.jsonl"))
    return path.read_text().strip()


class TestMonthlyVolume:
    """Service volume per month is the ESA activity signal."""

    def test_a_silent_mission_has_no_active_month(self, store):
        store.record_month(_month("2026-09", {"JUIC": 1654522, "GAIA": 0}), NAMES)
        assert store.missions["JUIC"].last_active_month == "2026-09"
        assert store.missions["GAIA"].last_active_month is None
        assert store.missions["GAIA"].name == "Gaia"

    def test_the_newest_month_with_volume_wins_whatever_the_fetch_order(self, store):
        store.record_month(_month("2026-09", {"SOLO": 524911}), NAMES)
        store.record_month(_month("2026-07", {"SOLO": 100}), NAMES)
        assert store.missions["SOLO"].last_active_month == "2026-09"
        assert store.missions["SOLO"].last_volume == 524911

    def test_a_refetched_month_replaces_rather_than_accumulates(self, store):
        store.record_month(_month("2026-09", {"JUIC": 100}), NAMES)
        store.record_month(_month("2026-09", {"JUIC": 250}), NAMES)
        assert store.missions["JUIC"].volume_by_month == {"2026-09": 250}

    def test_a_month_that_falls_out_of_the_upstream_window_is_kept(
        self, store, tmp_path
    ):
        store.record_month(_month("2026-07", {"JUIC": 42}), NAMES)
        store.record_month(_month("2026-09", {"JUIC": 100}), NAMES)
        kept = json.loads((tmp_path / "months" / "2026-07.json").read_text())
        assert kept["missions"]["JUIC"]["serviceVolume"] == 42
        assert store.missions["JUIC"].volume_by_month["2026-07"] == 42

    def test_state_survives_a_restart(self, store, tmp_path):
        store.record_month(_month("2026-09", {"JUIC": 1654522}), NAMES)
        reopened = EstrackStore(root=tmp_path)
        assert reopened.missions["JUIC"].last_active_month == "2026-09"


class TestLiveFlags:
    """The live flags read false for everyone; that is recorded, not derived from."""

    def test_an_empty_poll_is_still_recorded(self, store):
        assert (
            store.record_live({"JUIC": {"live": False}}, {"CEB": {"live": False}}) == []
        )
        assert store.live_polls == 1
        row = json.loads(_only_live_line(store))
        assert row["live_missions"] == [] and row["live_stations"] == []
        assert row["missions"] == {"JUIC": {"live": False}}

    def test_a_live_flag_is_captured_if_it_ever_comes_back(self, store):
        live = store.record_live(
            {"JUIC": {"live": True, "serviceVolume": 5}, "GAIA": {"live": False}},
            {"CEB": {"live": True}},
        )
        assert live == ["JUIC"]
        assert store.missions["JUIC"].last_live_at is not None
        row = json.loads(_only_live_line(store))
        assert row["missions"]["JUIC"]["serviceVolume"] == 5
        assert row["live_stations"] == ["CEB"]

    def test_live_codes_reads_the_flag(self):
        assert live_codes({"A": {"live": True}, "B": {"live": False}}) == ["A"]
