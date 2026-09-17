"""Parsing and roll-up for the DSN activity poller.

The live feed spends stretches with every antenna on engineering tasks, so the
active-contact path is exercised against a fixture shaped like the real
document rather than against whatever the network happens to be doing.
"""

import gzip
import json
from datetime import UTC, datetime, timedelta

import pytest

from space_map_data.tracking.dsn.feed import parse_config, parse_feed
from space_map_data.tracking.dsn.store import ActivityStore

ACTIVE_FEED = """<dsn>
    <station name="cdscc" friendlyName="Canberra" timeUTC="1789470294000" timeZoneOffset="36000000.0"/>
    <dish name="DSS43" azimuthAngle="12.3" elevationAngle="40.1" windSpeed="5" isMSPA="false" isArray="false" isDDOR="false" activity="Voyager 1 Track">
        <downSignal signalType="data" active="true" power="-155.1" frequency="8420000000" dataRate="160.0" band="X" spacecraft="VGR1" spacecraftId="31"/>
        <upSignal signalType="data" active="true" power="18.0" frequency="2110000000" dataRate="16.0" band="S" spacecraft="VGR1" spacecraftId="31"/>
        <downSignal signalType="none" active="false" power="" frequency="" dataRate="" band="" spacecraft="VGR1" spacecraftId="31"/>
        <target name="VGR1" id="31" uplegRange="2.5e10" downlegRange="2.5e10" rtlt="167000"/>
    </dish>
    <dish name="DSS35" azimuthAngle="0" elevationAngle="90" windSpeed="" isMSPA="false" isArray="false" isDDOR="false" activity="Engineering Sustaining">
        <target name="DSN" id="99" uplegRange="-1" downlegRange="-1" rtlt="-1"/>
    </dish>
    <station name="mdscc" friendlyName="Madrid" timeUTC="1789470294000" timeZoneOffset="7200000.0"/>
    <dish name="DSS54" azimuthAngle="200.0" elevationAngle="30.0" windSpeed="2" isMSPA="true" isArray="false" isDDOR="false" activity="MSPA">
        <downSignal signalType="data" active="true" power="-140.0" frequency="8430000000" dataRate="2000.0" band="X" spacecraft="M20" spacecraftId="168"/>
        <downSignal signalType="carrier" active="true" power="-141.0" frequency="8440000000" dataRate="0.0" band="X" spacecraft="MRO" spacecraftId="74"/>
        <target name="M20" id="168" uplegRange="3.1e11" downlegRange="3.1e11" rtlt="2070"/>
        <target name="MRO" id="74" uplegRange="3.1e11" downlegRange="3.1e11" rtlt="2070"/>
    </dish>
</dsn>
"""

IDLE_FEED = """<dsn>
    <station name="cdscc" friendlyName="Canberra" timeUTC="1789470294000" timeZoneOffset="36000000.0"/>
    <dish name="DSS43" azimuthAngle="0" elevationAngle="90" windSpeed="" isMSPA="false" isArray="false" isDDOR="false" activity="Engineering Sustaining">
        <target name="DSN" id="99" uplegRange="-1" downlegRange="-1" rtlt="-1"/>
    </dish>
</dsn>
"""

CONFIG = """<?xml version="1.0" encoding="UTF-8"?>
<config>
    <sites>
        <site name="cdscc" friendlyName="Canberra" longitude="148.98" latitude="-35.22">
            <dish name="DSS43" friendlyName="DSS 43" type="70M"></dish>
        </site>
    </sites>
    <spacecraftMap>
        <spacecraft name="vgr1" explorerName="sc_voyager_1" friendlyName="Voyager 1" thumbnail="true"></spacecraft>
        <spacecraft name="m20" explorerName="" friendlyAcronym="mars2020" friendlyName="Mars 2020" thumbnail="true"></spacecraft>
    </spacecraftMap>
</config>
"""


@pytest.fixture
def config():
    return parse_config(CONFIG)


@pytest.fixture
def store(tmp_path):
    return ActivityStore(root=tmp_path)


def _feed(text: str, at: datetime):
    return parse_feed(text, at)


class TestParseFeed:
    """dsn.xml maps onto dishes, targets and active signals."""

    def test_dishes_inherit_the_preceding_station(self):
        feed = _feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC))
        stations = {d.name: d.station for d in feed.dishes}
        assert stations == {
            "DSS43": "Canberra",
            "DSS35": "Canberra",
            "DSS54": "Madrid",
        }

    def test_inactive_signals_are_dropped(self):
        feed = _feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC))
        dss43 = next(d for d in feed.dishes if d.name == "DSS43")
        assert [(s.direction, s.band) for s in dss43.signals] == [
            ("down", "X"),
            ("up", "S"),
        ]

    def test_test_targets_are_not_spacecraft(self):
        feed = _feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC))
        assert set(feed.active_targets()) == {"VGR1", "M20", "MRO"}

    def test_feed_timestamp_is_epoch_milliseconds(self):
        feed = _feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC))
        assert feed.feed_time == datetime.fromtimestamp(1789470294, tz=UTC)


class TestRecord:
    """One poll folds into the per-spacecraft roll-up."""

    def test_first_sighting_snapshots_the_evidence(self, store, config):
        store.record(_feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC)), config)
        snapshot = next((store.snapshots_dir / "VGR1").glob("*.xml")).read_text()
        assert 'friendlyName="Voyager 1"' in snapshot
        assert '<target name="VGR1"' in snapshot

    def test_a_code_missing_from_the_map_is_still_recorded(self, store, config):
        store.record(_feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC)), config)
        assert store.spacecraft["MRO"].friendly_name == ""
        assert "<spacecraft-unknown/>" in (
            next((store.snapshots_dir / "MRO").glob("*.xml")).read_text()
        )

    def test_the_spacecraft_attribute_picks_the_signal_under_mspa(self, store, config):
        store.record(_feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC)), config)
        assert store.spacecraft["M20"].last_data_rate == 2000.0
        assert store.spacecraft["MRO"].last_data_rate == 0.0

    def test_a_pointed_target_with_no_signal_has_no_signal_time(self, store, config):
        store.record(_feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC)), config)
        store.spacecraft["VGR1"].last_signal_at = None
        feed = parse_feed(
            ACTIVE_FEED.replace('active="true"', 'active="false"'),
            datetime(2026, 9, 15, 1, tzinfo=UTC),
        )
        store.record(feed, config)
        assert store.spacecraft["VGR1"].last_target_at.startswith("2026-09-15T01")
        assert store.spacecraft["VGR1"].last_signal_at is None

    def test_the_no_value_sentinel_does_not_overwrite_a_real_range(self, store, config):
        store.record(_feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC)), config)
        blank = ACTIVE_FEED.replace(
            'uplegRange="2.5e10" downlegRange="2.5e10" rtlt="167000"',
            'uplegRange="-1" downlegRange="-1" rtlt="-1"',
        )
        store.record(parse_feed(blank, datetime(2026, 9, 15, 1, tzinfo=UTC)), config)
        assert store.spacecraft["VGR1"].last_downleg_range == 2.5e10
        assert store.spacecraft["VGR1"].last_rtlt == 167000

    def test_state_survives_a_restart(self, store, config, tmp_path):
        store.record(_feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC)), config)
        reopened = ActivityStore(root=tmp_path)
        assert reopened.spacecraft["VGR1"].friendly_name == "Voyager 1"
        assert reopened.polls == 1


class TestObservations:
    """Every poll is written out, so a sample the feed has dropped is not lost."""

    def test_each_poll_writes_one_line_with_a_row_per_spacecraft(self, store, config):
        store.record(_feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC)), config)
        store.record(
            _feed(ACTIVE_FEED, datetime(2026, 9, 15, 0, 1, tzinfo=UTC)), config
        )
        lines = (
            (store.observations.directory / "2026-09-15.jsonl").read_text().splitlines()
        )
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["t"] == "2026-09-15T00:00:00+00:00"
        assert {r["c"] for r in first["targets"]} == {"VGR1", "M20", "MRO"}

    def test_an_idle_poll_still_writes_its_line(self, store, config):
        store.record(_feed(IDLE_FEED, datetime(2026, 9, 15, tzinfo=UTC)), config)
        row = json.loads(
            (store.observations.directory / "2026-09-15.jsonl").read_text().strip()
        )
        assert row["targets"] == []

    def test_a_row_carries_the_signal_the_spacecraft_attribute_picks(
        self, store, config
    ):
        store.record(_feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC)), config)
        row = json.loads(
            (store.observations.directory / "2026-09-15.jsonl").read_text().strip()
        )
        vgr1 = next(r for r in row["targets"] if r["c"] == "VGR1")
        assert vgr1["band"] == "X"
        assert vgr1["rate"] == 160.0
        assert sorted(vgr1["dir"]) == ["down", "up"]
        assert vgr1["rtlt"] == 167000

    def test_the_raw_document_is_archived_verbatim(self, store, config):
        store.record(_feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC)), config)
        row = json.loads((store.raw.directory / "2026-09-15.jsonl").read_text().strip())
        assert row["xml"] == ACTIVE_FEED
        # Fields the parser drops must still be there to recover later.
        assert 'windSpeed="5"' in row["xml"]
        assert 'frequency="8420000000"' in row["xml"]

    def test_a_finished_day_is_compressed_when_the_next_one_opens(self, store, config):
        store.record(_feed(ACTIVE_FEED, datetime(2026, 9, 15, tzinfo=UTC)), config)
        store.record(_feed(ACTIVE_FEED, datetime(2026, 9, 16, tzinfo=UTC)), config)
        closed = store.observations.directory / "2026-09-15.jsonl.gz"
        assert closed.exists()
        assert not (store.observations.directory / "2026-09-15.jsonl").exists()
        assert (store.observations.directory / "2026-09-16.jsonl").exists()
        assert '"VGR1"' in gzip.decompress(closed.read_bytes()).decode()


class TestContacts:
    """Contacts group consecutive sightings and close after a quiet gap."""

    def test_consecutive_polls_are_one_contact(self, store, config):
        now = datetime.now(UTC)
        for minute in range(3):
            store.record(
                _feed(ACTIVE_FEED, now - timedelta(minutes=2 - minute)), config
            )
        assert store.open["VGR1|DSS43"].polls == 3
        assert not store.contacts_file.exists()

    def test_a_quiet_gap_closes_the_contact(self, store, config):
        store.record(_feed(ACTIVE_FEED, datetime.now(UTC) - timedelta(hours=2)), config)
        store.record(_feed(IDLE_FEED, datetime.now(UTC)), config)
        assert store.open == {}
        closed = [line for line in store.contacts_file.read_text().splitlines() if line]
        assert len(closed) == 3
        assert store.spacecraft["VGR1"].contacts == 1

    def test_max_data_rate_and_bands_accumulate(self, store, config):
        now = datetime.now(UTC)
        store.record(_feed(ACTIVE_FEED, now - timedelta(minutes=1)), config)
        store.record(
            parse_feed(ACTIVE_FEED.replace('dataRate="160.0"', 'dataRate="5.0"'), now),
            config,
        )
        contact = store.open["VGR1|DSS43"]
        assert contact.max_data_rate == 160.0
        assert sorted(contact.bands) == ["S", "X"]
        assert sorted(contact.directions) == ["down", "up"]
