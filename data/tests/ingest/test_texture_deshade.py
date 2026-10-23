"""Tests for deshading: a site mosaic taken in a low Sun, with the shading of
that Sun taken out by the site's terrain model."""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from scipy import ndimage

from space_map_data.ingest.providers.textures import config, deshade, patches, tiles

from . import test_texture_patches as patch_tests
from .test_texture_patches import (
    TILE,
    _height_raster,
    _relief,
    _texture,
    _write_geotiff,
)
from .test_texture_tiles import _write_pds_image

RADIUS_KM = 1737.4
# A mosaic of 1 m pixels, 768 m a side, near the equator unless placed
# elsewhere.
SIDE = 768
DEGREES = SIDE / (math.radians(1.0) * RADIUS_KM * 1000.0)
WEST, NORTH = 10.0, 0.02
# The terrain model: 2 m pixels over the west three quarters.
MODEL_SIDE = SIDE * 3 // 4
SUN = (120.0, 25.0)
ALBEDO = 0.1


@pytest.fixture(autouse=True)
def _small_site(monkeypatch):
    """Grids, blends and blocks to the size of the test site."""
    monkeypatch.setattr(deshade, "_FIT_M", 8.0)
    monkeypatch.setattr(deshade, "_SHADOW_M", 2.0)
    monkeypatch.setattr(deshade, "_DETAIL_M", 150.0)
    monkeypatch.setattr(deshade, "_FEATHER_M", 20.0)
    monkeypatch.setattr(deshade, "_BLEND_M", 40.0)
    monkeypatch.setattr(deshade, "_FILL_SIGMAS", (4.0, 16.0))
    monkeypatch.setattr(deshade, "_BLOCK", 256)


def _ground() -> np.ndarray:
    """Hills some 100 m across, in metres on the mosaic's grid, with slopes
    below the Sun: they cast no shadow."""
    rng = np.random.default_rng(seed=11)
    hills = ndimage.gaussian_filter(rng.normal(size=(SIDE, SIDE)), 30.0)
    down, across = np.gradient(hills)
    steepest = np.hypot(down, across).max()
    return (hills * math.tan(math.radians(20.0)) / steepest).astype(np.float32)


def _site(tmp_path: Path, north: float = NORTH) -> tuple[Path, tiles.Layer, np.ndarray]:
    """The mosaic of the ground in the Sun ``SUN``, its terrain model, and
    the mosaic's albedo. Its pixels are square on the ground, as those of a
    mosaic whose label sets its latitude of true scale: away from the
    equator, a degree east holds more of them than a degree north."""
    metres = _ground()
    rng = np.random.default_rng(seed=12)
    albedo = (ALBEDO * rng.uniform(0.9, 1.1, size=metres.shape)).astype(np.float32)
    shading = deshade._shading(deshade._normals(metres, 1.0, 1.0), *SUN)
    mosaic = tmp_path / "site.img"
    south = north - DEGREES
    wide = DEGREES / math.cos(math.radians(north - DEGREES / 2))
    west, east = WEST, WEST + wide
    _write_pds_image(
        mosaic,
        albedo * shading,
        MAP_PROJECTION_TYPE="EQUIRECTANGULAR",
        A_AXIS_RADIUS=f"{RADIUS_KM} <KM>",
        WESTERNMOST_LONGITUDE=f"{west} <DEG>",
        EASTERNMOST_LONGITUDE=f"{east} <DEG>",
        MAXIMUM_LATITUDE=f"{north} <DEG>",
        MINIMUM_LATITUDE=f"{south} <DEG>",
    )
    model = metres[:, :MODEL_SIDE].reshape(SIDE // 2, 2, MODEL_SIDE // 2, 2)
    model_bounds = (west, west + wide * 3 / 4, north, south)
    terrain = _height_raster(model.mean(axis=(1, 3)) / 1000.0, model_bounds)
    return mosaic, terrain, albedo


def _samples(path: Path) -> np.ndarray:
    raw = np.fromfile(path, dtype="<f4")
    return raw[raw.size - SIDE * SIDE :].reshape(SIDE, SIDE)


class TestDeshade:
    """The copy has the shading of the mosaic's Sun taken out."""

    def test_finds_the_mosaics_sun(self, tmp_path):
        mosaic, terrain, _ = _site(tmp_path)
        light = deshade.write(mosaic, [terrain], tmp_path / "copy.img")
        assert light.azimuth == pytest.approx(SUN[0], abs=6.0)
        assert light.elevation == pytest.approx(SUN[1], abs=5.0)
        assert light.match > 0.8
        assert 0.7 < light.gain <= 1.0

    @pytest.mark.parametrize("north", [NORTH, -45.0], ids=["equator", "45°S"])
    def test_ground_over_the_model_is_its_albedo(self, tmp_path, north):
        mosaic, terrain, albedo = _site(tmp_path, north)
        deshade.write(mosaic, [terrain], tmp_path / "copy.img")
        before = _samples(mosaic) / albedo
        after = _samples(tmp_path / "copy.img") / albedo
        # Well inside the model and the mosaic.
        inside = (slice(64, SIDE - 64), slice(64, MODEL_SIDE - 64))

        def spread(ratio: np.ndarray) -> float:
            return float(ratio[inside].std() / ratio[inside].mean())

        assert spread(before) > 0.1
        assert spread(after) < 0.1 * spread(before)

    def test_ground_past_the_model_keeps_its_samples(self, tmp_path):
        mosaic, terrain, _ = _site(tmp_path)
        deshade.write(mosaic, [terrain], tmp_path / "copy.img")
        past = (slice(None), slice(MODEL_SIDE + 4, None))
        assert (_samples(tmp_path / "copy.img")[past] == _samples(mosaic)[past]).all()

    def test_site_too_wide_for_the_grid_takes_a_coarser_one(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(deshade, "_GRID_PIXELS", 20_000)
        mosaic, terrain, _albedo = _site(tmp_path)
        light = deshade.write(mosaic, [terrain], tmp_path / "copy.img")
        assert light.azimuth == pytest.approx(SUN[0], abs=8.0)
        assert light.elevation == pytest.approx(SUN[1], abs=6.0)

    def test_dark_ground_across_the_edge_of_the_model_ends_softly(self, tmp_path):
        """Inside the model it takes the ground around it, past it it stays:
        between the two, no line."""
        mosaic, terrain, _ = _site(tmp_path)
        samples = np.memmap(mosaic, dtype="<f4", mode="r+")
        band = samples[samples.size - SIDE * SIDE :].reshape(SIDE, SIDE)
        band[300:420] = ALBEDO * 0.02
        samples.flush()
        del samples, band
        deshade.write(mosaic, [terrain], tmp_path / "copy.img")
        row = _samples(tmp_path / "copy.img")[360, MODEL_SIDE - 80 : MODEL_SIDE + 8]
        assert row[0] > 0.5 * ALBEDO and row[-1] < 0.05 * ALBEDO
        assert np.abs(np.diff(row)).max() < 0.25 * (row[0] - row[-1])

    def test_wide_hidden_ground_shows_no_blocks(self, tmp_path):
        """Ground hidden from far around takes a brightness that every block
        shares, not each block's own."""
        mosaic, terrain, _ = _site(tmp_path)
        samples = np.memmap(mosaic, dtype="<f4", mode="r+")
        image = samples[samples.size - SIDE * SIDE :].reshape(SIDE, SIDE)
        # Brighter to the east, so that the ground of each block differs.
        image *= np.linspace(0.6, 1.4, SIDE, dtype=np.float32)[None, :]
        image[200:520, 120:440] = ALBEDO * 0.02
        samples.flush()
        del samples, image
        deshade.write(mosaic, [terrain], tmp_path / "copy.img")
        copy = _samples(tmp_path / "copy.img")
        # Far from the dark area's edges, across the edges of the blocks.
        across = copy[280:440, 255:257]
        down = copy[255:257, 200:360]
        assert copy[280:440, 200:360].min() > 0.3 * ALBEDO
        steps = [np.abs(np.diff(across, axis=1)).max()]
        steps.append(np.abs(np.diff(down, axis=0)).max())
        assert max(steps) < 0.05 * ALBEDO

    def test_copy_reads_as_its_source(self, tmp_path):
        mosaic, terrain, _ = _site(tmp_path)
        deshade.write(mosaic, [terrain], tmp_path / "copy.img")
        copy = tiles.open_region_layer(tmp_path / "copy.img").pixels
        source = tiles.open_region_layer(mosaic).pixels
        assert isinstance(copy, tiles.Region) and isinstance(source, tiles.Region)
        assert (copy.shape, copy.bounds) == (source.shape, source.bounds)

    def test_mosaic_that_the_models_do_not_explain_is_refused(self, tmp_path):
        """Dividing by a shading it does not hold would print a false one."""
        mosaic, terrain, albedo = _site(tmp_path)
        samples = np.memmap(mosaic, dtype="<f4", mode="r+")
        rng = np.random.default_rng(seed=13)
        hills = ndimage.gaussian_filter(rng.normal(size=(SIDE, SIDE)), 30.0)
        samples[samples.size - SIDE * SIDE :] = (
            albedo * (1.0 + 0.8 * hills / np.abs(hills).max())
        ).ravel()
        samples.flush()
        del samples
        with pytest.raises(ValueError, match="matches the models"):
            deshade.write(mosaic, [terrain], tmp_path / "copy.img")

    def test_flat_model_is_refused(self, tmp_path):
        """No Sun shades it, so none can match: the search ends all the same."""
        mosaic, _, _ = _site(tmp_path)
        flat = np.full((SIDE // 2, MODEL_SIDE // 2), 1.5, np.float32)
        region = tiles.open_region_layer(mosaic).pixels
        assert isinstance(region, tiles.Region)
        terrain = _height_raster(flat, region.bounds)
        with pytest.raises(ValueError, match="matches the models"):
            deshade.write(mosaic, [terrain], tmp_path / "copy.img")

    def test_integer_samples_are_refused(self, tmp_path):
        """They are stretched for viewing: a corrected value has no place in
        the stretch."""
        mosaic, terrain, _ = _site(tmp_path)
        raw = mosaic.read_bytes()
        header = raw[: len(raw) - SIDE * SIDE * 4]
        odd = tmp_path / "odd.img"
        odd.write_bytes(
            header.replace(
                b"SAMPLE_TYPE = PC_REAL", b"SAMPLE_TYPE = LSB_INTEGER"
            ).replace(b"SAMPLE_BITS = 32", b"SAMPLE_BITS = 16")
            + np.zeros(SIDE * SIDE, "<i2").tobytes()
        )
        with pytest.raises(ValueError, match="calibrated"):
            deshade.write(odd, [terrain], tmp_path / "copy.img")


class TestCastShadows:
    """A slope that hides the Sun shades the ground behind it."""

    @staticmethod
    def _shade(azimuth: float) -> np.ndarray:
        heights = np.zeros((100, 100), np.float32)
        heights[48:52, 48:52] = 10.0
        flat = np.ones_like(heights)
        grid = deshade._Grid(flat, heights, flat, 1.0, 0, 0, 100)
        return deshade._cast_shadows(grid, 1.0, azimuth, 20.0)

    def test_shadow_falls_away_from_a_sun_in_the_east(self):
        shade = self._shade(90.0)
        # 10 m up, in a Sun 20° up: 27 m long.
        assert shade[50, 28:47].mean() > 0.8
        assert not shade[50, 53:].any()
        assert not shade[:40].any() and not shade[60:].any()

    def test_shadow_falls_away_from_a_sun_in_the_north(self):
        shade = self._shade(0.0)
        assert shade[53:72, 50].mean() > 0.8
        assert not shade[:47, 50].any()


class TestHeights:
    """Heights past the edge of a model are those at its edge."""

    def test_edge_of_a_model_is_no_cliff(self):
        km = np.full((64, 32), 1.5, np.float32)
        terrain = [patches.fields(_height_raster(km, (10.0, 15.0, 5.0, -5.0)))]
        # Twice the model's pixels a degree: the model, then as much east of it.
        edges = np.linspace(5.0, -5.0, 65)
        heights, inside = deshade._heights(
            terrain, 4608, edges, 2432, 2560, 100.0, 100.0
        )
        assert np.allclose(heights, 1500.0)
        assert inside[:, 4:60].min() == 1.0 and inside[:, 68:].max() == 0.0

    def test_window_inside_a_model_is_inside_it_everywhere(self):
        km = np.full((64, 32), 1.5, np.float32)
        terrain = [patches.fields(_height_raster(km, (10.0, 15.0, 5.0, -5.0)))]
        edges = np.linspace(4.0, -4.0, 52)
        _, inside = deshade._heights(terrain, 4608, edges, 2440, 2480, 100.0, 100.0)
        assert inside.min() == 1.0

    def test_feather_east_is_in_metres_of_the_columns(self):
        """On a grid whose columns are closer than its rows, the correction
        comes in over the same metres, so over more columns."""
        km = np.full((64, 32), 1.5, np.float32)
        terrain = [patches.fields(_height_raster(km, (10.0, 15.0, 5.0, -5.0)))]
        edges = np.linspace(5.0, -5.0, 65)
        # The model ends at column 64; 20 m is 10 columns of 2 m.
        _, inside = deshade._heights(terrain, 4608, edges, 2432, 2560, 4.0, 2.0)
        assert inside[32, 54] == 1.0 and inside[32, 55] < 1.0


class TestProcessDeshadedPatches:
    """A colour patch marked ``deshade`` is built from a copy of its mosaic
    with the shading taken out by the terrain models of its site."""

    @pytest.fixture(autouse=True)
    def _small_tiles(self, monkeypatch):
        monkeypatch.setattr(config, "TILE_SIZE", TILE)

    @staticmethod
    def _processor(monkeypatch, tmp_path, **extra):
        spec = patch_tests.TestProcessPatches._spec(deshade=True, **extra)
        proc = patch_tests.TestProcessPatches._processor(monkeypatch, tmp_path, [spec])
        _write_geotiff(tmp_path / "raw" / "site.tif", _texture())
        _write_geotiff(tmp_path / "raw" / "dtm.tif", _relief() * 1000)
        monkeypatch.setattr(config, "DESHADED_DIR", tmp_path / "deshaded")
        written: list[Path] = []

        def write(mosaic, terrain, out):
            written.append(mosaic)
            out.write_bytes(mosaic.read_bytes())
            return deshade.Light(120.0, 25.0, 0.9, 0.8)

        monkeypatch.setattr(deshade, "write", write)
        proc._raw_meta.append(
            {
                "body": "naif-499",
                "file": "dem.tif",
                "type": "cylindrical_displacement",
                "patches": [
                    {
                        **patch_tests.TestProcessPatches._spec(),
                        "files": [{"file": "dtm.tif"}],
                    }
                ],
                "_source_dir": tmp_path / "raw",
            }
        )
        return proc, written

    @staticmethod
    def _run(proc) -> None:
        """The colour pyramid and its patches, and not the height pyramid."""
        entry = proc._raw_meta[0]
        proc._process_tiles(entry, "naif-499", force=False)
        proc._process_patches(entry, "naif-499")

    @staticmethod
    def _copies(tmp_path) -> list[str]:
        folder = tmp_path / "deshaded" / "naif-499"
        return sorted(path.name for path in folder.iterdir())

    def test_patch_is_built_from_the_copy(self, tmp_path, monkeypatch):
        proc, written = self._processor(monkeypatch, tmp_path)
        self._run(proc)
        assert written == [tmp_path / "raw" / "site.tif"]
        (copy,) = self._copies(tmp_path)
        assert copy.startswith("site-") and copy.endswith(".tif")
        meta = json.loads(
            (tmp_path / "meta" / "naif-499" / "metadata.json").read_text()
        )
        (patch,) = meta["patches"]
        assert patch["files"] == ["site.tif"]

    def test_copy_is_made_once(self, tmp_path, monkeypatch):
        proc, written = self._processor(monkeypatch, tmp_path)
        self._run(proc)
        proc._raw_meta[0]["patches"][0]["tiles_max_level"] = 5
        self._run(proc)
        assert len(written) == 1

    def test_other_terrain_is_another_copy_and_patch(self, tmp_path, monkeypatch):
        proc, written = self._processor(monkeypatch, tmp_path)
        self._run(proc)
        meta_path = tmp_path / "meta" / "naif-499" / "metadata.json"
        first = json.loads(meta_path.read_text())["patches"][0]["version"]
        _write_geotiff(tmp_path / "raw" / "dtm.tif", _relief(128) * 1000)
        self._run(proc)
        assert len(written) == 2 and len(self._copies(tmp_path)) == 1
        assert json.loads(meta_path.read_text())["patches"][0]["version"] != first

    def test_copy_no_longer_used_is_removed(self, tmp_path, monkeypatch):
        proc, _ = self._processor(monkeypatch, tmp_path)
        self._run(proc)
        del proc._raw_meta[0]["patches"][0]["deshade"]
        self._run(proc)
        assert self._copies(tmp_path) == []

    @pytest.mark.parametrize(
        "change",
        [{"id": "elsewhere"}, {"files": []}],
        ids=["no height patch", "no files in it"],
    )
    def test_site_with_no_terrain_model_is_not_built(
        self, tmp_path, monkeypatch, caplog, change
    ):
        proc, written = self._processor(monkeypatch, tmp_path)
        proc._raw_meta[1]["patches"][0].update(change)
        self._run(proc)
        meta = json.loads(
            (tmp_path / "meta" / "naif-499" / "metadata.json").read_text()
        )
        assert "patches" not in meta and written == []
        assert any("no terrain model" in r.message for r in caplog.records)

    def test_copy_of_a_mosaic_out_of_reach_stays(self, tmp_path, monkeypatch):
        """A share that is down for a run would otherwise cost every copy."""
        proc, _ = self._processor(monkeypatch, tmp_path)
        self._run(proc)
        (copy,) = self._copies(tmp_path)
        (tmp_path / "raw" / "site.tif").rename(tmp_path / "site.tif")
        self._run(proc)
        assert self._copies(tmp_path) == [copy]

    def test_copies_go_when_the_pyramid_has_no_patches(self, tmp_path, monkeypatch):
        proc, _ = self._processor(monkeypatch, tmp_path)
        self._run(proc)
        proc._raw_meta[0]["patches"] = []
        self._run(proc)
        stray = tmp_path / "deshaded" / "naif-499" / "site-0123456789.tif"
        stray.write_bytes(b"")
        self._run(proc)
        assert self._copies(tmp_path) == []
