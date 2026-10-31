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
    measured_radius,
)


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
