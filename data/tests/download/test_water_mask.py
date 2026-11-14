"""Tests for the banded water mask renderer."""

from pathlib import Path

import numpy as np
import shapefile
import tifffile
from PIL import Image

from space_map_data.download.providers.images.water_mask import render_water_mask

WIDTH, HEIGHT, BAND = 64, 32, 16


def _polygons(path: Path, rings: list[list[shapefile.PointsT]]) -> Path:
    """One feature per entry, each a list of rings (outer clockwise)."""
    writer = shapefile.Writer(str(path), shapeType=shapefile.POLYGON)
    # pyshp types its field decorator as taking the writer.
    writer.field("id", "N")  # ty: ignore[invalid-argument-type]
    for i, parts in enumerate(rings):
        writer.poly(parts)
        writer.record(i)
    writer.close()
    return path.with_suffix(".shp")


def _rivers(path: Path, lines: list[tuple[shapefile.PointsT, float]]) -> Path:
    writer = shapefile.Writer(str(path), shapeType=shapefile.POLYLINE)
    writer.field("DIS_AV_CMS", "N", decimal=1)  # ty: ignore[invalid-argument-type]
    for points, discharge in lines:
        writer.line([points])
        writer.record(discharge)
    writer.close()
    return path.with_suffix(".shp")


def _box(west: float, south: float, east: float, north: float) -> shapefile.PointsT:
    """A clockwise ring."""
    return [(west, south), (west, north), (east, north), (east, south), (west, south)]


def _render(tmp_path: Path, ocean, lakes, rivers) -> tuple[np.ndarray, np.ndarray]:
    render_water_mask(
        ocean=_polygons(tmp_path / "ocean", ocean),
        lakes=_polygons(tmp_path / "lakes", lakes),
        rivers=_rivers(tmp_path / "rivers", rivers),
        tiles_path=tmp_path / "mask.tif",
        tier_path=tmp_path / "mask.png",
        width=WIDTH,
        height=HEIGHT,
        band_rows=BAND,
    )
    return tifffile.imread(tmp_path / "mask.tif"), np.asarray(
        Image.open(tmp_path / "mask.png")
    )


class TestRenderWaterMask:
    """The mask is drawn in bands and written in full and reduced."""

    def test_polygon_across_bands_fills_both(self, tmp_path):
        """The eastern hemisphere, from 60°N to 60°S: rows 5 to 26 of 32."""
        full, _ = _render(tmp_path, [[_box(0, -60, 180, 60)]], [], [])
        assert full.shape == (HEIGHT, WIDTH)
        assert full[6:26, 33:].min() == 255
        assert full[:, :31].max() == 0
        assert full[:4].max() == 0 and full[28:].max() == 0

    def test_hole_of_a_lake_stays_land(self, tmp_path):
        lake = [_box(-90, -45, 0, 45), _box(-60, -20, -30, 20)[::-1]]
        full, _ = _render(tmp_path, [], [lake], [])
        assert full[10, 18] == 255
        assert full[16, 23] == 0

    def test_edge_texel_holds_the_water_fraction(self, tmp_path):
        """A box edge at the middle of a texel covers half of it."""
        half = 360.0 / WIDTH / 2
        full, _ = _render(tmp_path, [[_box(half, -60, 180, 60)]], [], [])
        assert 100 < full[16, 32] < 156

    def test_river_is_stroked_at_its_discharge_width(self, tmp_path):
        wide = ([(-170.0, 0.0), (-10.0, 0.0)], 1e10)
        thin = ([(10.0, 0.0), (170.0, 0.0)], 1.0)
        full, _ = _render(tmp_path, [], [], [wide, thin])
        assert full[15:17, 5:25].min() > 0
        assert full[:, 34:].max() == 0

    def test_bands_draw_as_one_canvas(self, tmp_path):
        """Vertices off the texel grid, on both sides of the band edge."""
        triangle: shapefile.PointsT = [
            (-170.3, 79.1),
            (171.1, 67.7),
            (3.7, -81.3),
            (-170.3, 79.1),
        ]
        lake: shapefile.PointsT = [
            (-100.9, 40.3),
            (-60.6, 10.1),
            (-20.2, -50.9),
            (-100.9, 40.3),
        ]
        layers = {
            "ocean": _polygons(tmp_path / "ocean", [[triangle]]),
            "lakes": _polygons(tmp_path / "lakes", [[lake]]),
            "rivers": _rivers(tmp_path / "rivers", []),
        }
        masks = []
        for band in (BAND, HEIGHT):
            render_water_mask(
                **layers,
                tiles_path=tmp_path / f"{band}.tif",
                tier_path=tmp_path / f"{band}.png",
                width=WIDTH,
                height=HEIGHT,
                band_rows=band,
            )
            masks.append(tifffile.imread(tmp_path / f"{band}.tif"))
        assert masks[0].max() == 255
        np.testing.assert_array_equal(masks[0], masks[1])

    def test_null_record_at_the_end_is_skipped(self, tmp_path):
        writer = shapefile.Writer(str(tmp_path / "lakes"), shapeType=shapefile.POLYGON)
        writer.field("id", "N")  # ty: ignore[invalid-argument-type]
        writer.poly([_box(0, -60, 180, 60)])
        writer.record(0)
        writer.null()
        writer.record(1)
        writer.close()
        render_water_mask(
            ocean=_polygons(tmp_path / "ocean", []),
            lakes=tmp_path / "lakes.shp",
            rivers=_rivers(tmp_path / "rivers", []),
            tiles_path=tmp_path / "mask.tif",
            tier_path=tmp_path / "mask.png",
            width=WIDTH,
            height=HEIGHT,
            band_rows=BAND,
        )
        assert tifffile.imread(tmp_path / "mask.tif")[6:26, 33:].min() == 255

    def test_tier_is_the_full_mask_reduced(self, tmp_path):
        full, tier = _render(tmp_path, [[_box(0, -60, 180, 60)]], [], [])
        assert tier.shape == (HEIGHT // 4, WIDTH // 4)
        mean = full.reshape(HEIGHT // 4, 4, WIDTH // 4, 4).mean(axis=(1, 3))
        assert np.abs(tier - mean).max() <= 1
