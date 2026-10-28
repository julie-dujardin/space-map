"""The class order of Metadata and the kind of a system node."""

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar.match import SYSTEM_KIND, Pairs, PositionMatcher
from space_map_data.extrasolar.tables import METADATA, merge_by_source_order


class TestClassOrder:
    """A specific class wins over "binary star", which wins over "star"."""

    @staticmethod
    def merged(rows: list[tuple[str, str]]) -> tuple[str, str]:
        table = pa.table(
            {
                "id": pa.array([1] * len(rows), pa.int64()),
                "source": [source for source, _ in rows],
                "name": pa.nulls(len(rows), pa.string()),
                "class": [name for _, name in rows],
            }
        )
        (row,) = merge_by_source_order(METADATA, table).to_pylist()
        return row["class"], row["class_source"]

    def test_a_white_dwarf_of_simbad_beats_the_default_of_a_host(self):
        rows = [
            ("nasa-exoplanet-archive", "star"),
            ("simbad", "white dwarf"),
            ("gaia-dr3", "star"),
        ]
        assert self.merged(rows) == ("white dwarf", "simbad")

    def test_a_pulsar_that_holds_two_stars_stays_a_pulsar(self):
        rows = [
            ("nasa-exoplanet-archive", "pulsar"),
            ("gaia-dr3", "star"),
            ("star-systems", "binary star"),
        ]
        assert self.merged(rows) == ("pulsar", "nasa-exoplanet-archive")

    def test_a_star_that_holds_two_stars_is_a_binary_star(self):
        rows = [("hipparcos-2007", "star"), ("star-systems", "binary star")]
        assert self.merged(rows) == ("binary star", "star-systems")
        assert self.merged([("simbad", "star")]) == ("star", "simbad")


class TestSystemKind:
    """A system node is never the match of a star, also with no kind."""

    def test_kinds(self):
        matcher = PositionMatcher()
        n = 4
        pairs = Pairs(
            separation=np.zeros(n),
            row_error=np.full(n, 0.1),
            row_size=np.full(n, np.nan),
            row_mag=np.full(n, np.nan),
            row_kind=pa.array(["star", None, SYSTEM_KIND, "star"]),
            key_error=np.full(n, 0.1),
            key_size=np.full(n, np.nan),
            key_mag=np.full(n, np.nan),
            key_kind=pa.array([SYSTEM_KIND, SYSTEM_KIND, SYSTEM_KIND, None]),
        )
        score = matcher.score(pairs)
        assert np.isnan(score[:2]).all()
        assert np.isfinite(score[2:]).all()
