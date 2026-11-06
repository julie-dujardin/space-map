"""Tests for space_map_data.export.groups.planetary_systems_map."""

import gzip
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from space_map_data.export.groups.planetary_systems_map import (
    build_planetary_systems_map,
    write_planetary_systems_map,
)
from space_map_data.export.objects.body_radius import BodyRadii, BodyRadius
from space_map_data.models.object import Object, ObjectType, OrbitalSource
from space_map_data.models.object.sbdb import SBDB, OrbitClass


def _sphere(radius_km: float) -> BodyRadius:
    return BodyRadius(radius_km, radius_km, radius_km, "johnston")


def _body(
    session: Session,
    object_id: str,
    object_type: ObjectType,
    parent_id: str | None = None,
    naif_id: int | None = None,
    a_au: float | None = None,
) -> None:
    session.add(
        Object(
            id=object_id,
            object_type=object_type,
            parent_id=parent_id,
            naif_id=naif_id,
            orbital_source=OrbitalSource.sbdb if a_au is not None else None,
        )
    )
    if a_au is not None:
        spkid = object_id.removeprefix("spkid-")
        session.add(
            SBDB(spkid=spkid, object_id=object_id, class_=OrbitClass.TNO, a=a_au, i=0.0)
        )


class TestSystemKeys:
    """Each system is keyed by its barycenter, else by its host body."""

    def _systems(self, session: Session) -> dict:
        _body(session, "naif-10", ObjectType.star, naif_id=10)
        _body(session, "naif-9", ObjectType.barycenter, "naif-10", 9)
        _body(session, "naif-999", ObjectType.dwarf_planet, "naif-9", 999)
        _body(session, "spkid-901", ObjectType.moon, "naif-9", a_au=1.3e-4)
        # Two dwarf hosts that orbit the Sun itself.
        _body(session, "spkid-20050000", ObjectType.dwarf_planet, "naif-10", 20050000)
        _body(session, "spkid-120050000", ObjectType.moon, "spkid-20050000", a_au=9e-5)
        _body(session, "spkid-20136199", ObjectType.dwarf_planet, "naif-10", 20136199)
        _body(
            session, "spkid-120136199", ObjectType.moon, "spkid-20136199", a_au=2.5e-4
        )
        session.commit()
        radii = BodyRadii(
            shapes={999: _sphere(1188.3)},
            sizes={"spkid-20050000": _sphere(555.0), "spkid-20136199": _sphere(1163.0)},
        )
        return {
            s.primary_id: s for s in build_planetary_systems_map(session, radii, {}, {})
        }

    def test_every_dwarf_system_survives(self, session: Session, tmp_path: Path):
        systems = self._systems(session)
        write_planetary_systems_map(tmp_path, list(systems.values()))
        path = tmp_path / "groups" / "__planetary_systems_map__.json.gz"
        payload = orjson.loads(gzip.decompress(path.read_bytes()))
        assert set(payload) == {"naif-9", "spkid-20050000", "spkid-20136199"}
        assert payload["spkid-20050000"]["primary"]["id"] == "spkid-20050000"
        assert [m["id"] for m in payload["spkid-20050000"]["moons"]] == [
            "spkid-120050000"
        ]

    def test_a_host_on_the_sun_has_no_barycenter(self, session: Session):
        systems = self._systems(session)
        assert systems["naif-999"].barycenter_id == "naif-9"
        assert systems["spkid-20050000"].barycenter_id is None
