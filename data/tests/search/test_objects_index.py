"""Tests for the objects search-index field builders."""

import gzip
import json

from space_map_data.search.indices.objects import (
    _date_to_int,
    _inception,
    _load_earth_membership,
    _small_body_groups,
)


class TestDateToInt:
    """`_date_to_int` parses assorted date strings into sortable YYYYMMDD ints."""

    def test_full_iso(self):
        assert _date_to_int("1957-10-04") == 19571004

    def test_year_only_defaults_to_jan_1(self):
        assert _date_to_int("1801") == 18010101

    def test_wikidata_signed_time(self):
        assert _date_to_int("+1957-10-04T00:00:00Z") == 19571004

    def test_zero_month_and_day_default_to_one(self):
        assert _date_to_int("2018-00-00") == 20180101

    def test_unparseable_returns_none(self):
        assert _date_to_int("not a date") is None


class TestInception:
    """`_inception` picks one sortable date by source precedence."""

    def test_prefers_sbdb_first_obs(self):
        g = {
            "sbdb": {"first_obs": "1801-01-01"},
            "celestrak": {"launch_date": "2020-05-30"},
        }
        assert _inception(g) == 18010101

    def test_falls_back_to_launch_date(self):
        assert _inception({"celestrak": {"launch_date": "2020-05-30"}}) == 20200530

    def test_wikidata_inception_last_resort(self):
        assert (
            _inception({"wikidata": {"inception": "+1999-12-31T00:00:00Z"}}) == 19991231
        )

    def test_discovery_date_list(self):
        assert _inception({"wikidata": {"discovery_date": ["1846-09-23"]}}) == 18460923

    def test_none_when_absent(self):
        assert _inception({"type": "moon"}) is None


class TestSmallBodyGroups:
    """`_small_body_groups` mirrors the export/groups/registry.py slug scheme."""

    def test_class_and_flags(self):
        assert _small_body_groups({"class": "MBA", "neo": True, "pha": True}) == [
            "class-MBA",
            "flag-neo",
            "flag-pha",
        ]

    def test_empty_when_no_signal(self):
        assert _small_body_groups({}) == []


class TestLoadEarthMembership:
    """`_load_earth_membership` inverts the {slug: [ids]} index to {id: [slugs]}."""

    def test_inverts(self, tmp_path):
        membership_dir = tmp_path / "v1" / "membership"
        membership_dir.mkdir(parents=True)
        (membership_dir / "earth.json.gz").write_bytes(
            gzip.compress(
                json.dumps({"starlink": ["a", "b"], "op-spacex": ["a"]}).encode()
            )
        )
        assert _load_earth_membership(tmp_path) == {
            "a": ["starlink", "op-spacex"],
            "b": ["starlink"],
        }

    def test_missing_file_returns_empty(self, tmp_path):
        assert _load_earth_membership(tmp_path) == {}
