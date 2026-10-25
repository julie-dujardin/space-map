"""Tests for the one placement rule of the export and the ingest report."""

import pyarrow as pa

from space_map_data.extrasolar.placement import placement


def test_parallax_fidelity_hipparcos_and_catalogue_distance():
    rows = pa.table(
        {
            "parallax": pa.array([10.0, 10.0, 10.0, 1.0, None, 1.0], pa.float32()),
            "parallax_error": pa.array([0.1, 0.1, 0.1, 1.0, None, 1.0], pa.float32()),
            "fidelity_v2": pa.array([0.9, 0.2, 0.2, None, None, None], pa.float32()),
            "hipparcos_photometry_source": pa.array(
                [None, None, "hipparcos-2007", None, None, None], pa.string()
            ),
            "host_distance": pa.array(
                [None, 50.0, None, 300.0, 4000.0, None], pa.float32()
            ),
        }
    )
    found = placement(rows)
    assert found.positioned.tolist() == [True, True, True, False, False, False]
    # A spurious Gaia source does not have a Hipparcos match.
    assert found.by_parallax.tolist() == [True, False, True, False, False, False]
    assert found.by_catalogue.tolist() == [False, True, False, True, True, False]
