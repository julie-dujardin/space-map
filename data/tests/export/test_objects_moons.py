"""Tests for notable-moon selection and host resolution."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.export.objects.moons import (
    NOTABLE_MOON_COUNT,
    _mean_diameter_km,
    notable_moons_by_host,
)
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.base import Base

# Triaxial radii keyed by naif_id (km), as load_radii returns.
RADII = {
    501: {"a": 1829.4, "b": 1819.3, "c": 1815.7},  # Io
    502: {"a": 1562.6, "b": 1560.3, "c": 1559.5},  # Europa
}


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def _add(
    session: Session,
    obj_id: str,
    object_type: ObjectType,
    *,
    name: str | None = None,
    parent_id: str | None = None,
    naif_id: int | None = None,
    image: bool = False,
    sitelinks: int = 0,
    qid: str | None = None,
) -> None:
    session.add(
        Object(
            id=obj_id,
            name=name,
            object_type=object_type,
            parent_id=parent_id,
            naif_id=naif_id,
            image_available=image,
            sitelinks_count=sitelinks,
            wikidata_qid=qid,
        )
    )


def test_mean_diameter_from_radii() -> None:
    assert _mean_diameter_km(None, RADII) is None
    assert _mean_diameter_km(999, RADII) is None  # not in table
    # (1829.4 + 1819.3 + 1815.7) / 3 * 2
    assert _mean_diameter_km(501, RADII) == pytest.approx(3642.93, abs=0.1)


class TestNotableMoonsByHost:
    def test_barycenter_moons_attach_to_planet_host(self, session: Session) -> None:
        _add(session, "naif-5", ObjectType.barycenter)
        _add(session, "naif-599", ObjectType.planet, name="Jupiter", parent_id="naif-5")
        _add(
            session,
            "naif-501",
            ObjectType.moon,
            name="Io",
            parent_id="naif-5",
            naif_id=501,
            image=True,
            sitelinks=111,
        )
        _add(
            session,
            "naif-502",
            ObjectType.moon,
            name="Europa",
            parent_id="naif-5",
            naif_id=502,
            image=True,
            sitelinks=113,
        )
        session.commit()

        hosts = notable_moons_by_host(session, RADII)
        # Keyed by the planet, not the barycenter.
        assert set(hosts) == {"naif-599"}
        host = hosts["naif-599"]
        assert host.total == 2
        # Europa outranks Io on sitelinks.
        assert [m.object_id for m in host.moons] == ["naif-502", "naif-501"]
        assert host.moons[0].fallback_name == "Europa"
        assert host.moons[0].diameter_km == pytest.approx(3121.6, abs=0.5)

    def test_asteroid_moons_attach_to_asteroid(self, session: Session) -> None:
        _add(session, "spkid-20000130", ObjectType.asteroid, name="Elektra")
        _add(
            session,
            "spkid-120000130",
            ObjectType.moon,
            name="S/2003 (130) 1",
            parent_id="spkid-20000130",
        )
        session.commit()

        hosts = notable_moons_by_host(session, RADII)
        assert set(hosts) == {"spkid-20000130"}
        assert hosts["spkid-20000130"].total == 1
        # No naif_id / radii → no diameter, no discovery date.
        moon = hosts["spkid-20000130"].moons[0]
        assert moon.diameter_km is None
        assert moon.first_obs is None

    def test_named_count_excludes_unnamed_moons(self, session: Session) -> None:
        _add(session, "spkid-1", ObjectType.asteroid, name="Ida")
        _add(session, "spkid-2", ObjectType.moon, name="Dactyl", parent_id="spkid-1")
        # Provisional-only moonlet: no IAU name.
        _add(session, "spkid-3", ObjectType.moon, name=None, parent_id="spkid-1")
        session.commit()

        host = notable_moons_by_host(session, RADII)["spkid-1"]
        assert host.total == 2
        assert host.named == 1

    def test_ranking_image_then_sitelinks_then_diameter(self, session: Session) -> None:
        _add(session, "naif-5", ObjectType.barycenter)
        _add(session, "naif-599", ObjectType.planet, parent_id="naif-5")
        # No image, low sitelinks, but largest radii.
        _add(session, "naif-501", ObjectType.moon, parent_id="naif-5", naif_id=501)
        # Image wins outright despite no sitelinks/diameter.
        _add(session, "naif-590", ObjectType.moon, parent_id="naif-5", image=True)
        # No image but sitelinks beat the diameter-only moon.
        _add(session, "naif-591", ObjectType.moon, parent_id="naif-5", sitelinks=10)
        session.commit()

        host = notable_moons_by_host(session, RADII)["naif-599"]
        assert [m.object_id for m in host.moons] == ["naif-590", "naif-591", "naif-501"]

    def test_id_tiebreak_is_deterministic(self, session: Session) -> None:
        _add(session, "naif-5", ObjectType.barycenter)
        _add(session, "naif-599", ObjectType.planet, parent_id="naif-5")
        for n in (512, 510, 511):  # equal rank (no image/sitelinks/diameter)
            _add(session, f"naif-{n}", ObjectType.moon, parent_id="naif-5")
        session.commit()

        host = notable_moons_by_host(session, RADII)["naif-599"]
        assert [m.object_id for m in host.moons] == ["naif-510", "naif-511", "naif-512"]

    def test_limits_to_notable_moon_count(self, session: Session) -> None:
        _add(session, "naif-5", ObjectType.barycenter)
        _add(session, "naif-599", ObjectType.planet, parent_id="naif-5")
        for n in range(NOTABLE_MOON_COUNT + 5):
            _add(session, f"naif-{600 + n}", ObjectType.moon, parent_id="naif-5")
        session.commit()

        host = notable_moons_by_host(session, RADII)["naif-599"]
        assert len(host.moons) == NOTABLE_MOON_COUNT
        assert host.total == NOTABLE_MOON_COUNT + 5

    def test_barycenter_without_planet_falls_back_to_barycenter(
        self, session: Session
    ) -> None:
        _add(session, "naif-5", ObjectType.barycenter)
        _add(session, "naif-501", ObjectType.moon, parent_id="naif-5")
        session.commit()

        hosts = notable_moons_by_host(session, RADII)
        assert set(hosts) == {"naif-5"}
