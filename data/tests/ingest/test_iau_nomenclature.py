"""Unit tests for IAU nomenclature KML parsing."""

import pytest

from space_map_data.ingest.providers.iau_nomenclature import _parse_kml

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
    feature_type: str = "Crater",
    approval: str = "Adopted",
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
      <SimpleData name="type">{feature_type}</SimpleData>
      <SimpleData name="approval">{approval}</SimpleData>
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
