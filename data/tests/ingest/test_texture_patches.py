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
from space_map_data.ingest.providers.textures.image_io import ChunkedTiff

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


class TestPatchTiles:
    """A patch built aside goes into its pyramid, and comes out again."""

    def test_put_in_place_then_removed(self, tmp_path):
        pyramid = _pyramid(tmp_path / "tiles")
        own = _files(pyramid)
        builder = patches.PatchBuilder(
            "test", pyramid, BASE, [_raster(_texture())], pyramid / ".patch-site", 1.0
        )
        builder.build()
        patches.put_in_place(pyramid / ".patch-site", pyramid)
        assert not (pyramid / ".patch-site").exists()
        assert sorted(_files(pyramid)) == [0, 1, 2, 3, 4, 5, 6, 7]

        x0, x1, y0, y1 = builder.tile_range(7)
        patches.remove(pyramid, BASE, {"max_level": 7, "x": [x0, x1], "y": [y0, y1]})
        assert _files(pyramid) == own
        assert not (pyramid / "4").exists()


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
        assert (patch["x"], patch["y"]) == ([135, 151], [49, 65])
        assert patch["attribution"] == "Site credit"
        assert [level["level"] for level in patch["levels"]] == [4, 5, 6, 7]
        assert patch["levels"][-1]["tiles"] == 289
        assert len(_files(tmp_path / "tiles" / "naif-499")[7]) == 289

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
