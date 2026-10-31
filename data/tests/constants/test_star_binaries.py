"""The entries of the paper table of binary orbits."""

import math

import pytest

from space_map_data.constants.stars import binaries
from space_map_data.constants.stars.binaries import BINARIES, REFERENCES, Value
from space_map_data.extrasolar import families


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
        cited = {b.reference for b in BINARIES.values()}
        cited |= {b.type_reference for b in BINARIES.values() if b.type_reference}
        assert cited == set(REFERENCES)
        for reference in REFERENCES.values():
            assert reference.url.startswith("https://doi.org/")

    def test_kepler_16_is_doyle_2011(self):
        kepler_16 = BINARIES[("gaia", "dr3", "2133476355197071616")]
        assert kepler_16.period == Value(41.079220, 0.000078, 0.000077)
        assert kepler_16.stars[1].radius == Value(0.22623, 0.00059, 0.00053)
        assert kepler_16.osculating_epoch == 2455212.12316

    def test_the_family_rules_read_each_type(self):
        for binary in BINARIES.values():
            for star in binary.stars:
                if star.spectral_type:
                    letter, _, extra = families.parse_spectral_type(star.spectral_type)
                    assert (
                        letter or extra or families.of_spectral_type(star.spectral_type)
                    )

    @pytest.mark.parametrize(
        "key, label, family",
        [
            ("2133476355197071616", "A", "k-type-main-sequence"),
            ("2133476355197071616", "B", "red-dwarf"),
            ("2073478823183937536", "Aa", "f-type-main-sequence"),
            ("3675067076961979264", "A", "subdwarf-b"),
            ("3675067076961979264", "B", "red-dwarf"),
            ("1191504471436192512", "A", "white-dwarf"),
            ("4245906369913936000", "A", "subdwarf-b"),
            ("709709093301608448", "B", "g-type-main-sequence"),
        ],
    )
    def test_the_words_of_a_paper_give_their_family(self, key, label, family):
        stars = {star.label: star for star in BINARIES["gaia", "dr3", key].stars}
        spectral_type = stars[label].spectral_type
        assert spectral_type
        assert family in families.of_spectral_type(spectral_type)

    def test_a_letter_alone_gives_no_family(self):
        kepler_413 = BINARIES[("gaia", "dr3", "2133352385261516928")]
        assert kepler_413.stars[0].spectral_type == "K"
        assert families.of_spectral_type("K") == []

    def test_a_star_with_no_type_in_its_paper_has_none(self):
        kepler_34 = BINARIES[("gaia", "dr3", "2079692678777827712")]
        assert all(star.spectral_type is None for star in kepler_34.stars)

    def test_kepler_16_cites_the_work_of_its_types(self):
        kepler_16 = BINARIES[("gaia", "dr3", "2133476355197071616")]
        assert kepler_16.type_reference == "triaud_2022"

    def test_an_angle_in_radians_is_read_as_degrees(self):
        bebop_3 = BINARIES[("gaia", "dr3", "1141769093744241536")]
        assert bebop_3.arg_periastron is not None
        assert bebop_3.arg_periastron.value == pytest.approx(math.degrees(4.90226))
