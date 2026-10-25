"""Tests for the one placement rule of the export and the ingest report."""

import pyarrow as pa

from space_map_data.extrasolar.placement import placement

GAIA, NAMED, ARCHIVE = "gaia-dr3", "gaia-dr3-named", "nasa-exoplanet-archive"


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
    floats = pa.float32()
    table = pa.table(
        {
            "astrometry_source": pa.array(columns[0], pa.string()),
            "parallax": pa.array(columns[1], floats),
            "parallax_error": pa.array(columns[2], floats),
            "fidelity_v2": pa.array(columns[3], floats),
            "hipparcos_photometry_source": pa.array(columns[4], pa.string()),
            "simbad_photometry_source": pa.array(columns[5], pa.string()),
            "host_distance": pa.array(columns[6], floats),
            "host_star_source": pa.array(
                [ARCHIVE if d else None for d in columns[6]], pa.string()
            ),
            "distance": pa.array(columns[7], floats),
            "distance_source": pa.array(columns[8], pa.string()),
        }
    )
    found = placement(table)
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
