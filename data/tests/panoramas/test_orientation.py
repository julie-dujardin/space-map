import numpy as np
import pytest
from PIL import Image

from space_map_data.panoramas import orientation

WIDTH, HEIGHT = 512, 256


def _sphere(path, horizon, *, roll=0, sky=230, ground=60):
    """A sphere texture whose horizon row follows `horizon` per column."""
    rows = np.arange(HEIGHT)[:, None]
    limit = np.roll(np.asarray(horizon), roll)[None, :]
    value = np.where(rows < limit, sky, ground).astype(np.uint8)
    rgba = np.dstack([value] * 3 + [np.full_like(value, 255)])
    Image.fromarray(rgba).save(path, lossless=True)


def _terrain(seed=0):
    generator = np.random.default_rng(seed)
    shape = generator.normal(size=WIDTH)
    smooth = np.convolve(np.tile(shape, 3), np.ones(21) / 21, "same")[WIDTH : 2 * WIDTH]
    return np.rint(HEIGHT / 2 + smooth * 18).astype(int)


class TestSkyline:
    """The horizon row the matcher reads off a sphere texture."""

    def test_it_follows_the_sky_and_ground_boundary(self, tmp_path):
        horizon = _terrain()
        path = tmp_path / "a.webp"
        _sphere(path, horizon)
        assert np.allclose(orientation.skyline(path, smooth=1), horizon, atol=1)

    def test_an_empty_texture_reads_nothing(self, tmp_path):
        path = tmp_path / "blank.webp"
        Image.fromarray(np.zeros((HEIGHT, WIDTH, 4), np.uint8)).save(
            path, lossless=True
        )
        assert np.isnan(orientation.skyline(path)).all()


class TestMatch:
    """Recovering how far a strip is turned from a north-referenced sphere."""

    @pytest.mark.parametrize("roll", [0, 64, 200, 400])
    def test_it_recovers_the_turn(self, tmp_path, roll):
        horizon = _terrain()
        reference, strip = tmp_path / "ref.webp", tmp_path / "strip.webp"
        _sphere(reference, horizon)
        # The strip is the same skyline turned, and tone-mapped differently.
        _sphere(strip, horizon, roll=-roll, sky=200, ground=90)
        degrees, score = orientation.match(reference, strip)
        error = (degrees - roll * 360 / WIDTH + 180) % 360 - 180
        assert error == pytest.approx(0, abs=1.5)
        assert score > 0.9

    def test_unrelated_terrain_scores_poorly(self, tmp_path):
        reference, strip = tmp_path / "ref.webp", tmp_path / "strip.webp"
        _sphere(reference, _terrain(1))
        _sphere(strip, _terrain(2))
        assert orientation.match(reference, strip)[1] < 0.7


class TestGroundDistance:
    """How far apart two panoramas stood."""

    def test_a_degree_of_latitude_spans_the_expected_arc(self):
        first = {"latitude": 0.0, "longitude": 0.0}
        second = {"latitude": 1.0, "longitude": 0.0}
        expected = orientation.BODY_RADIUS_M * np.deg2rad(1)
        assert orientation.ground_distance(first, second) == pytest.approx(expected)

    def test_longitude_shrinks_towards_the_pole(self):
        at_equator = orientation.ground_distance(
            {"latitude": 0.0, "longitude": 0.0}, {"latitude": 0.0, "longitude": 1.0}
        )
        at_sixty = orientation.ground_distance(
            {"latitude": 60.0, "longitude": 0.0}, {"latitude": 60.0, "longitude": 1.0}
        )
        assert at_sixty == pytest.approx(at_equator / 2, rel=0.01)
