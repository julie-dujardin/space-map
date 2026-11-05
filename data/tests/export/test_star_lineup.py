"""Tests for the sizes and colours of listed stars.

A wrong row here draws a star at the wrong size for every reader of its page,
with nothing to show it is wrong: the dust shell of VY CMa came out at 147,000
solar radii before its mid-infrared row was left out.
"""

import pytest

from space_map_data.constants.stars.literature import REFERENCES
from space_map_data.export.groups.star_lineup import (
    JMDC,
    _bp_rp,
    _size,
    drawable_star_radii,
    measured_radius,
)
from space_map_data.extrasolar.tables import STAR_SYSTEMS


def row(**values: float | str | None) -> dict:
    return {
        "radius_literature": None,
        "angular_diameter": None,
        "parallax": None,
        "parallax_error": None,
        "distance": None,
        "distance_source": None,
        "host_radius": None,
        "radius_flame": None,
        "radius_gspphot": None,
        "host_teff": None,
        "teff_gspphot": None,
        "phot_bp_mean_mag": None,
        "phot_rp_mean_mag": None,
        "v_i": None,
        **values,
    }


NO_IDS: dict = {"cross_ids": []}


def literature(key: str) -> dict:
    return {
        "cross_ids": [
            {"catalogue": "literature", "release": "star", "catalogue_id": key}
        ]
    }


class TestSize:
    def test_a_paper_comes_first(self) -> None:
        with_paper = row(radius_literature=1420.0, angular_diameter=420.0)
        size = _size(literature("hd/1949/58061"), with_paper)
        assert size is not None
        assert (size.radius_sun, size.source) == (1420.0, "literature")
        assert size.reference == REFERENCES["wittkowski_2012"]

    def test_a_diameter_at_the_distance_gives_the_radius(self) -> None:
        measured = row(angular_diameter=44.0, parallax=6.55, parallax_error=0.83)
        size = _size(NO_IDS, measured)
        assert size is not None
        assert size.reference == JMDC
        # 0.1075 R☉ per mas at one parsec.
        assert size.radius_sun == pytest.approx(0.1075 * 44 * 1000 / 6.55, rel=1e-3)

    def test_a_paper_distance_stands_in_for_a_parallax(self) -> None:
        measured = row(
            angular_diameter=10.0, distance=100.0, distance_source="literature"
        )
        assert measured_radius(measured) == (
            pytest.approx(107.5, rel=1e-3),
            "interferometry",
        )

    def test_a_system_distance_stands_in_for_a_parallax(self) -> None:
        """The panel and the scene show the system's distance."""
        measured = row(
            angular_diameter=10.0,
            parallax=5.0,
            parallax_error=0.1,
            distance=100.0,
            distance_source=STAR_SYSTEMS,
        )
        assert measured_radius(measured) == (
            pytest.approx(107.5, rel=1e-3),
            "interferometry",
        )

    def test_a_poor_parallax_gives_no_distance(self) -> None:
        poor = row(
            angular_diameter=22.0, parallax=0.6, parallax_error=0.5, distance=2500.0
        )
        assert _size(NO_IDS, poor) is None

    def test_a_compact_star_takes_no_gaia_radius(self) -> None:
        assert _size(NO_IDS, row(radius_flame=4.0), compact=True) is None
        assert _size(NO_IDS, row(host_radius=0.01), compact=True) is not None

    def test_falls_back_to_the_catalogue(self) -> None:
        size = _size(NO_IDS, row(host_radius=0.14, radius_flame=0.16))
        assert size is not None
        assert (size.radius_sun, size.source) == (0.14, "catalogue")


class TestColour:
    def test_prefers_gaia(self) -> None:
        assert _bp_rp(row(phot_bp_mean_mag=2.5, phot_rp_mean_mag=1.0, v_i=9)) == 1.5

    def test_falls_back_to_hipparcos_v_i(self) -> None:
        assert _bp_rp(row(v_i=2.32)) == pytest.approx(2.5, abs=0.05)

    def test_none_without_either(self) -> None:
        assert _bp_rp(row()) is None


class FakeReader:
    def __init__(self, tables: dict[str, dict[int, dict]]) -> None:
        self.tables = tables
        self.metadata = {
            "families": [{"slug": "neutron-star"}, {"slug": "white-dwarf"}]
        }

    def rows(self, slug: str, ids: list[int], columns: list[str]) -> dict[int, dict]:
        table = self.tables.get(slug, {})
        return {id_: table[id_] for id_ in ids if id_ in table}


def tags(families: int = 0) -> dict:
    return {"cross_ids": [], "families": families, "families_estimated": 0}


class TestDrawableStars:
    """`drawable_stars` asks what the comparison row asks of a star."""

    def stars(self, ids: list[int], **points: dict) -> set[int]:
        rows = {int(key.removeprefix("s")): value for key, value in points.items()}
        reader = FakeReader(
            {
                "point-source": rows,
                "metadata": {id_: tags() for id_ in rows},
                "system": {9: {"primary": 1}, 8: {"primary": 7}},
            }
        )
        return set(drawable_star_radii(reader, ids))  # ty: ignore[invalid-argument-type]

    def test_a_size_and_a_temperature(self) -> None:
        assert self.stars([1], s1=row(radius_flame=2.0, teff_gspphot=5000.0)) == {1}

    def test_a_colour_stands_in_for_the_temperature(self) -> None:
        sized = row(host_radius=2.0, phot_bp_mean_mag=5.0, phot_rp_mean_mag=4.0)
        assert self.stars([1], s1=sized) == {1}

    def test_no_size_or_no_colour_draws_nothing(self) -> None:
        points = {"s1": row(teff_gspphot=5000.0), "s2": row(radius_flame=2.0)}
        assert self.stars([1, 2], **points) == set()

    def test_a_star_with_no_point_draws_nothing(self) -> None:
        assert self.stars([5]) == set()

    def test_a_system_stands_for_its_main_star(self) -> None:
        sized = row(radius_flame=2.0, teff_gspphot=5000.0)
        assert self.stars([9, 8], s1=sized) == {9}

    def test_gaia_says_nothing_of_a_compact_star(self) -> None:
        reader = FakeReader(
            {
                "point-source": {1: row(radius_flame=2.0, teff_gspphot=5000.0)},
                "metadata": {1: tags(families=0b10)},
            }
        )
        assert not drawable_star_radii(reader, [1])  # ty: ignore[invalid-argument-type]

    def test_a_system_takes_the_size_of_its_main_star(self) -> None:
        sized = row(radius_flame=2.0, teff_gspphot=5000.0)
        reader = FakeReader(
            {
                "point-source": {1: sized},
                "metadata": {1: tags()},
                "system": {9: {"primary": 1}},
            }
        )
        radii = drawable_star_radii(reader, [9])  # ty: ignore[invalid-argument-type]
        assert radii == {9: 1390000.0}
