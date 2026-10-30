"""Tests for the tier-B fingerprint of the incremental export."""

from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from space_map_data.export.objects.stars import StarObject
from space_map_data.export.pipeline import incremental


@pytest.fixture
def fingerprint(monkeypatch, session: Session) -> Callable[..., dict]:
    """The fingerprint of ``stars``, with every file input stubbed."""
    for name in (
        "kernels_digest",
        "load_probe_position_sources",
        "served_families_stamp",
        "served_planet_families_stamp",
    ):
        monkeypatch.setattr(incremental, name, dict)
    monkeypatch.setattr(incremental, "_source_stamp", lambda path: None)
    monkeypatch.setattr(incremental, "_file_stamp", lambda path: None)
    monkeypatch.setattr(incremental, "read_ingest_stamp", lambda session: None)
    return lambda stars=(): incremental.tier_b_fingerprint(session, stars, [])


class TestTierBFingerprint:
    """An input that changes a name rewrites the tier-B outputs."""

    def test_the_titles_of_the_systems_are_stamped(self, fingerprint, monkeypatch):
        before = fingerprint()
        titles = {"en": ("{primary} system", "Earth–Moon system")}
        monkeypatch.setattr(incremental, "system_titles", lambda: titles)
        assert fingerprint() != before

    def test_the_iau_status_of_a_star_is_stamped(self, fingerprint):
        star = StarObject(1, "Tislit", "Q1")
        named = StarObject(1, "Tislit", "Q1", iau_named=True)
        assert fingerprint([star]) != fingerprint([named])
