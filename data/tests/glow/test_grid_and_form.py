"""Tests for the layout of the grid, its form and its textures."""

import numpy as np
import pytest

from space_map_data.glow import encode, form, sky_map
from space_map_data.glow.grid import SkyGrid
from space_map_data.glow.march import Textures

GRID = SkyGrid(16, 8, 20.0, 400_000.0)


def _unit(rng: np.random.Generator, n: int) -> np.ndarray:
    d = rng.normal(size=(n, 3))
    return d / np.linalg.norm(d, axis=1, keepdims=True)


class TestSkyGrid:
    def test_the_cells_cover_the_sphere(self):
        assert GRID.angles.sum() == pytest.approx(4 * np.pi)

    def test_the_ring_has_no_solid_angle(self):
        a = GRID.angles
        assert a[0].sum() == a[-1].sum() == a[:, 0].sum() == a[:, -1].sum() == 0

    def test_a_cell_holds_its_share_of_directions(self):
        rng = np.random.default_rng(2)
        row, column = GRID.cell_of(_unit(rng, 2_000_000))
        counts = np.zeros((16, 16))
        np.add.at(counts, (row, column), 1)
        share = counts / counts.sum() * 4 * np.pi
        used = GRID.angles > 0
        assert np.abs(share[used] / GRID.angles[used] - 1).max() < 0.05

    def test_the_voxels_fill_the_reach(self):
        assert GRID.volumes().sum() == pytest.approx(4 / 3 * np.pi * GRID.reach**3)

    def test_a_point_falls_in_the_shell_of_its_radius(self):
        edges = GRID.edges()
        r = np.sqrt(edges[3] * edges[4])
        assert GRID.shell_of(np.array([r]))[0] == 3

    def test_the_last_row_of_the_tree_stays_in_the_grid(self):
        assert GRID.shell_of(np.array([1e7]))[0] == GRID.shells - 1

    def test_the_ring_copies_the_cell_that_holds_its_ray(self):
        volume = np.arange(16.0 * 16).reshape(1, 16, 16)
        GRID.fill_ring(volume)
        pairs = GRID.ring_sources()
        assert volume[0, pairs[:, 0], pairs[:, 1]] == pytest.approx(
            volume[0, pairs[:, 2], pairs[:, 3]]
        )
        assert (pairs[:, 2:] >= 1).all() and (pairs[:, 2:] <= 14).all()


def _table() -> form.Table:
    """Equal light in each 2 mag from -6 to 8, R = G = B."""
    points = form.curve_points()
    histogram = np.zeros((len(points) - 1, 3))
    for m in range(-6, 8, 2):
        histogram[form.curve_bin(np.array([m + 0.5]))[0]] = 1.0
    return form.make_table(histogram)


class TestTable:
    def test_a_cut_past_all_stars_reads_the_first_value(self):
        place, _ = form.read_table(_table(), np.array([-19.0]))
        assert place[0] == 0.0

    def test_a_cut_on_an_edge_reads_that_value(self):
        place, _ = form.read_table(_table(), np.array([form.EDGES[2]]))
        assert place[0] == pytest.approx(3.0, abs=1e-3)

    def test_past_the_faintest_star_the_light_is_zero(self):
        place, _ = form.read_table(_table(), np.array([15.0]))
        assert place[0] == 7.0

    def test_the_summed_light_is_exact_at_every_cut(self):
        histogram = np.zeros((len(form.curve_points()) - 1, 3))
        rng = np.random.default_rng(3)
        m0 = rng.normal(0.5, 3.0, 20_000)
        histogram += np.bincount(form.curve_bin(m0), minlength=len(histogram))[:, None]
        table = form.make_table(histogram)
        edges = np.array((-np.inf, *form.EDGES))
        values = np.array([3.0 * (m0 > e).sum() for e in edges])
        for cut in (-9.0, -3.5, 0.5, 2.0, 4.0, 7.0):
            place, _ = form.read_table(table, np.array([cut]))
            weights, _ = form.shares(place)
            got = (weights[0] * values).sum()
            assert got == pytest.approx(3.0 * (m0 > cut).sum(), rel=0.03)

    def test_the_soft_cut_keeps_more_than_the_sharp_cut(self):
        table = _table()
        sharp, _ = form.read_table(table, np.array([1.0]))
        soft, _ = form.read_table(table, np.array([1.0]), soft=True)
        assert soft[0] < sharp[0]

    def test_a_cut_far_from_the_fade_is_not_soft(self):
        histogram = np.zeros((len(form.curve_points()) - 1, 3))
        histogram[form.curve_bin(np.array([0.0]))[0]] = 1.0
        curve = form.fainter_curve(histogram)
        soft = form.soft_curve(curve)
        at = np.searchsorted(form.curve_points(), 3.0)
        assert soft[at] == pytest.approx(curve[at])


class TestVoxelValues:
    def test_each_value_holds_the_stars_fainter_than_its_edge(self):
        light = np.zeros((7, 3))
        light[1] = (1, 1, 1)
        light[3] = (2, 0, 1)
        light[6] = (0, 0, 4)
        values = form.voxel_values(light)
        assert values[:7] == pytest.approx([10.0, 10.0, 7.0, 7.0, 4.0, 4.0, 4.0])

    def test_the_light_falls_with_m(self):
        rng = np.random.default_rng(4)
        values = form.voxel_values(rng.random((10, 7, 3)))
        assert (np.diff(values[:, :7], axis=1) <= 0).all()

    def test_the_tint_is_blue_over_red_and_blue_at_the_tint_edge(self):
        light = np.zeros((7, 3))
        light[form.TINT_EDGE + 2] = (1.0, 5.0, 3.0)
        assert form.voxel_values(light)[7] == pytest.approx(0.75)

    def test_a_voxel_with_nothing_at_the_tint_edge_has_no_tint(self):
        assert np.isnan(form.voxel_values(np.zeros((7, 3)))[7])


class TestColourFromTint:
    def test_a_neutral_tint_keeps_the_colour_of_the_summed_light(self):
        base = np.array([[0.4, 0.35, 0.25]])
        rgb = form.rgb_of(np.array([2.0]), np.array([0.3]), base, 0.3)
        assert rgb == pytest.approx(base * 2.0)

    def test_a_bluer_tint_moves_light_to_blue_and_keeps_the_sum(self):
        base = np.array([[0.4, 0.35, 0.25]])
        rgb = form.rgb_of(np.array([2.0]), np.array([0.6]), base, 0.3)
        assert rgb.sum() == pytest.approx(2.0)
        assert rgb[0, 2] > 0.5 > rgb[0, 0]


class TestTextures:
    def test_half_floats_go_there_and_back(self):
        values = np.array([0.0, 1.5, 1024.0, 3.25e-3], np.float32)
        back = encode.bits_to_values(encode.half_bits(values))
        assert back == pytest.approx(values, rel=1e-3)

    def test_the_scale_is_a_power_of_two_under_the_top_of_a_half_float(self):
        scale = encode.scale_of(np.array([3.0, 177.0]))
        assert np.log2(scale) == int(np.log2(scale))
        assert 177.0 * scale <= encode.TOP

    def test_the_tint_takes_no_scale(self):
        values = np.ones((1, 1, 1, form.VALUES), np.float32)
        bits = encode.encode_values(values, 8.0)
        back = encode.bits_to_values(bits)[0, 0, 0]
        assert back[0] == 8.0
        assert back[-1] == 1.0

    def _textures(self) -> Textures:
        grid = SkyGrid(8, 6, 20.0, 400_000.0)
        values = np.ones((*grid.shape, form.VALUES), np.float32)
        histogram = np.zeros((len(form.curve_points()) - 1, 3))
        histogram[form.curve_bin(np.array([0.0]))[0]] = 1.0
        return Textures(
            grid, encode.encode_values(values, 4.0), 4.0, form.make_table(histogram)
        )

    def test_a_read_gives_flux_density_at_any_point(self):
        tex = self._textures()
        got = tex.filtered(np.array([[10.0, 20.0, -5.0], [1000.0, 0.0, 0.0]]))
        assert got[:, :7] == pytest.approx(np.ones((2, 7)))

    def test_past_the_reach_there_is_no_light(self):
        got = self._textures().filtered(np.array([[1e6, 0.0, 0.0]]))
        assert (got[:, :7] == 0).all()

    def test_the_read_and_the_map_share_their_cells(self):
        d = np.array([[0.6, 0.0, 0.8]])
        u, v = sky_map.map_uv(d, 8)
        row, column = SkyGrid(8, 6, 20.0, 400_000.0).cell_of(d)
        assert row[0] == int(v[0] * 8)
        assert column[0] == int(u[0] * 8)
