"""Tests for Earth's curated featured-satellites attachment."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.constants.categories import SATELLITES_SLUG
from space_map_data.export.objects import satellites
from space_map_data.export.objects.satellites import (
    EARTH_ID,
    attach_featured_satellites,
)
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.models.object import Object, ObjectType, OrbitalSource
from space_map_data.models.object.base import Base


@pytest.fixture
def session() -> Iterator[Session]:
    """Fresh in-memory SQLite with the full schema, scoped to one test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


class _StubCache:
    """Minimal WikidataEntityCache: objects via get_entity, others referenced."""

    def __init__(self, by_qid: dict[str, dict[str, str]]) -> None:
        self._labels = by_qid

    def _entity(self, qid: str | None) -> dict | None:
        if qid is None or qid not in self._labels:
            return None
        return {"labels": self._labels[qid]}

    def get_entity(self, qid: str | None) -> dict | None:
        return self._entity(qid)

    def get_referenced(self, qid: str | None) -> dict | None:
        return self._entity(qid)


def _add_sat(session: Session, object_id: str, qid: str | None, name: str) -> None:
    session.add(
        Object(
            id=object_id,
            name=name,
            object_type=ObjectType.spacecraft,
            wikidata_qid=qid,
            orbital_source=OrbitalSource.celestrak,
            parent_id=EARTH_ID,
        )
    )
    session.commit()


def _empty_chunk() -> ChunkObjectData:
    chunk = ChunkObjectData()
    chunk.global_data[EARTH_ID] = {}
    for lang in chunk.localized_data:
        chunk.localized_data[lang][EARTH_ID] = {}
    return chunk


def test_attaches_objects_and_constellation(session: Session, monkeypatch) -> None:
    # No thumbnails — keeps the entry shape minimal and assertable.
    monkeypatch.setattr(satellites, "collect_object_images", lambda _id: None)
    monkeypatch.setattr(satellites, "collect_group_images", lambda _slug: None)
    monkeypatch.setattr(satellites, "pick_thumbnail", lambda imgs: None)

    _add_sat(session, "norad_satcat-25544", "Q25271", "ISS (ZARYA)")
    _add_sat(session, "norad_satcat-20580", "Q2513", "HST")
    # A second debris-typed Earth child so the total exceeds the featured count.
    session.add(
        Object(
            id="norad_satcat-99999",
            name="DEBRIS",
            object_type=ObjectType.debris,
            orbital_source=OrbitalSource.celestrak,
            parent_id=EARTH_ID,
        )
    )
    session.commit()

    cache = _StubCache(
        {
            "Q25271": {"en": "International Space Station", "ru": "МКС"},
            "Q2513": {"en": "Hubble Space Telescope"},
            "Q19867977": {"en": "Starlink"},  # Starlink constellation
        }
    )
    chunk = _empty_chunk()
    attach_featured_satellites(session, chunk, cache)  # type: ignore[arg-type]

    g = chunk.global_data[EARTH_ID]
    assert g["satellites_group"] == SATELLITES_SLUG
    assert g["satellite_count"] == 3  # 2 spacecraft + 1 debris
    assert g["notable_satellites"] == [
        {"name": "International Space Station", "id": "norad_satcat-25544"},
        {"name": "Hubble Space Telescope", "id": "norad_satcat-20580"},
        {"name": "Starlink", "group": "const-starlink"},
    ]
    # Localized override only where the label differs from English (ISS in ru).
    assert chunk.localized_data["ru"][EARTH_ID]["notable_satellite_names"] == {
        "norad_satcat-25544": "МКС"
    }


def test_skips_when_earth_bundle_missing(session: Session) -> None:
    chunk = ChunkObjectData()  # no Earth bundle
    attach_featured_satellites(session, chunk, _StubCache({}))  # type: ignore[arg-type]
    assert EARTH_ID not in chunk.global_data
