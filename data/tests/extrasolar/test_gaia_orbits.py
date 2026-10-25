"""Tests for the Gaia DR3 orbit solutions and masses of table 2."""

from collections.abc import Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from space_map_data.download.providers.stars import gaia_source
from space_map_data.extrasolar.sources import gaia_orbits
from space_map_data.extrasolar.sources.gaia_orbits import (
    SOLUTION_ORDER,
    Orbits,
    parse_vectors,
)
from space_map_data.extrasolar.tables import (
    BINARY_ORBIT,
    METADATA,
    NSS_ASTROMETRY,
    POINT_SOURCE,
)

# The published types of nss_two_body_orbit, as the download keeps them.
PUBLISHED_TYPES = {
    "solution_id": pa.int64(),
    "source_id": pa.int64(),
    "nss_solution_type": pa.string(),
    "bit_index": pa.int64(),
    "corr_vec": pa.string(),
    "flags": pa.int64(),
    "temperature_ratio_definition": pa.int8(),
}


def solutions(rows: list[dict]) -> pa.Table:
    """nss_two_body_orbit rows with every published column; the rest null."""
    names = ["source_id"] + [
        gaia_orbits.PUBLISHED.get(f.name, f.name)
        for f in gaia_orbits.ORBIT_GROUP.columns
    ]
    columns = {}
    for name in names:
        kind = PUBLISHED_TYPES.get(name)
        if kind is None:
            stored = BINARY_ORBIT.schema.field(NSS_ASTROMETRY.get(name, name)).type
            kind = pa.float64() if pa.types.is_floating(stored) else stored
        columns[name] = pa.array([row.get(name) for row in rows], kind)
    return pa.table(columns)


def solution(source_id: int, kind: str, **values) -> dict:
    return {
        "source_id": source_id,
        "nss_solution_type": kind,
        "solution_id": 4338096422163308546,
        "corr_vec": "[0.5,NaN,-0.25]",
        "period": 100.0 + source_id,
    } | values


def masses(rows: list[tuple[int, str, float]]) -> pa.Table:
    """binary_masses rows: source_id, combination method and m1."""
    columns = {}
    for field in gaia_orbits.MASS_GROUP.columns:
        columns[field.name] = pa.nulls(len(rows), field.type)
    columns["source_id"] = pa.array([r[0] for r in rows], pa.int64())
    columns["combination_method"] = pa.array([r[1] for r in rows], pa.string())
    columns["m1"] = pa.array([r[2] for r in rows], pa.float32())
    return pa.table(columns)


def build(rows: list[dict], mass_rows: Sequence[tuple[int, str, float]] = ()) -> Orbits:
    return Orbits.build(solutions(rows).column, masses(list(mass_rows)))


class TestTable:
    """The columns of table 2 against the published tables."""

    def test_every_published_column_is_stored(self):
        stored = set(BINARY_ORBIT.schema.names)
        published = set(solutions([]).column_names) - {"source_id"}
        renamed = {NSS_ASTROMETRY.get(name, name) for name in published}
        assert renamed <= stored
        assert len(published) == 76
        assert {"m1", "m2_upper", "fluxratio", "combination_method", "flag"} <= stored

    def test_the_astrometry_does_not_clash_with_point_source(self):
        names = {f.name for f in BINARY_ORBIT.group_fields}
        others = {f.name for t in (POINT_SOURCE, METADATA) for f in t.group_fields}
        assert not names & others
        assert NSS_ASTROMETRY["pmra_error"] == "pmra_nss_error"

    def test_every_solution_type_names_its_mass_terms(self):
        assert set(gaia_orbits.METHOD_TERMS) == set(SOLUTION_ORDER)
        assert len(set(SOLUTION_ORDER)) == 12


class TestVectors:
    """The published correlation vectors as float32 lists."""

    def test_nan_entries_stay_and_an_empty_vector_is_empty(self):
        parsed = parse_vectors(pa.array(["[1.5,NaN,-0.25]", "[]", None, "[3]"]))
        values = parsed.to_pylist()
        assert values[0][0] == 1.5 and np.isnan(values[0][1]) and values[0][2] == -0.25
        assert values[1:] == [[], None, [3.0]]
        assert parsed.type == pa.list_(pa.float32())


class TestSelection:
    """One solution per source, by the priority of the solution types."""

    def test_the_astrometric_solution_wins_and_the_others_are_listed(self):
        orbits = build(
            [
                solution(9, "SB1"),
                solution(5, "SB1"),
                solution(5, "Orbital", ra=10.0, parallax=2.5),
                solution(7, "EclipsingBinary"),
                solution(7, "SB2C"),
                solution(7, "OrbitalTargetedSearchValidated"),
                solution(8, "AstroSpectroSB1"),
                solution(8, "OrbitalTargetedSearchValidated"),
            ]
        )
        rows = orbits.rows
        assert rows["source_id"].to_pylist() == [5, 7, 8, 9]
        assert rows["nss_solution_type"].to_pylist() == [
            "Orbital",
            "OrbitalTargetedSearchValidated",
            "AstroSpectroSB1",
            "SB1",
        ]
        assert rows["left_out"].to_pylist() == [
            ["SB1"],
            ["SB2C", "EclipsingBinary"],
            ["OrbitalTargetedSearchValidated"],
            [],
        ]
        assert rows["ra_nss"][0].as_py() == 10.0
        assert rows["parallax_nss"][0].as_py() == 2.5
        assert rows["period"].to_pylist()[0] == 105.0
        assert orbits.counts["solutions"] == 8 and orbits.counts["sources"] == 4

    def test_large_integers_are_kept_exactly(self):
        flags = (1 << 57) | (1 << 6)
        rows = build([solution(1, "SB1", flags=flags, bit_index=127)]).rows
        assert rows["solution_id"].to_pylist() == [4338096422163308546]
        assert rows["flags"].to_pylist() == [flags]
        assert rows.schema.field("flags").type == pa.uint64()
        assert rows["bit_index"].to_pylist() == [127]

    def test_an_unknown_solution_type_stops_the_build(self):
        with pytest.raises(ValueError, match="no rank: \\['Triple'\\]"):
            build([solution(1, "Triple")])

    def test_no_solutions(self):
        orbits = build([])
        assert orbits.rows.num_rows == 0
        assert orbits.rows.schema.field("corr_vec").type == pa.list_(pa.float32())


class TestMasses:
    """The mass rows join by source; a second row names the kept solution."""

    def test_join(self):
        orbits = build(
            [
                solution(1, "Orbital"),
                solution(1, "SB2"),
                solution(2, "Orbital"),
                solution(2, "SB1"),
                solution(3, "AstroSpectroSB1"),
                solution(4, "SB1"),
            ],
            [
                (1, "SB2+M1", 0.5),
                (1, "Orbital+M1", 1.5),
                (2, "SB1+M1", 2.0),
                (3, "Orbital+M1", 3.0),
            ],
        )
        assert orbits.rows["m1"].to_pylist() == [1.5, 2.0, 3.0, None]
        assert orbits.rows["combination_method"].to_pylist() == [
            "Orbital+M1",
            "SB1+M1",
            "Orbital+M1",
            None,
        ]
        assert orbits.counts["mass_rows_left_out"] == 1
        # Source 2 keeps the Orbital solution and the SB1 masses.
        assert orbits.counts["masses_from_another_solution"] == 1

    def test_a_mass_row_without_a_solution_is_left_out(self):
        orbits = build([solution(1, "SB1")], [(1, "SB1+M1", 1.0), (2, "SB1+M1", 2.0)])
        assert orbits.rows["m1"].to_pylist() == [1.0]
        assert orbits.counts["mass_rows_without_solution"] == 1


class TestJoin:
    """The columns of table 2 on the stars, and the report of a pass."""

    def test_stars_without_an_orbit_get_nulls(self):
        orbits = build([solution(5, "Orbital"), solution(9, "SB1")])
        stars = pa.table({"source_id": pa.array([9, 4, 5], pa.int64())})
        joined = orbits.join(stars)
        assert joined["nss_solution_type"].to_pylist() == ["SB1", None, "Orbital"]
        assert joined["corr_vec"].to_pylist()[1] is None
        assert set(gaia_orbits.COLUMNS) <= set(joined.column_names)
        assert "left_out" not in joined.column_names

    def test_report_counts_rows_left_out_and_outside(self):
        pixel = 1234
        base = pixel << gaia_source.PIXEL_SHIFT
        orbits = build(
            [
                solution(base + 1, "Orbital"),
                solution(base + 1, "SB1"),
                solution(base + 2, "SB1"),
                solution(base + 3, "EclipsingBinary"),
                # In a chunk that was not read.
                solution((pixel + 10) << gaia_source.PIXEL_SHIFT, "SB1"),
            ]
        )
        report = orbits.report(np.array([base + 1, base + 2]), [(pixel, pixel + 1)])
        assert report["joined"] == 2
        assert report["joined_by_family"] == {"astrometric": 1, "spectroscopic": 1}
        assert report["left_out_by_pair"] == {"Orbital over SB1": 1}
        assert report["outside"] == 1
        assert report["outside_by_family"] == {"eclipsing": 1}


class TestRead:
    """The download's files, read one column at a time."""

    def test_read(self, tmp_path):
        pq.write_table(
            solutions([solution(1, "SB1"), solution(2, "Orbital")]),
            tmp_path / "NssTwoBodyOrbit_1.parquet",
        )
        pq.write_table(
            masses([(2, "Orbital+M1", 1.0)]), tmp_path / "BinaryMasses-001.parquet"
        )
        orbits = Orbits.read(tmp_path, tmp_path)
        assert orbits.rows["source_id"].to_pylist() == [1, 2]
        assert orbits.rows["m1"].to_pylist() == [None, 1.0]

    def test_missing_files(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="NssTwoBodyOrbit_"):
            Orbits.read(tmp_path, tmp_path)
