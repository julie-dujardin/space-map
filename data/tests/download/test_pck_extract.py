"""Tests for the nutation terms read from a text PCK."""

import pytest
import spiceypy

from space_map_data.download.providers.spice.bodies.pck_extract import (
    extract_nutation,
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

    def load(body: str) -> None:
        kernel = tmp_path / "test.tpc"
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
