"""Tests for the split of the rest scale into a smooth base and a near factor."""

import numpy as np
import pytest

from space_map_data.dust import rest

SIGHTLINES = 12 * 4**7


def _profiles(room: np.ndarray) -> np.ndarray:
    """Room spread evenly over the first 100 bins of each sightline."""
    profiles = np.zeros((len(room), rest.PROFILE_BINS), np.float32)
    profiles[:, :100] = (room / 100.0)[:, None]
    return profiles


class TestAtShare:
    def test_distances_where_the_room_reaches_a_share(self):
        profiles = _profiles(np.array([100.0, 50.0]))
        at = rest.at_share(profiles, 0.25)
        assert at == pytest.approx([2500.0, 2500.0])
        assert rest.at_share(profiles, 0.5)[0] == pytest.approx(5000.0)


class TestSmoothBase:
    def test_a_uniform_scale_is_its_own_base(self):
        scale = np.full(SIGHTLINES, 2e-3)
        room = np.full(SIGHTLINES, 1e4)
        seen = np.full(SIGHTLINES, 1.0)
        base = rest.smooth_base(scale, seen, room)
        assert np.median(base) == pytest.approx(2e-3, rel=1e-3)


class TestSplitField:
    # Once: a split of the whole sky takes seconds, and no test changes it.
    @pytest.fixture(scope="class")
    def split(self):
        rng = np.random.default_rng(5)
        scale = 1e-3 * np.exp(rng.normal(0.0, 0.15, SIGHTLINES))
        room = np.full(SIGHTLINES, 1e4)
        seen = np.full(SIGHTLINES, 2.0)
        return scale, seen, room, rest.split_field(scale, seen, room, _profiles(room))

    def test_each_sightline_keeps_its_column(self, split):
        scale, _, room, (field, placed) = split
        unclipped = (field[1] > 0) & (field[1] < rest.MAX_NEAR_FACTOR)
        assert unclipped.mean() > 0.99
        assert placed[unclipped] == pytest.approx(scale[unclipped] * room[unclipped])

    def test_the_base_is_smoother_than_the_scale(self, split):
        scale, _, _, (field, _) = split
        assert np.std(np.log(field[0])) < 0.2 * np.std(np.log(scale))

    def test_the_window_covers_the_first_part_of_the_room(self, split):
        _, _, _, (field, _) = split
        start, end = field[2], field[3]
        assert np.median(start) == pytest.approx(2500.0)
        assert np.median(end) == pytest.approx(5000.0)

    def test_the_scale_far_past_the_window_is_the_base(self, split):
        _, _, _, (field, _) = split
        x, y, z = np.array([[18_000.0], [0.0], [0.0]])
        no_factor = field.copy()
        no_factor[1] = 1.0
        assert rest.scale_at(field, x, y, z) == pytest.approx(
            rest.scale_at(no_factor, x, y, z), rel=1e-6
        )
