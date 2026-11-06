"""Tests for what the grid takes from the shader: the colour, the dust and the map."""

import numpy as np
import pytest

from space_map_data.glow import colour, light, sky_map


class TestColour:
    def test_it_gives_the_bytes_of_the_app(self):
        # From `starColours` of frontend/src/lib/scene/starfield/colour.ts.
        bp_rp = np.array(
            [-1, -0.12, 0, 0.32, 0.5, 1, 1.6, 3, 5.1, 6, np.nan], np.float32
        )
        expected = [
            (147, 171, 255),
            (147, 171, 255),
            (166, 185, 255),
            (208, 213, 255),
            (241, 233, 255),
            (255, 208, 173),
            (255, 175, 110),
            (255, 131, 49),
            (255, 91, 14),
            (255, 91, 14),
            (255, 255, 255),
        ]
        rgb = colour.star_colours(bp_rp.astype(np.float64))
        assert np.array_equal(np.floor(rgb * 255 + 0.5), np.array(expected))


def _byte(bound: float) -> float:
    """The bound as the shader reads it from `dustBounds`."""
    return np.floor(min(bound, 16.0) / 16.0 * 255.0 + 0.5) / 255.0 * 16.0


class TestDustBound:
    # The same cases are in frontend/src/lib/scene/dust/extinction.test.ts, so the
    # grid and the shader take out the same dust.
    @pytest.mark.parametrize(
        ("bp_rp", "mag", "bound"),
        [
            (1.0, 5.0, 1.3 / 0.447),
            (5.37, -5.8, (-5.8 + 10) / 0.825),
            (np.nan, 3.0, 0.0),
            (-1.0, 3.0, 0.0),
            (2.0, -12.0, 0.0),
            (9.0, 10.0, 16.0),
        ],
        ids=["colour", "brightness", "no colour", "bluest", "brightest", "byte top"],
    )
    def test_the_bound_is_the_shader_form(self, bp_rp, mag, bound):
        got = light.dust_bound(np.array([bp_rp]), np.array([mag]))
        assert got[0] == pytest.approx(_byte(bound), abs=1e-12)

    def test_the_bound_is_the_byte_of_float32_inputs(self):
        # The tree's colour and magnitude are float32, as the shader's inputs.
        rng = np.random.default_rng(8)
        bp_rp = rng.uniform(-0.5, 8, 10000).astype(np.float32)
        mag = rng.uniform(-12, 15, 10000).astype(np.float32)
        got = light.dust_bound(bp_rp, mag) / 16.0 * 255.0
        assert np.allclose(got, np.rint(got), atol=1e-9)
        assert got.min() >= 0 and got.max() <= 255

    def test_a_star_with_no_colour_gains_nothing(self):
        taken = light.taken_out(np.array([3.0]), np.array([np.nan]), np.array([5.0]))
        assert taken[0] == 0.0

    def test_a_star_within_the_bound_gives_back_its_column(self):
        taken = light.taken_out(np.array([0.4]), np.array([1.0]), np.array([5.0]))
        assert taken[0] == 0.4

    def test_a_star_past_the_colour_bound_stops_there(self):
        taken = light.taken_out(np.array([9.0]), np.array([0.147]), np.array([5.0]))
        assert taken[0] == pytest.approx(_byte(1.0))

    def test_a_red_star_stops_at_the_brightest_star_there_is(self):
        # BP - RP 5.37 allows 12.7 mag by colour alone. M0 stops at BRIGHTEST_M0,
        # within half a step of the byte.
        mag, column = -5.8, 10.45
        taken = light.taken_out(np.array([column]), np.array([5.37]), np.array([mag]))
        m0 = light.dust_free_magnitude(np.array([mag]), taken)[0]
        step = light.K_G * light.BOUND_MAX / 255.0
        assert m0 == pytest.approx(light.BRIGHTEST_M0, abs=step / 2)

    def test_the_sun_reads_no_change(self):
        # At the Sun the change is 0, and a bound is never negative.
        rng = np.random.default_rng(3)
        bound = light.dust_bound(rng.uniform(-1.5, 6, 1000), rng.uniform(-14, 12, 1000))
        assert (np.maximum(0.0, -bound) == 0.0).all()


class TestStarFlux:
    def test_the_same_column_back_gives_the_star_as_seen(self):
        mag = np.array([2.0])
        tint = np.array([[1.0, 0.8, 0.6]])
        column = 1.7
        flux = light.star_flux(mag, tint, np.array([column]))
        seen = flux * 10.0 ** (-0.4 * light.K_RGB * column)
        assert seen == pytest.approx(tint * 10.0 ** (-0.4 * mag[0]))

    def test_m0_and_the_limit_rule_agree(self):
        """From the Sun, a star within the bound is fainter than the cut when it is
        fainter than the limit."""
        mag, column, modulus, limit = 3.0, 1.2, 9.0, 11.5
        m0 = light.dust_free_magnitude(np.array([mag]), np.array([column]))[0]
        cut = limit - modulus - light.K_G * column
        assert (m0 > cut) == (mag + modulus > limit)


class TestSkyMap:
    def test_a_read_gives_the_texel_direction_back(self):
        rng = np.random.default_rng(1)
        d = rng.normal(size=(2000, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        u, v = sky_map.map_uv(d)
        assert sky_map.uv_directions(u, v) == pytest.approx(d, abs=1e-9)

    def test_the_ring_holds_the_rays_past_the_fold(self):
        size = 8
        u = np.array([0.5 / size])
        v = np.array([3.5 / size])
        ring = sky_map.uv_directions(u, v, size)
        back = sky_map.uv_directions(*sky_map.map_uv(ring, size), size)
        assert back == pytest.approx(ring, abs=1e-9)

    def test_the_jitter_is_that_of_the_app(self):
        assert [sky_map.pass_jitter(i, 8) for i in range(4)] == [
            0.0625,
            0.5625,
            0.3125,
            0.8125,
        ]

    def test_a_ray_leaves_the_box_where_the_box_ends(self):
        near, far = sky_map.box_span(np.zeros(3), np.array([[0.0, 0.0, 1.0]]))
        assert near[0] == 0.0
        assert far[0] == pytest.approx(3000.0, abs=1e-2)

    def _flat_nest(self, density: float) -> sky_map.Nest:
        floor = 1e-6
        top = density
        span = float(np.log1p(top / floor))
        level = sky_map.NestLevel(
            sky_map.BOX,
            np.array((4, 4, 4)),
            floor,
            span,
            np.full((4, 4, 4), 255, np.uint8),
        )
        return sky_map.Nest((level,), np.eye(3), "t")

    def test_a_column_through_even_dust_is_density_times_length(self):
        nest = self._flat_nest(0.001)
        sky = sky_map.build_map(nest, np.zeros(3), 2)
        at = np.array([[100.0, 0.0, 0.0], [0.0, 2000.0, 100.0], [30.0, 40.0, -50.0]])
        got = sky_map.read_map(sky, np.zeros(3), at)
        want = np.linalg.norm(at, axis=1) * 0.001
        # A read is linear between slices that are even in the log: up to 1% high.
        assert got == pytest.approx(want, rel=0.015)

    def test_the_map_saturates_past_the_box(self):
        nest = self._flat_nest(0.001)
        sky = sky_map.build_map(nest, np.zeros(3), 2)
        got = sky_map.read_map(sky, np.zeros(3), np.array([[0.0, 0.0, 50_000.0]]))
        assert got[0] == pytest.approx(3.0, rel=1e-3)
