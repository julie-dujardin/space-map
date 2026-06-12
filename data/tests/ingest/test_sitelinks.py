"""Tests for the sitelinks_count ingest provider."""

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.ingest.providers import sitelinks
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.base import Base


@pytest.fixture
def session(monkeypatch) -> Iterator[Session]:
    """In-memory DB exposed through the provider's ``get_session``."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        monkeypatch.setattr(sitelinks, "get_session", lambda: sess)
        yield sess


@pytest.fixture
def wikidata_dir(tmp_path, monkeypatch):
    objects_dir = tmp_path / "wikidata" / "objects"
    objects_dir.mkdir(parents=True)
    monkeypatch.setattr(sitelinks, "WIKIDATA_OBJECTS_DIR", objects_dir)
    return objects_dir


def _add_object(session: Session, obj_id: str, qid: str | None) -> None:
    session.add(
        Object(
            id=obj_id, name=obj_id, object_type=ObjectType.asteroid, wikidata_qid=qid
        )
    )
    session.commit()


def _write_entity(objects_dir, qid: str, n_sitelinks: int) -> None:
    links = {
        f"{chr(97 + i)}{chr(97 + i)}wiki": {"title": "T"} for i in range(n_sitelinks)
    }
    (objects_dir / f"{qid}.json").write_text(json.dumps({"sitelinks": links}))


class TestSitelinksIngest:
    """Reset-then-set behaviour of ``sitelinks.ingest``."""

    def test_sets_counts_from_entity_json(self, session, wikidata_dir) -> None:
        _add_object(session, "spkid-1", "Q1")
        _add_object(session, "spkid-2", "Q2")
        _add_object(session, "spkid-3", None)
        _write_entity(wikidata_dir, "Q1", 5)
        # Q2 has no entity file → stays 0.

        sitelinks.ingest()

        counts = dict(session.query(Object.id, Object.sitelinks_count).all())
        assert counts == {"spkid-1": 5, "spkid-2": 0, "spkid-3": 0}

    def test_resets_stale_counts(self, session, wikidata_dir) -> None:
        _add_object(session, "spkid-1", "Q1")
        session.query(Object).update({Object.sitelinks_count: 42})
        session.commit()

        sitelinks.ingest()

        assert session.query(Object.sitelinks_count).scalar() == 0

    def test_corrupt_entity_counts_zero(self, session, wikidata_dir) -> None:
        _add_object(session, "spkid-1", "Q1")
        (wikidata_dir / "Q1.json").write_text("{not json")

        sitelinks.ingest()

        assert session.query(Object.sitelinks_count).scalar() == 0

    def test_shared_qid_updates_all_objects(self, session, wikidata_dir) -> None:
        _add_object(session, "spkid-1", "Q1")
        _add_object(session, "spkid-2", "Q1")
        _write_entity(wikidata_dir, "Q1", 3)

        sitelinks.ingest()

        counts = dict(session.query(Object.id, Object.sitelinks_count).all())
        assert counts == {"spkid-1": 3, "spkid-2": 3}
