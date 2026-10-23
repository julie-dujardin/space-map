import numpy as np
import pytest

from space_map_data.extrasolar import ids, sky
from space_map_data.extrasolar.ids import CELL_COUNT, MAX_ID, MAX_SERIAL
from tests.extrasolar.conftest import offset


class TestIds:
    """The ID layout: encode, decode, bounds and the URL check."""

    def test_round_trip_arrays(self):
        rng = np.random.default_rng(1)
        serial = rng.integers(0, MAX_SERIAL + 1, 10_000)
        table = rng.integers(1, 31, 10_000)
        cell = rng.integers(0, CELL_COUNT, 10_000)
        encoded = ids.encode(serial, table, cell)
        assert (encoded > 0).all() and (encoded <= MAX_ID).all()
        back = ids.decode(encoded)
        assert (back[0] == serial).all()
        assert (back[1] == table).all()
        assert (back[2] == cell).all()

    def test_round_trip_int(self):
        id_ = ids.encode(3, 1, 12345)
        assert id_ == 3 * 2**29 + 2**24 + 12345
        assert ids.decode(id_) == (3, 1, 12345)

    def test_extremes(self):
        assert ids.encode(MAX_SERIAL, 30, CELL_COUNT - 1) <= MAX_ID
        assert ids.encode(0, 1, 0) == 2**24

    @pytest.mark.parametrize(
        "serial,table,cell",
        [
            (0, 0, 0),
            (0, 31, 0),
            (0, 1, CELL_COUNT),
            (-1, 1, 0),
            (MAX_SERIAL + 1, 1, 0),
        ],
    )
    def test_bounds(self, serial, table, cell):
        with pytest.raises(ValueError):
            ids.encode(serial, table, cell)

    def test_parse(self):
        good = ids.encode(7, 1, 4242)
        assert ids.parse(str(good), {1}) == good
        assert ids.parse(str(good), {2}) is None
        for text in ("0", "01", "-5", "12a", "", " 1", str(2**53)):
            assert ids.parse(text, {1}) is None
        # Cell 12,582,912 and above is not a cell.
        assert ids.parse(str(2**24 + CELL_COUNT), {1}) is None


class TestCells:
    """HEALPix cells against healpy and the disc cover."""

    def test_reference_cells(self):
        # healpy.ang2pix(1024, ra, dec, nest=True, lonlat=True)
        points = [
            (0.0, 0.0, 4980736),
            (101.28715533, -16.71611586, 5360653),
            (279.23473479, 38.78368896, 3816046),
            (266.4168, -29.0078, 7380516),
            (10.6847, 41.2690, 693522),
            (359.9999, 89.9999, 4194303),
            (180.0, -89.9999, 10485760),
            (45.0, 41.81, 262143),
            (201.365, -43.019, 11075289),
            (83.8221, -5.3911, 5488553),
            (0.0001, -0.0001, 4456447),
            (123.456, 78.9, 2071607),
        ]
        ra, dec, expected = (np.array(column) for column in zip(*points))
        assert sky.cells(ra, dec).tolist() == expected.tolist()

    def test_regions(self):
        assert sky.REGION_COUNT == 768
        low, high = sky.region_cells(5)
        assert sky.region_of(low) == 5 and sky.region_of(high - 1) == 5
        assert sky.region_of(high) == 6
        neighbours = sky.neighbour_regions(0)
        assert 0 not in neighbours and 7 <= len(neighbours) <= 8

    @pytest.mark.parametrize("level", [sky.MATCH_LEVEL, 10])
    def test_disc_ranges_hold_the_disc(self, level):
        rng = np.random.default_rng(2)
        n = 3000
        ra = rng.uniform(0, 360, n)
        dec = np.degrees(np.arcsin(rng.uniform(-1, 1, n)))
        # Points near the poles and radii from a fraction of a cell to degrees.
        dec[:200] = np.sign(dec[:200]) * rng.uniform(89, 90, 200)
        radius = 10 ** rng.uniform(-1, 4.5, n)
        row, low, high = sky.disc_ranges(ra, dec, radius, level)
        for k in range(8):
            angle = rng.uniform(0, 360, n)
            reach = radius * np.sqrt(rng.uniform(0, 1, n)) if k else radius * 0.999
            points = [offset(a, d, r, t) for a, d, r, t in zip(ra, dec, reach, angle)]
            cell = sky.cells(*map(np.array, zip(*points)), level=level)
            inside = (low <= cell[row]) & (cell[row] < high)
            covered = np.zeros(n, bool)
            np.logical_or.at(covered, row, inside)
            assert covered.all()

    def test_separation(self):
        ra, dec = offset(10.0, 20.0, 7.5, 33.0)
        assert sky.separation(10.0, 20.0, ra, dec) == pytest.approx(7.5, rel=1e-6)
