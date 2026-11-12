"""Tests for the small-body discovery-date ingest provider."""

import json
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from space_map_data.ingest.providers import small_body_discovery
from space_map_data.models.object import Object, ObjectType


@pytest.fixture
def session(monkeypatch, engine) -> Iterator[Session]:
    with Session(engine) as sess:
        monkeypatch.setattr(small_body_discovery, "get_session", lambda: sess)
        yield sess


@pytest.fixture
def wikidata_dir(tmp_path, monkeypatch):
    objects_dir = tmp_path / "wikidata" / "objects"
    objects_dir.mkdir(parents=True)
    monkeypatch.setattr(small_body_discovery, "WIKIDATA_OBJECTS_DIR", objects_dir)
    return objects_dir


def _entity(objects_dir, qid: str, time: str | None) -> None:
    claims = {}
    if time is not None:
        value = {"time": time, "precision": 11}
        snak = {"snaktype": "value", "datavalue": {"type": "time", "value": value}}
        claims["P575"] = [{"rank": "normal", "mainsnak": snak}]
    (objects_dir / f"{qid}.json").write_text(json.dumps({"claims": claims}))


class TestSmallBodyDiscoveryIngest:
    """Reset-then-set of the SBDB bodies' ``discovery_date``."""

    def test_sets_dates_from_p575(self, session, wikidata_dir) -> None:
        session.add_all(
            [
                Object(
                    id="naif-2000001",
                    name="Ceres",
                    object_type=ObjectType.dwarf_planet,
                    spkid=20000001,
                    wikidata_qid="Q596",
                ),
                Object(
                    id="spkid-20000004",
                    name="4 Vesta",
                    object_type=ObjectType.asteroid,
                    spkid=20000004,
                    wikidata_qid="Q3030",
                    discovery_date="1950-09-23",
                ),
                Object(
                    id="spkid-20000005",
                    name="5 Astraea",
                    object_type=ObjectType.asteroid,
                    spkid=20000005,
                ),
                Object(
                    id="naif-799",
                    name="Uranus",
                    object_type=ObjectType.planet,
                    wikidata_qid="Q324",
                ),
            ]
        )
        session.commit()
        _entity(wikidata_dir, "Q596", "+1801-01-01T00:00:00Z")
        _entity(wikidata_dir, "Q3030", None)
        _entity(wikidata_dir, "Q324", "+1781-03-13T00:00:00Z")

        small_body_discovery.ingest()

        dates = dict(session.query(Object.id, Object.discovery_date).all())
        assert dates == {
            "naif-2000001": "1801-01-01",
            "spkid-20000004": None,
            "spkid-20000005": None,
            "naif-799": None,
        }
