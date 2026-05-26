"""Unit tests for the post-ingest namespace-collision check."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.ingest.checks import (
    NamespaceCollisionError,
    assert_no_namespace_collision,
)
from space_map_data.models.object import (
    ElementsScale,
    Object,
    ObjectType,
    OrbitalSource,
)
from space_map_data.models.object.base import Base
from space_map_data.models.object.satcat import Satcat


@pytest.fixture
def session() -> Iterator[Session]:
    """Fresh in-memory SQLite with the full schema, scoped to one test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def _add_satcat(session: Session, norad: int, cospar: str | None = None) -> None:
    session.add(Satcat(NORAD_CAT_ID=norad, COSPAR_ID=cospar))


def _add_probe(
    session: Session,
    *,
    probe_id: int,
    name: str,
    norad: int | None = None,
    cospar: str | None = None,
    satcat_fk: int | None = None,
) -> Object:
    obj = Object(
        id=f"probe-{probe_id}",
        name=name,
        object_type=ObjectType.spacecraft,
        probe_id=probe_id,
        norad_cat_id=norad,
        cospar_id=cospar,
        satcat_norad_cat_id=satcat_fk,
        orbital_source=OrbitalSource.spice_probe,
        parent_id=None,
    )
    session.add(obj)
    return obj


def _add_norad_satcat(
    session: Session,
    *,
    norad: int,
    cospar: str | None = None,
    satcat_fk: int | None = None,
) -> Object:
    obj = Object(
        id=f"norad_satcat-{norad}",
        name=f"NORAD-{norad}",
        object_type=ObjectType.spacecraft,
        norad_cat_id=norad,
        cospar_id=cospar,
        satcat_norad_cat_id=satcat_fk,
        scale=ElementsScale.planet,
        parent_id=None,
    )
    session.add(obj)
    return obj


class TestAssertNoNamespaceCollision:
    def test_passes_on_disjoint_namespaces(self, session: Session) -> None:
        _add_satcat(session, 25008, "1997-061A")
        _add_satcat(session, 20580, "1990-037B")
        _add_probe(
            session,
            probe_id=88592384,
            name="Cassini",
            norad=25008,
            cospar="1997-061A",
            satcat_fk=25008,
        )
        _add_norad_satcat(session, norad=20580, cospar="1990-037B", satcat_fk=20580)
        session.commit()
        assert_no_namespace_collision(session)  # no raise

    def test_passes_on_joint_launch_within_probe_namespace(
        self, session: Session
    ) -> None:
        # Cassini + Huygens both at NORAD 25008 — legal, both probe-*.
        _add_satcat(session, 25008, "1997-061A")
        _add_probe(
            session,
            probe_id=88592384,
            name="Cassini",
            norad=25008,
            cospar="1997-061A",
            satcat_fk=25008,
        )
        _add_probe(
            session,
            probe_id=89915392,
            name="Huygens",
            norad=25008,
            cospar="1997-061C",
            satcat_fk=25008,
        )
        session.commit()
        assert_no_namespace_collision(session)

    def test_raises_on_norad_overlap(self, session: Session) -> None:
        _add_satcat(session, 25008, "1997-061A")
        _add_probe(
            session,
            probe_id=88592384,
            name="Cassini",
            norad=25008,
            cospar="1997-061A",
            satcat_fk=25008,
        )
        # Bug-state: a parallel norad_satcat-25008 row with the same NORAD.
        _add_norad_satcat(session, norad=25008, cospar="1997-061A", satcat_fk=25008)
        session.commit()
        with pytest.raises(NamespaceCollisionError, match="NORAD overlap"):
            assert_no_namespace_collision(session)

    def test_raises_on_cospar_overlap(self, session: Session) -> None:
        # Probe carries a cospar; an unrelated norad_satcat-* row also carries it.
        _add_satcat(session, 25008, "1997-061A")
        _add_satcat(session, 99999, "1997-061A")
        _add_probe(
            session,
            probe_id=88592384,
            name="Cassini",
            norad=25008,
            cospar="1997-061A",
            satcat_fk=25008,
        )
        _add_norad_satcat(session, norad=99999, cospar="1997-061A", satcat_fk=99999)
        session.commit()
        with pytest.raises(NamespaceCollisionError, match="COSPAR overlap"):
            assert_no_namespace_collision(session)

    def test_raises_on_fk_mismatch(self, session: Session) -> None:
        _add_satcat(session, 25008, "1997-061A")
        _add_satcat(session, 99999, None)
        _add_probe(
            session,
            probe_id=88592384,
            name="Cassini",
            norad=25008,
            cospar="1997-061A",
            satcat_fk=99999,  # FK points elsewhere
        )
        session.commit()
        with pytest.raises(NamespaceCollisionError, match="FK"):
            assert_no_namespace_collision(session)

    def test_passes_on_empty_db(self, session: Session) -> None:
        assert_no_namespace_collision(session)

    def test_diagnostic_lists_offending_ids(self, session: Session) -> None:
        _add_satcat(session, 25008, "1997-061A")
        _add_probe(
            session,
            probe_id=88592384,
            name="Cassini",
            norad=25008,
            cospar="1997-061A",
            satcat_fk=25008,
        )
        _add_norad_satcat(session, norad=25008, cospar="1997-061A", satcat_fk=25008)
        session.commit()
        with pytest.raises(NamespaceCollisionError) as exc_info:
            assert_no_namespace_collision(session)
        msg = str(exc_info.value)
        assert "probe-88592384" in msg
        assert "norad_satcat-25008" in msg
