import math

import numpy as np
import pytest

from space_map_data.panoramas import clpds
from space_map_data.panoramas.clpds import Frame

LABEL = """<?xml version="1.0" encoding="UTF-8"?>
<Product_Observational xmlns="http://pds.nasa.gov/pds4/pds/v1">
  <Observation_Area>
    <Time_Coordinates>
      <start_date_time>2022-04-12T17:18:30.300000Z</start_date_time>
    </Time_Coordinates>
  </Observation_Area>
  <File_Area_Observational>
    <Array_3D_Image>
      <axis_index_order>Last Index Fastest</axis_index_order>
      <Element_Array><data_type>UnsignedByte</data_type></Element_Array>
      <Axis_Array><axis_name>Line</axis_name><elements>2048</elements><sequence_number>1</sequence_number></Axis_Array>
      <Axis_Array><axis_name>Sample</axis_name><elements>2048</elements><sequence_number>2</sequence_number></Axis_Array>
      <Axis_Array><axis_name>Band</axis_name><elements>3</elements><sequence_number>3</sequence_number></Axis_Array>
    </Array_3D_Image>
  </File_Area_Observational>
  <Mission_Area>
    <product_id>HX1-Ro_GRAS_NaTeCamA-F-005_SCI_N_20220412171830_20220412171830_00325_A.2C</product_id>
    <instrument_id>NaTeCam</instrument_id>
    <sequence_id>00325</sequence_id>
    <Instrument_Parm>
      <pixel_size unit="micrometer">5.5</pixel_size>
      <focal_length unit="mm">13.174201</focal_length>
      <Principal_Point_Coordinate>
        <x0 unit="mm">0.010239</x0><y0 unit="mm">0.022188</y0>
      </Principal_Point_Coordinate>
    </Instrument_Parm>
    <Rover_Location>
      <longitude unit="deg">109.912440</longitude>
      <latitude unit="deg">25.060494</latitude>
      <altitude unit="km">-4.935192</altitude>
    </Rover_Location>
    <Vector_Cartesian_3_Pointing>
      <Up_Left_Point_Observe_Vector><x>0.994159</x><y>-0.103184</y><z>-0.031642</z></Up_Left_Point_Observe_Vector>
      <Down_Left_Point_Observe_vector><x>0.715718</x><y>0.011069</y><z>-0.698302</z></Down_Left_Point_Observe_vector>
      <Up_Right_Point_Observe_Vector><x>0.658068</x><y>-0.752953</y><z>-0.002855</z></Up_Right_Point_Observe_Vector>
      <Down_Right_Point_Observe_Vector><x>0.379852</x><y>-0.637860</y><z>-0.669961</z></Down_Right_Point_Observe_Vector>
      <Center_Point_Observe_Vector><x>0.802700</x><y>-0.433063</y><z>-0.410035</z></Center_Point_Observe_Vector>
    </Vector_Cartesian_3_Pointing>
  </Mission_Area>
</Product_Observational>
"""


def frame(**kwargs) -> Frame:
    found = clpds.read_label(LABEL, clpds.RELEASES["zhurong"])
    for key, value in kwargs.items():
        setattr(found, key, value)
    return found


def test_a_label_states_the_frame_and_where_the_rover_stood():
    found = clpds.read_label(LABEL, clpds.RELEASES["zhurong"])

    assert found.sequence == 325
    assert (found.width, found.height) == (2048, 2048)
    assert found.latitude == pytest.approx(25.060494)
    assert found.longitude == pytest.approx(109.912440)
    assert found.elevation_m == pytest.approx(-4935.192)
    assert len(found.pointing) == 5


def test_a_frame_of_another_instrument_is_refused():
    with pytest.raises(ValueError, match="Not a NaTeCam frame"):
        clpds.read_label(
            LABEL.replace("NaTeCam</instrument_id>", "MSCam</instrument_id>"),
            clpds.RELEASES["zhurong"],
        )


def test_the_camera_model_matches_the_stated_pointing_to_a_pixel():
    """The archive never writes its pixel sign convention down, so the fit onto
    the stated corner directions is what establishes it."""
    found = clpds.read_label(LABEL, clpds.RELEASES["zhurong"])
    rotation = clpds.rotation(found)
    rays = clpds.camera_rays(
        found,
        np.array([found.width / 2]),
        np.array([found.height / 2]),
    )
    centre = (rotation @ rays[0]) / np.linalg.norm(rays[0])

    assert np.allclose(centre, found.pointing[4], atol=2e-3)


def test_a_camera_model_that_misses_the_pointing_is_refused():
    """A wrong axis or focal length misses by degrees, not by a lens's worth of
    distortion, which the tolerance has to leave room for."""
    with pytest.raises(ValueError, match="misses the stated pointing"):
        clpds.rotation(frame(focal_mm=4.0))
    assert clpds.fit(clpds.read_label(LABEL, clpds.RELEASES["zhurong"]))[1] < 0.1


def test_the_sphere_puts_north_first_and_runs_clockwise():
    """The archive states pointing east-north-up; reading it north-east-up
    instead mirrors every panorama about the meridian and still stitches."""
    directions = clpds.sphere_directions(720)
    equator = directions[len(directions) // 2]
    east, north, _ = equator[720 // 4]

    assert equator[0][1] == pytest.approx(1, abs=1e-2)
    assert east == pytest.approx(1, abs=1e-2)
    assert north == pytest.approx(0, abs=1e-2)


def test_a_frame_window_covers_the_azimuth_the_pointing_names():
    found = clpds.read_label(LABEL, clpds.RELEASES["zhurong"])
    columns, rows = clpds.frame_window(found, 720)
    centre = found.pointing[4]
    azimuth = math.degrees(math.atan2(centre[0], centre[1])) % 360

    assert (columns % 720).min() <= azimuth / 360 * 720 <= (columns % 720).max()
    assert len(rows)


def test_a_window_crossing_north_stays_one_run():
    """A sweep looking north wraps; the columns must not split into two ends."""
    straddling = frame(
        pointing=(
            (-0.2, 0.95, 0.2),
            (-0.2, 0.95, -0.2),
            (0.2, 0.95, 0.2),
            (0.2, 0.95, -0.2),
            (0.0, 1.0, 0.0),
        )
    )
    columns, _ = clpds.frame_window(straddling, 720)

    assert np.all(np.diff(columns) == 1)
    assert 0 in set(columns % 720)
    assert columns.max() - columns.min() < 720


def test_sweeps_group_a_standing_sol_and_drop_the_passing_shot():
    frames = [
        frame(product_id=f"a{n}", sequence=10, latitude=25.0, longitude=109.0)
        for n in range(4)
    ] + [frame(product_id="b", sequence=11, latitude=25.1, longitude=109.0)]

    found = clpds.sweeps(frames)

    assert list(found) == [(10, 25.0, 109.0)]
    assert len(found[(10, 25.0, 109.0)]) == 4


def test_a_band_sequential_raster_is_refused_rather_than_scrambled():
    """Band-first holds the same samples as band-last, so reading the order off
    the label is all that separates a colour frame from a scrambled one."""
    swapped = LABEL.replace(
        "<axis_name>Band</axis_name><elements>3</elements><sequence_number>3</sequence_number>",
        "<axis_name>Band</axis_name><elements>3</elements><sequence_number>0</sequence_number>",
    )
    with pytest.raises(ValueError, match="Unsupported raster axes"):
        clpds.read_label(swapped, clpds.RELEASES["zhurong"])


def test_the_release_path_names_the_file_host():
    url = clpds.file_url(
        None,
        {"image": "/img-api/upload/HX1ROLL/x/2C/2022-05/p.2C.jpg", "name": "p.2CL"},
    )

    assert url == "https://moon.bao.ac.cn/WEBDATA/HX1ROLL/x/2C/2022-05/p.2CL"


CHANGE_LABEL = (
    LABEL.replace("NaTeCam", "PCAM")
    .replace("<Rover_Location>", "<Lander_Location>")
    .replace("</Rover_Location>", "</Lander_Location>")
    .replace("Principal_Point_Coordinate", "principle_point_coordinate")
    .replace("<longitude ", "<Longitude ")
    .replace("</longitude>", "</Longitude>")
    .replace("Up_Left_Point_Observe_Vector", "up_left_point_observe_vector")
    .replace("Center_Point_Observe_Vector", "center_point_observe_vector")
    .replace("UnsignedByte", "UnsignedLSB2")
)


def test_the_moon_spells_the_same_label_differently():
    """One lunar label writes `Longitude` beside `latitude`, lower-cases the
    vectors, misspells the principal point and files the craft as a lander."""
    found = clpds.read_label(CHANGE_LABEL, clpds.RELEASES["yutu-2"])

    assert found.latitude == pytest.approx(25.060494)
    assert found.longitude == pytest.approx(109.912440)
    assert found.dtype == "<u2"
    assert found.principal_mm[0] == pytest.approx(0.010239)
    assert found.pointing[4][0] == pytest.approx(0.802700)


def test_every_release_names_a_body_the_export_knows():
    from space_map_data.panoramas.missions import body_id, probe_id

    for release in clpds.RELEASES.values():
        assert body_id(release.slug) == release.body_id
        assert probe_id(release.slug)
