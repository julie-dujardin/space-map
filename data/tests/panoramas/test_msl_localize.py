import json

import pytest

from space_map_data.panoramas import msl_localize

HEADER = (
    "frame,site,drive,planetocentric_latitude,longitude,elevation,"
    "easting,northing,sol\n"
)


def _table(tmp_path, rows):
    path = tmp_path / "positions.csv"
    body = "".join(
        f"ROVER,{site},{drive},{lat},{lon},{elev},{east},{north},{sol}\n"
        for site, drive, lat, lon, elev, east, north, sol in rows
    )
    path.write_text(HEADER + "SITE,1,-1,0,0,0,0,0,-1\n" + body)
    return path


class TestCaptionSol:
    """The capture sol a NASA release caption states."""

    @pytest.mark.parametrize(
        ("caption", "expected"),
        [
            ("during the 1,647th Martian day, or sol, of the mission.", 1647),
            ("the 2,440th Martian day, or sol, of the mission", 2440),
            ("the mission's 1,421st sol, or Martian day", 1421),
            ("a new rock sample on August 9, 2018 (Sol 2137), the rover", 2137),
            ("no sol here at all", None),
        ],
        ids=["ordinal day", "comma thousands", "ordinal sol", "bare sol", "none"],
    )
    def test_reads_the_stated_sol(self, caption, expected):
        assert msl_localize.caption_sol(caption) == expected

    def test_the_capture_sol_wins_over_a_cited_drive(self):
        caption = (
            "recorded during the 1,451st Martian day, or sol, of the mission. "
            "The rover reached the site in its Sol 1448 drive."
        )
        assert msl_localize.caption_sol(caption) == 1451


class TestLocate:
    """Where the rover stood on a sol, and how far it drove that sol."""

    def test_a_parked_sol_takes_the_last_stopping_point(self, tmp_path):
        rows = msl_localize.drives(
            _table(tmp_path, [(52, 0, -4.68, 137.36, -4419.9, 10.0, 20.0, 1196)])
        )
        found = msl_localize.locate(rows, 1197)
        assert found is not None
        stop, spread = found
        assert stop["site"] == 52
        assert spread == 0

    def test_a_driven_sol_measures_the_drive(self, tmp_path):
        rows = msl_localize.drives(
            _table(
                tmp_path,
                [
                    (60, 2928, -4.71, 137.35, -4314.0, 0.0, 0.0, 1598),
                    (60, 3000, -4.71, 137.35, -4314.0, 3.0, 4.0, 1601),
                    (60, 3162, -4.71, 137.35, -4314.0, 6.0, 8.0, 1601),
                ],
            )
        )
        found = msl_localize.locate(rows, 1601)
        assert found is not None
        stop, spread = found
        assert stop["drive"] == 3162
        assert spread == pytest.approx(10.0)

    def test_a_sol_before_any_drive_is_unplaceable(self, tmp_path):
        rows = msl_localize.drives(
            _table(tmp_path, [(1, 8, 0.0, 0.0, 0.0, 0.0, 0.0, 40)])
        )
        assert msl_localize.locate(rows, 2) is None


class TestCaptureSol:
    """Which sol a product is placed on, and what said so."""

    def test_a_reviewed_sol_beats_the_caption(self):
        product = {"sol": 2595, "description": "the 2,554th Martian day"}
        assert msl_localize.capture_sol(product)[0] == 2595

    def test_the_caption_stands_in_without_one(self):
        product = {"description": "the 2,440th Martian day, or sol"}
        assert msl_localize.capture_sol(product) == (2440, "NASA caption")

    def test_neither_leaves_it_unplaced(self):
        assert msl_localize.capture_sol({"description": ""})[0] is None


class TestApply:
    """What a placed product records about its position."""

    def test_a_placed_product_carries_its_evidence(self, tmp_path):
        positions = _table(
            tmp_path, [(52, 0, -4.68, 137.36, -4419.9, 10.0, 20.0, 1196)]
        )
        folder = tmp_path / "curiosity" / "curiosity-pia1"
        folder.mkdir(parents=True)
        (folder / "metadata.json").write_text(
            json.dumps(
                {
                    "id": "curiosity-pia1",
                    "image": "sphere.webp",
                    "description": "the 1,197th Martian day, or sol",
                }
            )
        )
        (tmp_path / "curiosity" / "catalog.json").write_text(
            json.dumps(
                {
                    "panoramas": [
                        {
                            "id": "curiosity-pia1",
                            "metadata": "curiosity/curiosity-pia1/metadata.json",
                        }
                    ]
                }
            )
        )
        assert msl_localize.apply(tmp_path, positions) == 1
        written = json.loads((folder / "metadata.json").read_text())
        assert written["body_id"] == "naif-499"
        assert written["sol"] == 1197
        assert written["position"]["latitude"] == -4.68
        assert written["position"]["uncertainty_m"] is None
        assert written["localization_evidence"]["capture_sol_basis"] == "NASA caption"
