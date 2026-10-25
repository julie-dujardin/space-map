import numpy as np
import pyarrow as pa
import pytest

from space_map_data.extrasolar.ids import encode
from space_map_data.extrasolar.match import Pairs, PositionMatcher, assign
from space_map_data.extrasolar.tables import (
    ColumnGroup,
    TableDef,
    merge_by_source_order,
)
from tests.extrasolar.conftest import POINT


class TestMerge:
    """One row per ID, each group from the first source that has it."""

    def test_source_order(self):
        a, b, c = (encode(0, 1, cell) for cell in (500, 20, 7))
        rows = pa.table(
            {
                "id": [a, a, b, c],
                "source": ["hip", "gaia", "hip", "gaia"],
                "ra": [1.0, 2.0, 3.0, None],
                "dec": [1.0, 2.0, 3.0, None],
                "parallax": pa.array([1, 2, 3, None], pa.float32()),
                "g": pa.array([None, None, None, None], pa.float32()),
                "hp": pa.array([9, None, 8, None], pa.float32()),
            }
        )
        merged = merge_by_source_order(POINT, rows)
        # c has no value in any group, so it has no row; rows sort by cell.
        assert merged["id"].to_pylist() == [b, a]
        assert merged["ra"].to_pylist() == [3.0, 2.0]
        assert merged["astrometry_source"].to_pylist() == ["hip", "gaia"]
        assert merged["photometry_source"].to_pylist() == [None, None]
        assert merged["hp"].to_pylist() == [8.0, 9.0]
        assert merged["hip_photometry_source"].to_pylist() == ["hip", "hip"]
        assert merged.schema.names == POINT.schema.names

    def test_a_source_outside_the_order_is_ignored(self):
        rows = pa.table(
            {
                "id": [encode(0, 1, 3)],
                "source": ["other"],
                "ra": [1.0],
                "dec": [1.0],
                "parallax": pa.array([1], pa.float32()),
                "g": pa.array([1], pa.float32()),
                "hp": pa.array([1], pa.float32()),
            }
        )
        assert merge_by_source_order(POINT, rows).num_rows == 0

    def test_definition_checks(self):
        group = ColumnGroup("a", (pa.field("x", pa.float32()),), ("s",))
        with pytest.raises(ValueError):
            TableDef(31, "bad", (group,))
        with pytest.raises(ValueError):
            TableDef(2, "twice", (group, ColumnGroup("b", group.columns, ("s",))))


def _pairs(separation, row_mag=np.nan, key_mag=np.nan, row_kind=None, key_kind=None):
    n = len(separation)
    return Pairs(
        separation=np.asarray(separation, float),
        row_error=np.full(n, 0.3),
        row_size=np.full(n, np.nan),
        row_mag=np.full(n, row_mag),
        row_kind=pa.array([row_kind] * n, pa.string()),
        key_error=np.full(n, 0.4),
        key_size=np.full(n, np.nan),
        key_mag=np.full(n, key_mag),
        key_kind=pa.array([key_kind] * n, pa.string()),
    )


class TestMatcher:
    """Position scores and the mutual best assignment."""

    def test_radius_grows_with_error_and_size(self):
        matcher = PositionMatcher(reach=0.0)
        small, large = matcher.radius(np.array([0.5, 0.5]), np.array([np.nan, 30.0]))
        assert small == pytest.approx(2.5)
        assert large > 150

    def test_score(self):
        matcher = PositionMatcher()
        # Combined error 0.5″: 1″ is 2σ, 2″ is 4σ, 3″ is 6σ.
        near, far, beyond = matcher.score(_pairs([1.0, 2.0, 3.0]))
        assert np.isfinite(near) and np.isnan(far) and np.isnan(beyond)
        far_with_mags = matcher.score(_pairs([2.0], 10.0, 10.2))[0]
        assert np.isfinite(far_with_mags) and far_with_mags > near
        assert np.isnan(matcher.score(_pairs([0.1], 10.0, 12.0))[0])

    def test_a_close_pair_needs_no_magnitudes(self):
        matcher = PositionMatcher(near_sigma=0.0, near_arcsec=0.3)
        close, far = matcher.score(_pairs([0.2, 0.4]))
        assert np.isfinite(close) and np.isnan(far)
        assert np.isfinite(matcher.score(_pairs([0.4], 10.0, 10.2))[0])

    def test_kinds(self):
        matcher = PositionMatcher(kinds=frozenset({("quasar", "star")}))
        assert np.isnan(
            matcher.score(_pairs([0.1], row_kind="galaxy", key_kind="star"))
        )
        assert np.isfinite(
            matcher.score(_pairs([0.1], row_kind="quasar", key_kind="star"))
        )
        assert np.isfinite(matcher.score(_pairs([0.1], row_kind=None, key_kind="star")))

    def test_assign_is_mutual(self):
        row = np.array([1, 2, 2, 3])
        key = np.array([10, 10, 20, 20])
        score = np.array([1.0, 0.5, 2.0, 3.0])
        kept = assign(row, key, score)
        # Row 2 takes key 10 (best for both); row 3 then takes key 20.
        assert sorted(zip(row[kept].tolist(), key[kept].tolist())) == [(2, 10), (3, 20)]

    def test_assign_equals_greedy(self):
        rng = np.random.default_rng(3)
        row = rng.integers(0, 40, 400)
        key = rng.integers(0, 40, 400)
        score = rng.uniform(0, 1, 400)
        score[rng.uniform(size=400) < 0.1] = np.nan
        order = np.lexsort((key, row, score))
        used_rows, used_keys, greedy = set(), set(), set()
        for at in order:
            if np.isnan(score[at]) or row[at] in used_rows or key[at] in used_keys:
                continue
            used_rows.add(row[at])
            used_keys.add(key[at])
            greedy.add(at)
        assert set(assign(row, key, score).tolist()) == greedy
