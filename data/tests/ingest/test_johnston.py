"""Tests for the Johnston's Archive page parser."""

import pytest

from space_map_data.ingest.providers.objects.johnston import _parse_confidence
from space_map_data.ingest.providers.objects.johnston_parse import (
    companion_labels,
    flatten,
    parse_companion,
    parse_discoveries,
    parse_system,
)

# A page in the archive's own shape: labels are <b>/<sub> runs, values carry
# a sigma, a unit and a bracketed source code, and "?" means "not known".
_PAGE = """<html><body>
<b>(22) Kalliope</b> and Linus<br>
compiled by Wm. Robert Johnston<br>last updated <b>30 April 2022</b>
<b>dynamical type, primary:</b><br>main belt asteroid
<b>orbital data, primary (osculating elements)</b>[JPL]<b>:</b><br>
semimajor axis <b>a:</b> 2.9094135691 AU
<b>orbital data, secondary:</b><br>
binary dynamical type<b>:</b>L [P07f]<br>
semimajor axis <b>a<sub>s</sub>:</b> 1098.6 &plusmn; 6.1 km [D21a]<br>
separation/primary radius <b>a<sub>s</sub>/r<sub>p</sub>:</b>13.2 [*D]<br>
separation/Hill radius <b>a<sub>s</sub>/r<sub>H</sub>:</b>0.025 [*D]<br>
orbital period <b>P<sub>s</sub>:</b> 3.595606 &plusmn; 0.000375 d [D21a]<br>
eccentricity <b>e<sub>s</sub>:</b> 0 [D21a]<br>
inclination <b>i<sub>s</sub>:</b>94.18&deg; &plusmn; 0.42&deg; [D21a]<br>
ascending node <b>&Omega;<sub>s</sub>:</b>284.3&deg; &plusmn; 0.34&deg; [D21a]<br>
mean anomaly <b>M:</b>323.2&deg; [D21a]<br>
Epoch<b>:</b>2017 Jan 1.0<br>
normalized ang. mom. <b>&alpha;<sub>L</sub>:</b> 0.69 [P07f]<br>
<b>other data, system (combined):</b><br>
absolute mag. <b>H:</b> 6.51 [MPC]<br>
geometric albedo<b>:</b> 0.166 &plusmn; 0.005 [M14c]<br>
effective diameter <b>d<sub>E</sub>:</b> 168.5 &plusmn; 3.1 km [M14c]<br>
taxonomic type<b>:</b> X (SMASSII) [JPL] <br> M (Tholen) [JPL]<br>
mass <b>m:</b> 8.13x10<sup>15</sup> &plusmn; 1.4x10<sup>14</sup> kg [D21a]<br>
density <b>&rho;:</b> 3.38 &plusmn; 0.06 g/cm<sup>3</sup>[*D]<br>
Hill radius <b>r<sub>H</sub>:</b> 4000 km [*D]<br>
<b>other data, primary:</b><br>
diameter <b>d<sub>p</sub>:</b> 166.2 &plusmn; 2.8 km [D08a]<br>
dimensions <b>:</b>231.4 x 175.3 x 146.1km []<br>
rotation period <b>RP<sub>p</sub>:</b> 4.1482003 &plusmn; 0.0000005 h [D95a]<br>
<b>other data, secondary:</b><br>
diameter <b>d<sub>s</sub>:</b> 28 &plusmn; 2 km [D08a]<br>
diameter ratio <b>d<sub>s</sub>/d<sub>p</sub>:</b> 0.168 &plusmn; 0.012 [*D]<br>
component mag. difference <b>&Delta;M:</b> 3.22 &plusmn; 0.2 [M03e]<br>
rotation period <b>RP<sub>s</sub>:</b> ?<br>
<b>--(22) Kalliope and Linus --discovery and notes:</b><br>
Primary discovered 1852 Nov 16 from London, United Kingdom by J. R. Hind.
Companion discovered 2001 Aug 29 by J.-L. Margot and M. E. Brown using
adaptive optics telescope observations from CFHT Telescope/W. M. Keck II
Telescope, Mauna Kea, Hawaii, USA. Announced 2001 Sep 03 [G01a].
Provisional designation S/2001 (22) 1. Permanent designation I Linus,
assigned 2003 Jul.<br>
<b>--Links, more technical:</b><br><a href="x">CBET 732</a>.
</body></html>"""


@pytest.fixture
def text():
    return flatten(_PAGE)


def _combined(body: str) -> str:
    """A page holding nothing but the system block, for one label at a time."""
    return flatten(f"<b>other data, system (combined):</b><br>{body}")


class TestCompanionLabels:
    """Each companion owns an `orbital data,` and an `other data,` block."""

    def test_secondary_only(self, text):
        assert companion_labels(text) == ["secondary"]

    def test_primary_blocks_are_not_companions(self, text):
        assert "primary" not in companion_labels(text)
        assert "primary (osculating elements)" not in companion_labels(text)


class TestParseSystem:
    """Whole-system and primary columns, with their published sigmas."""

    def test_values(self, text):
        row = parse_system(text)
        assert row["h_mag"] == 6.51
        assert (row["albedo"], row["albedo_sigma"]) == (0.166, 0.005)
        assert (row["diameter_km"], row["diameter_km_sigma"]) == (168.5, 3.1)
        assert row["hill_radius_km"] == 4000.0
        assert row["density_g_cm3"] == 3.38
        assert row["dynamical_type"] == "main belt asteroid"
        assert row["last_updated"] == "2022-04-30"

    def test_superscript_exponents(self, text):
        """Masses print as `8.13x10<sup>15</sup>`, not as a float literal."""
        row = parse_system(text)
        assert row["mass_kg"] == pytest.approx(8.13e15)
        assert row["mass_kg_sigma"] == pytest.approx(1.4e14)

    def test_taxonomy_keeps_every_scheme(self, text):
        assert parse_system(text)["taxonomy"] == "X (SMASSII), M (Tholen)"

    def test_an_uncertain_class_is_still_a_class(self):
        page = _combined("taxonomic type<b>:</b> L? (SMASSII) [P21g]<br>")
        assert parse_system(page)["taxonomy"] == "L? (SMASSII)"

    def test_a_class_with_no_scheme_is_kept(self):
        page = _combined("taxonomic type<b>:</b> C [H11e]<br>")
        assert parse_system(page)["taxonomy"] == "C"

    def test_assumed_values_are_kept(self):
        """The archive parenthesises a value it assumed rather than measured,
        and gives it its own markup run."""
        page = _combined(
            "slope parameter <b>G:</b> <i>(0.15)</i> [*A]<br>"
            "density <b>&rho;:</b> <i>(1.6 g/cm<sup>3</sup>)</i> [*A]<br>"
        )
        row = parse_system(page)
        assert row["slope_g"] == 0.15
        assert row["density_g_cm3"] == 1.6

    def test_primary_block_is_not_confused_with_the_companion(self, text):
        row = parse_system(text)
        assert row["primary_diameter_km"] == 166.2
        assert row["primary_rotation_h"] == 4.1482003


class TestParseCompanion:
    """The mutual orbit as published, plus the companion's own figures."""

    def test_orbit(self, text):
        row = parse_companion(text, "secondary")
        assert row["binary_type"] == "L"
        assert (row["a_km"], row["a_km_sigma"]) == (1098.6, 6.1)
        assert (row["per_d"], row["per_d_sigma"]) == (3.595606, 0.000375)
        assert row["e"] == 0.0
        assert (row["i"], row["i_sigma"]) == (94.18, 0.42)
        assert (row["om"], row["om_sigma"]) == (284.3, 0.34)
        assert row["ma"] == 323.2
        assert row["epoch"] == "2017-01-01"
        assert row["a_over_primary_radius"] == 13.2
        assert row["a_over_hill_radius"] == 0.025
        assert row["normalised_ang_mom"] == 0.69

    def test_absent_apse_line_is_absent(self, text):
        """A circular orbit has no argument of pericenter to publish."""
        assert "w" not in parse_companion(text, "secondary")

    def test_component_figures(self, text):
        row = parse_companion(text, "secondary")
        assert (row["diameter_km"], row["diameter_km_sigma"]) == (28.0, 2.0)
        assert (row["diameter_ratio"], row["diameter_ratio_sigma"]) == (0.168, 0.012)
        assert row["mag_difference"] == 3.22

    def test_unknown_values_are_dropped(self, text):
        """The archive prints `?` where it has no number."""
        assert "rotation_h" not in parse_companion(text, "secondary")


class TestParseDiscoveries:
    """One record per companion paragraph — never the primary's."""

    def test_record(self, text):
        records = parse_discoveries(text, companion_labels(text))
        assert len(records) == 1
        record = records[0]
        assert record["discovery_date"] == "2001-08-29"
        assert record["discoverers"] == "J.-L. Margot and M. E. Brown"
        assert record["discovery_method"] == "adaptive optics telescope"
        assert record["discovery_facility"].startswith("CFHT Telescope/W. M. Keck II")
        assert record["announced"] == "2001-09-03"
        assert record["provisional_designation"] == "S/2001 (22) 1"
        assert record["permanent_name"] == "Linus"

    @pytest.mark.parametrize(
        "prose,expected",
        [
            # The archive drops to whatever precision it has, and its prose
            # runs a full stop straight onto the date.
            ("Companion discovered 2013 Feb by lightcurve.", "2013-02"),
            ("Companion discovered 2016 using radar observations.", "2016"),
            ("Companion discovered 2004 Feb 12. Announced 2004 Feb 20.", "2004-02-12"),
        ],
    )
    def test_precision_is_kept_and_prose_is_not(self, prose, expected):
        records = parse_discoveries(f"discovery and notes|{prose}", ["secondary"])
        assert records[0]["discovery_date"] == expected

    def test_link_lists_are_not_read_as_announcements(self, text):
        """The circulars below the notes belong to the page, not a companion."""
        assert "CBET" not in str(parse_discoveries(text, ["secondary"]))


# Shaped like the real page, which closes neither its rows nor its cells and
# wraps each rank's entries in a <ul>. A tree parser folds all of this into one
# row and loses every class but the last, so the fixture keeps the sloppiness.
_CONFIDENCE_PAGE = """<table cellpadding=5 border=2>
<tr>
<th></th>
<th>satellites<br> with permanent<br> designations</th>
<th>well observed<br> satellites</th>
<th>confirmed<br> satellites</th>
<th>probable<br> satellites</th>
</tr>

<tr>
<td><b>near-Earth objects</b></td>
<td><ul>
<li><a href=astmoons/am-65803.html> <b>(65803) Didymos <i>and</i> Dimorphos</b></a>
</ul></td>
<td><ul>
<li><a href=astmoons/am-136617.html> <b>(136617) 1994 CC</b></a> (two satellites)
</ul></td>
<td><ul>
<li><a href=astmoons/am-01862.html> <b>(1862) Apollo</b></a>
</ul></td>
<td><ul>
<li><a href=astmoons/am-05646.html> (5646) 1990 TR</a>
</ul></td>

<tr>
<td><b>Mars crossers</b></td>
<td>&nbsp;</td>
<td>&nbsp;</td>
<td><ul>
<li><a href=astmoons/am-01139.html> <b>(1139) Atami</b></a>
</ul></td>
<td><ul>
<li><a href=astmoons/am-05261.html> (5261) Eureka</a>
</ul></td>
</table>
<p>&copy; 2001-2026 by Wm. Robert Johnston.</p>"""


class TestParseConfidence:
    """Johnston ranks each system; SBDB has only a confirmed Y/N."""

    def test_ranks_by_column(self):
        ranks = _parse_confidence(_CONFIDENCE_PAGE)
        assert ranks["65803"].value == "permanent"
        assert ranks["136617"].value == "well_observed"
        assert ranks["1862"].value == "confirmed"
        assert ranks["5646"].value == "probable"

    def test_every_class_row_is_read(self):
        """Unclosed <tr>s: a tree parser keeps only the last class."""
        ranks = _parse_confidence(_CONFIDENCE_PAGE)
        assert ranks["1139"].value == "confirmed"
        assert ranks["5261"].value == "probable"

    def test_the_footer_is_not_mistaken_for_an_entry(self):
        """The final cell runs on past </table> into the copyright line."""
        assert all(len(key) < 40 for key in _parse_confidence(_CONFIDENCE_PAGE))
