"""The activity block: which bodies answer for one, and what survives the trip
from a `Measurement` to JSON."""

import json

import pytest

from space_map_data.constants.activity.magnetism import MAGNETIC_FIELDS
from space_map_data.constants.activity.tidal import TIDAL_HEATING
from space_map_data.constants.activity.volcanism import GEOLOGIC_ACTIVITY
from space_map_data.export.objects.activity import activity_block

EARTH = "naif-399"
IO = "naif-501"
ENCELADUS = "naif-602"
VENUS = "naif-299"
JUPITER = "naif-599"
MIMAS = "naif-601"
TITAN = "naif-606"

COVERED = sorted(set(GEOLOGIC_ACTIVITY) | set(TIDAL_HEATING) | set(MAGNETIC_FIELDS))


def block(object_id: str) -> dict:
    """`activity_block` for a body that must have one."""
    result = activity_block(object_id)
    assert result is not None, object_id
    return result


class TestWhoGetsOne:
    """A body is in the block iff one of the three tables names it."""

    @pytest.mark.parametrize("object_id", COVERED)
    def test_every_named_body_ships(self, object_id: str):
        assert block(object_id).keys() - {"sources"}

    def test_a_body_in_no_table_gets_nothing(self):
        assert activity_block("spkid-20000433") is None

    def test_a_table_only_contributes_its_own_key(self):
        """Jupiter has a field and nothing else — no empty volcanism stub for a
        planet with no surface to erupt through."""
        assert set(block(JUPITER)) == {"magnetism", "sources"}
        assert set(block(MIMAS)) == {"tidal", "sources"}

    def test_tectonics_rides_with_volcanism(self):
        """Both live on one `BodyActivity`, but Io has no tectonics entry."""
        assert "tectonics" in block(EARTH)
        assert "tectonics" not in block(IO)


class TestMeasurements:
    """Each number keeps whatever its source said about how sure it is."""

    def test_a_plain_value_ships_alone(self):
        assert block(EARTH)["volcanism"]["heat_flux_w_per_m2"] == {"value": 0.08}

    def test_a_range_rides_alongside_its_value(self):
        surface_age = block(VENUS)["volcanism"]["surface_age_years"]
        assert surface_age == {"value": 6.0e8, "range": [2.5e8, 1.0e9]}

    def test_an_extrapolation_says_so(self):
        """Venus's eruption count is Earth's record scaled by mass, and would
        otherwise draw exactly like Earth's own catalogue."""
        assert block(VENUS)["volcanism"]["eruptions_per_year"]["modelled"] is True

    def test_a_bound_says_so(self):
        assert block(TITAN)["magnetism"]["surface_field_t"]["upper_limit"] is True

    def test_a_survey_snapshot_carries_its_cut_off(self):
        centres = block(IO)["volcanism"]["known_centres"]
        assert centres["as_of"] == "through mid-2023"

    @pytest.mark.parametrize("object_id", COVERED)
    def test_the_block_is_json(self, object_id: str):
        """Tuples and NamedTuples both survive `json.dumps` as arrays, so a
        leaked one would only show up as a shape nobody can read."""
        round_tripped = json.loads(json.dumps(block(object_id)))
        assert round_tripped == block(object_id)


class TestHeatIsCountedOnce:
    """Io and Enceladus quote the same watts in two tables on purpose."""

    @pytest.mark.parametrize("object_id", [IO, ENCELADUS])
    def test_a_tide_that_is_the_whole_budget_says_so(self, object_id: str):
        result = block(object_id)
        assert result["tidal"]["explains_heat_output"] is True
        assert (
            result["tidal"]["power_w"]["value"]
            == result["volcanism"]["endogenic_power_w"]["value"]
        )

    def test_a_tide_that_is_a_share_of_it_does_not(self):
        """Earth's 3.7 TW of ocean tide against 47 TW of internal heat — a
        twelfth of the budget, and the two rows have to stay apart."""
        assert "explains_heat_output" not in block(EARTH)["tidal"]

    def test_a_body_with_only_one_of_the_two_does_not(self):
        assert "explains_heat_output" not in block(MIMAS)["tidal"]


class TestSources:
    """Every block credits the works behind what it shows, once each."""

    @pytest.mark.parametrize("object_id", COVERED)
    def test_sources_are_deduped(self, object_id: str):
        urls = [s["url"] for s in block(object_id)["sources"]]
        assert len(urls) == len(set(urls))

    @pytest.mark.parametrize("object_id", COVERED)
    def test_nothing_ships_uncredited(self, object_id: str):
        assert block(object_id)["sources"]

    def test_the_volcanic_status_leads(self):
        """The panel opens on the status line, so its work is the first credit
        rather than whichever measurement happens to sort first."""
        assert block(VENUS)["sources"][0]["title"].startswith("Herrick")

    def test_a_status_resting_on_two_works_credits_both(self):
        titles = [s["title"] for s in block(VENUS)["sources"]]
        assert any(t.startswith("Herrick") for t in titles)
        assert any(t.startswith("Sulcanese") for t in titles)
