"""Tests for the system lookup of export.system_groups."""

from sqlalchemy.orm import Session

from space_map_data.export.names import ObjectNames
from space_map_data.export.system_groups import load_system_lookup
from space_map_data.models.object import Object, ObjectType
from tests.conftest import EntityStub


def _barycenter(naif_id: int, name: str) -> Object:
    return Object(
        id=f"naif-{naif_id}",
        name=name,
        naif_id=naif_id,
        object_type=ObjectType.barycenter,
        parent_id="naif-0",
    )


class TestSystemNames:
    """A system takes the names of its planet, else of its barycenter."""

    def test_a_system_without_its_planet_row_keeps_the_barycenter(
        self, session: Session
    ):
        session.add_all(
            [
                _barycenter(5, "Jupiter Barycenter"),
                Object(
                    id="naif-599",
                    name="Jupiter",
                    object_type=ObjectType.planet,
                    parent_id="naif-5",
                ),
                _barycenter(4, "Mars Barycenter"),
                # A top-level barycenter that is no planet's.
                _barycenter(20, "Other Barycenter"),
            ]
        )
        session.commit()
        _, _, system_names, _ = load_system_lookup(
            session, ObjectNames(EntityStub(), session)
        )
        assert {bary: names.name for bary, names in system_names.items()} == {
            "naif-5": "Jupiter",
            "naif-4": "Mars Barycenter",
            "naif-20": "Other Barycenter",
        }
