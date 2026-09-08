import numpy as np
import pytest
from PIL import Image

from space_map_data.panoramas.strip_spheres import project_strip


def test_partial_strip_leaves_gap_and_poles_empty():
    source = Image.new("RGB", (580, 100), (140, 90, 40))
    sphere, percent = project_strip(source, 290, 0.5, width=360)
    alpha = np.asarray(sphere)[:, :, 3]
    assert not alpha[:, 290:].any()
    assert not alpha[0].any()
    assert not alpha[-1].any()
    assert alpha[90, :290].all()
    assert 0 < percent < 290 / 360 * 100


def test_black_holes_are_not_filled():
    sphere, percent = project_strip(Image.new("RGB", (360, 100)), 360, 0.5, width=360)
    assert percent == 0
    assert not np.asarray(sphere)[:, :, 3].any()


def test_invalid_sweep_rejected():
    with pytest.raises(ValueError):
        project_strip(Image.new("RGB", (100, 100)), 400, 0.5)
