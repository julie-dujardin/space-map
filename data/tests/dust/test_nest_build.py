"""Tests for the dust nest on small synthetic grids."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from space_map_data.dust import disc, march, merge, nest, resample
from space_map_data.dust.encode import Encoding, block_mean, compensate, filtered_mean
from space_map_data.dust.layers import inner_density
from space_map_data.dust.nest import Level, cube_weights, local_weight, regional_weight
from space_map_data.dust.rest import disc_shape
from space_map_data.export import dust as dust_export
from space_map_data.export import swap
from space_map_data.export.dust import volume_payload
from space_map_data.export.extrasolar import container
from space_map_data.export.extrasolar.container import VOLUME_INFO

SMALL = Level(0, (10.0, 10.0, 5.0), (8, 8, 4))


def _smooth(x, y, z):
    return 1.0 + 0.5 * x / 10.0 + 0.25 * np.sin(x) * np.cos(y) + z * z / 25.0


def _sampler(x, y, z):
    return _smooth(x, y, z), np.ones(len(x))


class TestPointsPixels:
    """The HEALPix pixel of a direction on Galactic axes."""

    def test_the_pixel_follows_the_direction_and_not_the_distance(self):
        points = np.array([[1.0, 0, 0], [500.0, 0, 0], [0, 0, 1.0], [0, 0, -3.0]])
        near, far, north, south = resample.points_pixels(points, 2)
        assert near == far
        assert north < 16
        assert south >= 8 * 16


class TestResample:
    def test_mean_over_voxels_keeps_the_integral(self, tmp_path: Path):
        resample.fill(SMALL, tmp_path, _sampler, 8, 1)
        value = np.load(tmp_path / "l0.value.npy")
        support = np.load(tmp_path / "l0.support.npy")
        # The integral of _smooth over the box, per unit volume.
        mean = 1.0 + (5.0**2 / 3.0) / 25.0
        assert value.mean() == pytest.approx(mean, rel=1e-3)
        assert support.mean() == pytest.approx(1.0)

    def test_a_small_cloud_keeps_its_mass_between_voxels(self, tmp_path: Path):
        # A voxel-centre sample misses this cloud, which sits at a voxel corner.
        def cloud(x, y, z):
            inside = (x * x + y * y + z * z) < 1.0
            return inside * 1.0, np.ones(len(x))

        resample.fill(SMALL, tmp_path, cloud, 16, 1)
        volume = float(np.prod(SMALL.voxel))
        mass = np.load(tmp_path / "l0.value.npy").sum() * volume
        assert mass == pytest.approx(4.0 / 3.0 * np.pi, rel=0.02)

    def test_reach_skips_far_voxels(self, tmp_path: Path):
        resample.fill(SMALL, tmp_path, _sampler, 2, 1, reach=(0.0, 2.0))
        assert np.load(tmp_path / "l0.value.npy")[0, 0, 0] == 0.0

    def test_stratified_points_stay_in_their_voxel(self):
        rng = np.random.default_rng(1)
        centres = np.array([[1.0, 2.0, 3.0]], dtype="f4")
        voxel = np.array((2.0, 2.0, 4.0))
        points = resample.stratified(centres, voxel, 3, rng)
        assert points.shape == (1, 27, 3)
        assert (np.abs(points - centres) <= voxel / 2).all()


class TestLowTier:
    def test_block_mean_keeps_the_mean_and_any_ray_along_an_axis(self):
        density = np.random.default_rng(2).random((8, 8, 4), dtype="f4")
        low = block_mean(density)
        assert low.shape == (4, 4, 2)
        assert low.mean() == pytest.approx(density.mean(), rel=1e-5)
        assert low.sum(axis=2).sum() * 2 == pytest.approx(density.sum() / 4, rel=1e-5)


class TestEncoding:
    encoding = Encoding(1e-5, 1.0)

    def test_zero_is_code_zero(self):
        assert self.encoding.encode(np.array([0.0]))[0] == 0
        assert self.encoding.decode(np.array([0]))[0] == 0.0

    def test_top_is_code_255(self):
        assert self.encoding.encode(np.array([1.0]))[0] == 255
        assert self.encoding.decode(np.array([255]))[0] == pytest.approx(1.0, rel=1e-5)

    def test_every_code_survives_a_round_trip(self):
        codes = np.arange(256, dtype=np.uint8)
        back = self.encoding.encode(self.encoding.decode(codes))
        assert (back == codes).all()

    def test_relative_error_is_bounded_above_the_floor(self):
        density = np.geomspace(1e-4, 1.0, 5000)
        back = self.encoding.decode(self.encoding.encode(density))
        assert np.abs(back / density - 1).max() < 0.5 * self.encoding.span / 255 * 1.2


class TestHandOvers:
    def test_weights_have_no_step(self):
        r = np.linspace(1000.0, 2500.0, 15001)
        assert np.abs(np.diff(local_weight(r))).max() < 0.01
        assert np.abs(np.diff(regional_weight(r))).max() < 0.01

    def test_cube_shares_stay_in_range(self):
        rng = np.random.default_rng(3)
        x, y = rng.uniform(-6000, 6000, (2, 1000))
        z = rng.uniform(-500, 500, 1000)
        fine, coarse = cube_weights(x, y, z)
        assert ((fine >= 0) & (fine <= 1)).all()
        assert (fine + (1 - fine) * coarse <= 1.0 + 1e-12).all()
        assert fine[np.abs(z) > nest.CUBE_Z_FADE[1]].max() == 0.0

    def test_nothing_of_the_local_map_reaches_its_edge(self):
        assert local_weight(np.array([1240.0]))[0] == 0.0
        assert regional_weight(np.array([1950.0]))[0] == 0.0


def _fields(value: float, share: float, shape=(2, 2, 2)):
    return np.full(shape, value, "f4"), np.full(shape, share, "f4")


class TestObserved:
    """The merge of the observed layers, by the function that the build runs."""

    def test_open_sums_the_layers_and_leaves_the_rest_share(self):
        value, rest = merge.combine(
            _fields(1.0, 0.5), _fields(2.0, 0.25), _fields(4.0, 0.125)
        )
        assert np.allclose(value, 7.0)
        assert np.allclose(rest, 0.125)

    def test_the_rest_share_stays_between_0_and_1(self):
        _, rest = merge.combine(
            _fields(0.0, 0.75), _fields(0.0, 0.5), _fields(0.0, 0.0)
        )
        assert np.allclose(rest, 0.0)

    def test_the_cubes_replace_the_regional_and_disc_layers_in_the_share_they_hold(
        self,
    ):
        # The cube holds half of what the local layer leaves.
        value, rest = merge.combine(
            _fields(1.0, 0.5),
            _fields(2.0, 0.25),
            _fields(4.0, 0.125),
            _fields(8.0, 0.25),
        )
        assert np.allclose(value, 1.0 + 8.0 + 0.5 * (2.0 + 4.0))
        assert np.allclose(rest, 1.0 - (0.5 + 0.25 + 0.5 * (0.25 + 0.125)))

    def test_a_cube_share_over_what_the_local_layer_leaves_takes_all_of_it(self):
        value, rest = merge.combine(
            _fields(1.0, 0.75),
            _fields(2.0, 0.125),
            _fields(4.0, 0.0),
            _fields(8.0, 0.5),
        )
        assert np.allclose(value, 1.0 + 8.0)
        assert np.allclose(rest, 0.0)

    def test_a_voxel_that_the_local_layer_fills_has_no_share_to_divide(self):
        value, rest = merge.combine(
            _fields(1.0, 1.0), _fields(2.0, 0.0), _fields(4.0, 0.0), _fields(8.0, 0.0)
        )
        assert np.isfinite(value).all()
        assert np.allclose(value, 1.0 + 8.0 + 2.0 + 4.0)
        assert np.allclose(rest, 0.0)

    @pytest.fixture
    def built(self, tmp_path, monkeypatch):
        level = Level(0, (10.0, 10.0, 5.0), (2, 2, 2))
        monkeypatch.setattr(merge, "LEVELS", (level,))
        for layer in ("LOCAL", "REGIONAL", "DISC"):
            monkeypatch.setattr(merge, f"{layer}_LEVELS", (level,))
        for name in ("LOCAL_DIR", "REGIONAL_OPEN_DIR", "DISC_DIR"):
            directory = tmp_path / name
            directory.mkdir()
            monkeypatch.setattr(merge, name, directory)
            np.save(directory / "l0.value.npy", np.full((2, 2, 2), 1.0, "f4"))
            np.save(directory / "l0.support.npy", np.full((2, 2, 2), 0.25, "f4"))
        cube = tmp_path / "cube"
        cube.mkdir()
        monkeypatch.setattr(merge, "REGIONAL_VERGELY_DIR", cube)
        return level

    def test_observed_reads_the_files_of_the_layers(self, built):
        value, rest = merge.observed("open", 0)
        assert np.allclose(value, 3.0)
        assert np.allclose(rest, 0.25)

    def test_a_cube_layer_that_was_never_built_raises(self, built):
        with pytest.raises(FileNotFoundError):
            merge.observed("vergely", 0)

    def test_a_level_that_a_layer_is_not_built_for_holds_none_of_it(
        self, built, monkeypatch
    ):
        monkeypatch.setattr(merge, "DISC_LEVELS", ())
        value, rest = merge.observed("open", 0)
        assert np.allclose(value, 2.0)
        assert np.allclose(rest, 0.5)

    def test_a_built_level_with_a_missing_file_raises(self, built, monkeypatch):
        (merge.DISC_DIR / "l0.support.npy").unlink()
        with pytest.raises(FileNotFoundError):
            merge.observed("open", 0)


class TestDifferencing:
    def test_cumulative_becomes_density_per_bin(self):
        cumulative = np.array([[0.0, 0.1, 0.1, 0.4]])
        delta = disc.density_bins(cumulative)
        assert np.allclose(delta, [[0.1, 0.0, 0.3]])
        widths = np.array([2.0, 2.0, 3.0])
        assert np.allclose(disc.clipped_density(delta, widths), [[0.05, 0.0, 0.1]])

    def test_density_times_width_returns_the_cumulative(self):
        increments = np.random.default_rng(4).random((5, 119))
        cumulative = np.concatenate(
            (np.zeros((5, 1)), increments.cumsum(axis=1)), axis=1
        )
        widths = np.diff(disc.NODES_PC)
        density = disc.clipped_density(disc.density_bins(cumulative), widths)
        assert np.allclose((density * widths).sum(axis=1), cumulative[:, -1])

    def test_float16_noise_cancels_when_the_mean_keeps_the_sign(self):
        rng = np.random.default_rng(5)
        truth = np.linspace(4.5, 4.6, 120)
        fine = (truth + rng.normal(0, 3e-3, (4096, 120))).astype(np.float16)
        differences = disc.density_bins(fine)
        assert (differences < 0).any()
        kept = differences.mean(axis=0).sum()
        clipped_first = np.maximum(differences, 0.0).mean(axis=0).sum()
        assert kept == pytest.approx(0.1, rel=0.02)
        assert clipped_first > 1.5 * kept

    def test_ratio_stats_drop_the_ratios_that_are_not_finite(self):
        stats = disc.ratio_stats(np.array([1.0, 2.0, 3.0, np.nan, np.inf]))
        assert (stats["rays"], stats["median"]) == (3, 2.0)

    @pytest.mark.parametrize("ratio", [[], [np.nan, np.inf]])
    def test_ratio_stats_of_nothing_is_a_count_of_zero(self, ratio):
        assert disc.ratio_stats(np.array(ratio)) == {"rays": 0}

    def test_reliable_share_fades_to_the_limit(self):
        share = disc.reliable_share(
            np.array([0.0, 0.0, 0.0]), np.array([12.0, -np.inf, np.nan])
        )
        middles = disc.NODES_DM[:-1] + 0.0625
        assert share[0][middles < 11.5].min() == 1.0
        assert share[0][middles >= 12.0].max() == 0.0
        assert share[1].max() == 0.0
        assert share[2].max() == 0.0

    def test_reliable_share_fades_in_above_the_minimum_as_wide(self):
        share = disc.reliable_share(np.array([9.0, np.inf]), np.array([14.0, 14.0]))
        middles = disc.NODES_DM[:-1] + 0.0625
        assert share[0][middles <= 9.0].max() == 0.0
        assert share[0][(middles >= 9.5) & (middles < 13.5)].min() == 1.0
        rising = share[0][(middles > 9.0) & (middles < 9.5)]
        falling = share[0][(middles > 13.5) & (middles < 14.0)]
        assert np.allclose(rising, falling[::-1])
        assert share[1].max() == 0.0

    def test_column_bins_sum_from_the_first_node(self):
        cumulative = np.array([[0.1, 0.1, 0.3, 0.7]])
        assert np.allclose(disc.column_bins(cumulative), [[0.0, 0.2, 0.6]])

    def test_a_column_from_the_first_node_counts_where_its_end_is_reliable(self):
        # The near bins are past no reliable minimum, the column's end is.
        bins = 8
        columns = np.outer([1.0, 2.0, 1.5], np.arange(1, bins + 1) * 0.1)
        cover = np.ones((3, bins), "f4")
        cover[:, :4] = 0.0
        cover[1, -1] = 0.5
        reference = 2.0 * columns[:, -1]
        fit = disc._fit_shell(reference, columns, cover, 0, bins, np.zeros(3))
        assert fit["rays"] == 2
        assert fit["median"] == pytest.approx(2.0)
        inner = disc._fit_shell(reference, columns, cover, 2, bins, np.zeros(3))
        assert inner["rays"] == 0


class TestReduceDecaps:
    def _reduce(self, tmp_path, monkeypatch, index, values, minimum=None):
        """Reduce a file of one pixel per index, each with the same difference in
        every bin, and return the Nside 256 means of the first bin."""
        source = tmp_path / "maps" / "decaps-2025"
        source.mkdir(parents=True)
        with h5py.File(source / "decaps_mean.h5", "w") as handle:
            info = handle.create_group("pixel_info")
            info["healpix_index"] = np.array(index, np.int64)
            info["converged"] = np.ones(len(index), np.uint8)
            info["DM_reliable_min"] = np.array(
                [-1.0] * len(index) if minimum is None else minimum, "f4"
            )
            info["DM_reliable_max"] = np.full(len(index), 100.0, "f4")
            ramp = np.arange(disc.BINS + 1, dtype="f4")
            handle["mean"] = (np.array(values, "f4")[:, None] * ramp)[:, None, :]
        monkeypatch.setattr(disc, "SOURCES_DUST_MAPS_DIR", tmp_path / "maps")
        monkeypatch.setattr(disc, "REDUCED_DIR", tmp_path / "reduced")
        monkeypatch.setattr(disc, "PIXELS", 2)
        disc.reduce_decaps()
        reduced = tmp_path / "reduced"
        return {
            name: np.load(reduced / f"decaps.{name}.npy")[:, 0] for name in disc.REDUCED
        }

    def test_pixels_of_one_parent_average(self, tmp_path, monkeypatch):
        # A parent holds 1,024 fine pixels.
        mean = self._reduce(tmp_path, monkeypatch, [5, 9, 1031], [1.0, 3.0, 10.0])
        assert mean["delta"] == pytest.approx([2.0, 10.0])
        assert mean["column"] == pytest.approx([2.0, 10.0])

    def test_a_parent_that_starts_two_runs_in_a_block_keeps_both(
        self, tmp_path, monkeypatch
    ):
        mean = self._reduce(tmp_path, monkeypatch, [5, 1031, 9], [1.0, 10.0, 3.0])
        assert mean["delta"] == pytest.approx([2.0, 10.0])

    def test_a_fine_pixel_below_its_reliable_minimum_does_not_count(
        self, tmp_path, monkeypatch
    ):
        mean = self._reduce(
            tmp_path, monkeypatch, [5, 9, 1031], [1.0, 3.0, 10.0], [-1.0, 20.0, -1.0]
        )
        assert mean["delta"] == pytest.approx([1.0, 10.0])
        assert mean["column"] == pytest.approx([1.0, 10.0])
        assert mean["cover"] == pytest.approx([1 / 1024, 1 / 1024])


class TestInnerColumn:
    @pytest.mark.parametrize("column,edge", [(0.02, 5e-5), (0.002, 5e-4), (0.0, 1e-5)])
    def test_the_profile_keeps_the_column_and_meets_the_map(self, column, edge):
        end = 68.6
        r = (np.arange(200000) + 0.5) / 200000 * end
        density = inner_density(
            r, np.full(r.shape, column), np.full(r.shape, edge), end
        )
        assert density.min() >= 0.0
        assert density.mean() * end == pytest.approx(column, abs=1e-5)
        last = inner_density(np.array([end]), np.array([column]), np.array([edge]), end)
        assert last[0] == pytest.approx(edge)


class TestMarch:
    def test_uniform_density_gives_the_path_length_to_the_edge_of_the_nest(self):
        grids = {level.index: np.ones(level.shape, "f4") for level in nest.LEVELS}
        directions = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        column = march.integrate((march.Stack(grids),), np.zeros(3), directions)[0]
        # Level 1 reaches higher in z than level 0.
        assert column == pytest.approx([20000.0, 3000.0], rel=1e-6)

    def test_a_ray_that_crosses_a_finer_box_keeps_its_length(self):
        grids = {level.index: np.ones(level.shape, "f4") for level in nest.LEVELS}
        origin = np.array([-1000.0, 0.0, 0.0])
        directions = np.array([[1.0, 0.0, 0.0]])
        column = march.integrate((march.Stack(grids),), origin, directions)[0]
        assert column == pytest.approx([21000.0], rel=1e-6)

    def test_a_level_is_never_chosen_for_a_point_it_does_not_hold(self):
        points = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 2500.0], [9000.0, 0.0, 0.0]])
        # Level 1 is taller than level 0, so only level 1 holds the second point.
        assert march.finest_level(points).tolist() == [3, 1, 0]
        assert march.finest_level(points, 0).tolist() == [0, -1, 0]
        assert march.finest_level(points, 1).tolist() == [1, 1, 0]

    def test_a_marcher_with_coarse_steps_reads_the_level_that_holds_the_point(self):
        zero = {level.index: np.zeros(level.shape, "f4") for level in nest.LEVELS}
        grids = {**zero, 1: np.ones(nest.LEVELS[1].shape, "f4")}
        origin = np.array([0.0, 0.0, 2100.0])
        up = np.array([[0.0, 0.0, 1.0]])
        # 0.25 voxels per step asks for level 0 at the first steps.
        coarse = march.march(march.Stack(grids), origin, up, 0.18, 10.0, 0.25)
        finest = march.march(march.Stack(grids), origin, up, 0.18, 10.0)
        assert finest[0] > 500.0
        assert coarse[0] == finest[0]

    def test_hardware_fetch_reads_a_texel_at_its_centre(self):
        level = nest.LEVELS[3]
        grid = np.zeros(level.shape, "f4")
        grid[100, 120, 140] = 7.0
        point = np.array(
            [[level.centres(0)[100], level.centres(1)[120], level.centres(2)[140]]]
        )
        assert march.trilinear(level, grid, point)[0] == pytest.approx(7.0)


class TestRestShape:
    def test_shape_is_one_at_the_solar_circle(self):
        value = disc_shape(np.array([0.0]), np.array([0.0]), np.array([-15.0]))
        assert value[0] == pytest.approx(1.0)

    def test_shape_falls_with_radius_and_height(self):
        at = disc_shape(
            np.array([0.0, -5000.0, 0.0]), np.zeros(3), np.array([-15.0, -15.0, 485.0])
        )
        assert at[1] < at[0] and at[2] < at[0]

    def test_shape_has_a_hole_at_the_centre(self):
        at = disc_shape(np.array([4000.0, 8000.0]), np.zeros(2), np.full(2, -15.0))
        assert at[1] < at[0]


class TestVolumeFile:
    def test_order_is_x_fastest(self):
        codes = np.zeros((4, 2, 2), np.uint8)
        codes[1, 0, 0] = 1
        codes[0, 1, 0] = 2
        codes[0, 0, 1] = 3
        payload = volume_payload(codes, 2, "low")
        decoded = container.decode(payload)
        assert decoded.kind == container.KIND_VOLUME
        assert VOLUME_INFO.unpack(decoded.info) == (4, 2, 2, 2, 1)
        flat = decoded.numpy("codes")
        nx, ny = 4, 2
        assert flat[1] == 1
        assert flat[nx] == 2
        assert flat[nx * ny] == 3

    def test_an_undecided_variant_stays_off_the_served_root(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(dust_export, "EXTRASOLAR_DIR", tmp_path)
        monkeypatch.setattr(dust_export, "_distribution", lambda _variant: "undecided")
        with pytest.raises(swap.ExportRefused):
            dust_export.export_dust("vergely", tmp_path)
        assert list(tmp_path.iterdir()) == []


class TestCompensation:
    encoding = Encoding(1e-6, 1.0)

    def _cloud(self) -> np.ndarray:
        rng = np.random.default_rng(6)
        return (1e-4 * np.exp(rng.normal(0, 2.0, (32, 32, 32)))).astype("f4")

    def _filtered_mean(self, codes: np.ndarray) -> float:
        return float(
            filtered_mean(codes.astype("f4"), self.encoding.decode).mean(dtype="f8")
        )

    def test_the_filtered_fetch_keeps_the_mean_density(self):
        density = self._cloud()
        wanted = float(filtered_mean(density, lambda grid: grid).mean(dtype="f8"))
        plain = self._filtered_mean(self.encoding.encode(density))
        moved = self._filtered_mean(compensate(density, self.encoding))
        assert plain < 0.9 * wanted
        assert moved == pytest.approx(wanted, rel=0.05)

    def test_a_uniform_field_keeps_its_code(self):
        density = np.full((8, 8, 8), 1e-3, "f4")
        codes = compensate(density, self.encoding)
        assert (codes == self.encoding.encode(density)).all()
