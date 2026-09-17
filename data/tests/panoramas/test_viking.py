"""Reading the Viking Lander panorama mosaics out of their VICAR labels."""

import pytest

from space_map_data.panoramas.viking import capture_date, position, read_vicar

HEADER = (
    "LBLSIZE=4010            FORMAT='BYTE'  TYPE='IMAGE'  DIM=3  EOL=0  "
    "RECSIZE=4010  ORG='BSQ'  NL=800  NS=4010  NB=1  "
    "LAB02='VIKING LANDER 1      CAMERA 1              CE LABEL 11A174/028         C'  "
    "LAB09='LLD/T 028/15:20:23   DATA LINK RAWEDR      EVENT D/GMT 231/05.28.44    C'  "
    "LAB18='MARS LOCAL   AZIMUTH/ELEVATION OF PIXEL(1,1) =237.500/  5.000 DEG    1HC'  "
    "LAB19='SCALE =0.0400000 DEG/PIXEL - RANGE DEPENDENT DISTORTIONS CORRECTED    HC'  "
)


class TestReadingTheLabel:
    """Each mosaic states where its first pixel points and how wide a pixel is,
    which is the whole geometry a sphere needs."""

    def test_the_raster_shape_comes_from_the_header(self):
        mosaic, _ = read_vicar(HEADER)

        assert (mosaic.width, mosaic.height, mosaic.bands) == (4010, 800, 1)
        assert mosaic.dtype == "u1"
        assert mosaic.offset == 4010

    def test_the_first_pixel_fixes_the_azimuth_and_the_scale(self):
        mosaic, _ = read_vicar(HEADER)

        assert mosaic.azimuth == pytest.approx(237.5)
        assert mosaic.scale_x == pytest.approx(25.0)
        assert mosaic.scale_y == pytest.approx(25.0)

    def test_the_horizon_lands_where_the_stated_elevation_puts_it(self):
        """Line one points five degrees up at a fortieth of a degree per pixel,
        so level ground is a hundred and twenty five lines below it."""
        mosaic, _ = read_vicar(HEADER)

        assert mosaic.zero_line == pytest.approx(126.0)

    def test_the_frame_is_the_lander_and_claims_no_north(self):
        """Nothing in the label ties the lander's own azimuth to north."""
        mosaic, _ = read_vicar(HEADER)
        mosaic.product_id, mosaic.start_time, mosaic.stop_time = "dnm207", "x", "x"
        mosaic.validate()

        assert mosaic.frame == "LANDER_FRAME"

    def test_the_lander_and_camera_are_read(self):
        _, who = read_vicar(HEADER)

        assert (who["lander"], who["camera"], who["doy"]) == (1, 1, 231)

    @pytest.mark.parametrize(
        "drop, message",
        [
            ("LAB18", "no pointing"),
            ("LAB02", "names no lander"),
            ("LAB09", "no capture sol"),
        ],
    )
    def test_a_label_missing_what_it_takes_is_refused(self, drop, message):
        stripped = " ".join(p for p in HEADER.split("  ") if not p.startswith(drop))

        with pytest.raises(ValueError, match=message):
            read_vicar(stripped)

    def test_a_raster_layout_the_archive_does_not_use_is_refused(self):
        with pytest.raises(ValueError, match="Unsupported VICAR raster layout"):
            read_vicar(HEADER.replace("FORMAT='BYTE'", "FORMAT='HALF'"))


class TestDatingASol:
    """The label counts sols since landing and, separately, the day the data
    came down; deriving one and finding the other says the sol was read right."""

    def test_a_sol_becomes_the_date_it_fell_on(self):
        """Viking 1 landed on day 202; twenty eight sols later is day 230."""
        assert capture_date(1, 28, 230) == "1976-08-17"

    def test_the_day_after_is_allowed(self):
        """A sol's data can come down on the following Earth day, which is what
        the archived label for sol 28 records."""
        assert capture_date(1, 28, 231) == "1976-08-17"

    def test_a_day_of_year_that_cannot_follow_is_refused(self):
        with pytest.raises(ValueError, match="disagree"):
            capture_date(1, 28, 99)

    def test_a_day_of_year_one_too_early_is_refused(self):
        with pytest.raises(ValueError, match="disagree"):
            capture_date(1, 28, 229)


class TestLandingSites:
    """The volume gives west longitude as the Viking era did."""

    def test_viking_one_sits_in_chryse(self):
        assert position(1)["longitude"] == pytest.approx(312.032)
        assert position(1)["latitude"] == pytest.approx(22.480)

    def test_viking_two_sits_in_utopia(self):
        assert position(2)["longitude"] == pytest.approx(134.263)

    def test_longitude_is_stated_as_east(self):
        assert position(1)["longitude_direction"] == "east"
