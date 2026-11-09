"""Tests for the body constants read from text PCKs."""

import pytest
import spiceypy

from space_map_data.download.providers.spice.bodies.pck_extract import (
    defining_kernels,
    extract_gms,
    extract_nutation,
    extract_radii,
)

_TERMS = """
BODY4_NUT_PREC_ANGLES = ( 10.0 20.0 30.0  40.0 50.0 60.0 )
BODY499_NUT_PREC_RA = ( 0.1 0.2 )
BODY499_NUT_PREC_DEC = ( 0.3 0.4 )
BODY499_NUT_PREC_PM = ( 0.5 0.6 )
"""


@pytest.fixture
def furnish(tmp_path):
    """Load a text kernel with `body` as its data. The pool is cleared after."""

    def load(body: str, name: str = "test.tpc") -> None:
        kernel = tmp_path / name
        kernel.write_text(f"KPL/PCK\n\\begindata\n{body}\n\\begintext\n")
        spiceypy.furnsh(str(kernel))

    spiceypy.kclear()
    yield load
    spiceypy.kclear()


class TestExtractNutation:
    """The phase polynomial degree comes with the angles it groups."""

    def test_degree_the_kernel_sets(self, furnish):
        furnish(_TERMS + "BODY4_MAX_PHASE_DEGREE = 2\n")
        coefficients, angles, degrees = extract_nutation()
        assert degrees == {4: 2}
        assert angles[4] == [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        assert coefficients[499]["dec"] == [0.3, 0.4]

    def test_kernel_with_no_degree_is_linear(self, furnish):
        """Kernels before pck00011 set no degree."""
        furnish(_TERMS)
        _, angles, degrees = extract_nutation()
        assert degrees == {}
        assert len(angles[4]) == 6


_SUN = "BODY10_GM = ( 132712440041.279 )\n"


class TestDefiningKernels:
    """The kernel loaded last sets the value, as in SPICE."""

    def test_the_last_kernel_wins(self, furnish):
        furnish("BODY904_RADII = ( 100 100 100 )", "nh_stars_kbo_centaur_v005.tpc")
        furnish("BODY904_RADII = ( 9 5 4 )\nBODY999_RADII = ( 1 1 1 )", "pck00011.tpc")
        assert defining_kernels("RADII") == {904: "pck00011.tpc", 999: "pck00011.tpc"}

    def test_a_comment_block_sets_nothing(self, furnish, tmp_path):
        kernel = tmp_path / "comments.tpc"
        kernel.write_text(
            "KPL/PCK\nBODY1_GMSUN/GM = 6023600.0\nBODY5_GM = 1\n"
            "\\begindata\nBODY10_GM = ( 1.0 )\n\\begintext\n"
        )
        spiceypy.furnsh(str(kernel))
        assert defining_kernels("GM") == {10: "comments.tpc"}


class TestExtractRadii:
    def test_each_radius_names_its_kernel(self, furnish):
        furnish("BODY904_RADII = ( 100 100 100 )", "nh_stars_kbo_centaur_v005.tpc")
        (row,) = extract_radii()
        assert row["naif_id"] == 904
        assert row["kernel"] == "nh_stars_kbo_centaur_v005.tpc"


class TestExtractGms:
    """GMs are keyed by the canonical NAIF id, as the radii are."""

    def test_a_binary_keeps_its_system_gm_and_its_primary(self, furnish):
        """Orcus: system 42.03 (20090482), primary 38.56 (920090482)."""
        furnish(
            _SUN + "BODY20090482_GM = ( 42.03 )\nBODY920090482_GM = ( 38.5596 )\n"
            "BODY120090482_GM = ( 3.4704 )",
            "gm_de440.tpc",
        )
        rows = {row["naif_id"]: row for row in extract_gms()}
        assert rows[2090482]["gm_km3_s2"] == 42.03
        assert rows[2090482]["kernel"] == "gm_de440.tpc"
        assert rows[2090482]["primary_gm_km3_s2"] == 38.5596
        assert rows[2090482]["primary_kernel"] == "gm_de440.tpc"
        assert rows[120090482]["gm_km3_s2"] == 3.4704
        assert rows[120090482]["primary_gm_km3_s2"] is None
        assert 20090482 not in rows and 920090482 not in rows

    def test_a_lone_primary_form_is_the_body_gm(self, furnish):
        furnish(_SUN + "BODY920090482_GM = ( 38.5596 )", "gm_de440.tpc")
        rows = {row["naif_id"]: row for row in extract_gms()}
        assert rows[2090482]["gm_km3_s2"] == 38.5596
        assert rows[2090482]["primary_gm_km3_s2"] is None

    def test_the_spkid_form_of_a_lone_body_maps_down(self, furnish):
        """Donaldjohanson in the estimates kernel."""
        furnish(_SUN + "BODY20052246_GM = ( 4.7E-6 )", "smallbody_gm_estimates.tpc")
        rows = {row["naif_id"]: row for row in extract_gms()}
        assert rows[2052246]["gm_km3_s2"] == 4.7e-6
        assert rows[2052246]["primary_gm_km3_s2"] is None

    def test_the_canonical_form_beats_the_spkid_form(self, furnish):
        furnish(_SUN + "BODY2000617_GM = ( 0.09 )\nBODY20000617_GM = ( 0.1 )")
        rows = {row["naif_id"]: row for row in extract_gms()}
        assert rows[2000617]["gm_km3_s2"] == 0.09

    def test_a_gm_of_zero_is_no_value(self, furnish):
        """Dysnomia: 0.E+00 in gm_de440."""
        furnish(_SUN + "BODY120136199_GM = ( 0.E+00 )")
        assert 120136199 not in {row["naif_id"] for row in extract_gms()}

    def test_the_ssb_takes_the_sun_without_its_kernel(self, furnish):
        furnish(_SUN, "gm_de440.tpc")
        ssb, sun = extract_gms()
        assert ssb == {
            "naif_id": 0,
            "gm_km3_s2": sun["gm_km3_s2"],
            "kernel": None,
            "primary_gm_km3_s2": None,
            "primary_kernel": None,
        }
        assert sun["kernel"] == "gm_de440.tpc"
