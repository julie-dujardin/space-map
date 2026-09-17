import math

import pytest

from space_map_data.panoramas import mer
from space_map_data.panoramas.labels import read_mer_pds3

TRAVERSE = """SITE,DRIVE,START_SOL,END_SOL,RAW_X,RAW_Y,RAW_Z,CORRECTED_X,CORRECTED_Y
0,0,1,1,0.000,0.000,0,-1000.00,-863000.00
1,0,2,4,0.000,0.000,0,-1000.00,-863000.00
2,0,5,5,0.000,0.000,0,-1000.00,-862000.00
2,16,5,7,0.000,0.000,0,-500.00,-862000.00
"""

POINTING = """<?xml version="1.0" encoding="UTF-8"?>
<pointing_correction mission="MER:MER2">
  <solution index1="23" index2="7" index3="0" index4="13" index5="0"/>
  <solution index1="23" index2="7" index3="0" index4="14" index5="0"/>
</pointing_correction>
"""

LABEL = """PDS_VERSION_ID                    = PDS3
RECORD_TYPE                       = FIXED_LENGTH
RECORD_BYTES                      = 100
^IMAGE_HEADER                     = 4
^IMAGE                            = 5
 PRODUCT_ID                       = "2NN001EDN00CYL00P1501L000M2"
 PLANET_DAY_NUMBER                = 1
 START_TIME                       = 2004-01-04T06:01:47.477
 STOP_TIME                        = 2004-01-04T06:31:47.477
OBJECT                            = IMAGE
  LINES                           = 40
  LINE_SAMPLES                    = 720
  SAMPLE_TYPE                     = MSB_INTEGER
  SAMPLE_BITS                     = 16
  BANDS                           = 1
  BAND_STORAGE_TYPE               = BAND_SEQUENTIAL
  INVALID_CONSTANT                = 0.0
  MISSING_CONSTANT                = 0.0
END_OBJECT                        = IMAGE
GROUP                             = SURFACE_PROJECTION_PARMS
  MAP_PROJECTION_TYPE             = CYLINDRICAL
  MAP_RESOLUTION                  = (2.0 <pix/deg>,2.0 <pix/deg>)
  REFERENCE_COORD_SYSTEM_INDEX    = 2
  REFERENCE_COORD_SYSTEM_NAME     = SITE_FRAME
  START_AZIMUTH                   = 0.0 <deg>
  STOP_AZIMUTH                    = 360.0 <deg>
  ZERO_ELEVATION_LINE             = 20.0 <pixel>
END_GROUP                         = SURFACE_PROJECTION_PARMS
END
"""

INDEX_LABEL = """
  OBJECT                     = FIELD
    NAME                     = PATH_NAME
  END_OBJECT                 = FIELD
  OBJECT                     = FIELD
    NAME                     = FILE_NAME
  END_OBJECT                 = FIELD
  OBJECT                     = FIELD
    NAME                     = INSTRUMENT_ID
  END_OBJECT                 = FIELD
  OBJECT                     = FIELD
    NAME                     = PLANET_DAY_NUMBER
  END_OBJECT                 = FIELD
  OBJECT                     = FIELD
    NAME                     = MAP_PROJECTION_TYPE
  END_OBJECT                 = FIELD
"""

INDEX = "\n".join(
    "\t".join(row)
    for row in (
        ('"/v/data/navcam/site0002/"', '"a.img"', '"NAVCAM_LEFT"', "5", '"CYL"'),
        ('"/v/data/navcam/site0002/"', '"b.img"', '"NAVCAM_LEFT"', "5", '"CYP"'),
        ('"/v/data/hazcam/site0002/"', '"c.img"', '"FRONT_HAZCAM_LEFT"', "5", '"CYL"'),
        ('"/v/data/pancam/site0003/"', '"d.img"', '"PANCAM_LEFT"', "9", '"CYL"'),
    )
)


def table(tmp_path, text=TRAVERSE):
    path = tmp_path / "traverse.csv"
    path.write_text(text)
    return path


def test_traverse_is_anchored_on_the_published_landing_site(tmp_path):
    """The first stop is the landing site itself, whatever datum the table uses."""
    found = mer.traverse_positions("spirit", table(tmp_path))

    latitude, longitude = mer.LANDING["spirit"]
    assert found[(0, 0)]["latitude"] == pytest.approx(latitude)
    assert found[(0, 0)]["longitude"] == pytest.approx(longitude)


def test_traverse_offsets_are_read_as_easting_and_northing(tmp_path):
    """Corrected x moves the rover east and corrected y moves it north."""
    found = mer.traverse_positions("spirit", table(tmp_path))
    latitude, longitude = mer.LANDING["spirit"]
    degree = mer.MARS_RADIUS_M * math.pi / 180

    north = found[(2, 0)]
    east = found[(2, 16)]
    assert north["latitude"] - latitude == pytest.approx(1000 / degree)
    assert north["longitude"] == pytest.approx(longitude)
    assert east["longitude"] - longitude == pytest.approx(
        500 / (degree * math.cos(math.radians(latitude)))
    )


def test_a_sol_spent_driving_names_no_single_place(tmp_path):
    """Sol 5 covers two stops, so nothing taken that sol can be placed by it."""
    found = mer.traverse_sol_positions("spirit", table(tmp_path))

    assert sorted(found) == [1, 2, 3, 4, 6, 7]
    assert found[3] == found[1]


def test_a_still_sol_names_the_drive_it_was_held_at(tmp_path):
    """A sol spent parked names one drive twice; a driving sol names the stretch."""
    drives = mer.traverse_drives("spirit", table(tmp_path))

    assert drives[(1, 3)] == (0, 0)
    assert drives[(2, 5)] == (0, 16)


def test_pointing_file_states_the_site_and_drive():
    """A mosaic shot standing still names one stop as both ends of its span."""
    assert mer.nav_stops(POINTING) == ((23, 7), (23, 7))
    assert mer.nav_stops("   ") is None


def test_a_mosaic_spanning_two_stops_carries_both_ends():
    """A sweep shot while driving is bounded by its ends, not refused."""
    spanning = POINTING.replace(
        '<solution index1="23" index2="7" index3="0" index4="14" index5="0"/>',
        '<solution index1="23" index2="9" index3="0" index4="14" index5="0"/>',
    )
    assert mer.nav_stops(spanning) == ((23, 7), (23, 9))


def test_counter_fields_carry_on_in_base_36():
    """Sites ran past 99, and the archive numbers them the same way everywhere."""
    assert mer.counter_field("00") == 0
    assert mer.counter_field("99") == 99
    assert mer.counter_field("A0") == 100
    assert mer.counter_field("B2") == 138


def test_source_frames_name_the_stop_when_no_pointing_file_does():
    listing = (
        "/home/rgd/sol3/pan/f2/2P126552133ILF0200P2302L2V1.VIC\n"
        "/home/rgd/sol3/pan/f2/2P126552207ILF0200P2302L2V1.VIC\n"
    )
    assert mer.source_stops(listing) == ((2, 0), (2, 0))
    assert mer.source_stops("nothing here") is None


def test_source_frames_from_two_stops_bound_the_sweep():
    listing = "2P126552133ILF0200P2302L2V1.VIC\n2P126552207ILF0201P2302L2V1.VIC\n"
    assert mer.source_stops(listing) == ((2, 0), (2, 1))


def test_the_sol_answers_only_when_nothing_else_does(tmp_path):
    """Half the mosaics have no pointing file; a still sol places them anyway."""
    drives = mer.traverse_drives("spirit", table(tmp_path))
    url = "https://example.test/v/data/navcam/site0001/"

    assert mer.mosaic_stops(None, None, url, 3, drives) == ((1, 0), (1, 0))
    assert mer.mosaic_stops(
        None, None, "https://example.test/v/data/navcam/site0002/", 5, drives
    ) == ((2, 0), (2, 16))
    with pytest.raises(ValueError, match="names no stop"):
        mer.mosaic_stops(
            None, None, "https://example.test/v/data/navcam/site0009/", 5, drives
        )


def test_a_stated_position_beats_the_sol(tmp_path):
    """A driving sol is no obstacle when the product says where it stood."""
    drives = mer.traverse_drives("spirit", table(tmp_path))
    url = "https://example.test/v/data/navcam/site0002/"
    listing = "2P126552133ILF0216P2302L2V1.VIC"

    assert mer.mosaic_stops(None, listing, url, 5, drives) == ((2, 16), (2, 16))


def test_a_stated_position_must_agree_with_the_archive_path(tmp_path):
    with pytest.raises(ValueError, match="disagree on the site"):
        mer.mosaic_stops(
            POINTING, None, "https://example.test/v/data/navcam/site0002/", 3, {}
        )


def test_listing_keeps_only_cylindrical_mapping_cameras():
    groups = mer.mosaic_listings(
        INDEX, INDEX_LABEL, "https://a.test/", ("NAVCAM", "PANCAM")
    )

    assert groups == {
        5: [("https://a.test/v/data/navcam/site0002/", "a.img")],
        9: [("https://a.test/v/data/pancam/site0003/", "d.img")],
    }


def test_attached_label_reads_geometry_and_the_drive_from_beside_it():
    """The label states the site; only the pointing file knows the drive."""
    found = read_mer_pds3(LABEL, 7)

    assert (found.site, found.drive) == (2, 7)
    assert found.sol == 1
    assert found.width / found.scale_x == pytest.approx(360)
    assert found.offset == 400
    assert found.missing == (0.0, 0.0)


def test_a_detached_image_pointer_is_not_an_attached_raster():
    detached = LABEL.replace(
        "^IMAGE                            = 5", '^IMAGE = ("X.IMG",5)'
    )
    with pytest.raises(ValueError, match="Unsupported image pointer"):
        read_mer_pds3(detached, 7)


def test_camera_is_read_from_the_product_name():
    assert mer.instrument("2NN001EDN00CYL00P1501L000M2") == "Navcam"
    assert mer.instrument("2PP762ILFAOCYLDQP2368L777M1") == "Pancam"
