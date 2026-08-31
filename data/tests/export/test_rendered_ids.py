"""`_load_rendered_ids` gates label auto-promotion.

A label for a body the scene can never find makes the renderer's pending-
promotion loop retry an unfindable getBody every frame, so probes come from
the coverage the probes pass wrote rather than from their orbital_source.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.export.pipeline.orchestrator import _load_rendered_ids
from space_map_data.models.object import Object, ObjectType, OrbitalSource
from space_map_data.models.object.base import Base


@pytest.fixture
def session() -> Iterator[Session]:
    """Fresh in-memory SQLite with the full schema, scoped to one test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def _probe(session: Session, oid: str, probe_id: int) -> None:
    session.add(
        Object(
            id=oid,
            name=oid,
            object_type=ObjectType.spacecraft,
            probe_id=probe_id,
            parent_id="naif-10",
            orbital_source=OrbitalSource.spice_probe,
            has_position=False,
        )
    )


class TestLoadRenderedIds:
    """Elements-backed rows come from the column, probes from coverage."""

    def test_probe_without_coverage_is_not_rendered(self, session):
        _probe(session, "probe-1", 1)
        _probe(session, "probe-2", 2)
        session.commit()
        rendered = _load_rendered_ids(
            session, {"probe-1": {"start_jd": 0.0, "end_jd": 1.0, "windows": []}}
        )
        assert rendered == {"probe-1"}

    def test_has_position_rows_ride_along(self, session):
        session.add(
            Object(
                id="naif-499",
                name="Mars",
                object_type=ObjectType.planet,
                parent_id="naif-0",
                orbital_source=OrbitalSource.spice,
                has_position=True,
            )
        )
        _probe(session, "probe-1", 1)
        session.commit()
        assert _load_rendered_ids(session, {}) == {"naif-499"}
