"""Unit tests for IAU nomenclature KML parsing."""

import datetime
from collections import defaultdict
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.constants.nomenclature.continents import Continent
from space_map_data.ingest.providers.iau_nomenclature import (
    IAUNomenclatureIngestor,
    _derive_sf_stem,
    _haversine_km,
    _normalize_name,
    _parse_approval_date,
    _parse_continent,
    _parse_kml,
)
from space_map_data.models.feature import Feature
from space_map_data.models.object import SBDB, Object, ObjectType
from space_map_data.models.object.sbdb import OrbitClass
from space_map_data.models.object.base import Base

KML_NS = "http://www.opengis.net/kml/2.2"


def _make_kml(*placemarks: str) -> bytes:
    """Build a minimal KML document from Placemark XML fragments."""
    body = "\n".join(placemarks)
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="{KML_NS}">
<Document>
{body}
</Document>
</kml>""".encode()


def _make_placemark(
    name: str,
    feature_id: int,
    *,
    clean_name: str | None = None,
    diameter: str = "100.0",
    code: str = "AA",
    approvaldt: str = "",
    continent: str = "",
) -> str:
    """Build a single Placemark XML fragment."""
    clean_name_field = (
        f'<SimpleData name="clean_name">{clean_name}</SimpleData>' if clean_name else ""
    )
    return f"""\
<Placemark>
  <name>{name}</name>
  <ExtendedData>
    <SchemaData>
      {clean_name_field}
      <SimpleData name="link">https://planetarynames.usgs.gov/Feature/{feature_id}</SimpleData>
      <SimpleData name="diameter">{diameter}</SimpleData>
      <SimpleData name="code">{code}</SimpleData>
      <SimpleData name="approvaldt">{approvaldt}</SimpleData>
      <SimpleData name="continent">{continent}</SimpleData>
      <SimpleData name="center_lon">10.5</SimpleData>
      <SimpleData name="center_lat">-20.3</SimpleData>
    </SchemaData>
  </ExtendedData>
</Placemark>"""


class TestParseKml:
    def test_single_feature(self):
        kml = _make_kml(_make_placemark("Occator", 15600))
        rows = _parse_kml(kml, "ceres")
        assert len(rows) == 1
        assert rows[0]["feature_id"] == 15600
        assert rows[0]["target"] == "ceres"
        assert rows[0]["diameter"] == pytest.approx(100.0)

    def test_clean_name_preferred(self):
        kml = _make_kml(_make_placemark("Óccat\u00f6r", 15600, clean_name="Occator"))
        rows = _parse_kml(kml, "ceres")
        assert rows[0]["name"] == "Occator"

    def test_falls_back_to_placemark_name(self):
        """When clean_name is absent, the Placemark name is used."""
        kml = _make_kml(_make_placemark("Occator", 15600))
        rows = _parse_kml(kml, "ceres")
        assert rows[0]["name"] == "Occator"

    def test_multiple_features(self):
        kml = _make_kml(
            _make_placemark("Occator", 15600),
            _make_placemark("Kerwan", 15601),
        )
        rows = _parse_kml(kml, "ceres")
        assert len(rows) == 2
        ids = {r["feature_id"] for r in rows}
        assert ids == {15600, 15601}

    def test_skips_placemark_without_feature_link(self):
        """Placemarks without a /Feature/ link are skipped."""
        bad_pm = """\
<Placemark>
  <name>NoLink</name>
  <ExtendedData>
    <SchemaData>
      <SimpleData name="link">https://example.com/nothing</SimpleData>
    </SchemaData>
  </ExtendedData>
</Placemark>"""
        kml = _make_kml(bad_pm)
        rows = _parse_kml(kml, "ceres")
        assert len(rows) == 0

    def test_skips_placemark_without_name(self):
        """Placemarks with no name element are skipped."""
        nameless = """\
<Placemark>
  <ExtendedData>
    <SchemaData>
      <SimpleData name="link">https://planetarynames.usgs.gov/Feature/999</SimpleData>
    </SchemaData>
  </ExtendedData>
</Placemark>"""
        kml = _make_kml(nameless)
        rows = _parse_kml(kml, "ceres")
        assert len(rows) == 0

    def test_coordinates_parsed(self):
        kml = _make_kml(_make_placemark("Occator", 15600))
        rows = _parse_kml(kml, "ceres")
        assert rows[0]["center_lon"] == pytest.approx(10.5)
        assert rows[0]["center_lat"] == pytest.approx(-20.3)

    def test_empty_kml(self):
        kml = _make_kml()
        rows = _parse_kml(kml, "ceres")
        assert rows == []

    def test_approval_date_and_continent_parsed(self):
        kml = _make_kml(
            _make_placemark(
                "Occator",
                15600,
                approvaldt="2014/07/03 00:00:00",
                continent="Europe",
            )
        )
        rows = _parse_kml(kml, "ceres")
        assert rows[0]["approval_date"] == datetime.date(2014, 7, 3)
        assert rows[0]["continent"] is Continent.EUROPE


class TestParseApprovalDate:
    def test_iau_format(self):
        assert _parse_approval_date("2014/07/03 00:00:00") == datetime.date(2014, 7, 3)

    def test_empty(self):
        assert _parse_approval_date("") is None
        assert _parse_approval_date("   ") is None

    def test_garbage_returns_none(self):
        assert _parse_approval_date("not a date") is None


class TestParseContinent:
    def test_known(self):
        assert _parse_continent("Europe") is Continent.EUROPE
        assert _parse_continent("South and Central America") is (
            Continent.SOUTH_AND_CENTRAL_AMERICA
        )

    def test_empty(self):
        assert _parse_continent("") is None
        assert _parse_continent("  ") is None

    def test_unknown_returns_none(self):
        assert _parse_continent("Atlantis") is None


class TestDeriveSfStem:
    def test_single_letter_suffix(self):
        assert _derive_sf_stem("Abel J") == "Abel"

    def test_two_letter_suffix(self):
        assert _derive_sf_stem("Abulfeda BA") == "Abulfeda"

    def test_inner_then_letter(self):
        assert _derive_sf_stem("Gerard Q Inner") == "Gerard"
        assert _derive_sf_stem("Gerard Q Outer") == "Gerard"

    def test_no_suffix_returns_none(self):
        assert _derive_sf_stem("Abulfeda") is None

    def test_lowercase_suffix_not_stripped(self):
        assert _derive_sf_stem("Foo bar") is None


class TestNormalizeName:
    def test_strips_apostrophes(self):
        assert _normalize_name("Bel'kovich") == "Belkovich"

    def test_collapses_double_spaces(self):
        assert _normalize_name("Engel gardt  Engelhardt") == "Engel gardt Engelhardt"


class TestHaversine:
    def test_zero_distance(self):
        assert _haversine_km(10.0, 20.0, 10.0, 20.0) == pytest.approx(0.0)

    def test_one_degree_lat_on_moon(self):
        # 1° latitude on a 1737.4 km Moon ≈ 30.3 km
        assert _haversine_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(30.32, abs=0.1)


def _fake_row(
    feature_id: int,
    name: str,
    target: str = "moon",
    code: str | None = None,
    origin: str | None = None,
    unicode_name: str | None = None,
):
    return SimpleNamespace(
        feature_id=feature_id,
        name=name,
        unicode_name=unicode_name,
        target=target,
        feature_type_code=code,
        origin=origin,
        center_lon=0.0,
        center_lat=0.0,
        diameter=10.0,
    )


def _build_indexes(rows):
    by_name: dict[tuple[str, str], list[int]] = defaultdict(list)
    by_norm: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in rows:
        by_name[(r.target, r.name)].append(r.feature_id)
        if r.unicode_name:
            by_norm[(r.target, _normalize_name(r.unicode_name))].append(r.feature_id)
    return by_name, by_norm


class TestResolveSfParent:
    def test_exact_stem_match(self):
        parent = _fake_row(1, "Abulfeda", code="AA")
        child = _fake_row(2, "Abulfeda A", code="SF")
        by_name, by_norm = _build_indexes([parent, child])
        assert IAUNomenclatureIngestor._resolve_sf_parent(child, by_name, by_norm) == 1

    def test_origin_overrides_stem(self):
        mons = _fake_row(10, "Mons Bradley", code="MO")
        rima = _fake_row(11, "Rima Bradley", code="RI")
        child = _fake_row(12, "Bradley H", code="SF", origin="Named for Rima Bradley.")
        by_name, by_norm = _build_indexes([mons, rima, child])
        assert IAUNomenclatureIngestor._resolve_sf_parent(child, by_name, by_norm) == 11

    def test_latin_prefix_fallback(self):
        parent = _fake_row(20, "Mons Pico", code="MO")
        child = _fake_row(21, "Pico B", code="SF")
        by_name, by_norm = _build_indexes([parent, child])
        assert IAUNomenclatureIngestor._resolve_sf_parent(child, by_name, by_norm) == 20

    def test_apostrophe_via_unicode_norm(self):
        parent = _fake_row(30, "Belkovich", code="AA", unicode_name="Bel'kovich")
        child = _fake_row(31, "Bel kovich A", code="SF", unicode_name="Bel'kovich A")
        by_name, by_norm = _build_indexes([parent, child])
        assert IAUNomenclatureIngestor._resolve_sf_parent(child, by_name, by_norm) == 30

    def test_no_match_returns_none(self):
        child = _fake_row(40, "Mystery A", code="SF")
        by_name, by_norm = _build_indexes([child])
        assert (
            IAUNomenclatureIngestor._resolve_sf_parent(child, by_name, by_norm) is None
        )

    def test_no_stem_returns_none(self):
        child = _fake_row(50, "JustACrater", code="SF")
        by_name, by_norm = _build_indexes([child])
        assert (
            IAUNomenclatureIngestor._resolve_sf_parent(child, by_name, by_norm) is None
        )


@pytest.fixture
def session(monkeypatch, tmp_path) -> Iterator[Session]:
    """Fresh in-memory SQLite installed as the global session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sess = Session(engine)
    monkeypatch.setattr("space_map_data.utils.db._session", sess)
    yield sess
    sess.close()


class TestMatchToObjects:
    def test_prefers_moon_over_asteroid(self, session: Session, tmp_path) -> None:
        """Moon Titania wins over asteroid 593 Titania on name collision."""
        # Insert the asteroid first so a naive query would return it.
        session.add(
            Object(
                id="spkid-2000593",
                name="593 Titania",
                object_type=ObjectType.asteroid,
            )
        )
        session.add(
            SBDB(
                spkid="2000593",
                object_id="spkid-2000593",
                name="Titania",
                class_=OrbitClass.MBA,
            )
        )
        session.add(Object(id="naif-703", name="Titania", object_type=ObjectType.moon))
        session.add(Feature(feature_id=1, name="Belmont", target="titania"))
        session.commit()

        ingestor = IAUNomenclatureIngestor(tmp_path)
        matched = ingestor._match_to_objects()

        feature = session.get(Feature, 1)
        assert feature is not None
        assert feature.object_id == "naif-703"
        assert matched == 1

    def test_planet_match(self, session: Session, tmp_path) -> None:
        """Planet target still matches when no name collision exists."""
        session.add(Object(id="naif-499", name="Mars", object_type=ObjectType.planet))
        session.add(Feature(feature_id=2, name="Olympus Mons", target="mars"))
        session.commit()

        ingestor = IAUNomenclatureIngestor(tmp_path)
        matched = ingestor._match_to_objects()

        feature = session.get(Feature, 2)
        assert feature is not None
        assert feature.object_id == "naif-499"
        assert matched == 1

    def test_asteroid_via_sbdb_name(self, session: Session, tmp_path) -> None:
        """SBDB-named asteroid target (e.g. "bennu") still matches."""
        session.add(
            Object(
                id="spkid-2101955",
                name="101955 Bennu (1999 RQ36)",
                object_type=ObjectType.asteroid,
            )
        )
        session.add(
            SBDB(
                spkid="2101955",
                object_id="spkid-2101955",
                name="Bennu",
                class_=OrbitClass.APO,
            )
        )
        session.add(Feature(feature_id=3, name="Nightingale", target="bennu"))
        session.commit()

        ingestor = IAUNomenclatureIngestor(tmp_path)
        matched = ingestor._match_to_objects()

        feature = session.get(Feature, 3)
        assert feature is not None
        assert feature.object_id == "spkid-2101955"
        assert matched == 1
