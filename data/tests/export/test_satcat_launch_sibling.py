"""A probe must not quote a launch sibling's hardware as its own.

The registry keys each probe to a SATCAT row by NORAD, and for a spacecraft
that was never catalogued separately that row belongs to whatever it flew
with: Huygens lands on Cassini's row, a Venera lander on its flyby bus. The
launch is shared, the hardware is not, so only the launch fields survive.
"""

from typing import cast

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.export.objects.celestrak import (
    build_satcat_global,
    satcat_describes,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object import Object, ObjectType, OrbitalSource, Satcat
from space_map_data.models.object.base import Base

from tests.conftest import make_object


class _NoUnits:
    """Cache with no unit entities — mass/span stay in their raw columns."""

    def unit_items(self) -> dict:
        return {}


UNITS = UnitConverter(cast(WikidataEntityCache, _NoUnits()))


def _probe(cospar: str | None, sat: Satcat | None) -> Object:
    obj = make_object(
        id="probe-89915392",
        name="Huygens",
        object_type=ObjectType.spacecraft,
        orbital_source=OrbitalSource.spice_probe,
        parent_id="naif-10",
        probe_id=89915392,
        cospar_id=cospar,
        norad_cat_id=25008,
        satcat_norad_cat_id=25008 if sat is not None else None,
    )
    obj.satcat = sat
    return obj


def _sat(cospar: str | None) -> Satcat:
    return Satcat(
        NORAD_CAT_ID=25008,
        OBJECT_NAME="CASSINI",
        COSPAR_ID=cospar,
        launch_date="1997-10-15",
        launch_site_code="AFETR",
        decay_date="2017-09-15",
        owner="US",
        mass_kg=5712.0,
        span_m=6.8,
    )


class TestSatcatDescribes:
    """Which objects own the row their satcat FK points at."""

    def test_probe_with_a_matching_cospar_owns_the_row(self):
        assert satcat_describes(_probe("1997-061A", _sat("1997-061A"))) is True

    def test_probe_with_a_siblings_cospar_does_not(self):
        assert satcat_describes(_probe("1997-061C", _sat("1997-061A"))) is False

    def test_probe_without_a_cospar_keeps_the_row(self):
        # Nothing to disagree with; the registry NORAD is the only claim there is.
        assert satcat_describes(_probe(None, _sat("1997-061A"))) is True

    def test_no_satcat_row_describes_nothing(self):
        assert satcat_describes(_probe("1997-061C", None)) is False

    def test_earth_satellite_owns_its_row_despite_a_cospar_drift(self):
        # A norad_satcat-N row *is* its SATCAT entry, so a COSPAR that drifts
        # (upstream re-designates rideshare payloads) is not a different craft.
        obj = make_object(
            id="norad_satcat-66779",
            name="FOSSASAT2E22",
            object_type=ObjectType.spacecraft,
            orbital_source=OrbitalSource.spacetrack,
            parent_id="naif-399",
            cospar_id="2025-276DT",
            norad_cat_id=66779,
            satcat_norad_cat_id=66779,
        )
        obj.satcat = Satcat(NORAD_CAT_ID=66779, COSPAR_ID="2025-276DU")
        assert satcat_describes(obj) is True


class TestBuildSatcatGlobal:
    """What a sibling's row is allowed to contribute."""

    def test_own_row_ships_what_describes_the_craft(self):
        data = build_satcat_global(_sat("1997-061A"), UNITS)
        assert data["decay_date"] == "2017-09-15"
        assert data["owner"] == "US"

    def test_siblings_row_ships_only_the_launch(self):
        data = build_satcat_global(_sat("1997-061A"), UNITS, own_craft=False)
        assert data == {"launch_date": "1997-10-15", "launch_site_code": "AFETR"}


class TestDetachedObjects:
    """An object handed to a worker thread must not fire a satcat lazy load."""

    def test_expunged_object_without_a_satcat_row(self):
        # SBDB batches are expunged as soon as they are submitted, so a
        # relationship read in the worker raises instead of returning None.
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine, expire_on_commit=False) as session:
            obj = make_object(
                id="sbdb-2000433",
                name="Eros",
                object_type=ObjectType.asteroid,
                orbital_source=OrbitalSource.sbdb,
            )
            session.add(obj)
            session.commit()
            session.expunge(obj)
            assert satcat_describes(obj) is False
