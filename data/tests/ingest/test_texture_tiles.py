"""Tests for the tile pyramid builder and its place in the texture processor."""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image

from space_map_data.ingest.providers.textures import TextureProcessor, config, tiles
from space_map_data.ingest.providers.textures.image_io import (
    HeightRaster,
    open_height_raster,
)

TILE = 16


@pytest.fixture(autouse=True)
def _small_tiles(monkeypatch):
    monkeypatch.setattr(config, "TILE_SIZE", TILE)


def _stitch(root, level: int) -> np.ndarray:
    """A whole level read back from its tiles."""
    rows = []
    for y in range(1 << level):
        row = [
            np.asarray(Image.open(root / str(level) / str(x) / f"{y}.webp"))
            for x in range(2 << level)
        ]
        rows.append(np.concatenate(row, axis=1))
    return np.concatenate(rows, axis=0)


def _decode_km(rgb: np.ndarray, coding: tiles.HeightCoding) -> np.ndarray:
    code = rgb[..., 0].astype(np.uint32) * 256 + rgb[..., 1]
    return coding.bias_km + coding.step_km * code


def _height_layer(metres: np.ndarray, **placement) -> tiles.Layer:
    raster = HeightRaster(metres, scale=1.0, offset=0.0, unit_km=1e-3, nodata=-32768)
    return tiles.height_layer(raster, tiles.Placement(**placement))


def _terrain(width: int, height: int) -> np.ndarray:
    rng = np.random.default_rng(seed=7)
    return rng.integers(-8000, 21000, size=(height, width)).astype(np.int16)


class TestFinestLevel:
    """The finest level is the first one wide enough for the source."""

    def test_level_holds_the_source(self):
        assert tiles.finest_level(2 * TILE) == 0
        assert tiles.finest_level(4 * TILE) == 1
        assert tiles.finest_level(5 * TILE) == 2

    def test_barely_wider_source_stays_a_level_down(self):
        """Four times the tiles for a few percent of detail is a bad trade."""
        assert tiles.finest_level(int(4 * TILE * 1.05)) == 1


class TestColourPyramid:
    """Lossy colour tiles at every level, in the renderer's alignment."""

    @staticmethod
    def _build(tmp_path, pixels: np.ndarray, **placement) -> tiles.PyramidStats:
        layer = tiles.Layer(pixels, tiles.Placement(**placement))
        return tiles.PyramidBuilder("test", [layer], tmp_path / "out", 1).build()

    @staticmethod
    def _halves() -> np.ndarray:
        """Red over the western half, blue over the eastern."""
        pixels = np.zeros((2 * TILE, 4 * TILE, 3), dtype=np.uint8)
        pixels[:, : 2 * TILE, 0] = 255
        pixels[:, 2 * TILE :, 2] = 255
        return pixels

    def test_every_level_is_fully_tiled(self, tmp_path):
        stats = self._build(tmp_path, self._halves())
        assert stats.tiles == [2, 8]
        assert _stitch(tmp_path / "out", 0).shape == (TILE, 2 * TILE, 3)
        assert _stitch(tmp_path / "out", 1).shape == (2 * TILE, 4 * TILE, 3)

    def test_coarser_level_averages_the_finer_one(self, tmp_path):
        self._build(tmp_path, self._halves())
        west = _stitch(tmp_path / "out", 0)[:, : TILE // 2]
        assert west[..., 0].mean() > 240
        assert west[..., 2].mean() < 15

    def test_source_starting_at_the_prime_meridian_is_shifted(self, tmp_path):
        """The renderer expects 180°W at the left edge."""
        self._build(tmp_path, self._halves(), lon_at_left_deg=0.0)
        west = _stitch(tmp_path / "out", 1)[:, : TILE // 2]
        assert west[..., 2].mean() > 240

    def test_planar_source_reads_like_a_chunky_one(self, tmp_path):
        planar = np.moveaxis(self._halves(), -1, 0)
        layer = tiles.Layer(planar, tiles.Placement(), planar=True)
        tiles.PyramidBuilder("test", [layer], tmp_path / "out", 1).build()
        west = _stitch(tmp_path / "out", 1)[:, : TILE // 2]
        assert west[..., 0].mean() > 240


class TestMemmapPage:
    """Sources are mapped in place: a 20 GB DEM must never be copied."""

    @pytest.mark.parametrize("byteorder", ["<", ">"])
    def test_height_raster_is_mapped_whatever_its_byte_order(self, tmp_path, byteorder):
        metres = _terrain(4 * TILE, 2 * TILE)
        tifffile.imwrite(tmp_path / "dem.tif", metres, byteorder=byteorder)
        raster = open_height_raster(tmp_path / "dem.tif")
        assert isinstance(raster.samples, np.memmap)
        assert np.array_equal(raster.samples, metres)

    def test_planar_colour_is_mapped_as_planes(self, tmp_path):
        planes = np.arange(3 * 8 * 16, dtype=np.uint8).reshape(3, 8, 16)
        tifffile.imwrite(
            tmp_path / "map.tif", planes, photometric="rgb", planarconfig="separate"
        )
        layer = tiles.open_colour_layer(tmp_path / "map.tif", tiles.Placement())
        assert isinstance(layer.pixels, np.memmap) and layer.planar
        assert (layer.width, layer.height) == (16, 8)
        assert np.array_equal(layer.rows(0, 8), np.moveaxis(planes, 0, -1))

    def test_grey_band_is_mapped_and_read_as_colour(self, tmp_path):
        """A greyscale mosaic of a whole planet must not be decoded to RGB at
        once: Mercury's is 4 GiB as stored and 13 GiB as RGB."""
        grey = np.arange(8 * 16, dtype=np.uint8).reshape(8, 16)
        tifffile.imwrite(tmp_path / "map.tif", grey)
        layer = tiles.open_colour_layer(tmp_path / "map.tif", tiles.Placement())
        assert isinstance(layer.pixels, np.memmap) and layer.grey
        band = layer.rows(2, 5)
        assert band.shape == (3, 16, 3)
        assert all(np.array_equal(band[..., c], grey[2:5]) for c in range(3))

    def test_source_too_large_to_decode_whole_is_refused(self, tmp_path, monkeypatch):
        Image.new("RGB", (64, 32)).save(tmp_path / "map.png")
        monkeypatch.setattr(config, "TILE_MAX_LOAD_BYTES", 1000)
        with pytest.raises(ValueError, match="uncompressed TIFF"):
            tiles.open_colour_layer(tmp_path / "map.png", tiles.Placement())

    def test_compressed_colour_is_read_whole(self, tmp_path):
        Image.new("RGB", (16, 8), color=(1, 2, 3)).save(tmp_path / "map.png")
        layer = tiles.open_colour_layer(tmp_path / "map.png", tiles.Placement())
        assert not isinstance(layer.pixels, np.memmap)
        assert layer.rows(0, 8)[0, 0].tolist() == [1, 2, 3]


class TestHeightCoding:
    """Sixteen-bit heights split over the red and green bytes."""

    def test_step_is_the_source_quantum_when_the_range_fits(self):
        coding = tiles.HeightCoding.for_range(-8.2, 21.2, 1e-3, None)
        assert coding.step_km == 1e-3
        assert coding.bias_km == -8.2

    def test_float_source_spreads_sixteen_bits_over_the_range(self):
        coding = tiles.HeightCoding.for_range(0.0, 6.5535, 0.0, None)
        assert coding.step_km == pytest.approx(1e-4)

    def test_range_too_wide_for_the_quantum_coarsens_the_step(self):
        coding = tiles.HeightCoding.for_range(0.0, 131.07, 1e-3, None)
        assert coding.step_km == pytest.approx(2e-3)

    def test_gaps_sink_to_the_lowest_terrain_unless_told(self):
        assert tiles.HeightCoding.for_range(-3.0, 4.0, 1e-3, None).fill_km == -3.0
        assert tiles.HeightCoding.for_range(-3.0, 4.0, 1e-3, 0.0).fill_km == 0.0


class TestHeightPyramid:
    """Lossless height tiles that decode back to the source's own values."""

    def test_native_level_reproduces_every_sample(self, tmp_path):
        metres = _terrain(4 * TILE, 2 * TILE)
        layer = _height_layer(metres)
        lo, hi, gaps = tiles.height_range_km([layer])
        coding = tiles.HeightCoding.for_range(lo, hi, 1e-3, None)
        tiles.PyramidBuilder("test", [layer], tmp_path / "out", 1, coding).build()

        decoded = _decode_km(_stitch(tmp_path / "out", 1), coding)
        assert gaps == 0
        assert np.abs(decoded * 1000 - metres).max() < 0.01

    def test_coarser_level_is_the_mean_of_four(self, tmp_path):
        metres = _terrain(4 * TILE, 2 * TILE)
        layer = _height_layer(metres)
        coding = tiles.HeightCoding.for_range(-8.0, 21.0, 1e-3, None)
        tiles.PyramidBuilder("test", [layer], tmp_path / "out", 1, coding).build()

        decoded = _decode_km(_stitch(tmp_path / "out", 0), coding) * 1000
        mean = metres.reshape(TILE, 2, 2 * TILE, 2).mean(axis=(1, 3))
        assert np.abs(decoded - mean).max() <= 0.51

    def test_gaps_take_the_fill_height(self, tmp_path):
        metres = np.zeros((2 * TILE, 4 * TILE), dtype=np.int16)
        metres[:, 2 * TILE :] = 1000
        metres[:, :TILE] = -32768
        layer = _height_layer(metres)
        lo, hi, gaps = tiles.height_range_km([layer])
        coding = tiles.HeightCoding.for_range(lo, hi, 1e-3, 0.75)
        tiles.PyramidBuilder("test", [layer], tmp_path / "out", 1, coding).build()

        # Four columns on each side are thin enough to interpolate.
        assert (lo, hi, gaps) == (0.0, 1.0, (TILE - 8) * 2 * TILE)
        decoded = _decode_km(_stitch(tmp_path / "out", 1), coding)
        assert decoded[0, TILE // 2] == pytest.approx(0.75)
        assert decoded[0, 3 * TILE // 2] == 0.0

    def test_dead_edge_column_does_not_cut_a_trench(self, tmp_path):
        """Global DEMs often ship a blank last column, which sits on the
        ±180° seam."""
        metres = np.full((2 * TILE, 4 * TILE), 500, dtype=np.int16)
        metres[:, -1] = -32768
        layer = _height_layer(metres)
        lo, hi, gaps = tiles.height_range_km([layer])
        coding = tiles.HeightCoding.for_range(-1.0, 1.0, 1e-3, None)
        tiles.PyramidBuilder("test", [layer], tmp_path / "out", 1, coding).build()

        assert gaps == 0
        decoded = _decode_km(_stitch(tmp_path / "out", 1), coding)
        assert np.abs(decoded - 0.5).max() < 1e-6

    def test_inset_replaces_the_base_inside_its_band(self, tmp_path):
        base = _height_layer(np.zeros((2 * TILE, 4 * TILE), dtype=np.int16))
        inset = _height_layer(
            np.full((2 * TILE, 8 * TILE), 1000, dtype=np.int16),
            lat_top=45.0,
            lat_bottom=-45.0,
        )
        coding = tiles.HeightCoding.for_range(0.0, 1.0, 1e-3, None)
        tiles.PyramidBuilder("test", [base, inset], tmp_path / "out", 1, coding).build()

        column = _decode_km(_stitch(tmp_path / "out", 1), coding)[:, 0]
        assert column[0] == 0.0 and column[-1] == 0.0
        assert column[TILE] == pytest.approx(1.0)
        # It only ever rises towards the equator: no step back at the join.
        assert (np.diff(column[: TILE + 1]) >= 0).all()

    def test_wider_inset_listed_last_hides_a_narrower_one(self, tmp_path):
        base = _height_layer(np.zeros((4 * TILE, 8 * TILE), dtype=np.int16))
        narrow = _height_layer(
            np.full((TILE, 8 * TILE), 1000, dtype=np.int16),
            lat_top=20.0,
            lat_bottom=-20.0,
        )
        wide = _height_layer(
            np.full((4 * TILE, 8 * TILE), 2000, dtype=np.int16),
            lat_top=80.0,
            lat_bottom=-80.0,
        )
        coding = tiles.HeightCoding.for_range(0.0, 2.0, 1e-3, None)
        layers = [base, narrow, wide]
        tiles.PyramidBuilder("test", layers, tmp_path / "out", 2, coding).build()

        column = _decode_km(_stitch(tmp_path / "out", 2), coding)[:, 0]
        assert column[0] == 0.0
        # 34° and 6° north: beside the narrow inset, and under both.
        assert column[5 * TILE // 4] == pytest.approx(2.0)
        assert column[15 * TILE // 8] == pytest.approx(2.0)

    def test_gap_in_an_inset_shows_the_base(self, tmp_path):
        base = _height_layer(np.full((4 * TILE, 8 * TILE), 500, dtype=np.int16))
        raised = np.full((4 * TILE, 8 * TILE), 1000, dtype=np.int16)
        raised[:, : 4 * TILE] = -32768
        inset = _height_layer(raised, lat_top=60.0, lat_bottom=-60.0)
        coding = tiles.HeightCoding.for_range(0.0, 1.0, 1e-3, None)
        tiles.PyramidBuilder("test", [base, inset], tmp_path / "out", 2, coding).build()

        km = _decode_km(_stitch(tmp_path / "out", 2), coding)
        # 50° north, where the inset only reaches part of the tile row, and
        # 20° north, where it covers the whole row.
        for row in (7 * TILE // 8, 25 * TILE // 16):
            assert km[row, 6 * TILE] == pytest.approx(1.0)
            assert km[row, 2 * TILE] == pytest.approx(0.5)

    def test_inset_fades_in_over_the_feather(self):
        inset = tiles.Layer(np.zeros((4, 8)), tiles.Placement(60.0, -60.0))
        weights = inset.weights(np.array([61.0, 60.0, 59.5, 59.0, 0.0]))
        assert weights.tolist() == [0.0, 0.0, 0.5, 1.0]

    def test_inset_touching_a_pole_does_not_fade_there(self):
        cap = tiles.Layer(np.zeros((4, 8)), tiles.Placement(90.0, 60.0))
        assert cap.weights(np.array([90.0, 89.9, 61.0])).tolist() == [1.0, 1.0]


def _write_pds_image(path, values: np.ndarray, **label) -> None:
    """A PDS3 image with an attached label, as LROC ships them."""
    lines, samples = values.shape
    record = samples * 4
    fields = {
        "RECORD_BYTES": record,
        "LINES": lines,
        "LINE_SAMPLES": samples,
        "SAMPLE_TYPE": "PC_REAL",
        "SAMPLE_BITS": 32,
        **label,
    }
    body = "".join(f"{key} = {value}\r\n" for key, value in fields.items())
    # The label fills whole records, and names the record the image starts at.
    records = -(-(len(body) + 40) // record)
    text = f"LABEL_RECORDS = {records}\r\n^IMAGE = {records + 1}\r\n{body}END\r\n"
    header = text.encode().ljust(records * record, b" ")
    path.write_bytes(header + values.astype("<f4").tobytes())


class TestLayerWindows:
    """A window of the output grid reads only the pixels under it, and wraps
    around the globe like the whole row does."""

    @staticmethod
    def _layer(**placement) -> tiles.Layer:
        rng = np.random.default_rng(seed=3)
        pixels = rng.integers(0, 255, size=(2 * TILE, 8 * TILE, 3), dtype=np.uint8)
        return tiles.Layer(pixels, tiles.Placement(**placement))

    @pytest.mark.parametrize(
        "placement",
        [
            {},
            {"lon_at_left_deg": 0.0},
            {"west_positive": True, "lon_at_left_deg": 90.0},
        ],
    )
    def test_window_equals_the_same_columns_of_the_whole_row(self, placement):
        layer = self._layer(**placement)
        edges = 90.0 - np.arange(TILE + 1) * (180.0 / (2 * TILE))
        whole = layer.resample(8 * TILE, edges)
        for x0, x1 in ((0, 2 * TILE), (3 * TILE, 5 * TILE), (6 * TILE, 8 * TILE)):
            assert np.array_equal(
                layer.window(8 * TILE, edges, x0, x1), whole[:, x0:x1]
            )

    def test_columns_past_the_edge_wrap_around(self):
        layer = self._layer()
        edges = 90.0 - np.arange(TILE + 1) * (180.0 / (2 * TILE))
        whole = layer.resample(8 * TILE, edges)
        wrapped = layer.window(8 * TILE, edges, -TILE, TILE)
        assert np.array_equal(wrapped, np.roll(whole, TILE, axis=1)[:, : 2 * TILE])

    def test_part_of_a_raster_with_gaps_reads_like_the_whole(self):
        """Thin gaps are filled from their neighbours, also from the ones
        outside the part. A wide gap stays a gap at the part's edge."""
        metres = _terrain(8 * TILE, 2 * TILE)
        metres[:, 3 * TILE - 2 : 3 * TILE + 3] = -32768
        metres[TILE - 3 : TILE + 2, : 2 * TILE] = -32768
        metres[:, 5 * TILE : 7 * TILE] = -32768
        layer = _height_layer(metres)
        whole = layer.rows(0, 2 * TILE)
        assert np.isnan(whole).sum() == 2 * TILE * (2 * TILE - 8)
        for y0, y1, c0, c1 in (
            (0, TILE, 0, 3 * TILE),
            (TILE, 2 * TILE, 3 * TILE, 6 * TILE),
            (TILE // 2, TILE, 6 * TILE, 8 * TILE),
        ):
            part = layer.read(y0, y1, c0, c1)
            assert np.array_equal(part, whole[y0:y1, c0:c1], equal_nan=True)

    def test_window_with_an_edge_inside_a_gap_keeps_the_gap(self):
        """The far side of the window is not the ground beside its edge."""
        metres = _terrain(8 * TILE, 2 * TILE)
        metres[:, 2 * TILE : 6 * TILE] = -32768
        layer = _height_layer(metres)
        edges = 90.0 - np.arange(TILE + 1) * (180.0 / (2 * TILE))
        whole = layer.resample(8 * TILE, edges)
        part = layer.window(8 * TILE, edges, 3 * TILE, 7 * TILE)
        assert np.isnan(part[:, 0]).all()
        assert np.array_equal(part, whole[:, 3 * TILE : 7 * TILE], equal_nan=True)

    def test_read_matches_flip_then_shift_of_the_stored_rows(self):
        layer = self._layer(west_positive=True, lon_at_left_deg=90.0)
        stored = np.asarray(layer.pixels)
        expected = np.roll(stored[:, ::-1], 6 * TILE, axis=1)
        assert np.array_equal(layer.rows(0, 2 * TILE), expected)


class TestMosaic:
    """Adjoining rasters read as one."""

    def test_rows_span_tiles_in_both_directions(self):
        whole = np.arange(8 * 12, dtype=np.float32).reshape(8, 12)
        grid = [[whole[:4, :6], whole[:4, 6:]], [whole[4:, :6], whole[4:, 6:]]]
        mosaic = tiles.Mosaic(grid)
        assert mosaic.shape == (8, 12)
        assert np.array_equal(mosaic.read(2, 7, 0, 12), whole[2:7])
        assert np.array_equal(mosaic.read(3, 5, 4, 9), whole[3:5, 4:9])

    def test_file_is_opened_only_when_a_read_touches_it(self, tmp_path):
        """A mosaic of thousands of files must not map them all up front."""
        whole = np.arange(8 * 12, dtype=np.float32).reshape(8, 12) + 1
        _write_pds_image(tmp_path / "west.IMG", whole[:, :6])
        mosaic = tiles.Mosaic([[tmp_path / "west.IMG", tmp_path / "absent.IMG"]])
        assert np.array_equal(mosaic.read(1, 3, 2, 6), whole[1:3, 2:6])
        with pytest.raises(FileNotFoundError):
            mosaic.read(1, 3, 2, 8)

    def test_only_the_last_files_read_stay_mapped(self, tmp_path, monkeypatch):
        """Every file of Mars' mosaic held mapped outgrows the build's memory
        in page tables alone."""
        monkeypatch.setattr(tiles, "_MOSAIC_OPEN", 2)
        whole = np.arange(4 * 24, dtype=np.float32).reshape(4, 24) + 1
        paths = [tmp_path / f"{i}.IMG" for i in range(4)]
        for i, path in enumerate(paths):
            _write_pds_image(path, whole[:, i * 6 : (i + 1) * 6])
        mosaic = tiles.Mosaic([paths])
        assert np.array_equal(mosaic.read(0, 4, 0, 24), whole)
        assert list(mosaic._mapped) == [(0, 2), (0, 3)]
        # A file that was let go is mapped again when a read comes back to it.
        assert np.array_equal(mosaic.read(1, 3, 2, 9), whole[1:3, 2:9])
        assert list(mosaic._mapped) == [(0, 0), (0, 1)]

    def test_tiles_of_different_sizes_are_refused(self):
        with pytest.raises(ValueError):
            tiles.Mosaic([[np.zeros((4, 6)), np.zeros((4, 5))]])


class TestBrightness:
    """A sharper greyscale map adds detail to a colour base without moving
    its tone."""

    @staticmethod
    def _sharpened(brightness: np.ndarray, colour=(120, 110, 100)) -> np.ndarray:
        base = tiles.Layer(
            np.full((2 * TILE, 4 * TILE, 3), colour, dtype=np.uint8), tiles.Placement()
        )
        fine = tiles.Layer(brightness, tiles.Placement(), to_values=tiles._brightness)
        builder = tiles.PyramidBuilder("test", [base], Path(), 3, brightness=[fine])
        band = np.full((TILE, 16 * TILE, 3), colour, dtype=np.uint8)
        return builder._sharpen(band, 0, TILE)

    @staticmethod
    def _stripes() -> np.ndarray:
        """Bright and dark columns four output pixels wide."""
        columns = np.where(np.arange(16 * TILE) // 4 % 2, 0.2, 0.1)
        return np.tile(columns, (8 * TILE, 1)).astype(np.float32)

    def test_detail_finer_than_the_base_comes_through(self):
        out = self._sharpened(self._stripes())
        assert out[4, 6, 0] > 128 and out[4, 2, 0] < 112

    def test_tone_and_colour_stay_the_bases(self):
        out = self._sharpened(self._stripes()).astype(float)
        linear = tiles._SRGB_TO_LINEAR[np.rint(out).astype(np.uint8)]
        assert linear[..., 0].mean() == pytest.approx(
            tiles._SRGB_TO_LINEAR[120], rel=0.03
        )
        # The same factor on every channel.
        assert (out[..., 0] > out[..., 1]).all() and (out[..., 1] > out[..., 2]).all()

    def test_uniform_brightness_changes_nothing(self):
        out = self._sharpened(np.full((8 * TILE, 16 * TILE), 0.3, dtype=np.float32))
        assert np.abs(out.astype(int) - (120, 110, 100)).max() <= 1

    def test_unobserved_ground_keeps_the_base(self):
        brightness = self._stripes()
        brightness[:, : 8 * TILE] = 0.0
        out = self._sharpened(brightness)
        # A few pixels in from the gap's edges, which are interpolated across.
        inside = out[:, TILE : 7 * TILE].astype(int)
        assert np.abs(inside - (120, 110, 100)).max() <= 1
        assert out[4, 12 * TILE + 6, 0] > 128

    def test_gap_in_a_later_layer_keeps_the_layer_under_it(self):
        base = tiles.Layer(
            np.zeros((2 * TILE, 4 * TILE, 3), dtype=np.uint8), tiles.Placement()
        )
        under = np.full((8 * TILE, 16 * TILE), 0.2, dtype=np.float32)
        over = np.full((8 * TILE, 16 * TILE), 0.4, dtype=np.float32)
        over[:, : 8 * TILE] = 0.0
        layers = [
            tiles.Layer(values, tiles.Placement(), to_values=tiles._brightness)
            for values in (under, over)
        ]
        builder = tiles.PyramidBuilder("test", [base], Path(), 3, brightness=layers)
        got = builder._brightness_window(0, TILE, 0, 16 * TILE)
        assert got[:, 4 * TILE] == pytest.approx(tiles._brightness(under[:1, :1])[0, 0])
        assert got[:, 12 * TILE] == pytest.approx(
            tiles._brightness(over[:1, -1:])[0, 0]
        )

    def test_grid_of_tiles_and_a_single_file_open_alike(self, tmp_path):
        whole = self._stripes()[: 2 * TILE, : 4 * TILE]
        _write_pds_image(tmp_path / "west.IMG", whole[:, : 2 * TILE])
        _write_pds_image(tmp_path / "east.IMG", whole[:, 2 * TILE :])
        layer = tiles.open_brightness_layer(
            [[tmp_path / "west.IMG", tmp_path / "east.IMG"]], tiles.Placement()
        )
        assert layer.dimensions == [4 * TILE, 2 * TILE]
        assert np.array_equal(layer.rows(0, 2 * TILE), whole)


class TestBlockBuild:
    """A level too wide to hold a tile row of is built in blocks, and gives
    the tiles the row-by-row build gives."""

    LEVEL = 5

    @staticmethod
    def _force_blocks(monkeypatch):
        monkeypatch.setattr(tiles, "MAX_BAND_LEVEL", 0)

    def _both(self, tmp_path, monkeypatch, make):
        """One pyramid built by rows, the same one by blocks."""
        make(tmp_path / "rows").build()
        self._force_blocks(monkeypatch)
        stats = make(tmp_path / "blocks").build()
        return stats

    def _same_tiles(self, tmp_path, exact: bool) -> None:
        for level in range(self.LEVEL + 1):
            rows = _stitch(tmp_path / "rows", level).astype(int)
            blocks = _stitch(tmp_path / "blocks", level).astype(int)
            assert np.abs(rows - blocks).max() <= (0 if exact else 2), level

    def test_height_tiles_are_identical(self, tmp_path, monkeypatch):
        width = tiles.level_width(self.LEVEL)
        layer = _height_layer(_terrain(width, width // 2))
        coding = tiles.HeightCoding.for_range(-8.0, 21.0, 1e-3, None)
        stats = self._both(
            tmp_path,
            monkeypatch,
            lambda out: tiles.PyramidBuilder("t", [layer], out, self.LEVEL, coding),
        )
        assert stats.tiles == [2 * 4**z for z in range(self.LEVEL + 1)]
        self._same_tiles(tmp_path, exact=True)

    def test_sharpened_colour_tiles_match(self, tmp_path, monkeypatch):
        width = tiles.level_width(self.LEVEL)
        rng = np.random.default_rng(seed=5)
        base = tiles.Layer(
            rng.integers(60, 200, size=(width // 8, width // 4, 3), dtype=np.uint8),
            tiles.Placement(),
        )
        fine = tiles.Layer(
            rng.uniform(0.05, 0.3, size=(width // 2, width)).astype(np.float32),
            tiles.Placement(lat_top=60.0, lat_bottom=-60.0),
            to_values=tiles._brightness,
        )
        self._both(
            tmp_path,
            monkeypatch,
            lambda out: tiles.PyramidBuilder(
                "t", [base], out, self.LEVEL, brightness=[fine]
            ),
        )
        self._same_tiles(tmp_path, exact=False)

    def test_wide_blend_on_a_reduced_copy_matches_the_direct_blur(
        self, tmp_path, monkeypatch
    ):
        """A blur of hundreds of pixels runs on a reduced copy; the result
        must be the one the full-size blur gives."""
        self._force_blocks(monkeypatch)
        width = tiles.level_width(self.LEVEL)
        side = TILE << tiles.BLOCK_LEVELS
        rng = np.random.default_rng(seed=9)
        base = tiles.Layer(
            np.full((TILE, 2 * TILE, 3), 120, dtype=np.uint8), tiles.Placement()
        )
        # Detail on top of a slow swell, so both scales are in play.
        swell = 0.2 + 0.05 * np.sin(np.arange(width) / 40.0)[None, :]
        brightness = (swell + rng.uniform(-0.02, 0.02, (width // 2, width))).astype(
            np.float32
        )
        fine = tiles.Layer(brightness, tiles.Placement(), to_values=tiles._brightness)
        builder = tiles.PyramidBuilder(
            "t", [base], Path(), self.LEVEL, brightness=[fine]
        )
        colour = np.full((side, side, 3), 120, dtype=np.uint8)
        sigma = builder.sharpen_sigma * width / base.width
        assert sigma > 2 * tiles._REDUCED_SIGMA

        got = builder._sharpen_block(colour, side, 2 * side, side, 2 * side)

        margin = int(4 * sigma + 0.5) + 1
        window = builder._brightness_window(
            side - margin, 2 * side + margin, side - margin, 2 * side + margin
        )
        ratio = tiles.detail_ratio(window, sigma)[margin:-margin, margin:-margin]
        expected = tiles.apply_detail(colour, ratio)
        assert np.abs(got.astype(int) - expected.astype(int)).mean() < 0.6
        assert got.std() > 3

    def test_stopped_build_resumes_and_finishes_the_same(self, tmp_path, monkeypatch):
        self._force_blocks(monkeypatch)
        width = tiles.level_width(self.LEVEL)
        layer = _height_layer(_terrain(width, width // 2))
        coding = tiles.HeightCoding.for_range(-8.0, 21.0, 1e-3, None)

        def make(out):
            return tiles.PyramidBuilder(
                "t", [layer], out, self.LEVEL, coding, checkpoint="v1"
            )

        make(tmp_path / "rows").build()

        class Stop(Exception):
            pass

        stopped = make(tmp_path / "blocks")
        save = stopped._save

        def save_then_stop(next_row: int) -> None:
            save(next_row)
            if next_row == 1:
                raise Stop

        monkeypatch.setattr(stopped, "_save", save_then_stop)
        with pytest.raises(Stop):
            stopped.build()
        assert tiles.resumable(tmp_path / "blocks", "v1")
        assert not tiles.resumable(tmp_path / "blocks", "v2")

        resumed = make(tmp_path / "blocks")
        stats = resumed.build()

        assert stats.tiles == [2 * 4**z for z in range(self.LEVEL + 1)]
        self._same_tiles(tmp_path, exact=True)
        # The save stays until the caller has put the output in place.
        assert tiles.resumable(tmp_path / "blocks", "v1")
        tiles.clear_state(tmp_path / "blocks")
        assert not (tmp_path / "blocks" / ".build").exists()


class TestPolarLayer:
    """A polar stereographic cap sampled into rows of latitude."""

    SIDE = 201
    # Pixels from the pole to latitude 60°.
    REACH_60 = 100.0

    def _layer(self, tmp_path, north: bool) -> tiles.PolarLayer:
        """An image whose value is ``2 + cos(longitude)`` everywhere."""
        centre = (self.SIDE - 1) / 2
        line, sample = np.mgrid[0 : self.SIDE, 0 : self.SIDE] - centre
        towards_zero = line if north else -line
        values = 2.0 + np.cos(np.arctan2(sample, towards_zero))
        scale = 1000.0
        radius_km = self.REACH_60 / (2 * np.tan(np.radians(15))) * scale / 1000
        _write_pds_image(
            tmp_path / "cap.IMG",
            values,
            MAP_PROJECTION_TYPE='"POLAR STEREOGRAPHIC"',
            MAP_SCALE=f"{scale} <METERS/PIXEL>",
            A_AXIS_RADIUS=f"{radius_km} <KM>",
            CENTER_LONGITUDE="0.0 <DEG>",
            LINE_PROJECTION_OFFSET=f"{self.SIDE / 2} <PIXEL>",
            SAMPLE_PROJECTION_OFFSET=f"{self.SIDE / 2} <PIXEL>",
        )
        lat_range = (60.0, 90.0) if north else (-90.0, -60.0)
        placement = tiles.Placement(lat_top=lat_range[1], lat_bottom=lat_range[0])
        return tiles.open_polar_brightness_layer(tmp_path / "cap.IMG", placement)

    @pytest.mark.parametrize("north", [True, False])
    def test_rows_follow_longitude_from_180_west(self, tmp_path, north):
        layer = self._layer(tmp_path, north)
        edges = np.array([75.0, 70.0, 65.0]) * (1 if north else -1)
        rows = layer.resample(72, np.sort(edges)[::-1])
        lons = np.radians(-180.0 + (np.arange(72) + 0.5) * 5.0)
        assert np.abs(rows - (2.0 + np.cos(lons))).max() < 0.02

    def test_reach_matches_the_stereographic_projection(self, tmp_path):
        layer = self._layer(tmp_path, north=True)
        assert layer.dimensions == [self.SIDE, self.SIDE]
        assert layer.pole == (100.0, 100.0)
        # Latitude 60° lands on the image's edge, 100 px from the pole.
        edge = layer.resample(4, np.array([60.0001, 59.9999]))
        assert np.isfinite(edge).all()

    def test_release_drops_the_image_read_into_memory(self, tmp_path):
        layer = self._layer(tmp_path, north=True)
        layer.resample(4, np.array([80.0, 79.0]))
        assert layer._values is not None
        layer.release()
        assert layer._values is None

    def test_equirectangular_label_is_refused(self, tmp_path):
        _write_pds_image(
            tmp_path / "flat.IMG",
            np.ones((4, 8)),
            MAP_PROJECTION_TYPE="EQUIRECTANGULAR",
        )
        with pytest.raises(ValueError):
            tiles.open_polar_brightness_layer(tmp_path / "flat.IMG", tiles.Placement())


def _globe(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """A height in metres that is smooth over the whole globe, poles included."""
    lat, lon = np.radians(lats), np.radians(lons)
    return 3000.0 * np.sin(lat) + 2000.0 * np.cos(lat) * np.cos(lon - 0.7)


def _cap_lat_lon(cap: tiles.Cap) -> tuple[np.ndarray, np.ndarray]:
    """Latitude and east longitude of every pixel of ``cap``, from its
    definition: the prime meridian to the right, east counter-clockwise seen
    from above the north pole."""
    x, y = cap.plane(0, cap.size, 0, cap.size)
    lats = cap.latitudes(0, cap.size, 0, cap.size)
    lons = np.degrees(np.arctan2(y[:, None], x[None, :]))
    return lats, lons if cap.north else -lons


def _stitch_cap(root, level: int) -> np.ndarray:
    side = 1 << (level - 1)
    rows = []
    for y in range(side):
        row = [
            np.asarray(Image.open(root / str(level) / str(x) / f"{y}.webp"))
            for x in range(side)
        ]
        rows.append(np.concatenate(row, axis=1))
    return np.concatenate(rows, axis=0)


class TestCap:
    """A polar cap is a stereographic square around its pole."""

    @pytest.mark.parametrize("north", [True, False])
    def test_sides_touch_latitude_45(self, north):
        cap = tiles.Cap(north, 6)
        lats = np.abs(cap.latitudes(0, cap.size, 0, cap.size))
        middle = cap.size // 2
        assert lats[middle, middle] == pytest.approx(90.0, abs=0.2)
        for edge in (lats[0, middle], lats[-1, middle], lats[middle, 0]):
            assert edge == pytest.approx(45.0, abs=0.2)
        # The corners are further from the pole than the sides.
        assert lats[0, 0] < 30.0

    def test_level_one_is_a_single_tile(self):
        assert tiles.Cap(True, 1).size == TILE
        assert tiles.Cap(True, 4).size == 8 * TILE

    @pytest.mark.parametrize("north", [True, False])
    @pytest.mark.parametrize("width", [16 * TILE, 64 * TILE])
    def test_equirectangular_layer_lands_where_the_cap_says(self, north, width):
        """Sources coarser and finer than the cap, read through its patches."""
        edges = 90.0 - np.arange(width // 2 + 1) * (360.0 / width)
        lats = (edges[:-1] + edges[1:]) / 2
        lons = -180.0 + (np.arange(width) + 0.5) * (360.0 / width)
        metres = _globe(lats[:, None], lons[None, :]).astype(np.float32)
        raster = HeightRaster(metres, scale=1.0, offset=0.0, unit_km=1e-3, nodata=None)
        layer = tiles.height_layer(raster, tiles.Placement())
        cap = tiles.Cap(north, 4)
        got = layer.cap(cap, 0, cap.size, 0, cap.size)
        expected = _globe(*_cap_lat_lon(cap)) / 1000
        assert got.shape == (cap.size, cap.size)
        assert np.abs(got - expected).max() < 0.02

    def test_detail_finer_than_the_cap_is_averaged_out(self):
        """A raster four times as fine as the cap, in stripes two of its
        pixels wide: nothing of them fits in the cap."""
        width = 128 * TILE
        stripes = (np.arange(width // 2)[:, None] // 2 % 2 * 1000.0).astype(np.float32)
        raster = HeightRaster(
            np.broadcast_to(stripes, (width // 2, width)),
            scale=1.0,
            offset=0.0,
            unit_km=1e-3,
            nodata=None,
        )
        layer = tiles.height_layer(raster, tiles.Placement())
        cap = tiles.Cap(True, 4)
        got = layer.cap(cap, 0, cap.size, 0, cap.size)
        assert abs(float(got.mean()) - 0.5) < 0.01
        assert float(got.std()) < 0.05

    def test_part_of_a_cap_equals_the_same_pixels_of_the_whole(self):
        rng = np.random.default_rng(seed=5)
        pixels = rng.integers(0, 255, size=(16 * TILE, 32 * TILE, 3), dtype=np.uint8)
        layer = tiles.Layer(pixels, tiles.Placement())
        cap = tiles.Cap(True, 4)
        whole = layer.cap(cap, 0, cap.size, 0, cap.size)
        assert whole.dtype == np.uint8 and whole.shape == (cap.size, cap.size, 3)
        y0, y1, x0, x1 = TILE, 3 * TILE, 5 * TILE, 8 * TILE
        part = layer.cap(cap, y0, y1, x0, x1).astype(int)
        # A part picks its own patches, so the two differ by rounding.
        assert np.abs(part - whole[y0:y1, x0:x1]).max() <= 1

    @pytest.mark.parametrize("north", [True, False])
    def test_polar_image_lands_where_the_cap_says(self, tmp_path, north):
        """An image in the cap's own projection, turned and scaled into it."""
        side, scale, radius_m = 401, 1000.0, 300_000.0
        centre = (side - 1) / 2
        line, sample = np.mgrid[0:side, 0:side] - centre
        towards_zero = line if north else -line
        centre_lon = 30.0
        lons = np.degrees(np.arctan2(sample, towards_zero)) + centre_lon
        colat = 2 * np.degrees(
            np.arctan(np.hypot(line, sample) * scale / (2 * radius_m))
        )
        lats = 90.0 - colat if north else colat - 90.0
        _write_pds_image(
            tmp_path / "cap.IMG",
            # Brightness: a sample that is not positive is a gap.
            _globe(lats, lons) + 10_000.0,
            MAP_PROJECTION_TYPE='"POLAR STEREOGRAPHIC"',
            MAP_SCALE=f"{scale} <METERS/PIXEL>",
            A_AXIS_RADIUS=f"{radius_m / 1000} <KM>",
            CENTER_LONGITUDE=f"{centre_lon} <DEG>",
            LINE_PROJECTION_OFFSET=f"{side / 2} <PIXEL>",
            SAMPLE_PROJECTION_OFFSET=f"{side / 2} <PIXEL>",
        )
        placement = tiles.Placement(
            lat_top=90.0 if north else -60.0, lat_bottom=60.0 if north else -90.0
        )
        layer = tiles.open_polar_brightness_layer(tmp_path / "cap.IMG", placement)
        cap = tiles.Cap(north, 4)
        got = layer.cap(cap, 0, cap.size, 0, cap.size)
        cap_lats, cap_lons = _cap_lat_lon(cap)
        inside = np.abs(cap_lats) > 62.0
        expected = _globe(cap_lats, cap_lons) + 10_000.0
        assert np.abs(got - expected)[inside].max() < 5.0


class TestCapPyramid:
    """Each pole's cap is tiled from the finest level down to one tile."""

    @staticmethod
    def _layer(width: int = 32 * TILE) -> tiles.Layer:
        edges = 90.0 - np.arange(width // 2 + 1) * (360.0 / width)
        lats = (edges[:-1] + edges[1:]) / 2
        lons = -180.0 + (np.arange(width) + 0.5) * (360.0 / width)
        metres = np.rint(_globe(lats[:, None], lons[None, :])).astype(np.int16)
        return _height_layer(metres)

    def test_every_level_down_to_one_tile_is_written(self, tmp_path):
        coding = tiles.HeightCoding.for_range(-5.0, 5.0, 0.001, None)
        stats = tiles.CapBuilder(
            "test", True, [self._layer()], tmp_path / "out", 3, coding
        ).build()
        assert stats.tiles == [0, 1, 4, 16]
        assert (tmp_path / "out" / "1" / "0" / "0.webp").exists()
        assert not (tmp_path / "out" / "0").exists()

    def test_heights_follow_the_ground_and_coarser_levels_average(self, tmp_path):
        coding = tiles.HeightCoding.for_range(-5.0, 5.0, 0.001, None)
        cap = tiles.Cap(False, 3)
        tiles.CapBuilder(
            "test", False, [self._layer()], tmp_path / "out", 3, coding
        ).build()
        fine = _decode_km(_stitch_cap(tmp_path / "out", 3), coding)
        assert np.abs(fine - _globe(*_cap_lat_lon(cap)) / 1000).max() < 0.02
        coarse = _decode_km(_stitch_cap(tmp_path / "out", 2), coding)
        mean = fine.reshape(2 * TILE, 2, 2 * TILE, 2).mean(axis=(1, 3))
        assert np.abs(coarse - mean).max() <= coding.step_km

    def test_inset_replaces_the_base_inside_its_band(self, tmp_path):
        flat = _height_layer(np.zeros((4 * TILE, 8 * TILE), dtype=np.int16))
        raised = _height_layer(
            np.full((TILE, 8 * TILE), 1000, dtype=np.int16),
            lat_top=90.0,
            lat_bottom=45.0,
        )
        coding = tiles.HeightCoding.for_range(0.0, 1.0, 0.001, None)
        cap = tiles.Cap(True, 3)
        tiles.CapBuilder(
            "test", True, [flat, raised], tmp_path / "out", 3, coding
        ).build()
        km = _decode_km(_stitch_cap(tmp_path / "out", 3), coding)
        lats = cap.latitudes(0, cap.size, 0, cap.size)
        assert np.allclose(km[lats > 47.0], 1.0, atol=0.002)
        assert np.allclose(km[lats < 45.0], 0.0, atol=0.002)

    def test_gap_in_an_inset_shows_the_base(self, tmp_path):
        flat = _height_layer(np.full((4 * TILE, 8 * TILE), 500, dtype=np.int16))
        raised = np.full((TILE, 8 * TILE), 1000, dtype=np.int16)
        raised[:, : 4 * TILE] = -32768
        inset = _height_layer(raised, lat_top=90.0, lat_bottom=45.0)
        coding = tiles.HeightCoding.for_range(0.0, 1.0, 0.001, None)
        cap = tiles.Cap(True, 3)
        tiles.CapBuilder(
            "test", True, [flat, inset], tmp_path / "out", 3, coding
        ).build()
        km = _decode_km(_stitch_cap(tmp_path / "out", 3), coding)
        lats, lons = _cap_lat_lon(cap)
        # Clear of the feather, of the gap's edges, and of the pole, where
        # the columns are wide.
        ring = (lats > 47.0) & (lats < 75.0)
        assert np.allclose(km[ring & (np.abs(lons - 90.0) < 70.0)], 1.0, atol=0.002)
        assert np.allclose(km[ring & (np.abs(lons + 90.0) < 70.0)], 0.5, atol=0.002)

    def test_finished_build_is_not_written_again(self, tmp_path):
        coding = tiles.HeightCoding.for_range(-5.0, 5.0, 0.001, None)

        def build() -> tiles.PyramidStats:
            return tiles.CapBuilder(
                "test",
                True,
                [self._layer()],
                tmp_path / "out",
                2,
                coding,
                checkpoint="same",
            ).build()

        first = build()
        tile = tmp_path / "out" / "2" / "0" / "0.webp"
        tile.write_bytes(b"kept")
        assert build().tiles == first.tiles
        assert tile.read_bytes() == b"kept"

    def test_block_build_gives_the_tiles_of_the_row_build(self, tmp_path, monkeypatch):
        coding = tiles.HeightCoding.for_range(-5.0, 5.0, 0.001, None)

        def build(out) -> tiles.PyramidStats:
            return tiles.CapBuilder(
                "test", True, [self._layer(64 * TILE)], out, 5, coding
            ).build()

        build(tmp_path / "rows")
        monkeypatch.setattr(tiles, "MAX_BAND_LEVEL", 0)
        stats = build(tmp_path / "blocks")
        assert stats.tiles == [0, 1, 4, 16, 64, 256]
        for level in range(1, 6):
            rows = _decode_km(_stitch_cap(tmp_path / "rows", level), coding)
            blocks = _decode_km(_stitch_cap(tmp_path / "blocks", level), coding)
            # Each build reads the source in its own patches.
            assert np.abs(rows - blocks).max() <= 1.5 * coding.step_km, level

    def test_brightness_detail_shows_at_the_pole(self, tmp_path):
        """A brightness map as fine as the cap, over a flat colour."""
        colour = np.full((2 * TILE, 4 * TILE, 3), 120, dtype=np.uint8)
        base = tiles.Layer(colour, tiles.Placement())
        rng = np.random.default_rng(seed=11)
        fine = rng.uniform(0.5, 1.5, size=(8 * TILE, 16 * TILE)).astype(np.float32)
        detail = tiles.Layer(fine, tiles.Placement(), to_values=tiles._brightness)
        tiles.CapBuilder(
            "test", True, [base], tmp_path / "out", 3, brightness=[detail]
        ).build()
        sharp = _stitch_cap(tmp_path / "out", 3)[..., 0].astype(float)
        assert sharp.std() > 8.0
        assert abs(sharp.mean() - 120) < 6.0


class TestProcessTiles:
    """The processor builds a pyramid per ``tiles:`` entry and describes it."""

    @staticmethod
    def _processor(monkeypatch, tmp_path, entries: list[dict]) -> TextureProcessor:
        raw = tmp_path / "raw"
        raw.mkdir(exist_ok=True)
        monkeypatch.setattr(config, "TILES_PROCESSED_DIR", tmp_path / "tiles")
        monkeypatch.setattr(config, "TILES_METADATA_DIR", tmp_path / "meta")
        proc = TextureProcessor.__new__(TextureProcessor)
        for entry in entries:
            entry["_source_dir"] = raw
        proc._raw_meta = entries
        return proc

    @staticmethod
    def _colour_entry(tmp_path, **extra) -> dict:
        raw = tmp_path / "raw"
        raw.mkdir(exist_ok=True)
        Image.new("RGB", (4 * TILE, 2 * TILE), color=(200, 90, 40)).save(
            raw / "mars.png"
        )
        return {
            "body": "naif-499",
            "source": "https://example.com/mars",
            "organisation": "USGS",
            "license": "Public domain",
            "attribution": "Test credit",
            "file": "mars.png",
            "type": "cylindrical",
            **extra,
        }

    def test_colour_pyramid_and_its_descriptor(self, tmp_path, monkeypatch):
        proc = self._processor(monkeypatch, tmp_path, [self._colour_entry(tmp_path)])
        proc.process_tiles()

        meta = json.loads(
            (tmp_path / "meta" / "naif-499" / "metadata.json").read_text()
        )
        assert meta["id"] == "naif-499"
        assert (meta["tile_size"], meta["max_level"]) == (TILE, 1)
        assert [level["tiles"] for level in meta["levels"]] == [2, 8]
        assert meta["cap_levels"] == [
            {"level": 1, "tiles": 2, "size_bytes": meta["cap_levels"][0]["size_bytes"]}
        ]
        assert meta["attribution"] == "Test credit"
        assert "displacement_scale_km" not in meta
        out = tmp_path / "tiles" / "naif-499"
        assert (out / "1" / "3" / "1.webp").exists()
        assert (out / "north" / "1" / "0" / "0.webp").exists()
        assert (out / "south" / "1" / "0" / "0.webp").exists()
        assert not list(out.rglob(".build"))

    def test_map_of_one_level_has_no_caps(self, tmp_path, monkeypatch):
        entry = self._colour_entry(tmp_path, tiles_max_level=0)
        proc = self._processor(monkeypatch, tmp_path, [entry])
        proc.process_tiles()

        meta = json.loads(
            (tmp_path / "meta" / "naif-499" / "metadata.json").read_text()
        )
        assert meta["cap_levels"] == []
        assert not (tmp_path / "tiles" / "naif-499" / "north").exists()

    def test_stop_between_parts_keeps_the_parts_already_built(
        self, tmp_path, monkeypatch
    ):
        proc = self._processor(monkeypatch, tmp_path, [self._colour_entry(tmp_path)])
        built = []
        real = tiles.CapBuilder.build

        def fail_in_the_south(self):
            if not self.cap.north and not built:
                built.append("failed")
                raise RuntimeError("stopped")
            return real(self)

        monkeypatch.setattr(tiles.CapBuilder, "build", fail_in_the_south)
        with pytest.raises(RuntimeError):
            proc.process_tiles()
        building = tmp_path / "tiles" / "naif-499.building"
        kept = building / "1" / "0" / "0.webp"
        kept.write_bytes(b"kept")
        proc.process_tiles()
        assert (
            tmp_path / "tiles" / "naif-499" / "1" / "0" / "0.webp"
        ).read_bytes() == b"kept"
        assert (
            tmp_path / "tiles" / "naif-499" / "south" / "1" / "0" / "0.webp"
        ).exists()

    @pytest.mark.parametrize("force", [False, True])
    def test_stop_while_the_old_pyramid_goes_keeps_the_new_one(
        self, tmp_path, monkeypatch, force
    ):
        entry = self._colour_entry(tmp_path)
        proc = self._processor(monkeypatch, tmp_path, [entry])
        proc.process_tiles()
        if not force:
            entry["tiles_max_level"] = 1
        out = tmp_path / "tiles" / "naif-499"
        stopped = []
        real = shutil.rmtree

        def stop_on_the_old_pyramid(path, *args, **kwargs):
            if Path(path) == out and not stopped:
                stopped.append(path)
                raise RuntimeError("stopped")
            real(path, *args, **kwargs)

        monkeypatch.setattr(shutil, "rmtree", stop_on_the_old_pyramid)
        with pytest.raises(RuntimeError):
            proc.process_tiles(force=force)
        building = tmp_path / "tiles" / "naif-499.building"
        (building / "1" / "0" / "0.webp").write_bytes(b"kept")
        proc.process_tiles()
        assert (out / "1" / "0" / "0.webp").read_bytes() == b"kept"
        assert not building.exists()
        assert not list(out.rglob(".build"))

    def test_stop_before_the_descriptor_keeps_the_new_pyramid(
        self, tmp_path, monkeypatch
    ):
        proc = self._processor(monkeypatch, tmp_path, [self._colour_entry(tmp_path)])
        stopped = []
        real = Path.write_text

        def stop_on_the_descriptor(path, *args, **kwargs):
            if path.name == "metadata.json" and not stopped:
                stopped.append(path)
                raise RuntimeError("stopped")
            return real(path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", stop_on_the_descriptor)
        with pytest.raises(RuntimeError):
            proc.process_tiles()
        out = tmp_path / "tiles" / "naif-499"
        (out / "1" / "0" / "0.webp").write_bytes(b"kept")
        proc.process_tiles()
        assert (out / "1" / "0" / "0.webp").read_bytes() == b"kept"
        meta = json.loads(
            (tmp_path / "meta" / "naif-499" / "metadata.json").read_text()
        )
        assert meta["max_level"] == 1
        assert not list(out.rglob(".build"))

    def test_height_pyramid_states_its_scale(self, tmp_path, monkeypatch):
        raw = tmp_path / "raw"
        raw.mkdir()
        metres = _terrain(4 * TILE, 2 * TILE)
        tifffile.imwrite(raw / "dem.tif", metres)
        entry = {
            "body": "naif-499",
            "source": "https://example.com/dem",
            "organisation": "USGS",
            "file": "dem.tif",
            "type": "cylindrical_displacement",
        }
        proc = self._processor(monkeypatch, tmp_path, [entry])
        proc.process_tiles()

        meta_file = tmp_path / "meta" / "naif-499_displacement" / "metadata.json"
        meta = json.loads(meta_file.read_text())
        assert meta["displacement_bias_km"] == pytest.approx(metres.min() / 1000)
        assert meta["displacement_scale_km"] == pytest.approx(65.535)
        assert meta["absolute_radius"] is False

    def test_unchanged_source_is_not_rebuilt(self, tmp_path, monkeypatch):
        proc = self._processor(monkeypatch, tmp_path, [self._colour_entry(tmp_path)])
        proc.process_tiles()
        marker = tmp_path / "tiles" / "naif-499" / "marker"
        marker.touch()
        proc.process_tiles()
        assert marker.exists()

    def test_credit_edit_reaches_the_descriptor_without_a_rebuild(
        self, tmp_path, monkeypatch
    ):
        entry = self._colour_entry(tmp_path)
        proc = self._processor(monkeypatch, tmp_path, [entry])
        proc.process_tiles()
        marker = tmp_path / "tiles" / "naif-499" / "marker"
        marker.touch()
        entry["attribution"] = "New credit"
        proc.process_tiles()

        meta = json.loads(
            (tmp_path / "meta" / "naif-499" / "metadata.json").read_text()
        )
        assert meta["attribution"] == "New credit"
        assert marker.exists()

    def test_changed_level_cap_rebuilds_under_a_new_version(
        self, tmp_path, monkeypatch
    ):
        entry = self._colour_entry(tmp_path)
        proc = self._processor(monkeypatch, tmp_path, [entry])
        proc.process_tiles()
        meta_file = tmp_path / "meta" / "naif-499" / "metadata.json"
        before = json.loads(meta_file.read_text())["version"]
        entry["tiles_max_level"] = 0
        proc.process_tiles()

        after = json.loads(meta_file.read_text())
        assert after["version"] != before
        assert after["max_level"] == 0
        assert not (tmp_path / "tiles" / "naif-499" / "1").exists()

    def test_pyramid_of_a_map_that_is_gone_is_removed(self, tmp_path, monkeypatch):
        entry = self._colour_entry(tmp_path)
        proc = self._processor(monkeypatch, tmp_path, [entry])
        proc.process_tiles()
        entry["skip"] = True
        proc.process_tiles()
        assert not (tmp_path / "tiles" / "naif-499").exists()
        assert not (tmp_path / "meta" / "naif-499").exists()

    def test_stopped_build_of_a_map_still_there_is_kept(self, tmp_path, monkeypatch):
        """A run that cannot continue it, for a missing source, must not drop it."""
        entry = self._colour_entry(tmp_path)
        proc = self._processor(monkeypatch, tmp_path, [entry])
        stopped = tmp_path / "tiles" / "naif-499.building"
        stopped.mkdir(parents=True)
        gone = tmp_path / "tiles" / "naif-301.building"
        gone.mkdir()
        (tmp_path / "raw" / "mars.png").unlink()
        proc.process_tiles()
        assert stopped.exists()
        assert not gone.exists()

    def test_missing_source_keeps_the_pyramid_already_built(
        self, tmp_path, monkeypatch
    ):
        """An unmounted downloads directory must not look like a dropped entry."""
        entry = self._colour_entry(tmp_path)
        proc = self._processor(monkeypatch, tmp_path, [entry])
        proc.process_tiles()
        (tmp_path / "raw" / "mars.png").unlink()
        proc.process_tiles()
        assert (tmp_path / "tiles" / "naif-499").exists()

    def test_second_source_for_one_bundle_is_ignored(
        self, tmp_path, monkeypatch, caplog
    ):
        caplog.set_level("WARNING")
        entries = [
            self._colour_entry(tmp_path, tiles="only"),
            self._colour_entry(tmp_path, tiles="only"),
        ]
        proc = self._processor(monkeypatch, tmp_path, entries)
        proc.process_tiles()
        assert any("already has a tile source" in r.message for r in caplog.records)

    def test_entry_written_for_the_pyramid_replaces_the_tier_entry(
        self, tmp_path, monkeypatch
    ):
        """The tiers keep their map; the pyramid takes the sharper one."""
        tier = self._colour_entry(tmp_path)
        Image.new("RGB", (8 * TILE, 4 * TILE), color=(20, 60, 200)).save(
            tmp_path / "raw" / "sharp.png"
        )
        sharp = {
            **tier,
            "file": "sharp.png",
            "source": "https://example.com/sharp",
            "tiles": "only",
        }
        proc = self._processor(monkeypatch, tmp_path, [tier, sharp])
        proc.process_tiles()

        meta = json.loads(
            (tmp_path / "meta" / "naif-499" / "metadata.json").read_text()
        )
        assert meta["source"] == "https://example.com/sharp"
        assert meta["max_level"] == 2
        assert _stitch(tmp_path / "tiles" / "naif-499", 0)[0, 0, 2] > 150

    def test_monthly_map_gets_a_pyramid_per_frame(self, tmp_path, monkeypatch):
        raw = tmp_path / "raw"
        raw.mkdir()
        for month, red in ((1, 250), (2, 10)):
            Image.new("RGB", (4 * TILE, 2 * TILE), color=(red, 90, 40)).save(
                raw / f"earth_{month:02d}.png"
            )
        entry = {
            "body": "naif-399",
            "source": "https://example.com/earth",
            "organisation": "NASA",
            "file": "earth_{month:02d}.png",
            "type": "cylindrical_monthly",
            "months": 2,
        }
        proc = self._processor(monkeypatch, tmp_path, [entry])
        proc.process_tiles()

        meta = json.loads(
            (tmp_path / "meta" / "naif-399" / "metadata.json").read_text()
        )
        assert meta["frames"] == 2
        assert [level["tiles"] for level in meta["levels"]] == [4, 16]
        root = tmp_path / "tiles" / "naif-399"
        assert _stitch(root / "01", 1)[0, 0, 0] > 200
        assert _stitch(root / "02", 1)[0, 0, 0] < 60

    @pytest.mark.parametrize(
        ("type_", "pyramid_id"),
        [
            ("cylindrical_specular", "naif-399_specular"),
            ("cylindrical_night_lights", "naif-399_night"),
        ],
    )
    def test_sibling_layers_are_tiled_under_their_own_id(
        self, tmp_path, monkeypatch, type_, pyramid_id
    ):
        entry = {**self._colour_entry(tmp_path), "body": "naif-399", "type": type_}
        proc = self._processor(monkeypatch, tmp_path, [entry])
        proc.process_tiles()
        assert (tmp_path / "tiles" / pyramid_id / "0" / "0" / "0.webp").exists()

    def test_skybox_is_not_tiled(self, tmp_path, monkeypatch):
        entry = {**self._colour_entry(tmp_path), "type": "cubemap_skybox"}
        proc = self._processor(monkeypatch, tmp_path, [entry])
        proc.process_tiles()
        assert not (tmp_path / "tiles").exists()
