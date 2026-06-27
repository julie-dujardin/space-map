"""Unit tests for the JPL satellite-discovery table parser."""

from space_map_data.download.providers.objects.jpl_satellite_discovery import (
    _parse_table,
)

_HTML = """
<table class="sat-discovery table">
  <thead><tr><th>num</th><th>name</th><th>prov</th><th>year</th></tr></thead>
  <tbody>
    <tr class="sat-discovery-planet"><td colspan="6">Satellites of  Mars: 2</td></tr>
    <tr><td>I</td><td>Phobos</td><td></td><td>1877</td><td>A. Hall</td><td>ref</td></tr>
    <tr class="sat-discovery-planet"><td colspan="6">Satellites of  Saturn: 2</td></tr>
    <tr><td>LIII</td><td>Aegaeon</td><td>S/2008 S1</td><td>2009</td><td>x</td><td>ref</td></tr>
    <tr><td></td><td></td><td>S/2005 S6</td><td>2023</td><td>x</td><td>ref</td></tr>
  </tbody>
</table>
"""


def test_flattens_planet_sections():
    rows = _parse_table(_HTML)
    assert len(rows) == 3
    assert rows[0] == {
        "planet": "Mars",
        "iau_number": "I",
        "name": "Phobos",
        "provisional_designation": None,
        "year": "1877",
    }
    # Planet carries across rows until the next header.
    assert rows[1]["planet"] == "Saturn"
    assert rows[1]["name"] == "Aegaeon"
    assert rows[1]["provisional_designation"] == "S/2008 S1"
    # Designation-only row keeps an empty name as None.
    assert rows[2]["name"] is None
    assert rows[2]["provisional_designation"] == "S/2005 S6"
