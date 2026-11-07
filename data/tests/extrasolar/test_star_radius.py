"""Tests for the one source order of a star's radius.

Every star record of the export takes its radius from this order, so a wrong
source draws a star at the wrong size on every page.
"""

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.export.extrasolar.radius import (
    COLUMNS,
    FLAME,
    FLAME_SPEC,
    GSPPHOT,
    held_columns,
    measuring_points,
    star_radius,
)
from space_map_data.extrasolar import families
from space_map_data.extrasolar.exoplanets.catalogues import ARCHIVE, EU, OEC
from space_map_data.extrasolar.measured_radius import MEASURED_COLUMNS
from space_map_data.extrasolar.tables import POINT_SOURCE, STAR_SYSTEMS, SYSTEM_STAR

STRINGS = {"distance_source", "host_radius_source"}


def table(*rows: dict) -> pa.Table:
    return pa.table(
        {
            name: pa.array(
                [row.get(name) for row in rows],
                pa.string() if name in STRINGS else pa.float32(),
            )
            for name in COLUMNS
        }
    )


def chosen(
    row: dict, masks: int = 0, transits: bool = False
) -> tuple[float | None, str | None]:
    size, source = star_radius(
        table(row), np.array([masks], np.uint64), np.array([transits])
    )
    return size[0].as_py(), source[0].as_py()


class TestOrder:
    def test_a_paper_comes_first(self) -> None:
        row = {"radius_literature": 1420.0, "angular_diameter": 420.0}
        assert chosen(row) == (1420.0, "literature")

    def test_a_diameter_at_the_parallax_distance(self) -> None:
        size, source = chosen(
            {"angular_diameter": 44.0, "parallax": 6.55, "parallax_error": 0.83}
        )
        assert source == "jmdc"
        # 0.1075 R☉ per mas at one parsec, to three digits.
        assert size == pytest.approx(0.1075 * 44 * 1000 / 6.55, rel=5e-3)

    @pytest.mark.parametrize("by", ["literature", STAR_SYSTEMS])
    def test_a_chosen_distance_stands_in_for_the_parallax(self, by: str) -> None:
        row = {
            "angular_diameter": 10.0,
            "parallax": 5.0,
            "parallax_error": 0.1,
            "distance": 100.0,
            "distance_source": by,
        }
        assert chosen(row)[0] == pytest.approx(107.5, rel=1e-3)

    def test_a_poor_parallax_gives_no_distance(self) -> None:
        row = {"angular_diameter": 22.0, "parallax": 0.6, "parallax_error": 0.5}
        assert chosen(row) == (None, None)

    @pytest.mark.parametrize("error", [0.0, None])
    def test_a_parallax_with_no_error_gives_no_distance(self, error) -> None:
        row = {"angular_diameter": 22.0, "parallax": 6.0, "parallax_error": error}
        assert chosen(row) == (None, None)

    def test_the_planet_catalogue_before_gaia(self) -> None:
        row = {
            "host_radius": 0.14,
            "host_radius_source": EU,
            "radius_flame": 0.16,
            "radius_gspphot": 0.17,
        }
        assert chosen(row) == (pytest.approx(0.14), EU)

    def test_flame_before_gspphot(self) -> None:
        assert chosen({"radius_flame": 0.807, "radius_gspphot": 0.805}) == (
            pytest.approx(0.807),
            FLAME,
        )
        assert chosen({"radius_gspphot": 0.805}) == (pytest.approx(0.805), GSPPHOT)

    def test_flame_spec_between_flame_and_gspphot(self) -> None:
        row = {"radius_flame_spec": 0.9, "radius_gspphot": 0.8}
        assert chosen(row) == (pytest.approx(0.9), FLAME_SPEC)
        assert chosen(row | {"radius_flame": 1.0}) == (pytest.approx(1.0), FLAME)

    def test_the_digits_of_the_source(self) -> None:
        """A file that shows the radius rounds it once."""
        size, _ = chosen({"radius_flame": 0.80721807})
        assert size == pytest.approx(0.80721807, rel=1e-6)

    def test_no_source_no_radius(self) -> None:
        assert chosen({}) == (None, None)


# HD 189733: the archive's 0.75 R☉ against 0.80 R☉ from its diameter.
HD_189733 = {
    "angular_diameter": 0.3721,
    "parallax": 50.6,
    "parallax_error": 0.02,
    "host_radius": 0.75,
    "host_radius_source": ARCHIVE,
}


class TestTransitHosts:
    """A transit gives a planet's radius from its catalogue's star radius, so
    the host keeps that radius before a measurement."""

    def test_a_transit_host_takes_the_catalogue_first(self) -> None:
        assert chosen(HD_189733, transits=True) == (pytest.approx(0.75), ARCHIVE)

    def test_another_host_keeps_the_measurement_first(self) -> None:
        size, source = chosen(HD_189733)
        assert (size, source) == (pytest.approx(0.79, abs=0.005), "jmdc")

    def test_with_no_catalogue_radius_the_measurement(self) -> None:
        row = {"radius_literature": 0.8, "radius_flame": 0.7}
        assert chosen(row, transits=True) == (pytest.approx(0.8), "literature")

    def test_a_transit_pulsar_takes_no_catalogue_radius(self) -> None:
        pulsar = int(families.BIT["neutron-star"])
        row = {"host_radius": 1.4e-5, "host_radius_source": OEC}
        assert chosen(row, pulsar, transits=True) == (None, None)


class TestCompactStars:
    def test_gaia_says_nothing_of_a_white_dwarf(self) -> None:
        dwarf = int(families.BIT["white-dwarf"])
        assert chosen({"radius_flame": 4.0}, dwarf) == (None, None)
        assert chosen({"radius_flame_spec": 4.0}, dwarf) == (None, None)
        row = {"host_radius": 0.0131, "host_radius_source": ARCHIVE}
        assert chosen(row, dwarf) == (pytest.approx(0.0131), ARCHIVE)

    def test_a_pulsar_takes_no_catalogue_radius(self) -> None:
        """OEC gives PSR B1257+12 the 10 km of a model neutron star."""
        pulsar = int(families.BIT["neutron-star"])
        row = {"host_radius": 1.4e-5, "host_radius_source": OEC, "radius_flame": 1.0}
        assert chosen(row, pulsar) == (None, None)


class TestHeldStars:
    """A held star reads its System `star` and the measurement of its point."""

    def held(
        self,
        radius: float | None,
        source: str | None,
        dominant: bool = False,
        **star: object,
    ) -> dict:
        """`star` adds to the System `star` value. A catalogue radius is its
        host radius too, as `drawn` gives it."""
        value = {"radius": radius, "radius_source": source, "dominant": dominant}
        if source not in (None, "literature"):
            value |= {"host_radius": radius, "host_radius_source": source}
        held = pa.table(
            {
                "id": pa.array([2], pa.int64()),
                "parent": pa.array([1], pa.int64()),
                "star": pa.array([value | star], SYSTEM_STAR),
            }
        )
        points = pa.table(
            {
                "id": pa.array([1], pa.int64()),
                **{
                    name: pa.array(
                        [{"angular_diameter": 10.0, "distance": 100.0}.get(name)],
                        POINT_SOURCE.schema.field(name).type,
                    )
                    for name in MEASURED_COLUMNS
                },
            }
        )
        points = points.set_column(
            points.schema.get_field_index("distance_source"),
            "distance_source",
            pa.array(["literature"]),
        )
        found = held_columns(held, points)
        return {name: values[0].as_py() for name, values in found.items()}

    def test_a_paper_is_a_measurement(self) -> None:
        assert self.held(0.65, "literature")["radius_literature"] == pytest.approx(0.65)

    def test_a_planet_catalogue_is_a_host_value(self) -> None:
        found = self.held(1.69, ARCHIVE)
        assert found["host_radius"] == pytest.approx(1.69)
        assert found["host_radius_source"] == ARCHIVE
        assert found["radius_literature"] is None

    def test_a_dominant_star_takes_the_measurement_of_its_point(self) -> None:
        found = self.held(1.69, ARCHIVE, dominant=True)
        assert found["angular_diameter"] == pytest.approx(10.0)
        assert found["distance_source"] == "literature"
        row = table({**found, "radius_flame": 3.0})
        _, source = star_radius(row, np.zeros(1, np.uint64), np.zeros(1, bool))
        assert source[0].as_py() == "jmdc"

    def test_a_star_whose_light_can_blend_keeps_it_on_the_point(self) -> None:
        assert self.held(None, None)["angular_diameter"] is None

    def test_a_paper_keeps_the_catalogue_radius(self) -> None:
        """A transit host takes the catalogue's radius before its paper's."""
        found = self.held(
            0.65, "literature", host_radius=0.7, host_radius_source=ARCHIVE
        )
        assert found["radius_literature"] == pytest.approx(0.65)
        assert found["host_radius"] == pytest.approx(0.7)
        rows = table(found, found)
        size, source = star_radius(
            rows, np.zeros(2, np.uint64), np.array([True, False])
        )
        assert source.to_pylist() == [ARCHIVE, "literature"]
        assert size.to_pylist() == pytest.approx([0.7, 0.65])

    def test_its_own_paper_comes_first(self) -> None:
        found = self.held(0.65, "literature", dominant=True)
        assert found["radius_literature"] == pytest.approx(0.65)
        assert found["angular_diameter"] is None

    def test_the_points_that_they_measure(self) -> None:
        held = pa.table(
            {
                "parent": pa.array([1, 1, 1, None], pa.int64()),
                "star": pa.array(
                    [
                        {"dominant": True},
                        {"dominant": False},
                        {"dominant": True, "radius_source": "literature"},
                        None,
                    ],
                    SYSTEM_STAR,
                ),
            }
        )
        assert measuring_points(held).to_pylist() == [1, None, None, None]


def test_every_column_is_a_point_source_column() -> None:
    assert set(COLUMNS) <= set(POINT_SOURCE.schema.names)
