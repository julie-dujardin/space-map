"""Tests for the sizes and colours of listed stars.

A wrong row here draws a star at the wrong size for every reader of its page,
with nothing to show it is wrong: the dust shell of VY CMa came out at 147,000
solar radii before its mid-infrared row was left out.
"""

import gzip
from pathlib import Path

import pytest

from space_map_data.export.groups.star_lineup import (
    JMDC,
    _bp_rp,
    _size,
    measured_diameters,
)


def jmdc_row(name: str, ud: str, ld: str, band: str) -> str:
    """One fixed-width row of jmdc.dat."""
    return f"{name:<28} {'x':<28} {ud:>9} {ld:>7} {'---':>8} {'H':<10} {'---':>7} 1 {band:>2}\n"


def write_jmdc(path: Path, rows: list[str]) -> Path:
    path.write_bytes(gzip.compress("".join(rows).encode("latin-1")))
    return path


def row(**values: float | str | None) -> dict:
    return {
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


def cross(hd: str) -> dict:
    return {
        "cross_ids": [{"catalogue": "hd", "release": "1949", "catalogue_id": f" {hd}"}]
    }


class TestMeasuredDiameters:
    def test_takes_the_median_limb_darkened_value(self, tmp_path: Path) -> None:
        path = write_jmdc(
            tmp_path / "jmdc.dat.gz",
            [
                jmdc_row("HD39801", "---", "42.0000", " 7"),
                jmdc_row("HD39801", "---", "44.0000", " 8"),
                jmdc_row("HD39801", "60.00000", "---", " 8"),
            ],
        )
        assert measured_diameters(path) == {"39801": 44.0}

    def test_leaves_out_the_dust_bands(self, tmp_path: Path) -> None:
        path = write_jmdc(
            tmp_path / "jmdc.dat.gz", [jmdc_row("HD58061", "420.00000", "---", "11")]
        )
        assert measured_diameters(path) == {}

    def test_reads_a_row_named_by_ccdm(self, tmp_path: Path) -> None:
        path = write_jmdc(
            tmp_path / "jmdc.dat.gz",
            [jmdc_row("CCDM J16294-2626 AB", "41.00000", "---", " 8")],
        )
        assert measured_diameters(path) == {"148478": 41.0}


class TestSize:
    def test_a_paper_comes_first(self) -> None:
        size = _size(
            cross("58061"), row(parallax=1.0, parallax_error=0.1), {"58061": 420.0}
        )
        assert size is not None
        assert (size.radius_sun, size.source) == (1420, "literature")

    def test_a_diameter_at_the_distance_gives_the_radius(self) -> None:
        size = _size(
            cross("39801"), row(parallax=6.55, parallax_error=0.83), {"39801": 44.0}
        )
        assert size is not None
        assert size.reference == JMDC
        # 0.1075 R☉ per mas at one parsec.
        assert size.radius_sun == pytest.approx(0.1075 * 44 * 1000 / 6.55, rel=1e-3)

    def test_a_poor_parallax_gives_no_distance(self) -> None:
        poor = row(parallax=0.6, parallax_error=0.5, distance=2500.0)
        assert _size(cross("1"), poor, {"1": 22.0}) is None

    def test_a_compact_star_takes_no_gaia_radius(self) -> None:
        assert _size(cross("1"), row(radius_flame=4.0), {}, compact=True) is None
        hosted = _size(cross("1"), row(host_radius=0.01), {}, compact=True)
        assert hosted is not None

    def test_falls_back_to_the_catalogue(self) -> None:
        size = _size(cross("1"), row(host_radius=0.14, radius_flame=0.16), {})
        assert size is not None
        assert (size.radius_sun, size.source) == (0.14, "catalogue")

    def test_no_size_without_a_distance_or_a_radius(self) -> None:
        assert _size(cross("39801"), row(), {"39801": 44.0}) is None


class TestColour:
    def test_prefers_gaia(self) -> None:
        assert _bp_rp(row(phot_bp_mean_mag=2.5, phot_rp_mean_mag=1.0, v_i=9)) == 1.5

    def test_falls_back_to_hipparcos_v_i(self) -> None:
        assert _bp_rp(row(v_i=2.32)) == pytest.approx(2.5, abs=0.05)

    def test_none_without_either(self) -> None:
        assert _bp_rp(row()) is None
