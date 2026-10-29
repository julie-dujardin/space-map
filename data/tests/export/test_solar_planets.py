"""Tests for the Solar System planets as planet records."""

import pytest

from space_map_data.constants.planets.families import (
    EARTH_MASSES_PER_JUPITER,
    EARTH_RADII_PER_JUPITER,
)
from space_map_data.export.solar_planets import (
    PLANET_NAIF_IDS,
    heavy_element_fraction,
    page_families,
    solar_planet_records,
)

# km³/s², the planet's own GM (DE440).
GMS = {
    199: 22031.868551,
    299: 324858.592,
    399: 398600.435507,
    499: 42828.375816,
    599: 126686531.9,
    699: 37931206.234,
    799: 5793951.256,
    899: 6835099.97,
}
# km, equatorial (pck00011).
EQUATORIAL = {
    199: 2440.53,
    299: 6051.8,
    399: 6378.1366,
    499: 3396.19,
    599: 71492.0,
    699: 60268.0,
    799: 25559.0,
    899: 24764.0,
}
RADII = {n: {"a": a, "b": a, "c": a * 0.99} for n, a in EQUATORIAL.items()}
# Horizons mean elements: AU, deg, 1, d.
ELEMENTS = {
    199: {"a": 0.387098, "i": 7.005, "e": 0.205631, "period": 87.9691},
    299: {"a": 0.723329, "i": 3.3946, "e": 0.006756, "period": 224.6991},
    399: {"a": 0.999999, "i": 0.0001, "e": 0.016719, "period": 365.2558},
    499: {"a": 1.523681, "i": 1.8497, "e": 0.093414, "period": 686.9727},
    599: {"a": 5.202676, "i": 1.3039, "e": 0.048919, "period": 4332.4278},
    699: {"a": 9.55558, "i": 2.4871, "e": 0.054347, "period": 10787.5523},
    799: {"a": 19.21525, "i": 0.7717, "e": 0.047388, "period": 30765.1863},
    899: {"a": 30.11237, "i": 1.7703, "e": 0.009137, "period": 60354.099},
}


@pytest.fixture
def records() -> dict[str, dict]:
    return solar_planet_records(RADII, GMS, ELEMENTS)


class TestRecords:
    """The records have the shape and the units of the planet records."""

    def test_the_eight_planets_in_order(self, records):
        assert list(records) == [f"naif-{n}" for n in PLANET_NAIF_IDS]
        assert len(records) == 8

    def test_earth(self, records):
        earth = records["naif-399"]
        assert earth["class"] == "planet"
        assert earth["estimated"] == earth["assumed"] == earth["limits"] == []
        values = earth["values"]
        assert values["mass"] * EARTH_MASSES_PER_JUPITER == pytest.approx(1.0, 1e-4)
        assert values["radius"] * EARTH_RADII_PER_JUPITER == pytest.approx(1.0, 1e-4)
        assert values["mass_kind"] == "true"
        assert values["insolation"] == pytest.approx(1.0, 1e-5)
        assert values["period"] == 365.2558

    def test_jupiter_in_jupiter_units(self, records):
        values = records["naif-599"]["values"]
        assert values["mass"] == pytest.approx(1.0, 1e-3)
        assert values["radius"] == 1.0

    def test_a_missing_source_leaves_the_value_out(self):
        found = solar_planet_records({}, {}, {})["naif-399"]["values"]
        assert found == {"heavy_element_fraction": pytest.approx(1.0, abs=0.01)}


class TestHeavyElements:
    """The fraction of everything but hydrogen and helium."""

    def test_the_giants(self):
        jupiter, saturn = (heavy_element_fraction(f"naif-{n}") for n in (599, 699))
        uranus, neptune = (heavy_element_fraction(f"naif-{n}") for n in (799, 899))
        assert jupiter == pytest.approx(0.065, abs=0.005)
        assert saturn == pytest.approx(0.211, abs=0.005)
        assert uranus == pytest.approx(0.822)
        assert neptune == pytest.approx(0.826)

    def test_no_model(self):
        assert heavy_element_fraction("naif-2000433") is None


def _families(records: dict[str, dict]) -> dict[str, list[str]]:
    return {body: record["families"] for body, record in records.items()}


class TestFamilies:
    """The Solar System planets go through the exoplanet rules."""

    def test_families(self, records):
        assert _families(records) == {
            "naif-199": ["terrestrial-planet", "sub-earth"],
            "naif-299": ["terrestrial-planet", "sub-earth"],
            "naif-399": ["terrestrial-planet", "goldilocks-planet"],
            "naif-499": ["terrestrial-planet", "sub-earth", "goldilocks-planet"],
            "naif-599": [
                "giant-planet",
                "gas-giant",
                "cold-jupiter",
                "jupiter-analogue",
            ],
            "naif-699": ["giant-planet", "gas-giant", "cold-jupiter", "puffy-planet"],
            "naif-799": ["giant-planet", "ice-giant"],
            "naif-899": ["giant-planet", "ice-giant"],
        }

    def test_none_is_estimated(self, records):
        assert all(not record["families_estimated"] for record in records.values())

    def test_earth_is_no_super_earth_and_jupiter_no_super_jupiter(self, records):
        families = _families(records)
        assert "super-earth" not in families["naif-399"]
        assert "super-jupiter" not in families["naif-599"]
        assert "ice-giant" not in families["naif-599"]
        assert "ice-giant" not in families["naif-699"]

    def test_page_families_are_the_most_specific(self, records):
        found = page_families(records)
        assert found["naif-399"] == ["terrestrial-planet", "goldilocks-planet"]
        assert found["naif-499"] == ["sub-earth", "goldilocks-planet"]
        assert found["naif-599"] == ["jupiter-analogue"]
        assert found["naif-699"] == ["cold-jupiter", "puffy-planet"]
        assert found["naif-799"] == ["ice-giant"]
