"""Unit tests for the JPL satellite physical parameters parser."""

import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.objects.jpl_satellite_physical import (
    parse_table,
)


def _row(planet: str, name: str, code: str, gm: str, sigma: str, eph: str) -> str:
    # The page leaves the value cells unclosed, as here.
    return f"""
    <tr>
      <td class="text-left">{planet}</td>
      <td class="text-left">{name}</td>
      <td class="text-center">{code}</td>
      <td class="text-center"> {gm}
      <td class="text-center"> {sigma}
      <td class="text-center"> <span>{eph}</span> </td>
      <td class="text-center"> 6.0
      <td class="text-center"> 1.0
      <td class="text-center"> <a href="#refs">3</a> </td>
    </tr>"""


_HTML = f"""
<table id="sat_phys_par" class="sat-phys-par table">
  <thead><tr><th>Planet</th></tr></thead>
  <tbody>
    {_row("Jupiter", "Io", "501", "5959.91547", "0.00135", "JUP365")}
    {_row("Pluto", "Kerberos", "904", "&lt;0.0002", "n/a", "PLU060")}
    {_row("Neptune", "Nereid", "802", "0.00000", "0.00000", "NEP101")}
    {_row("Uranus", "Miranda", "705", "4.30", "0.20", "URA111")}
    {_row("Saturn", "Pan", "618", "n/a", "n/a", "")}
  </tbody>
</table>
"""


class TestParseTable:
    def test_a_measured_gm(self):
        io = parse_table(_HTML)[0]
        assert io == {
            "planet": "Jupiter",
            "name": "Io",
            "naif_id": 501,
            "gm_km3_s2": "5959.91547",
            "gm_sigma_km3_s2": 0.00135,
            "gm_upper_limit": False,
            "ephemeris": "JUP365",
        }

    def test_an_upper_limit_keeps_its_bound(self):
        kerberos = parse_table(_HTML)[1]
        assert kerberos["gm_km3_s2"] == "0.0002"
        assert kerberos["gm_upper_limit"] is True
        assert kerberos["gm_sigma_km3_s2"] is None
        assert kerberos["ephemeris"] == "PLU060"

    def test_a_zero_gm_is_kept_as_printed(self):
        nereid = parse_table(_HTML)[2]
        assert nereid["gm_km3_s2"] == "0.00000"
        assert nereid["ephemeris"] == "NEP101"

    def test_a_gm_keeps_its_printed_digits(self):
        """A trailing zero says to what precision the fit is known."""
        assert parse_table(_HTML)[3]["gm_km3_s2"] == "4.30"

    def test_no_gm_is_none(self):
        pan = parse_table(_HTML)[4]
        assert pan["gm_km3_s2"] is None
        assert pan["ephemeris"] is None

    def test_a_page_without_the_table_fails(self):
        with pytest.raises(DownloadError):
            parse_table("<html><table id='other'></table></html>")
