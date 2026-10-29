"""The entries of the paper table of binary orbits."""

import math

import pytest

from space_map_data.constants.stars import binaries
from space_map_data.constants.stars.binaries import BINARIES, REFERENCES, Value


class TestPaperTable:
    """The entries of constants/stars/binaries.py."""

    EVENTS = frozenset(
        {
            binaries.PERIASTRON,
            binaries.PRIMARY_ECLIPSE,
            binaries.CONJUNCTION,
            binaries.NOT_STATED,
        }
    )

    @staticmethod
    def values(binary: binaries.Binary) -> list[Value]:
        found = [v for v in binary if isinstance(v, Value)]
        for star in binary.stars:
            found += [v for v in star if isinstance(v, Value)]
        return found

    def test_entries(self):
        assert BINARIES
        for key, binary in BINARIES.items():
            assert len(key) == 3 and all(key)
            assert binary.reference in REFERENCES
            assert binary.epoch_event in self.EVENTS
            assert binary.axis_unit in {binaries.AU, binaries.SOLAR_RADIUS}
            assert binary.frame in {binaries.JACOBIAN, binaries.NOT_STATED}
            assert binary.arg_periastron_of in {
                binaries.PRIMARY,
                binaries.SECONDARY,
                binaries.NOT_STATED,
            }
            assert len({star.label for star in binary.stars}) == 2
            assert binary.node is None
            for value in self.values(binary):
                assert value.upper is None or value.upper >= 0
                assert value.lower is None or value.lower >= 0
            if binary.epoch is not None:
                assert 2_400_000 < binary.epoch.value < 2_470_000

    def test_every_reference_is_cited(self):
        assert {b.reference for b in BINARIES.values()} == set(REFERENCES)
        for reference in REFERENCES.values():
            assert reference.url.startswith("https://doi.org/")

    def test_kepler_16_is_doyle_2011(self):
        kepler_16 = BINARIES[("gaia", "dr3", "2133476355197071616")]
        assert kepler_16.period == Value(41.079220, 0.000078, 0.000077)
        assert kepler_16.stars[1].radius == Value(0.22623, 0.00059, 0.00053)
        assert kepler_16.osculating_epoch == 2455212.12316

    def test_an_angle_in_radians_is_read_as_degrees(self):
        bebop_3 = BINARIES[("gaia", "dr3", "1141769093744241536")]
        assert bebop_3.arg_periastron is not None
        assert bebop_3.arg_periastron.value == pytest.approx(math.degrees(4.90226))
