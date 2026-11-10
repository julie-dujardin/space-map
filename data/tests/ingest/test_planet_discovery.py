"""Tests for the planet discovery-year ingest provider."""

import json
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from space_map_data.ingest.providers import planet_discovery
from space_map_data.models.object import Object, ObjectType


@pytest.fixture
def session(monkeypatch, engine) -> Iterator[Session]:
    with Session(engine) as sess:
        monkeypatch.setattr(planet_discovery, "get_session", lambda: sess)
        yield sess


@pytest.fixture
def wikidata_dir(tmp_path, monkeypatch):
    objects_dir = tmp_path / "wikidata" / "objects"
    objects_dir.mkdir(parents=True)
    monkeypatch.setattr(planet_discovery, "WIKIDATA_OBJECTS_DIR", objects_dir)
    return objects_dir


def _p575(time: str) -> dict:
    return {
        "P575": [
            {
                "rank": "normal",
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {
                        "type": "time",
                        "value": {"time": time, "precision": 11},
                    },
                },
            }
        ]
    }


def _write_entity(objects_dir, qid: str, claims: dict) -> None:
    (objects_dir / f"{qid}.json").write_text(json.dumps({"claims": claims}))


class TestPlanetDiscoveryIngest:
    """Reset-then-set of the planets' ``discovery_year``."""

    def test_sets_year_from_p575(self, session, wikidata_dir) -> None:
        session.add_all(
            [
                Object(
                    id="naif-799",
                    name="Uranus",
                    object_type=ObjectType.planet,
                    wikidata_qid="Q324",
                ),
                Object(
                    id="naif-599",
                    name="Jupiter",
                    object_type=ObjectType.planet,
                    wikidata_qid="Q319",
                    discovery_year=1,
                ),
                Object(
                    id="naif-501",
                    name="Io",
                    object_type=ObjectType.moon,
                    discovery_year=1610,
                ),
            ]
        )
        session.commit()
        _write_entity(wikidata_dir, "Q324", _p575("+1781-03-13T00:00:00Z"))
        _write_entity(wikidata_dir, "Q319", {})

        planet_discovery.ingest()

        years = dict(session.query(Object.id, Object.discovery_year).all())
        assert years == {"naif-799": 1781, "naif-599": None, "naif-501": 1610}
