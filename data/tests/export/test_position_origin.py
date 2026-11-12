"""Tests for space_map_data.export.position.origin."""

import math

import pytest

from space_map_data.export.position.origin import visible_from_days
from space_map_data.models.object import Object, ObjectType, OrbitalSource
from space_map_data.models.object.sbdb import SBDB
from space_map_data.utils.convert import date_to_julian
from space_map_data.utils.time import J2000_JD
from tests.conftest import make_object


def _small_body(first_obs: str | None, discovery_date: str | None) -> Object:
    obj = make_object(
        id="spkid-2000001",
        object_type=ObjectType.asteroid,
        spkid=2000001,
        orbital_source=OrbitalSource.sbdb,
    )
    obj.sbdb = SBDB(spkid="2000001", object_id="spkid-2000001", first_obs=first_obs)
    obj.discovery_date = discovery_date
    return obj


def _days(iso: str) -> float:
    jd = date_to_julian(iso)
    assert jd is not None
    return jd - J2000_JD


class TestSmallBodyGate:
    def test_discovery_earlier_than_the_fit_arc(self):
        """Ceres: SBDB's first_obs is 1995, Wikidata's discovery 1801."""
        gate = visible_from_days(_small_body("1995-01-05", "1801-01-01"))
        assert gate == pytest.approx(_days("1801-01-01"))

    def test_precovery_earlier_than_discovery(self):
        gate = visible_from_days(_small_body("1930-01-23", "1930-02-18"))
        assert gate == pytest.approx(_days("1930-01-23"))

    def test_first_obs_alone(self):
        gate = visible_from_days(_small_body("2004-06-19", None))
        assert gate == pytest.approx(_days("2004-06-19"))

    def test_seen_before_the_common_era_is_always_visible(self):
        """Halley."""
        assert math.isnan(visible_from_days(_small_body("1835-08-21", "-0466-01-01")))
