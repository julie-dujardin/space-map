"""Recovering angular geometry from the grids printed on Mastcam-Z releases."""

import pytest

from space_map_data.panoramas.grid_geometry import fit_axis, fit_offset


def labelled(slope, offset, rows):
    """Printed elevations on a grid of a given scale, as OCR reports them."""
    return [(y, y * slope + offset) for y in rows]


class TestFittingAnAxisOnItsOwn:
    """Slope and offset together need enough labels spread far enough apart to
    tell a real grid from a pair of misreads."""

    def test_three_spread_labels_fit(self):
        slope, offset, count = fit_axis(labelled(-0.05, 10.0, [0, 100, 200]), 200)

        assert slope == pytest.approx(-0.05)
        assert offset == pytest.approx(10.0)
        assert count == 3

    def test_two_labels_are_too_few(self):
        with pytest.raises(ValueError, match="Too few readable grid labels"):
            fit_axis(labelled(-0.05, 10.0, [0, 200]), 200)


class TestBorrowingTheScaleFromTheOtherAxis:
    """A narrow strip prints too few elevations to fit a line, but the grid is
    square, so the azimuth axis already states the degrees per pixel."""

    def test_two_agreeing_labels_fix_the_offset(self):
        slope, offset, count = fit_offset(labelled(-0.04, 3.5, [20, 180]), -0.04)

        assert slope == pytest.approx(-0.04)
        assert offset == pytest.approx(3.5)
        assert count == 2

    def test_one_label_is_not_corroborated(self):
        """Borrowing the scale leaves the labels agreeing with each other as
        the only check, and a lone label agrees with nothing."""
        with pytest.raises(ValueError, match="Too few readable grid labels"):
            fit_offset(labelled(-0.04, 3.5, [20]), -0.04)

    def test_the_same_row_read_twice_is_still_one_label(self):
        """Every elevation is printed at both edges, so a pair at one height is
        one measurement repeated, not two that agree."""
        points = [(20.0, 2.7), (20.0, 2.7)]

        with pytest.raises(ValueError, match="Too few readable grid labels"):
            fit_offset(points, -0.04)

    def test_labels_that_disagree_are_refused(self):
        points = labelled(-0.04, 3.5, [20, 180])
        points.append((100.0, 28.0))

        with pytest.raises(ValueError, match="disagree on where the grid starts"):
            fit_offset(points, -0.04)

    def test_a_single_misread_among_many_is_outvoted(self):
        """One wrong digit moves an offset by whole degrees; the rest of the
        grid still agrees on where it starts."""
        points = labelled(-0.04, 3.5, [20, 60, 100, 140, 180])
        points.append((90.0, 41.0))

        slope, offset, count = fit_offset(points, -0.04)

        assert offset == pytest.approx(3.5)
        assert count == 5
