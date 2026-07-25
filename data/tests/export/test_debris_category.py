"""Tests for the payload/debris split behind the Satellites and Debris pages."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.constants.categories import DEBRIS_SLUG, SATELLITES_SLUG
from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_SLUG_PREFIX,
    DEBRIS_CONSTELLATION_SLUGS,
)
from space_map_data.constants.earth_sats.launch_vehicles import (
    LAUNCH_VEHICLE_SLUG_PREFIX,
)
from space_map_data.constants.earth_sats.satcat import (
    OpsStatus,
    OrbitCenter,
    OrbitType,
    SatcatObjectType,
)
from space_map_data.export.groups.bundles import _category_parent, _constellation_refs
from space_map_data.export.groups.earth_sat import build_earth_orbit_classes
from space_map_data.export.groups.registry import (
    CLASS_SLUG_PREFIX,
    GROUP_BY_SLUG,
    GroupType,
)
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.base import Base
from space_map_data.models.object.satcat import Satcat

_EARTH = "naif-399"
_LEO = f"{CLASS_SLUG_PREFIX}LEO"


@pytest.fixture
def session() -> Iterator[Session]:
    """Fresh in-memory SQLite with the full schema, scoped to one test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


@pytest.fixture(autouse=True)
def no_inclinations(monkeypatch):
    """Skip the CelesTrak day-dir scan — these tests don't need overlay bands."""
    monkeypatch.setattr(
        "space_map_data.export.groups.earth_sat._load_latest_inclinations",
        lambda: {},
    )


def _add(
    session: Session,
    norad: int,
    *,
    debris: bool = False,
    name: str = "OBJ",
    constellation: str | None = None,
    sitelinks: int = 0,
    launch_date: str = "2007-01-11",
) -> None:
    """One active Earth-orbiter; the 800 km shell puts it squarely in LEO."""
    session.add(
        Satcat(
            NORAD_CAT_ID=norad,
            OBJECT_NAME=name,
            object_type=(
                SatcatObjectType.DEBRIS if debris else SatcatObjectType.PAYLOAD
            ),
            ops_status=OpsStatus.OPERATIONAL,
            orbit_center=OrbitCenter.EARTH,
            orbit_type=OrbitType.ORBIT,
            perigee=800.0,
            apogee=820.0,
            launch_date=launch_date,
            constellation_slug=constellation,
        )
    )
    session.add(
        Object(
            id=f"norad_satcat-{norad}",
            name=name,
            object_type=ObjectType.debris if debris else ObjectType.spacecraft,
            parent_id=_EARTH,
            satcat_norad_cat_id=norad,
            sitelinks_count=sitelinks,
            image_available=False,
        )
    )
    session.commit()


class TestEarthOrbitSplit:
    """`build_earth_orbit_classes` partitions each zone by payload vs debris."""

    def test_counts_partition_the_zone(self, session):
        _add(session, 1)
        _add(session, 2)
        _add(session, 3, debris=True)
        stats = build_earth_orbit_classes(session)

        assert stats.payload_counts[_LEO] == 2
        assert stats.debris_counts[_LEO] == 1
        # The zone itself still holds both — it's a region, not a fleet.
        assert stats.member_counts[_LEO] == 3

    def test_notable_pools_are_disjoint(self, session):
        _add(session, 1, name="SAT", sitelinks=9)
        _add(session, 2, name="FRAGMENT", debris=True, sitelinks=4)
        stats = build_earth_orbit_classes(session)

        assert [m.object_id for m in stats.notable_members[_LEO]] == ["norad_satcat-1"]
        assert [m.object_id for m in stats.debris_notable_members[_LEO]] == [
            "norad_satcat-2"
        ]

    def test_launch_histograms_split(self, session):
        _add(session, 1, launch_date="1999-05-10")
        _add(session, 2, debris=True, launch_date="2007-01-11")
        stats = build_earth_orbit_classes(session)

        assert stats.payload_satcat_stats[_LEO].launch_histogram == {1999: 1}
        assert stats.debris_satcat_stats[_LEO].launch_histogram == {2007: 1}
        # The combined bucket still sees every object.
        assert stats.satcat_stats[_LEO].launch_histogram == {1999: 1, 2007: 1}

    def test_debris_sources_counted_once_per_object(self, session):
        _add(session, 1, debris=True, constellation="fengyun-1c-asat-debris")
        _add(session, 2, debris=True, constellation="fengyun-1c-asat-debris")
        # A payload of the same fleet must not inflate the debris source.
        _add(session, 3, constellation="fengyun-1c-asat-debris")
        stats = build_earth_orbit_classes(session)

        assert stats.debris_source_counts == {"fengyun-1c-asat-debris": 2}

    def test_payload_only_zone_has_no_debris_entry(self, session):
        _add(session, 1)
        stats = build_earth_orbit_classes(session)

        assert stats.debris_counts.get(_LEO) is None
        assert stats.debris_notable_members == {}


class TestCategoryParent:
    """`_category_parent` decides which category page a group climbs to."""

    def test_launch_vehicle_is_debris(self):
        lv = next(
            g for g in GROUP_BY_SLUG.values() if g.type is GroupType.LAUNCH_VEHICLE
        )
        assert _category_parent(lv) == DEBRIS_SLUG

    def test_breakup_cloud_is_debris(self):
        slug = f"{CONSTELLATION_SLUG_PREFIX}fengyun-1c-asat-debris"
        assert _category_parent(GROUP_BY_SLUG[slug]) == DEBRIS_SLUG

    def test_fleet_is_satellites(self):
        slug = f"{CONSTELLATION_SLUG_PREFIX}starlink"
        assert _category_parent(GROUP_BY_SLUG[slug]) == SATELLITES_SLUG

    def test_orbit_zone_is_satellites(self):
        assert _category_parent(GROUP_BY_SLUG[_LEO]) == SATELLITES_SLUG

    def test_non_earth_group_has_none(self):
        assert _category_parent(GROUP_BY_SLUG["cat-planets"]) is None

    def test_every_debris_constellation_resolves(self):
        """Each curated cloud must have a group page that climbs to Debris."""
        for bare in DEBRIS_CONSTELLATION_SLUGS:
            group = GROUP_BY_SLUG.get(f"{CONSTELLATION_SLUG_PREFIX}{bare}")
            assert group is not None, bare
            assert _category_parent(group) == DEBRIS_SLUG


class TestConstellationRefs:
    """Rocket families surface as lv- pages, so refs must not emit a dead const-."""

    def test_rocket_family_rewrites_to_launch_vehicle(self):
        refs = _constellation_refs(
            {"long-march": 2055},
            "en",
            _EmptyCache(),  # type: ignore[arg-type]
        )
        assert refs[0]["primary_id"] == f"{LAUNCH_VEHICLE_SLUG_PREFIX}long-march"
        assert refs[0]["n"] == 2055

    def test_plain_fleet_keeps_its_constellation_slug(self):
        refs = _constellation_refs(
            {"starlink": 12221},
            "en",
            _EmptyCache(),  # type: ignore[arg-type]
        )
        assert refs[0]["primary_id"] == f"{CONSTELLATION_SLUG_PREFIX}starlink"

    def test_every_ref_points_at_a_real_group(self):
        """Guards the dead-link class of bug: a ref whose slug has no page."""
        counts = {"long-march": 5, "delta": 4, "starlink": 3, "cosmos": 2}
        for ref in _constellation_refs(
            counts,
            "en",
            _EmptyCache(),  # type: ignore[arg-type]
            limit=10,
        ):
            assert ref["primary_id"] in GROUP_BY_SLUG, ref


class _EmptyCache:
    """Wikidata cache stub: no entities, so refs fall back to their slug name."""

    def get_entity(self, qid):
        return None

    def get_referenced(self, qid):
        return None
