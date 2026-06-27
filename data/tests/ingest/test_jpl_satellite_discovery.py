"""Unit tests for JPL satellite-discovery ingest (matching + year parse)."""

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.ingest.providers.objects.jpl_satellite_discovery import (
    JPLSatelliteDiscoveryIngestor,
    _desig,
    _first_year,
)
from space_map_data.models.object import Object, ObjectType, OrbitalSource
from space_map_data.models.object.base import Base


class TestHelpers:
    def test_desig_collapses_formats(self):
        # JPL `S/2005 S6` and our `S2005_S06` / `2005 S6` are one key.
        assert _desig("S/2005 S6") == _desig("S2005_S06") == _desig("2005 S6")

    def test_desig_keeps_distinct_numbers(self):
        assert _desig("S/2005 S6") != _desig("S/2005 S60")

    def test_first_year_takes_earliest(self):
        assert _first_year("1966, 1980") == 1966
        assert _first_year("2009") == 2009
        assert _first_year(None) is None


@pytest.fixture
def session(monkeypatch) -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sess = Session(engine)
    monkeypatch.setattr("space_map_data.utils.db._session", sess)
    yield sess


def _moon(oid, name=None, prov=None, source=OrbitalSource.spice):
    return Object(
        id=oid,
        name=name,
        provisional_designation=prov,
        object_type=ObjectType.moon,
        orbital_source=source,
        parent_id="naif-5",
    )


def test_ingest_matches_by_name_and_designation(session, tmp_path):
    session.add_all(
        [
            _moon("naif-502", name="Europa"),
            _moon("naif-555", name="S2003_J18", prov="2003J18"),
            _moon("naif-301", name="Moon"),  # not in table → stays None
            # Asteroid moon must be ignored even with a colliding name.
            _moon("spkid-1", name="Europa", source=OrbitalSource.sbdb_moon),
        ]
    )
    session.commit()

    rows = [
        {
            "planet": "Jupiter",
            "name": "Europa",
            "provisional_designation": None,
            "year": "1610",
        },
        {
            "planet": "Jupiter",
            "name": None,
            "provisional_designation": "S/2003 J 18",
            "year": "2003",
        },
    ]
    out = tmp_path / "sources" / "position" / "jpl_satellite_discovery"
    out.mkdir(parents=True)
    (out / "moons.json").write_text(json.dumps(rows))

    JPLSatelliteDiscoveryIngestor(tmp_path).run()

    years = {o.id: o.discovery_year for o in session.query(Object).all()}
    assert years["naif-502"] == 1610  # name match
    assert years["naif-555"] == 2003  # designation match (leading zero + spacing)
    assert years["naif-301"] is None  # absent from table
    assert years["spkid-1"] is None  # sbdb_moon excluded from the natural-moon query
