"""Tests for space_map_data.export.objects.johnston."""

import pytest

from space_map_data.export.objects.johnston import _mass_is_consistent
from space_map_data.models.object import JohnstonSystem


def _system(**kwargs) -> JohnstonSystem:
    return JohnstonSystem(
        object_id="spkid-20000022",
        page="am-00022",
        designation="(22) Kalliope",
        **kwargs,
    )


class TestMassIsConsistent:
    """A hand-maintained page can mistype an exponent; density catches it."""

    def test_agreeing_mass_is_kept(self):
        # Sylvia: 1.48e19 kg against 286 km at 1.2 g/cm^3.
        assert _mass_is_consistent(
            _system(mass_kg=1.48e19, density_g_cm3=1.2, diameter_km=286.0)
        )

    def test_scatter_between_papers_is_kept(self):
        """Mass and density come from different works; a factor of a few is normal."""
        assert _mass_is_consistent(
            _system(mass_kg=8.9e14, density_g_cm3=1.0, diameter_km=17.5)
        )

    def test_mistyped_exponent_is_dropped(self):
        """Kalliope reads 8.13e15 kg where 168 km at 3.38 g/cm^3 gives 8.5e18."""
        assert not _mass_is_consistent(
            _system(mass_kg=8.13e15, density_g_cm3=3.38, diameter_km=168.5)
        )

    @pytest.mark.parametrize(
        "row",
        [
            _system(mass_kg=8.13e15),
            _system(mass_kg=8.13e15, density_g_cm3=3.38),
            _system(density_g_cm3=3.38, diameter_km=168.5),
        ],
    )
    def test_nothing_to_check_against_passes(self, row):
        assert _mass_is_consistent(row)
