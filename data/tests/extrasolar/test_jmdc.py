"""Tests for JMDC as an ingest source.

A wrong row draws a star at the wrong size with nothing to show it is wrong:
VY CMa's only row sees its dust shell at 8 µm, which gave 147,000 solar radii.
"""

import gzip
from pathlib import Path

import pytest

from space_map_data.constants.stars.literature import Distance, Radius
from space_map_data.extrasolar.sources import jmdc
from space_map_data.extrasolar.sources.literature import engine_rows


def jmdc_row(name: str, ud: str, ld: str, band: str) -> str:
    """One fixed-width row of jmdc.dat."""
    return (
        f"{name:<28} {'x':<28} {ud:>9} {ld:>7} {'---':>8} {'H':<10}"
        f" {'---':>7} 1 {band:>2}\n"
    )


def write_jmdc(path: Path, rows: list[str]) -> Path:
    path.write_bytes(gzip.compress("".join(rows).encode("latin-1")))
    return path


class TestReadDiameters:
    def test_takes_the_median_limb_darkened_value(self, tmp_path: Path) -> None:
        path = write_jmdc(
            tmp_path / "jmdc.dat.gz",
            [
                jmdc_row("HD39801", "---", "42.0000", " 7"),
                jmdc_row("HD39801", "---", "44.0000", " 8"),
                jmdc_row("HD39801", "60.00000", "---", " 8"),
            ],
        )
        assert jmdc.read_diameters(path) == {"39801": (44.0, 3)}

    def test_leaves_out_the_dust_bands(self, tmp_path: Path) -> None:
        path = write_jmdc(
            tmp_path / "jmdc.dat.gz", [jmdc_row("HD58061", "420.00000", "---", "11")]
        )
        assert jmdc.read_diameters(path) == {}

    def test_reads_a_row_named_by_ccdm(self, tmp_path: Path) -> None:
        path = write_jmdc(
            tmp_path / "jmdc.dat.gz",
            [jmdc_row("CCDM J16294-2626 AB", "41.00000", "---", " 8")],
        )
        assert jmdc.read_diameters(path) == {"148478": (41.0, 1)}


def test_a_row_claims_its_hd_star_and_drops_an_unknown_one() -> None:
    rows = jmdc.engine_rows({"39801": (88.8, 7.4)}, {"39801": (44.0, 3), "9": (1.0, 1)})
    assert rows.num_rows == 1
    assert rows["claims"].to_pylist()[0][0]["catalogue_id"] == "39801"
    assert rows["angular_diameter"].to_pylist() == [44.0]


class TestLiteratureRadius:
    key = ("hd", "1949", "58061")

    def test_a_star_with_only_a_radius_has_no_distance(self) -> None:
        rows = engine_rows(
            {},
            {"58061": (110.0, -25.0)},
            {},
            table={},
            radii={self.key: Radius(1420, "wittkowski_2012")},
            measured={},
        )
        assert rows["radius_literature"].to_pylist() == [1420]
        assert rows["distance"].to_pylist() == [None]
        assert rows["distance_method"].to_pylist() == [None]

    def test_a_star_with_both_keeps_both(self) -> None:
        rows = engine_rows(
            {},
            {"58061": (110.0, -25.0)},
            {},
            table={self.key: Distance(100.0, 90.0, 110.0, "parallax", "gaia_dr2_2018")},
            radii={self.key: Radius(1420, "wittkowski_2012")},
            measured={},
        )
        assert rows["distance"].to_pylist() == pytest.approx([100.0])
        assert rows["radius_literature"].to_pylist() == [1420]
