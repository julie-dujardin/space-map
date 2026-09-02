"""Country and operator resolution from GCAT's per-object registry columns.

CelesTrak states one owner per object for the whole catalogue, so a Soviet
launch and a Russian one are both ``CIS``. GCAT states the country and the
operating organisation as they were at the time, which is what these paths use
it for; the owner code stays as the fallback for objects GCAT has yet to
catalogue.
"""

import pytest

from space_map_data.constants.earth_sats.gcat_states import countries_for_state
from space_map_data.ingest.providers.objects.enrichment import (
    resolve_country_codes,
    resolve_operator_qids,
)

SPACEX = "Q193701"
SOVIET_ARMED_FORCES = "Q7915590"
RUSSIAN_SPACE_FORCES = "Q1703142"
NASA = "Q23548"


class TestStateCodes:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("US", ("US",)),
            ("SU", ("SU",)),  # dissolved, but the state that registered the launch
            ("F", ("FR",)),  # GCAT spells several countries its own way
            ("UK", ("GB",)),
            ("J", ("JP",)),
            ("CSSR", ("CS",)),
            ("I-ESA", ("EU",)),  # organisations keep the country they are shown under
            ("I-INT", ("LU", "US")),
            ("ZZ", ()),  # unknown code is not an error
            ("-", ()),
            (None, ()),
        ],
    )
    def test_state_maps_to_countries(self, state, expected):
        assert countries_for_state(state) == expected


class TestCountryResolution:
    def test_gcat_dates_the_country(self):
        """CelesTrak files both Soviet and Russian launches under CIS."""
        assert resolve_country_codes("CIS", "SU") == ["SU"]
        assert resolve_country_codes("CIS", "RU") == ["RU"]

    def test_partnership_survives_the_registry(self):
        """CBERS is registered to China and built half in Brazil; a multi-country
        owner code is a partnership, so its partners are kept."""
        assert resolve_country_codes("CHBZ", "CN") == ["BR", "CN"]

    def test_owner_code_fills_in_before_gcat_catalogues_it(self):
        assert resolve_country_codes("JPN", None) == ["JP"]

    def test_no_owner_and_no_state(self):
        assert resolve_country_codes(None, None) == []


class TestOperatorResolution:
    def test_gcat_owner_resolves(self):
        assert SPACEX in resolve_operator_qids(None, None, gcat_owner=("SPXS",))

    def test_nasa_centres_resolve_to_the_agency(self):
        """GCAT names the centre that ran the mission, not the agency."""
        assert NASA in resolve_operator_qids(None, None, gcat_owner=("GSFC",))
        assert NASA in resolve_operator_qids(None, None, gcat_owner=("JSC",))

    def test_military_space_directorate_follows_its_era(self):
        """Six names for one branch; GCAT dates each code, so a 1975 launch is
        Soviet and a 2005 one is the Russian Space Forces."""
        soviet = resolve_operator_qids(
            None, None, gcat_owner=("GUKOS",), gcat_owner_ucodes=("GUKOS",)
        )
        russian = resolve_operator_qids(
            None, None, gcat_owner=("KVR",), gcat_owner_ucodes=("GUKOS",)
        )
        assert soviet == [SOVIET_ARMED_FORCES]
        assert russian == [RUSSIAN_SPACE_FORCES]

    def test_unknown_owner_code_leaves_the_owner_path(self):
        qids = resolve_operator_qids("ESA", None, gcat_owner=("NOSUCHORG",))
        assert qids  # the CelesTrak owner code still answers
