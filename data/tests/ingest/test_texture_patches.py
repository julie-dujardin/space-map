"""Tests for patches: the levels of a tile pyramid past its finest one, over
the ground a regional mosaic covers."""

import json
import os
from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image

from space_map_data.ingest.providers.textures import (
    TextureProcessor,
    config,
    image_io,
    patches,
    tiles,
)
from space_map_data.ingest.providers.textures.image_io import (
    ChunkedTiff,
    HeightRaster,
)

from .test_texture_tiles import _write_pds_image

TILE = 16
COLOUR = (200, 90, 40)
# A raster this wide is as fine as level 5 of a pyramid of 16 px tiles at
# 64 px a side, and as fine as level 7 at 256 px.
BOUNDS = (10.0, 32.5, 20.0, -2.5)
# The pyramid's own finest level: a pixel is 1.4°, so the raster is 16 wide.
BASE = 3
RADIUS = 1000.0


@pytest.fixture(autouse=True)
def _small_tiles(monkeypatch):
    monkeypatch.setattr(config, "TILE_SIZE", TILE)


def _pyramid(root: Path, level: int = BASE) -> Path:
    """A flat map tiled to ``level``."""
    image = np.full((TILE << level, (2 * TILE) << level, 3), COLOUR, dtype=np.uint8)
    out = root / "naif-499"
    tiles.PyramidBuilder(
        "map", [tiles.Layer(image, tiles.Placement())], out, level
    ).build()
    return out


def _texture(side: int = 256) -> np.ndarray:
    rng = np.random.default_rng(seed=3)
    return rng.uniform(60, 250, size=(side, side)).astype(np.uint8)


def _raster(pixels: np.ndarray, bounds=BOUNDS) -> tiles.Layer:
    return tiles.Layer(
        tiles.Region(pixels, *bounds), tiles.Placement(), to_values=tiles._brightness
    )


# A height pyramid in steps of a metre from 2 km below the datum, and the
# height of its flat ground.
CODING = tiles.HeightCoding(-2.0, 1e-3, -2.0)
GROUND_KM = 1.5


def _height_pyramid(root: Path, metres: np.ndarray | None = None) -> Path:
    """A height map tiled to ``BASE``: flat ground, or ``metres``."""
    if metres is None:
        metres = np.full((TILE << BASE, (2 * TILE) << BASE), GROUND_KM * 1000)
    raster = HeightRaster(
        metres.astype(np.int16), scale=1.0, offset=0.0, unit_km=1e-3, nodata=None
    )
    out = root / "naif-499_displacement"
    layer = tiles.height_layer(raster, tiles.Placement())
    tiles.PyramidBuilder("heights", [layer], out, BASE, CODING).build()
    return out


def _relief(side: int = 256) -> np.ndarray:
    """Rough ground in km, 80 m above that of the height pyramid."""
    rng = np.random.default_rng(seed=5)
    return (GROUND_KM + 0.08 + rng.normal(0.0, 0.02, size=(side, side))).astype("f4")


def _height_raster(km: np.ndarray, bounds=BOUNDS) -> tiles.Layer:
    raster = HeightRaster(km, scale=1.0, offset=0.0, unit_km=1.0, nodata=None)
    return tiles.Layer(
        tiles.Region(km, *bounds, blank=np.nan),
        tiles.Placement(),
        to_values=tiles._height_values(raster),
    )


def _km(root: Path, level: int, x: int, y: int) -> np.ndarray:
    return CODING.unpack(_tile(root, level, x, y))


def _files(root: Path) -> dict[int, set[tuple[int, int]]]:
    """Tiles under ``root`` as ``{level: {(x, y)}}``."""
    found: dict[int, set[tuple[int, int]]] = {}
    for path in root.glob("*/*/*.webp"):
        level, x = int(path.parts[-3]), int(path.parts[-2])
        found.setdefault(level, set()).add((x, int(path.stem)))
    return found


def _tile(root: Path, level: int, x: int, y: int) -> np.ndarray:
    return np.asarray(Image.open(root / str(level) / str(x) / f"{y}.webp"))


def _write_geotiff(
    path: Path,
    pixels: np.ndarray,
    bounds=BOUNDS,
    more_keys: tuple[int, ...] = (),
    tiepoint: tuple[float, float] = (0.0, 0.0),
    **storage,
) -> None:
    """An equirectangular GeoTIFF of a sphere of ``RADIUS`` metres.
    ``more_keys`` are further entries of its key directory."""
    west, east, north, south = bounds
    per_degree = np.radians(RADIUS)
    height, width = pixels.shape
    step = (east - west) * per_degree / width
    keys = (
        (1, 1, 0, 5 + len(more_keys) // 4)
        + (1024, 0, 1, 1)
        + (2057, 34736, 1, 0)
        + (3075, 0, 1, 17)
        + (3078, 34736, 1, 1)
        + (3088, 34736, 1, 2)
        + more_keys
    )
    scale = (step, (north - south) * per_degree / height, 0.0)
    corner = (*tiepoint, 0.0, west * per_degree, north * per_degree, 0.0)
    tifffile.imwrite(
        path,
        pixels,
        extratags=[
            (33550, "d", 3, scale, True),
            (33922, "d", 6, corner, True),
            (34735, "H", len(keys), keys, True),
            (34736, "d", 3, (RADIUS, 0.0, 0.0), True),
        ],
        **storage,
    )


class TestRegion:
    """A raster of part of the globe reads as one of all of it."""

    def test_holds_its_pixels_where_its_bounds_put_them(self):
        region = tiles.Region(_texture(64), *BOUNDS)
        assert region.shape == (512, 1024)
        assert region.bounds == pytest.approx(BOUNDS, abs=0.2)
        # 190° east of the left edge, 70° south of the north pole.
        window = region.read(190, 210, 530, 550)
        assert (window[:9] == 0).all() and (window[:, :10] == 0).all()
        assert (window[9:, 10:] == _texture(64)[:11, :10]).all()

    def test_bounds_may_count_longitude_from_zero(self):
        east_of_zero = tiles.Region(_texture(64), 190.0, 212.5, 20.0, -2.5)
        assert east_of_zero.bounds[0] == pytest.approx(-170.0, abs=0.2)

    def test_raster_across_the_antimeridian_is_refused(self):
        with pytest.raises(ValueError, match="180"):
            tiles.Region(_texture(64), 170.0, 192.5, 20.0, -2.5)

    def test_layer_has_no_data_outside_it(self):
        raster = _raster(_texture(64))
        # Its own pixel size, from 9 rows above and 10 columns west of it.
        edges = 90.0 - np.arange(190, 211) * (180.0 / 512)
        seen = np.isfinite(raster.window(1024, edges, 530, 550))
        assert seen[15, 15] and not seen[2, 15] and not seen[15, 2]

    def test_pds_image_is_placed_by_the_edges_its_label_states(self, tmp_path):
        west, east, north, south = BOUNDS
        _write_pds_image(
            tmp_path / "site.img",
            _texture(64).astype(np.float32),
            MAP_PROJECTION_TYPE="EQUIRECTANGULAR",
            WESTERNMOST_LONGITUDE=f"{west} <DEG>",
            EASTERNMOST_LONGITUDE=f"{east} <DEG>",
            MAXIMUM_LATITUDE=f"{north} <DEG>",
            MINIMUM_LATITUDE=f"{south} <DEG>",
        )
        raster = tiles.open_region_layer(tmp_path / "site.img")
        assert isinstance(raster.pixels, tiles.Region)
        assert raster.pixels.bounds == pytest.approx(BOUNDS, abs=0.2)
        assert raster.pixels.shape == (512, 1024)

    def test_bounds_of_a_geotiff(self, tmp_path):
        _write_geotiff(tmp_path / "site.tif", _texture(64))
        assert tiles._geotiff_bounds(tmp_path / "site.tif") == pytest.approx(BOUNDS)

    @pytest.mark.parametrize(
        "origin",
        [
            # ProjLinearUnitsGeoKey: kilometres.
            {"more_keys": (3076, 0, 1, 9036)},
            # ProjCenterLatGeoKey and ProjFalseEastingGeoKey: the first double.
            {"more_keys": (3089, 34736, 1, 0)},
            {"more_keys": (3082, 34736, 1, 0)},
            {"tiepoint": (4.0, 0.0)},
        ],
        ids=["kilometres", "latitude of origin", "false easting", "tiepoint"],
    )
    def test_geotiff_with_an_origin_it_cannot_read_is_refused(self, tmp_path, origin):
        """Its edges would come out wrong, with nothing to show it."""
        _write_geotiff(tmp_path / "site.tif", _texture(64), **origin)
        with pytest.raises(ValueError, match="origin or unit"):
            tiles._geotiff_bounds(tmp_path / "site.tif")

    def test_float_raster_reads_as_no_data_outside_it(self):
        region = tiles.Region(_texture(64).astype(np.float32), *BOUNDS)
        window = region.read(190, 210, 530, 550)
        assert np.isnan(window[:9]).all() and np.isfinite(window[9:, 10:]).all()

    @staticmethod
    def _site_image(path: Path, values: np.ndarray, **label) -> None:
        west, east, north, south = BOUNDS
        fields = {
            "MAP_PROJECTION_TYPE": "EQUIRECTANGULAR",
            "WESTERNMOST_LONGITUDE": f"{west} <DEG>",
            "EASTERNMOST_LONGITUDE": f"{east} <DEG>",
            "MAXIMUM_LATITUDE": f"{north} <DEG>",
            "MINIMUM_LATITUDE": f"{south} <DEG>",
            **label,
        }
        _write_pds_image(path, values, **fields)

    def test_shadow_in_a_calibrated_image_is_ground(self, tmp_path):
        """Noise puts a real sample in shadow at or below zero; only the
        file's null value is a gap."""
        values = _texture(64).astype(np.float32) / 1000.0
        values[20:30, 20:30] = -0.002
        # Wider than the gaps a layer fills in from their sides.
        values[34:58, 34:58] = -3.4028227e38
        self._site_image(tmp_path / "site.img", values)
        raster = tiles.open_region_layer(tmp_path / "site.img")
        # Its own pixel size, from its first row and column.
        edges = 90.0 - np.arange(199, 264) * (180.0 / 512)
        seen = raster.window(1024, edges, 540, 604)
        assert (seen[20:30, 20:30] == 0.0).all()
        assert np.isnan(seen[44:48, 44:48]).all()
        assert seen[5, 5] == pytest.approx(values[5, 5])

    def test_pds_image_counted_west_is_refused(self, tmp_path):
        self._site_image(
            tmp_path / "site.img",
            _texture(64).astype(np.float32),
            POSITIVE_LONGITUDE_DIRECTION="WEST",
        )
        with pytest.raises(ValueError, match="west"):
            tiles.open_region_layer(tmp_path / "site.img")

    def test_pds_image_across_the_prime_meridian(self, tmp_path):
        """A label that counts from 0° to 360° has its east edge below its
        west edge there."""
        self._site_image(
            tmp_path / "site.img",
            _texture(64).astype(np.float32),
            WESTERNMOST_LONGITUDE="350.0 <DEG>",
            EASTERNMOST_LONGITUDE="12.5 <DEG>",
        )
        raster = tiles.open_region_layer(tmp_path / "site.img")
        assert isinstance(raster.pixels, tiles.Region)
        assert raster.pixels.bounds == pytest.approx((-10.0, 12.5, 20.0, -2.5), abs=0.2)


class TestChunkedTiff:
    """A compressed mosaic is read by window, chunk by chunk."""

    @pytest.mark.parametrize(
        "storage",
        [
            {"tile": (64, 64), "compression": "packbits"},
            {"rowsperstrip": 48, "compression": "lzw"},
            {"tile": (128, 64), "compression": "deflate"},
        ],
        ids=["tiles", "strips", "tiles not square"],
    )
    def test_window_holds_the_pixels_of_the_file(self, tmp_path, storage):
        pixels = _texture(200)
        tifffile.imwrite(tmp_path / "site.tif", pixels, **storage)
        chunked = ChunkedTiff(tmp_path / "site.tif")
        assert chunked.shape == (200, 200)
        for window in (
            (slice(0, 200), slice(0, 200)),
            (slice(60, 70), slice(120, 131)),
            (slice(190, 200), slice(0, 5)),
        ):
            assert (chunked[window] == pixels[window]).all()

    def test_colour_window_holds_the_pixels_of_the_file(self, tmp_path):
        """As NASA stores Blue Marble at 500 m: one row a strip, the three
        samples of a pixel side by side."""
        pixels = np.random.default_rng(3).integers(0, 256, (120, 90, 3), np.uint8)
        tifffile.imwrite(
            tmp_path / "world.tif",
            pixels,
            photometric="rgb",
            rowsperstrip=1,
            compression="deflate",
        )
        chunked = ChunkedTiff(tmp_path / "world.tif")
        assert chunked.shape == (120, 90, 3)
        assert (chunked[40:73, 10:61] == pixels[40:73, 10:61]).all()

    def test_chunks_stay_decoded_up_to_a_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(image_io, "_CHUNK_CACHE_BYTES", 3 * 64 * 64)
        pixels = _texture(256)
        tifffile.imwrite(
            tmp_path / "site.tif", pixels, tile=(64, 64), compression="packbits"
        )
        chunked = ChunkedTiff(tmp_path / "site.tif")
        assert (chunked[0:256, 0:256] == pixels).all()
        assert len(chunked._cache) == 3

    def test_chunk_two_reads_decode_at_once_counts_once(self, tmp_path, monkeypatch):
        """The limit is on what the cache holds, not on what was decoded."""
        tifffile.imwrite(
            tmp_path / "site.tif", _texture(128), tile=(64, 64), compression="packbits"
        )
        chunked = ChunkedTiff(tmp_path / "site.tif")
        read = os.pread
        other_came_first = False

        def pread(fd: int, count: int, offset: int) -> bytes:
            nonlocal other_came_first
            if not other_came_first:
                other_came_first = True
                chunked._chunk(0)
            return read(fd, count, offset)

        monkeypatch.setattr(image_io.os, "pread", pread)
        chunked._chunk(0)
        assert chunked._held == sum(chunk.nbytes for chunk in chunked._cache.values())

    @pytest.mark.parametrize(
        "storage",
        [
            {"photometric": "miniswhite"},
            {
                "photometric": "palette",
                "colormap": np.tile(
                    np.arange(255, -1, -1, dtype=np.uint16) * 256, (3, 1)
                ),
            },
        ],
        ids=["white at zero", "palette in another order"],
    )
    def test_samples_that_are_not_brightness_as_stored_are_refused(
        self, tmp_path, storage
    ):
        tifffile.imwrite(
            tmp_path / "site.tif",
            _texture(128),
            tile=(64, 64),
            compression="packbits",
            **storage,
        )
        with pytest.raises(ValueError, match="grey scale"):
            ChunkedTiff(tmp_path / "site.tif")

    def test_palette_that_is_the_grey_ramp_is_brightness(self, tmp_path):
        pixels = _texture(128)
        tifffile.imwrite(
            tmp_path / "site.tif",
            pixels,
            tile=(64, 64),
            compression="packbits",
            photometric="palette",
            colormap=np.tile(np.arange(256, dtype=np.uint16) * 256, (3, 1)),
        )
        assert (ChunkedTiff(tmp_path / "site.tif")[0:128, 0:128] == pixels).all()

    def test_jpeg_chunks_take_their_tables_from_the_page(self, tmp_path):
        """A mosaic written by GDAL keeps them in a tag, once for all chunks."""
        ramp = np.add.outer(np.arange(128), np.arange(128)).astype(np.uint8)
        Image.fromarray(ramp).save(tmp_path / "site.tif", compression="jpeg")
        with tifffile.TiffFile(tmp_path / "site.tif") as tif:
            assert tif.pages[0].jpegtables is not None
        decoded = ChunkedTiff(tmp_path / "site.tif")[0:128, 0:128].astype(int)
        assert np.abs(decoded - ramp).max() <= 4

    def test_compressed_geotiff_is_a_regional_raster(self, tmp_path):
        _write_geotiff(
            tmp_path / "site.tif", _texture(64), tile=(32, 32), compression="packbits"
        )
        raster = tiles.open_region_layer(tmp_path / "site.tif")
        assert isinstance(raster.pixels, tiles.Region)
        assert (
            raster.pixels.read(190, 210, 530, 550)[9:, 10:] == _texture(64)[:11, :10]
        ).all()


class TestPatchBuilder:
    """A patch is the map's tone with the raster's detail, where the raster is."""

    @staticmethod
    def _build(tmp_path, pixels=None, **kwargs) -> patches.PatchBuilder:
        builder = patches.PatchBuilder(
            "test",
            _pyramid(tmp_path / "tiles"),
            BASE,
            [_raster(_texture() if pixels is None else pixels)],
            tmp_path / "patch",
            1.0,
            **kwargs,
        )
        builder.build()
        return builder

    def test_goes_as_deep_as_its_raster(self, tmp_path):
        builder = self._build(tmp_path)
        assert builder.level == 7
        assert sorted(_files(tmp_path / "patch")) == [4, 5, 6, 7]

    def test_has_tiles_only_where_the_raster_is(self, tmp_path):
        builder = self._build(tmp_path)
        assert builder.tile_range(7) == (135, 151, 49, 65)
        for level, found in _files(tmp_path / "patch").items():
            x0, x1, y0, y1 = builder.tile_range(level)
            assert found == {
                (x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)
            }
            assert builder.stats.tiles[level] == len(found)

    def test_level_limit(self, tmp_path):
        builder = self._build(tmp_path, max_level=5)
        assert sorted(_files(tmp_path / "patch")) == [4, 5]
        assert builder.level == 5

    def test_raster_no_finer_than_the_map_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="no finer"):
            self._build(tmp_path, max_level=BASE)

    def test_detail_is_the_rasters_and_tone_is_the_maps(self, tmp_path):
        self._build(tmp_path)
        inside = _tile(tmp_path / "patch", 7, 143, 57).astype(float)
        assert inside[..., 0].std() > 12.0
        assert abs(inside[..., 0].mean() - COLOUR[0]) < 25.0
        # Detail is brightness: the three channels move together.
        assert np.corrcoef(inside[..., 0].ravel(), inside[..., 1].ravel())[0, 1] > 0.9

    def test_darker_raster_over_another_leaves_no_step(self, tmp_path):
        """Two mosaics of one place differ in brightness by their sun."""
        wide = _texture()
        # The middle of the same ground, at half the brightness.
        inner = (wide[64:192, 64:192] // 2).astype(np.uint8)
        builder = patches.PatchBuilder(
            "test",
            _pyramid(tmp_path / "tiles"),
            BASE,
            [_raster(wide), _raster(inner, (15.625, 26.875, 14.375, 3.125))],
            tmp_path / "patch",
            1.0,
        )
        builder.build()
        middle = _tile(tmp_path / "patch", 7, 143, 57).astype(float)
        assert abs(middle[..., 0].mean() - COLOUR[0]) < 25.0

    def test_tile_past_the_raster_is_the_map(self, tmp_path):
        self._build(tmp_path)
        # The north-west tile: the raster starts 12 px down.
        corner = _tile(tmp_path / "patch", 7, 135, 49).astype(int)
        assert np.abs(corner[:6] - COLOUR).max() <= 4

    def test_thin_gaps_do_not_blank_the_ground_around_them(self, tmp_path):
        """A mosaic is strips with slivers of nothing between them."""
        pixels = _texture()
        pixels[:, ::16] = 0
        self._build(tmp_path, pixels=pixels)
        inside = _tile(tmp_path / "patch", 7, 143, 57).astype(float)
        assert inside[..., 0].std() > 12.0

    def test_level_is_that_of_the_finer_axis(self, tmp_path):
        """Away from the equator a pixel spans more longitude than latitude."""
        squat = _raster(_texture(), (10.0, 32.5, 20.0, 8.75))
        builder = patches.PatchBuilder(
            "test", _pyramid(tmp_path / "tiles"), BASE, [squat], tmp_path / "patch", 1.0
        )
        assert builder.level == 8

    def test_gap_in_the_raster_shows_the_map(self, tmp_path):
        pixels = _texture()
        pixels[64:192, 64:192] = 0
        self._build(tmp_path, pixels=pixels)
        hole = _tile(tmp_path / "patch", 7, 143, 57).astype(int)
        assert np.abs(hole - COLOUR).max() <= 4

    def test_wide_shadow_is_dark_and_its_noise_is_not_detail(self, tmp_path):
        """A calibrated mosaic has samples around zero in a shadow."""
        rng = np.random.default_rng(seed=5)
        pixels = _texture().astype(np.float32) / 1000.0
        pixels[64:192, 64:192] = rng.uniform(-0.002, 0.002, size=(128, 128))
        raster = tiles.Layer(
            tiles.Region(pixels, *BOUNDS),
            tiles.Placement(),
            to_values=tiles.brightness_values(None, shadows=True),
        )
        builder = patches.PatchBuilder(
            "test",
            _pyramid(tmp_path / "tiles"),
            BASE,
            [raster],
            tmp_path / "patch",
            1.0,
        )
        builder.build()
        shadow = _tile(tmp_path / "patch", 7, 143, 57).astype(float)
        assert shadow[..., 0].max() < 0.8 * COLOUR[0]
        assert shadow[..., 0].std() < 3.0


class TestFineHeights:
    """The tiles of a height patch count 256ths of a step in the blue byte."""

    def test_blue_is_the_part_of_a_step(self):
        km = np.array([[CODING.bias_km + 1e-3 * (1000 + 37 / 256)]])
        assert CODING.pack_fine(km)[0, 0].tolist() == [3, 232, 37]

    def test_tile_reads_back_as_its_heights(self):
        km = np.linspace(-1.9, 21.0, 64, dtype=np.float32).reshape(8, 8)
        back = CODING.unpack(CODING.pack_fine(km))
        assert np.abs(back - km).max() < 4e-6

    def test_tile_of_the_pyramid_reads_the_same_way(self):
        km = np.array([[0.25, 1.5]], dtype=np.float32)
        assert CODING.unpack(CODING.pack(km)) == pytest.approx(km)

    def test_coarser_part_of_a_step(self):
        km = np.array([[CODING.bias_km + 1e-3 * (1000 + 37 / 256)]])
        assert CODING.pack_fine(km, 4)[0, 0].tolist() == [3, 232, 64]
        assert CODING.pack_fine(km, 1)[0, 0].tolist() == [3, 232, 0]

    def test_height_out_of_the_range_stops_at_its_end(self):
        km = np.array([[-5.0, 100.0]])
        assert CODING.pack_fine(km).tolist() == [[[0, 0, 0], [255, 255, 255]]]


class TestHeightRegion:
    """A terrain model of a site reads as heights in km, with nothing around it."""

    def test_geotiff_states_its_heights_in_metres(self, tmp_path):
        metres = (_relief(64) * 1000).astype("f4")
        _write_geotiff(tmp_path / "site.tif", metres)
        raster = tiles.open_height_region_layer(tmp_path / "site.tif")
        # Its own pixel size, from 9 rows above and 10 columns west of it.
        edges = 90.0 - np.arange(190, 211) * (180.0 / 512)
        km = raster.window(1024, edges, 530, 550)
        assert np.isnan(km[0, 15]) and np.isnan(km[15, 2])
        assert km[15, 15] == pytest.approx(metres[6, 5] / 1000, abs=1e-6)

    def test_compressed_geotiff_is_read_by_window(self, tmp_path):
        metres = (_relief(64) * 1000).astype("f4")
        _write_geotiff(tmp_path / "site.tif", metres, compression="zlib", tile=(16, 16))
        raster = tiles.open_height_region_layer(tmp_path / "site.tif")
        region = raster.pixels
        assert isinstance(region, tiles.Region)
        assert isinstance(region._pixels, ChunkedTiff)
        assert (region.read(199, 201, 540, 542) == metres[:2, :2]).all()

    def test_tiepoint_at_a_pixel_centre_moves_the_edges_half_a_pixel(self, tmp_path):
        pixels = np.zeros((64, 64), dtype="f4")
        # 1025, 0, 1, 2: the raster type key, a pixel is a point.
        _write_geotiff(tmp_path / "point.tif", pixels, more_keys=(1025, 0, 1, 2))
        west, east, north, south = tiles._geotiff_bounds(tmp_path / "point.tif")
        half = (BOUNDS[1] - BOUNDS[0]) / 64 / 2
        assert (west, east) == pytest.approx((BOUNDS[0] - half, BOUNDS[1] - half))
        assert (north, south) == pytest.approx((BOUNDS[2] + half, BOUNDS[3] + half))

    def test_chunk_left_out_of_a_compressed_dtm_is_a_gap(self, tmp_path):
        metres = np.full((64, 64), 1500.0, dtype="f4")
        _write_geotiff(tmp_path / "site.tif", metres, compression="zlib", tile=(16, 16))
        raster = tiles.open_height_region_layer(tmp_path / "site.tif")
        region = raster.pixels
        assert isinstance(region, tiles.Region)
        chunks = region._pixels
        assert isinstance(chunks, ChunkedTiff)
        chunks._page.databytecounts = (0, *chunks._page.databytecounts[1:])
        assert raster.to_values is not None
        km = raster.to_values(raster._stored(199, 263, 540, 604))
        assert np.isnan(km[:16, :16]).all() and km[16:] == pytest.approx(1.5)

    def test_value_for_no_data_is_a_gap(self, tmp_path):
        metres = (_relief(64) * 1000).astype("f4")
        metres[10:20, 10:20] = -9999.0
        _write_geotiff(tmp_path / "site.tif", metres)
        raster = tiles.open_height_region_layer(tmp_path / "site.tif", nodata=-9999.0)
        assert raster.to_values is not None
        km = raster.to_values(raster._stored(199, 263, 540, 604))
        assert np.isnan(km[10:20, 10:20]).all() and np.isfinite(km[:10]).all()

    def test_manifest_overrides_what_the_file_states(self, tmp_path):
        _write_geotiff(tmp_path / "site.tif", np.full((64, 64), 3.0, dtype="f4"))
        raster = tiles.open_height_region_layer(
            tmp_path / "site.tif", unit="km", scale=2.0, offset=1.0
        )
        assert raster.read(199, 200, 540, 541)[0, 0] == pytest.approx(7.0)

    def test_integer_heights_need_a_value_for_no_data(self, tmp_path):
        _write_geotiff(tmp_path / "site.tif", np.zeros((64, 64), dtype=np.int16))
        with pytest.raises(ValueError, match="no data"):
            tiles.open_height_region_layer(tmp_path / "site.tif")
        raster = tiles.open_height_region_layer(tmp_path / "site.tif", nodata=-32768)
        # Past its edge: the value for no data, not ground at the datum.
        assert np.isnan(raster.read(190, 191, 540, 541)[0, 0])

    def test_pds_image_scales_by_its_label(self, tmp_path):
        west, east, north, south = BOUNDS
        _write_pds_image(
            tmp_path / "site.IMG",
            np.full((64, 64), 250.0),
            MAP_PROJECTION_TYPE='"EQUIRECTANGULAR"',
            WESTERNMOST_LONGITUDE=f"{west} <DEG>",
            EASTERNMOST_LONGITUDE=f"{east} <DEG>",
            MAXIMUM_LATITUDE=f"{north} <DEG>",
            MINIMUM_LATITUDE=f"{south} <DEG>",
            SCALING_FACTOR=2.0,
            OFFSET=1000.0,
            MISSING_CONSTANT="16#FF7FFFFB#",
        )
        raster = tiles.open_height_region_layer(tmp_path / "site.IMG")
        assert raster.read(199, 200, 540, 541)[0, 0] == pytest.approx(1.5)


class TestHeightPatchBuilder:
    """A height patch is the pyramid's broad heights with the raster's relief."""

    @staticmethod
    def _build(tmp_path, km=None, pyramid=None, **kwargs) -> patches.PatchBuilder:
        builder = patches.PatchBuilder(
            "test",
            _height_pyramid(tmp_path / "tiles") if pyramid is None else pyramid,
            BASE,
            [_height_raster(_relief() if km is None else km)],
            tmp_path / "patch",
            1.0,
            coding=CODING,
            **kwargs,
        )
        builder.build()
        return builder

    def test_has_the_tiles_of_a_colour_patch(self, tmp_path):
        builder = self._build(tmp_path)
        assert builder.level == 7
        assert sorted(_files(tmp_path / "patch")) == [4, 5, 6, 7]
        assert builder.tile_range(7) == (135, 151, 49, 65)

    def test_relief_is_the_rasters_and_broad_height_is_the_pyramids(self, tmp_path):
        self._build(tmp_path)
        inside = _km(tmp_path / "patch", 7, 143, 57)
        assert inside.std() > 0.015
        # Not the 80 m by which the raster stands above the pyramid.
        assert abs(inside.mean() - GROUND_KM) < 0.01

    def test_step_halves_with_each_level(self, tmp_path):
        """A level's pixels are half as wide as those of the level above."""
        self._build(tmp_path)
        parts = {
            level: np.unique(_tile(tmp_path / "patch", level, x, y)[..., 2]).tolist()
            for level, x, y in ((4, 16, 6), (5, 35, 14), (7, 143, 57))
        }
        assert parts[4] == [0, 128]
        assert parts[5] == [0, 64, 128, 192]
        assert parts[7] == list(range(0, 256, 16))

    def test_raster_apart_from_the_pyramid_leaves_no_step(self, tmp_path):
        self._build(tmp_path, km=np.full((256, 256), GROUND_KM + 0.08, dtype="f4"))
        for x, y in _files(tmp_path / "patch")[7]:
            assert np.abs(_km(tmp_path / "patch", 7, x, y) - GROUND_KM).max() < 1e-5

    def test_slope_at_the_edge_does_not_lift_the_patch(self, tmp_path):
        """A blur at the edge of a raster has ground on one side only."""
        # 4 m a pixel of the pyramid to the east: 0.25 m a pixel of the raster.
        ramp = np.arange((2 * TILE) << BASE) * 4.0
        pyramid = _height_pyramid(
            tmp_path / "tiles", np.broadcast_to(ramp, (TILE << BASE, ramp.size))
        )
        west = (BOUNDS[0] + 180.0) / 360.0 * ramp.size
        same = (west + (np.arange(256) + 0.5) / 16 - 0.5) * 4e-3
        self._build(
            tmp_path,
            km=np.broadcast_to(same, (256, 256)).astype("f4"),
            pyramid=pyramid,
        )
        edge = _km(tmp_path / "patch", 7, 136, 57)
        along = (136 * TILE + np.arange(TILE) + 0.5) / 16 - 0.5
        assert np.abs(edge - along * 4e-3).max() < 5e-4

    def test_tile_past_the_raster_is_the_pyramid(self, tmp_path):
        self._build(tmp_path)
        # The north-west tile: the raster starts 12 px down.
        corner = _km(tmp_path / "patch", 7, 135, 49)
        assert np.abs(corner[:6] - GROUND_KM).max() < 1e-5

    def test_gap_in_the_raster_is_the_pyramid(self, tmp_path):
        km = _relief()
        km[64:192, 64:192] = np.nan
        self._build(tmp_path, km=km)
        hole = _km(tmp_path / "patch", 7, 143, 57)
        assert np.abs(hole - GROUND_KM).max() < 1e-5

    def test_later_raster_comes_in_over_an_earlier_one_with_no_step(self, tmp_path):
        """Two rasters of one place differ by more than their blurs show."""
        flat = np.full((256, 256), GROUND_KM, dtype="f4")
        # Waves of 2 m, too short for the blur to level, with a crest at the
        # raster's west edge.
        waves = flat + 2e-3 * np.cos(np.pi * (np.arange(256) - 128) / 32).astype("f4")
        waves[:, :128] = np.nan
        patches.PatchBuilder(
            "test",
            _height_pyramid(tmp_path / "tiles"),
            BASE,
            [_height_raster(flat), _height_raster(waves)],
            tmp_path / "patch",
            1.0,
            coding=CODING,
        ).build()
        across = np.concatenate(
            [_km(tmp_path / "patch", 7, x, 57) for x in range(141, 148)], axis=1
        )
        # A cut would be a step of more than a metre; the waves are 0.2 m a pixel.
        assert np.abs(np.diff(across, axis=1)).max() < 4e-4
        assert np.ptp(across[:, -64:]) > 2e-3

    def test_level_above_is_the_average_of_the_heights(self, tmp_path):
        self._build(tmp_path)
        fine = np.concatenate(
            [
                np.concatenate(
                    [_km(tmp_path / "patch", 7, 142 + dx, 56 + dy) for dx in (0, 1)],
                    axis=1,
                )
                for dy in (0, 1)
            ]
        )
        mean = fine.reshape(TILE, 2, TILE, 2).mean(axis=(1, 3))
        # Each to its own step: a sixteenth and an eighth of a metre.
        assert np.abs(_km(tmp_path / "patch", 6, 71, 28) - mean).max() < 1.5e-4

    def test_leaves_the_levels_of_the_pyramid_alone(self, tmp_path):
        """Heights in three bytes do not mix by alpha."""
        builder = patches.PatchBuilder(
            "test",
            _height_pyramid(tmp_path / "tiles"),
            BASE,
            [_height_raster(_relief())],
            tmp_path / "patch",
            4.0,
            coding=CODING,
        )
        builder.build()
        assert builder.map_levels == 0
        assert not (tmp_path / "patch" / ".over").exists()

    def test_tiles_are_lossless(self, tmp_path):
        self._build(tmp_path)
        with Image.open(tmp_path / "patch" / "7" / "143" / "57.webp") as tile:
            assert tile.mode == "RGB"
        # A lossy tile would not hold a height to a 256th of a step.
        again = tmp_path / "again"
        self._build(again)
        assert (
            _tile(tmp_path / "patch", 7, 143, 57) == _tile(again / "patch", 7, 143, 57)
        ).all()


class TestPatchTiles:
    """A patch built aside goes into its pyramid, and comes out again."""

    def test_put_in_place_then_removed(self, tmp_path):
        pyramid = _pyramid(tmp_path / "tiles")
        own = _files(pyramid)
        builder = patches.PatchBuilder(
            "test", pyramid, BASE, [_raster(_texture())], pyramid / ".patch-site", 1.0
        )
        builder.build()
        patches.put_in_place(pyramid / ".patch-site", pyramid, "site")
        assert not (pyramid / ".patch-site").exists()
        assert sorted(_files(pyramid)) == [0, 1, 2, 3, 4, 5, 6, 7]

        x0, x1, y0, y1 = builder.tile_range(7)
        site = {"id": "site", "max_level": 7, "x": [x0, x1], "y": [y0, y1]}
        patches.remove(pyramid, BASE, site)
        assert _files(pyramid) == own
        assert not (pyramid / "4").exists()


def _blocks(side: int = 256, seed: int = 7) -> np.ndarray:
    """Ground with features as wide as a pixel of the map's finest level."""
    rng = np.random.default_rng(seed)
    coarse = rng.uniform(60, 250, size=(side // 16, side // 16))
    return np.kron(coarse, np.ones((16, 16))).astype(np.uint8)


def _bytes(pyramid: Path) -> dict[str, bytes]:
    """Each tile of the pyramid's own levels, as it is on disk."""
    return {
        str(path.relative_to(pyramid)): path.read_bytes()
        for level in range(BASE + 1)
        for path in (pyramid / str(level)).glob("*/*.webp")
    }


class TestMapLevels:
    """A patch shows in the finest levels of the pyramid itself."""

    # The blur is 4 px of the finest level and 2 px of the level above it.
    SIGMA = 4.0
    # A raster east of the first one. The two share no tile of the first
    # patch level, and one tile of each of the pyramid's two finest levels.
    EAST = (34.0, 56.5, 20.0, -2.5)

    @staticmethod
    def _place(pyramid: Path, patch_id: str = "site", bounds=BOUNDS, seed: int = 7):
        builder = patches.PatchBuilder(
            "test",
            pyramid,
            BASE,
            [_raster(_blocks(seed=seed), bounds)],
            pyramid / f".patch-{patch_id}",
            TestMapLevels.SIGMA,
        )
        builder.build()
        patches.put_in_place(pyramid / f".patch-{patch_id}", pyramid, patch_id)
        return builder

    @staticmethod
    def _site(builder: patches.PatchBuilder, patch_id: str = "site") -> dict:
        x0, x1, y0, y1 = builder.tile_range(builder.level)
        return {
            "id": patch_id,
            "max_level": builder.level,
            "x": [x0, x1],
            "y": [y0, y1],
        }

    @staticmethod
    def _drawn(pyramid: Path, patch_id: str, level: int, x: int, y: int) -> np.ndarray:
        """Where a patch draws on a tile of the pyramid, at over half weight."""
        over = pyramid / ".over" / patch_id / str(level) / str(x) / f"{y}.webp"
        return np.asarray(Image.open(over))[..., 3] > 128

    @staticmethod
    def _over(pyramid: Path, patch_id: str = "site") -> set[str]:
        """The tiles of the pyramid that a patch draws on."""
        folder = pyramid / ".over" / patch_id
        return {str(path.relative_to(folder)) for path in folder.glob("*/*/*.webp")}

    def test_levels_follow_the_blur(self):
        assert patches.map_levels(16.0, 10) == 4
        assert patches.map_levels(3.0, 6) == 2
        assert patches.map_levels(1.0, 6) == 0
        # No further than the pyramid goes.
        assert patches.map_levels(16.0, 2) == 3

    def test_coarser_level_takes_no_colour_from_what_is_not_drawn(self):
        image = np.zeros((2 * TILE, 2 * TILE, 3), dtype=np.uint8)
        alpha = np.zeros((2 * TILE, 2 * TILE), dtype=np.uint8)
        # One drawn pixel of each block of four, in red.
        image[::2, ::2] = (200, 0, 0)
        alpha[::2, ::2] = 255
        half, low = patches._coarser(image, alpha)
        assert (half == (200, 0, 0)).all()
        assert (low == 64).all()

    def test_patch_shows_in_the_tiles_of_the_map_under_it(self, tmp_path):
        pyramid = _pyramid(tmp_path / "tiles")
        own = _bytes(pyramid)
        builder = self._place(pyramid)
        assert builder.map_levels == 2

        assert self._over(pyramid) == {
            *(f"3/{x}/{y}.webp" for x in (8, 9) for y in (3, 4)),
            "2/4/1.webp",
            "2/4/2.webp",
        }
        now = _bytes(pyramid)
        changed = {name for name in own if now[name] != own[name]}
        assert "3/8/3.webp" in changed and changed <= self._over(pyramid)
        inside = self._drawn(pyramid, "site", 3, 8, 3)
        tile = _tile(pyramid, 3, 8, 3).astype(float)
        assert tile[inside][:, 0].std() > 12.0
        # The tone stays the map's, and so does the ground past the raster.
        assert abs(tile[inside][:, 0].mean() - COLOUR[0]) < 25.0
        assert np.abs(tile[:, :6] - COLOUR).max() <= 6

    def test_tile_of_the_map_is_kept_as_it_was_built(self, tmp_path):
        pyramid = _pyramid(tmp_path / "tiles")
        own = _bytes(pyramid)
        self._place(pyramid)
        kept = {
            str(path.relative_to(pyramid / ".map")): path.read_bytes()
            for path in (pyramid / ".map").glob("*/*/*.webp")
        }
        assert set(kept) == self._over(pyramid)
        assert all(kept[name] == own[name] for name in kept)

    def test_patch_built_again_gives_the_same_tiles(self, tmp_path):
        """It is drawn over the map's own tiles, not over itself."""
        pyramid = _pyramid(tmp_path / "tiles")
        self._place(pyramid)
        first = _bytes(pyramid)
        self._place(pyramid)
        assert _bytes(pyramid) == first

    def test_patch_taken_out_gives_the_map_its_tiles_back(self, tmp_path):
        pyramid = _pyramid(tmp_path / "tiles")
        own = _bytes(pyramid)
        builder = self._place(pyramid)
        patches.remove(pyramid, BASE, self._site(builder))
        assert _bytes(pyramid) == own
        assert not (pyramid / ".map").exists()
        assert not (pyramid / ".over").exists()

    def test_two_patches_on_one_tile_of_the_map(self, tmp_path):
        pyramid = _pyramid(tmp_path / "tiles")
        own = _bytes(pyramid)
        first = self._place(pyramid)
        self._place(pyramid, "east", self.EAST, seed=11)
        west = self._drawn(pyramid, "site", 3, 9, 3)
        east = self._drawn(pyramid, "east", 3, 9, 3)
        assert west.any() and east.any()
        shared = _tile(pyramid, 3, 9, 3).astype(float)
        assert shared[west][:, 0].std() > 8.0
        assert shared[east][:, 0].std() > 8.0

        patches.remove(pyramid, BASE, self._site(first))
        shared = _tile(pyramid, 3, 9, 3).astype(float)
        assert np.abs(shared[west] - COLOUR).max() <= 6
        assert shared[east][:, 0].std() > 8.0
        assert (pyramid / ".map" / "3" / "9" / "3.webp").read_bytes() == own[
            "3/9/3.webp"
        ]
        assert _bytes(pyramid)["3/8/3.webp"] == own["3/8/3.webp"]

    def test_patch_with_a_blur_of_one_pixel_leaves_the_map_alone(self, tmp_path):
        pyramid = _pyramid(tmp_path / "tiles")
        own = _bytes(pyramid)
        builder = patches.PatchBuilder(
            "test", pyramid, BASE, [_raster(_blocks())], pyramid / ".patch-site", 1.0
        )
        builder.build()
        patches.put_in_place(pyramid / ".patch-site", pyramid, "site")
        assert builder.map_levels == 0
        assert _bytes(pyramid) == own


class TestProcessPatches:
    """The processor builds the patches a pyramid's entry names."""

    @staticmethod
    def _processor(monkeypatch, tmp_path, patch_specs: list[dict]) -> TextureProcessor:
        raw = tmp_path / "raw"
        raw.mkdir(exist_ok=True)
        Image.new("RGB", (16 * TILE, 8 * TILE), color=COLOUR).save(raw / "mars.png")
        monkeypatch.setattr(config, "TILES_PROCESSED_DIR", tmp_path / "tiles")
        monkeypatch.setattr(config, "TILES_METADATA_DIR", tmp_path / "meta")
        proc = TextureProcessor.__new__(TextureProcessor)
        proc._raw_meta = [
            {
                "body": "naif-499",
                "source": "https://example.com/mars",
                "organisation": "USGS",
                "file": "mars.png",
                "type": "cylindrical",
                "patches": patch_specs,
                "_source_dir": raw,
            }
        ]
        return proc

    @staticmethod
    def _spec(**extra) -> dict:
        return {
            "id": "site",
            "name": "Site",
            "source": "https://example.com/site",
            "organisation": "USGS",
            "license": "Public domain",
            "attribution": "Site credit",
            "sharpen_sigma": 1.0,
            "files": [{"file": "site.tif"}],
            **extra,
        }

    @staticmethod
    def _meta(tmp_path) -> dict:
        return json.loads(
            (tmp_path / "meta" / "naif-499" / "metadata.json").read_text()
        )

    def test_patch_and_its_descriptor(self, tmp_path, monkeypatch):
        proc = self._processor(monkeypatch, tmp_path, [self._spec()])
        _write_geotiff(tmp_path / "raw" / "site.tif", _texture())
        proc.process_tiles()

        meta = self._meta(tmp_path)
        assert meta["max_level"] == BASE
        (patch,) = meta["patches"]
        assert (patch["id"], patch["max_level"]) == ("site", 7)
        assert patch["map_levels"] == 0
        assert (patch["x"], patch["y"]) == ([135, 151], [49, 65])
        assert patch["full_width"] == 4096
        # On the pixel grid of the raster, where a pixel is 0.09°.
        assert patch["bounds"] == pytest.approx(
            {"west": 10.0, "east": 32.5, "south": -2.5, "north": 20.0}, abs=0.05
        )
        assert (patch["name"], patch["attribution"]) == ("Site", "Site credit")
        assert [level["level"] for level in patch["levels"]] == [4, 5, 6, 7]
        assert patch["levels"][-1]["tiles"] == 289
        assert len(_files(tmp_path / "tiles" / "naif-499")[7]) == 289

    def test_patch_in_the_levels_of_the_map(self, tmp_path, monkeypatch):
        proc = self._processor(monkeypatch, tmp_path, [self._spec(sharpen_sigma=4.0)])
        _write_geotiff(tmp_path / "raw" / "site.tif", _blocks())
        proc._raw_meta[0]["patches"] = []
        proc.process_tiles()
        pyramid = tmp_path / "tiles" / "naif-499"
        own = _bytes(pyramid)

        proc._raw_meta[0]["patches"] = [self._spec(sharpen_sigma=4.0)]
        proc.process_tiles()
        (patch,) = self._meta(tmp_path)["patches"]
        assert patch["map_levels"] == 2
        assert _bytes(pyramid)["3/8/3.webp"] != own["3/8/3.webp"]

        # Another raster: the tiles of the map follow, from their own pixels.
        _write_geotiff(tmp_path / "raw" / "site.tif", _blocks(128))
        proc.process_tiles()
        assert (pyramid / ".map" / "3" / "8" / "3.webp").read_bytes() == own[
            "3/8/3.webp"
        ]

        proc._raw_meta[0]["patches"] = []
        proc.process_tiles()
        assert _bytes(pyramid) == own

    def test_patch_already_built_is_kept(self, tmp_path, monkeypatch):
        proc = self._processor(monkeypatch, tmp_path, [self._spec()])
        _write_geotiff(tmp_path / "raw" / "site.tif", _texture())
        proc.process_tiles()
        tile = tmp_path / "tiles" / "naif-499" / "7" / "143" / "57.webp"
        stamp = tile.stat().st_mtime_ns
        proc.process_tiles()
        assert tile.stat().st_mtime_ns == stamp

    def test_changed_patch_is_built_again(self, tmp_path, monkeypatch):
        proc = self._processor(monkeypatch, tmp_path, [self._spec()])
        _write_geotiff(tmp_path / "raw" / "site.tif", _texture())
        proc.process_tiles()
        first = self._meta(tmp_path)["patches"][0]["version"]
        proc._raw_meta[0]["patches"] = [self._spec(tiles_max_level=5)]
        proc.process_tiles()

        (patch,) = self._meta(tmp_path)["patches"]
        assert patch["version"] != first and patch["max_level"] == 5
        assert sorted(_files(tmp_path / "tiles" / "naif-499")) == [0, 1, 2, 3, 4, 5]

    def test_patch_no_longer_named_is_taken_out(self, tmp_path, monkeypatch):
        proc = self._processor(monkeypatch, tmp_path, [self._spec()])
        _write_geotiff(tmp_path / "raw" / "site.tif", _texture())
        proc.process_tiles()
        proc._raw_meta[0]["patches"] = []
        proc.process_tiles()

        assert "patches" not in self._meta(tmp_path)
        assert sorted(_files(tmp_path / "tiles" / "naif-499")) == [0, 1, 2, 3]

    def test_missing_raster_leaves_the_pyramid_alone(
        self, tmp_path, monkeypatch, caplog
    ):
        caplog.set_level("WARNING")
        proc = self._processor(monkeypatch, tmp_path, [self._spec()])
        proc.process_tiles()
        assert "patches" not in self._meta(tmp_path)
        assert any("patch source missing" in r.message for r in caplog.records)

    def test_stopped_build_keeps_the_patch_it_was_to_replace(
        self, tmp_path, monkeypatch
    ):
        proc = self._processor(monkeypatch, tmp_path, [self._spec()])
        _write_geotiff(tmp_path / "raw" / "site.tif", _texture())
        proc.process_tiles()
        first = self._meta(tmp_path)["patches"][0]
        proc._raw_meta[0]["patches"] = [self._spec(tiles_max_level=5)]

        def stop(self):
            raise KeyboardInterrupt

        monkeypatch.setattr(patches.PatchBuilder, "build", stop)
        with pytest.raises(KeyboardInterrupt):
            proc.process_tiles()
        assert self._meta(tmp_path)["patches"] == [first]
        assert len(_files(tmp_path / "tiles" / "naif-499")[7]) == 289

    def test_raster_it_cannot_place_does_not_stop_the_other_patches(
        self, tmp_path, monkeypatch, caplog
    ):
        elsewhere = (-100.0, -77.5, 20.0, -2.5)
        specs = [
            self._spec(id="odd", files=[{"file": "odd.tif"}]),
            self._spec(files=[{"file": "site.tif"}]),
        ]
        proc = self._processor(monkeypatch, tmp_path, specs)
        _write_geotiff(
            tmp_path / "raw" / "odd.tif", _texture(), elsewhere, tiepoint=(4.0, 0.0)
        )
        _write_geotiff(tmp_path / "raw" / "site.tif", _texture())
        proc.process_tiles()
        assert [patch["id"] for patch in self._meta(tmp_path)["patches"]] == ["site"]
        assert any("odd" in r.message for r in caplog.records if r.levelname == "ERROR")

    def test_patch_that_shares_tiles_with_another_is_refused(
        self, tmp_path, monkeypatch, caplog
    ):
        """Each would write the shared tiles without the other's detail."""
        # Its first column is the last of the other, at the first patch level.
        beside = (33.0, 55.5, 20.0, -2.5)
        specs = [
            self._spec(files=[{"file": "site.tif"}]),
            self._spec(id="beside", files=[{"file": "beside.tif"}]),
        ]
        proc = self._processor(monkeypatch, tmp_path, specs)
        _write_geotiff(tmp_path / "raw" / "site.tif", _texture())
        _write_geotiff(tmp_path / "raw" / "beside.tif", _texture(), beside)
        proc.process_tiles()
        assert [patch["id"] for patch in self._meta(tmp_path)["patches"]] == ["site"]
        assert any("belong in one patch" in r.message for r in caplog.records)
        assert len(_files(tmp_path / "tiles" / "naif-499")[7]) == 289

    def test_map_built_again_takes_its_patches_with_it(self, tmp_path, monkeypatch):
        proc = self._processor(monkeypatch, tmp_path, [self._spec()])
        _write_geotiff(tmp_path / "raw" / "site.tif", _texture())
        proc.process_tiles()
        first = self._meta(tmp_path)["patches"][0]["version"]
        Image.new("RGB", (16 * TILE, 8 * TILE), color=(20, 60, 200)).save(
            tmp_path / "raw" / "mars.png"
        )
        proc.process_tiles()

        (patch,) = self._meta(tmp_path)["patches"]
        assert patch["version"] != first
        inside = _tile(tmp_path / "tiles" / "naif-499", 7, 143, 57).astype(float)
        assert inside[..., 2].mean() > inside[..., 0].mean()


class TestProcessHeightPatches:
    """A height pyramid takes patches from terrain models."""

    @staticmethod
    def _processor(monkeypatch, tmp_path, patch_specs: list[dict]) -> TextureProcessor:
        raw = tmp_path / "raw"
        raw.mkdir(exist_ok=True)
        metres = np.full((8 * TILE, 16 * TILE), GROUND_KM * 1000, dtype=np.int16)
        # The lowest point of the body: no height of a patch is below it.
        metres[0, 0] = 0
        tifffile.imwrite(raw / "dem.tif", metres)
        monkeypatch.setattr(config, "TILES_PROCESSED_DIR", tmp_path / "tiles")
        monkeypatch.setattr(config, "TILES_METADATA_DIR", tmp_path / "meta")
        proc = TextureProcessor.__new__(TextureProcessor)
        proc._raw_meta = [
            {
                "body": "naif-499",
                "source": "https://example.com/dem",
                "organisation": "USGS",
                "attribution": "DEM credit",
                "file": "dem.tif",
                "type": "cylindrical_displacement",
                "patches": patch_specs,
                "_source_dir": raw,
            }
        ]
        return proc

    @staticmethod
    def _meta(tmp_path) -> dict:
        folder = tmp_path / "meta" / "naif-499_displacement"
        return json.loads((folder / "metadata.json").read_text())

    def test_patch_and_its_descriptor(self, tmp_path, monkeypatch):
        spec = TestProcessPatches._spec()
        proc = self._processor(monkeypatch, tmp_path, [spec])
        _write_geotiff(tmp_path / "raw" / "site.tif", _relief() * 1000)
        proc.process_tiles()

        meta = self._meta(tmp_path)
        assert meta["max_level"] == BASE
        (patch,) = meta["patches"]
        assert (patch["id"], patch["max_level"]) == ("site", 7)
        assert (patch["x"], patch["y"]) == ([135, 151], [49, 65])
        # In the coding of its pyramid, which the descriptor states once.
        coding = tiles.HeightCoding(
            meta["displacement_bias_km"],
            meta["displacement_scale_km"] / tiles.HEIGHT_LEVELS,
            0.0,
        )
        root = tmp_path / "tiles" / "naif-499_displacement"
        inside = coding.unpack(_tile(root, 7, 143, 57))
        assert inside.std() > 0.015 and abs(inside.mean() - GROUND_KM) < 0.01

    def test_other_unit_is_another_patch(self, tmp_path, monkeypatch):
        spec = TestProcessPatches._spec()
        proc = self._processor(monkeypatch, tmp_path, [spec])
        _write_geotiff(tmp_path / "raw" / "site.tif", _relief() * 1000)
        proc.process_tiles()
        first = self._meta(tmp_path)["patches"][0]["version"]
        proc.process_tiles()
        assert self._meta(tmp_path)["patches"][0]["version"] == first

        spec["files"] = [{"file": "site.tif", "height_unit": "half_m"}]
        proc.process_tiles()
        assert self._meta(tmp_path)["patches"][0]["version"] != first

    def test_colour_patch_has_no_field_of_a_height_patch(self, tmp_path, monkeypatch):
        """A colour patch's token is its own fields only."""
        proc = TestProcessPatches._processor(
            monkeypatch, tmp_path, [TestProcessPatches._spec()]
        )
        _write_geotiff(tmp_path / "raw" / "site.tif", _texture())
        proc.process_tiles()
        meta = json.loads(
            (tmp_path / "meta" / "naif-499" / "metadata.json").read_text()
        )
        size = (tmp_path / "raw" / "site.tif").stat().st_size
        assert meta["patches"][0]["version"] == tiles.signature_version(
            {
                "recipe": patches.RECIPE,
                "pyramid": meta["version"],
                "sigma": 1.0,
                "max_level": None,
                "files": [["site.tif", size, None]],
            }
        )
