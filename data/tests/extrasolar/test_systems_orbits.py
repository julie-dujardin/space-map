"""The orbit sources in their normal form, and the paper table."""

import gzip

import pyarrow.compute as pc
import pytest

from space_map_data.constants.stars import binaries
from space_map_data.constants.stars.binaries import BINARIES, Value
from space_map_data.download.providers.stars import msc, orb6, sbx
from space_map_data.extrasolar.systems import orbits
from space_map_data.extrasolar.systems.nodes import (
    ASTROMETRIC_ORBIT,
    SPECTROSCOPIC_ORBIT,
    VISUAL_ORBIT,
)
from tests.download.orbit_catalogue_files import (
    MSC_LINES,
    MSC_ORB_README,
    ORB6_LINES,
    SBX_ALIAS,
    SBX_ORBITS,
    SBX_SYSTEMS,
)

YEAR, BESSELIAN = orbits.JULIAN_YEAR, orbits.TROPICAL_YEAR


def ids(row: dict) -> set[tuple[str, str, str]]:
    return {(i["catalogue"], i["release"], i["catalogue_id"]) for i in row["ids"]}


class TestMSC:
    """Every element column of the MSC's orb.tsv."""

    @pytest.fixture
    def rows(self, tmp_path) -> list[dict]:
        (tmp_path / msc.README_FILE).write_text(MSC_ORB_README, encoding="latin-1")
        (tmp_path / msc.ORB_FILE).write_text(
            "\n".join(MSC_LINES) + "\n", encoding="latin-1"
        )
        return orbits.msc_orbits(tmp_path).to_pylist()

    def test_keeps_the_angles_and_the_epoch_of_a_visual_orbit(self, rows):
        visual = next(r for r in rows if r["reference"].startswith("VB6_Pbx2016"))
        assert (visual["primary"], visual["secondary"]) == ("A", "B")
        assert visual["period"] == pytest.approx(79.91 * YEAR)
        assert visual["epoch"] == pytest.approx(orbits.julian_year_jd(1955.66))
        assert (visual["semi_major_axis"], visual["eccentricity"]) == (17.66, 0.524)
        assert (visual["node"], visual["arg_periastron"], visual["inclination"]) == (
            204.75,
            232.3,
            79.32,
        )
        assert visual["known"] == [VISUAL_ORBIT]
        assert visual["arg_periastron_of"] is None
        assert ids(visual) == {
            ("wds", "id", "14396-6050"),
            ("msc", "id", "14396-6050 B"),
        }

    def test_a_zero_is_unknown_but_an_eccentricity(self, rows):
        spectroscopic = next(r for r in rows if r["reference"].endswith("386..280P"))
        assert spectroscopic["epoch"] == pytest.approx(2_435_319.1992)
        assert (spectroscopic["k1"], spectroscopic["k2"]) == (4.61, 5.45)
        assert (spectroscopic["node"], spectroscopic["inclination"]) == (None, None)
        assert spectroscopic["node_component"] == "B"
        assert spectroscopic["known"] == [SPECTROSCOPIC_ORBIT]

    def test_an_overflow_is_null(self, rows):
        proxima = next(r for r in rows if r["pair"] == "AB,C")
        assert (proxima["primary"], proxima["secondary"]) == ("AB", "C")
        assert (proxima["semi_major_axis"], proxima["node_component"]) == (None, "K")
        assert next(r for r in rows if r["system"] == "12102+7721")["epoch"] is None

    def test_a_large_t_is_a_day_number_whatever_the_period_unit(self, rows):
        row = next(r for r in rows if r["system"] == "00153+4412")
        assert row["period"] == pytest.approx(86.9 * YEAR)
        assert row["epoch"] == pytest.approx(2_451_501.0)


class TestORB6:
    """ORB6 orbits in fixed units."""

    @pytest.fixture
    def rows(self, tmp_path) -> dict[str, dict]:
        path = tmp_path / orb6.ORBITS_FILE
        path.write_text("\n".join(ORB6_LINES) + "\n", encoding="latin-1")
        table = orbits.orb6_orbits(path)
        return {f"{r['designation']} {r['pair']}": r for r in table.to_pylist()}

    def test_converts_the_units(self, rows):
        ab = rows["RHD   1 AB"]
        assert ab["period"] == pytest.approx(79.762 * YEAR)
        assert ab["period_error_upper"] == pytest.approx(0.019 * YEAR)
        assert ab["epoch"] == pytest.approx(orbits.besselian_year_jd(1955.564))
        assert ab["epoch_error_lower"] == pytest.approx(0.015 * BESSELIAN)
        assert ab["semi_major_axis"] == 17.493
        assert ab["node_ascending"] is False
        assert ab["arg_periastron_of"] == binaries.SECONDARY
        assert ids(ab) == {
            ("wds", "id", "14396-6050"),
            ("hip", "2007", "71683"),
            ("hd", "1949", "128620"),
        }
        proxima = rows["LDS 494 AC"]
        assert proxima["period"] == pytest.approx(5470 * 100 * YEAR)
        assert proxima["semi_major_axis"] == pytest.approx(188.62 * 60)
        assert proxima["epoch"] == pytest.approx(orbits.besselian_year_jd(285_000))
        assert proxima["equinox"] == 2000
        sigma_crb = rows["STF2032 Aa,Ab"]
        assert sigma_crb["period"] == pytest.approx(1641.299649 / 1440)
        assert sigma_crb["semi_major_axis"] == pytest.approx(1.225e-3)
        assert sigma_crb["epoch"] == pytest.approx(2_450_127.04855)
        assert rows["GHE   7 Aa,Ab"]["epoch"] == pytest.approx(
            orbits.julian_year_jd(2017.32)
        )

    def test_an_astrometric_orbit_has_no_side(self, rows):
        astrometric = rows["MCA  30 Aa"]
        assert astrometric["known"] == [ASTROMETRIC_ORBIT]
        assert astrometric["arg_periastron_of"] is None
        assert astrometric["period"] == pytest.approx(46.38428 / 24)
        assert astrometric["epoch"] == pytest.approx(2_454_051.64)


class TestSBX:
    """SBX orbits with the ids of their aliases."""

    @pytest.fixture
    def rows(self, tmp_path) -> dict[str, dict]:
        for name, text in (
            (sbx.ORBITS, SBX_ORBITS),
            (sbx.SYSTEMS, SBX_SYSTEMS),
            (sbx.ALIAS, SBX_ALIAS),
        ):
            (tmp_path / f"{name}.csv").write_text(text)
        return {r["system"]: r for r in orbits.sbx_orbits(tmp_path).to_pylist()}

    def test_gives_the_ids_of_the_aliases(self, rows):
        assert ids(rows["815"]) == {
            ("hip", "2007", "71683"),
            ("hd", "1949", "128620"),
            ("wds", "id", "14396-6050"),
            ("sbx", "sn", "815"),
        }
        assert rows["815"]["arg_periastron_of"] == binaries.PRIMARY

    def test_lengthens_each_epoch(self, rows):
        assert rows["815"]["epoch"] == pytest.approx(2_406_150.0)
        assert rows["22"]["epoch"] == pytest.approx(2_442_532.4)
        assert rows["815"]["epoch_event"] == binaries.PERIASTRON
        assert rows["6"]["epoch_event"] == orbits.OTHER_EVENT
        assert (rows["815"]["k1"], rows["815"]["k2"]) == (5.0, 5.0)


OEC_XML = """<systems>
<system>
  <name>Kepler-16</name>
  <rightascension>19 16 18</rightascension>
  <declination>+51 45 27</declination>
  <binary>
    <name>Kepler-16</name>
    <period errorminus="0.1" errorplus="0.2">41</period>
    <semimajoraxis>0.22</semimajoraxis>
    <ascendingnode>12.5</ascendingnode>
    <periastrontime unit="JD">2421946.382</periastrontime>
    <star><name>Kepler-16 A</name><mass>0.6897</mass><radius>0.6489</radius>
      <temperature errorminus="150" errorplus="150">4450</temperature></star>
    <star><name>Kepler-16 B</name><mass>0.20255</mass><radius>0.22623</radius></star>
  </binary>
</system>
<system>
  <name>Kepler-451</name>
  <binary>
    <name>Kepler-451</name>
    <transittime unit="BJD">2455276.60843</transittime>
  </binary>
</system>
</systems>"""


class TestOEC:
    """The binaries of OEC and the stars inside them."""

    def test_reads_the_binaries_and_their_stars(self, tmp_path):
        path = tmp_path / "systems.xml.gz"
        path.write_bytes(gzip.compress(OEC_XML.encode()))
        binary_table, star_table = orbits.read_oec(path)
        kepler_16, kepler_451 = binary_table.to_pylist()
        assert kepler_16["period"] == 41
        assert (kepler_16["period_error_upper"], kepler_16["period_error_lower"]) == (
            0.2,
            0.1,
        )
        assert kepler_16["semi_major_axis_au"] == 0.22
        assert (kepler_16["node"], kepler_16["node_ascending"]) == (12.5, True)
        assert kepler_16["epoch"] == 2421946.382
        assert kepler_16["epoch_event"] == binaries.PERIASTRON
        assert kepler_16["ra"] == pytest.approx(289.075)
        assert (kepler_451["epoch_event"], kepler_451["time_scale"]) == (
            orbits.TRANSIT,
            "BJD",
        )
        a, b = star_table.to_pylist()
        assert (a["label"], a["mass"], a["teff"], a["teff_error_lower"]) == (
            "Kepler-16 A",
            0.6897,
            4450,
            150,
        )
        assert ids(b) == {("open-exoplanet-catalogue", "systems", "Kepler-16 B")}
        assert (b["designation"], b["teff"]) == ("Kepler-16", None)


class TestLiterature:
    """The paper table as orbit rows."""

    def test_computes_omega_and_turns_solar_radii_to_au(self):
        key = ("gaia", "dr3", "1")
        stars = (
            binaries.Star("A", Value(1.0, 0.1), None, None),
            binaries.Star("B", None, Value(0.5, 0.01, 0.02), None),
        )
        table = {
            key: binaries.Binary(
                reference="doyle_2011",
                period=Value(10.0, 0.1),
                semi_major_axis=Value(2.0, 0.1),
                axis_unit=binaries.SOLAR_RADIUS,
                eccentricity=None,
                inclination=None,
                arg_periastron=None,
                arg_periastron_of=binaries.NOT_STATED,
                epoch=None,
                epoch_event=binaries.NOT_STATED,
                time_scale="BJD",
                frame=binaries.JACOBIAN,
                stars=stars,
                e_cos_omega=Value(0.0),
                e_sin_omega=Value(-0.1),
            )
        }
        orbit_table, star_table = orbits.read_literature(table)
        (row,) = orbit_table.to_pylist()
        assert row["system"] == "gaia/dr3/1"
        assert row["arg_periastron"] == pytest.approx(270.0)
        assert row["derived"] == ["arg_periastron"]
        assert row["semi_major_axis_au"] == pytest.approx(2.0 * orbits.SOLAR_RADIUS_AU)
        assert row["arg_periastron_of"] is None
        assert row["epoch_event"] is None
        a, b = star_table.to_pylist()
        assert (a["label"], a["mass"], b["radius_error_lower"]) == ("A", 1.0, 0.02)


class TestLiteratureRows:
    """The paper table gives one orbit row per entry."""

    def test_every_source_has_rows(self):
        orbit_table, _ = orbits.read_literature()
        assert orbit_table.num_rows == len(BINARIES)
        assert pc.all(pc.equal(orbit_table["source"], orbits.LITERATURE)).as_py()
