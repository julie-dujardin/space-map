"""Phoenix's horizon panoramas, read without the coordinate overlay drawn into
their pixels."""

import numpy as np

from space_map_data.panoramas.phoenix import read_label, read_pixels

LABEL = """PDS_VERSION_ID = PDS3
RECORD_BYTES = 720
^IMAGE = 4
PRODUCT_ID = S_020EDN_CYL_SR129F8_R888M1
START_TIME = 2008-06-15T10:25:17.917Z
STOP_TIME = 2008-06-15T11:24:30.991Z
OBJECT = IMAGE
  LINES = 60
  LINE_SAMPLES = 360
  SAMPLE_TYPE = MSB_INTEGER
  SAMPLE_BITS = 16
  BANDS = 1
  BAND_STORAGE_TYPE = BAND_SEQUENTIAL
  INVALID_CONSTANT = 0.0
  MISSING_CONSTANT = 0.0
END_OBJECT = IMAGE
GROUP = DERIVED_IMAGE_PARMS
  DERIVED_IMAGE_TYPE = IMAGE
END_GROUP = DERIVED_IMAGE_PARMS
GROUP = SURFACE_PROJECTION_PARMS
  MAP_PROJECTION_TYPE = CYLINDRICAL
  MAP_RESOLUTION = (1.0,1.0)
  REFERENCE_COORD_SYSTEM_INDEX = 0
  REFERENCE_COORD_SYSTEM_NAME = SITE_FRAME
  START_AZIMUTH = 0.0
  STOP_AZIMUTH = 360.0
  ZERO_ELEVATION_LINE = 10.5
END_GROUP = SURFACE_PROJECTION_PARMS
END
"""


def write_mosaic(tmp_path, pixels):
    path = tmp_path / "s_020edn_cyl_sr129f8_r888m1.img"
    header = LABEL.encode("latin-1").ljust(3 * 720, b" ")
    path.write_bytes(header + pixels.astype(">i2").tobytes())
    return path


def ground(height=60, width=360):
    """Brightness that grows down the picture, ten counts a line."""
    return np.broadcast_to(
        2000 + 10 * np.arange(height)[:, None], (height, width)
    ).copy()


class TestReadingTheLabel:
    """The label is attached to the raster and states everything but the sol,
    which the product name starts with."""

    def test_the_geometry_and_the_sol_are_read(self, tmp_path):
        mosaic = read_label(write_mosaic(tmp_path, ground()))

        assert (mosaic.width, mosaic.height, mosaic.sol) == (360, 60, 20)
        assert mosaic.frame == "SITE_FRAME"
        assert mosaic.offset == 3 * 720


class TestRemovingTheOverlay:
    """The grid crosses empty canvas, the numbers sit on the edges."""

    def test_grid_lines_over_empty_canvas_stay_empty(self, tmp_path):
        pixels = ground()
        pixels[:20] = 0
        pixels[:20, 100] = 4096
        path = write_mosaic(tmp_path, pixels)

        rgba, _ = read_pixels(path, read_label(path))

        assert not rgba[:20, 100, 3].any()
        assert rgba[30:, 100, 3].all()

    def test_numbers_inside_the_picture_are_filled_from_around_them(self, tmp_path):
        pixels = ground()
        pixels[30:35, 2:8] = 1
        pixels[29, 2:8] = 4096
        path = write_mosaic(tmp_path, pixels)

        rgba, _ = read_pixels(path, read_label(path))

        assert rgba[29:35, 2:8, 3].all()
        reference = rgba[29:35, 50:56, 0].astype(int)
        assert np.abs(rgba[29:35, 2:8, 0].astype(int) - reference).max() <= 25

    def test_rows_holding_numbers_along_the_bottom_are_dropped(self, tmp_path):
        pixels = ground()
        pixels[-6:-2, 50:56] = 1
        path = write_mosaic(tmp_path, pixels)

        rgba, _ = read_pixels(path, read_label(path))

        assert not rgba[-6:, :, 3].any()
        assert rgba[:-6, :, 3].all()

    def test_a_saturated_pixel_inside_the_picture_is_kept(self, tmp_path):
        pixels = ground()
        pixels[30, 180] = 4096
        path = write_mosaic(tmp_path, pixels)

        rgba, _ = read_pixels(path, read_label(path))

        assert rgba[30, 180, 0] == 255
