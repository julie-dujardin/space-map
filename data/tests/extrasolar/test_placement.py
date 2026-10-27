"""Tests for the one placement rule of the export and the ingest report."""

from collections.abc import Sequence

import pyarrow as pa

from space_map_data.extrasolar.placement import COLUMNS, placement

GAIA, NAMED, ARCHIVE = "gaia-dr3", "gaia-dr3-named", "nasa-exoplanet-archive"
HIPPARCOS, SIMBAD = "hipparcos-2007", "simbad"
NUMBERS = {
    "parallax",
    "parallax_error",
    "fidelity_v2",
    "distance",
    "distance_lower",
    "distance_upper",
    "host_distance",
}


def table(**columns: Sequence) -> pa.Table:
    """The columns that `placement` reads, null where not given."""
    n = len(next(iter(columns.values())))
    return pa.table(
        {
            name: pa.array(
                columns.get(name, [None] * n),
                pa.float32() if name in NUMBERS else pa.string(),
            )
            for name in COLUMNS
        }
    )


def test_the_steps_in_order():
    rows = [
        # (astrometry, parallax, error, fidelity, Hipparcos, SIMBAD, host
        #  distance, distance, distance source)
        (GAIA, 10.0, 0.1, 0.9, None, None, None, None, None),
        # A flagged host at its catalogue distance.
        (GAIA, 10.0, 0.1, 0.2, None, None, 50.0, None, None),
        # A flagged star that Hipparcos saw, at its suspect parallax.
        (GAIA, 10.0, 0.1, 0.2, "hipparcos-2007", None, None, None, None),
        (ARCHIVE, 1.0, 1.0, None, None, None, 300.0, None, None),
        (None, None, None, None, None, None, 4000.0, None, None),
        (GAIA, 1.0, 1.0, None, None, None, None, None, None),
        # A flagged star that no other catalogue saw.
        (GAIA, 10.0, 0.1, 0.2, None, None, None, None, None),
        (NAMED, 1.0, 1.0, 0.9, None, None, None, 200.0, "bailer-jones-2021"),
        # A distance from a paper comes before a good parallax.
        (GAIA, 10.0, 0.1, 0.9, None, None, None, 300.0, "literature"),
        # The distance group comes before the catalogue distance.
        (GAIA, 10.0, 0.1, 0.2, None, "simbad", 50.0, 400.0, "reyle-2021"),
    ]
    columns = list(zip(*rows, strict=True))
    found = placement(
        table(
            astrometry_source=columns[0],
            parallax=columns[1],
            parallax_error=columns[2],
            fidelity_v2=columns[3],
            hipparcos_photometry_source=columns[4],
            simbad_photometry_source=columns[5],
            host_distance=columns[6],
            host_star_source=[ARCHIVE if d else None for d in columns[6]],
            distance=columns[7],
            distance_source=columns[8],
        )
    )
    assert found.positioned.tolist() == [
        True,
        True,
        True,
        False,
        False,
        False,
        True,
        False,
        True,
        True,
    ]
    assert found.flagged.tolist() == [
        False,
        True,
        True,
        False,
        False,
        False,
        True,
        False,
        False,
        True,
    ]
    assert found.by_parallax.nonzero()[0].tolist() == [0]
    assert found.by_group.nonzero()[0].tolist() == [7, 8, 9]
    assert found.by_catalogue.nonzero()[0].tolist() == [1, 3, 4]
    assert found.by_suspect.nonzero()[0].tolist() == [2]
    assert (~found.placed).nonzero()[0].tolist() == [5, 6]


def test_a_more_precise_measured_parallax_in_the_group_wins():
    rows = [
        # (astrometry, parallax, error, distance, lower, upper, source, method)
        # α Cen B: Hipparcos 2007 ±3%, the 10 pc sample ±0.2%.
        (HIPPARCOS, 796.92, 25.9, 1.3459, 1.3435, 1.3483, "reyle-2021", "parallax"),
        (HIPPARCOS, 10.0, 0.1, 100.0, 95.0, 105.0, "reyle-2021", "parallax"),
        # Against Gaia astrometry, the group must be twice as precise.
        (GAIA, 10.0, 0.5, 100.0, 99.0, 101.0, "reyle-2021", "parallax"),
        (GAIA, 10.0, 0.15, 100.0, 99.0, 101.0, "ultracoolsheet", "parallax"),
        (SIMBAD, 10.0, 0.15, 100.0, 99.0, 101.0, "ultracoolsheet", "parallax"),
        # SIMBAD's parallax is Gaia DR2's.
        (HIPPARCOS, 10.0, 0.5, 100.0, 99.0, 101.0, "simbad-parallax", "parallax"),
        # A distance from a prior or from a cluster stays below the parallax.
        (GAIA, 10.0, 0.5, 100.0, 99.0, 101.0, "bailer-jones-2021", "geometric"),
        (GAIA, 10.0, 0.5, 100.0, 99.0, 101.0, "hunt-reffert-2024", "cluster"),
        # Without both bounds, the group's error is unknown.
        (GAIA, 10.0, 0.5, 100.0, None, 101.0, "ultracoolsheet", "parallax"),
    ]
    columns = list(zip(*rows, strict=True))
    found = placement(
        table(
            astrometry_source=columns[0],
            parallax=columns[1],
            parallax_error=columns[2],
            fidelity_v2=[0.9] * len(rows),
            distance=columns[3],
            distance_lower=columns[4],
            distance_upper=columns[5],
            distance_source=columns[6],
            distance_method=columns[7],
        )
    )
    assert found.by_group.nonzero()[0].tolist() == [0, 2, 4]
    assert found.by_parallax.nonzero()[0].tolist() == [1, 3, 5, 6, 7, 8]
