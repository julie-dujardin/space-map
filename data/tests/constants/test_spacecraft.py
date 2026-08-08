"""Tests for the spacecraft catalogue's internal consistency.

Everything here checks a claim the catalogue makes about itself: that its
enums are the declared ones, that every cited source exists, that every link
points at something already in the map, and that the derived Δv lands where
the missions it describes actually landed.
"""

import json

import pytest

from space_map_data.constants.earth_sats.constellations import CONSTELLATION_BY_SLUG
from space_map_data.constants.earth_sats.launch_vehicles import LAUNCH_VEHICLE_BY_SLUG
from space_map_data.constants.spacecraft import (
    CAPABILITIES,
    CATALOGUE,
    COST_KINDS,
    DEPARTURES,
    KINDS,
    POWER,
    PROPULSION,
    SPACECRAFT_SOURCES,
    STATUSES,
    delta_v_kms,
)
from space_map_data.download.providers.launch_performance import CURVES
from space_map_data.probes.probe_id import REGISTRY_PATH


class TestVocabularies:
    """Every categorical field uses a declared value."""

    def test_kinds_propulsion_status(self):
        for craft in CATALOGUE.values():
            assert craft.kind in KINDS, craft.id
            assert craft.propulsion in PROPULSION, craft.id
            assert craft.status in STATUSES, craft.id

    def test_power_and_capabilities(self):
        for craft in CATALOGUE.values():
            assert craft.power is None or craft.power in POWER, craft.id
            assert craft.capabilities <= CAPABILITIES, craft.id

    def test_departures(self):
        for craft in CATALOGUE.values():
            assert craft.departs_from <= DEPARTURES, craft.id

    def test_cost_kinds(self):
        for craft in CATALOGUE.values():
            if craft.cost is not None:
                assert craft.cost.kind in COST_KINDS, craft.id


class TestIdentity:
    """Each entry can be named, and named once."""

    def test_ids_are_unique_slugs(self):
        for craft_id in CATALOGUE:
            assert craft_id == craft_id.lower().strip()
            assert " " not in craft_id

    def test_named_by_qid_or_by_hand(self):
        # Wikidata gives twelve locales for free; a hand-authored name is the
        # fallback for ships with no item, and needs message keys instead.
        for craft in CATALOGUE.values():
            assert craft.qid or craft.name, craft.id
            if craft.qid:
                assert craft.qid.startswith("Q"), craft.id
                assert craft.qid[1:].isdigit(), craft.id


class TestSources:
    """Every figure is attributable, and every citation is used."""

    def test_every_cited_source_is_registered(self):
        for craft in CATALOGUE.values():
            for key in craft.sources():
                assert key in SPACECRAFT_SOURCES, f"{craft.id}: {key}"

    def test_no_unused_references(self):
        cited = {key for craft in CATALOGUE.values() for key in craft.sources()}
        assert set(SPACECRAFT_SOURCES) == cited

    def test_references_have_titles_and_urls(self):
        for key, ref in SPACECRAFT_SOURCES.items():
            assert ref.title and ref.url.startswith("https://"), key
            assert ref.contribution, key

    def test_fitted_figures_stay_in_fiction(self):
        # `space_map_fitted` says "somebody here chose this number". A real
        # spacecraft reaching for it would be inventing performance, which is
        # the one thing the catalogue is not allowed to do.
        for craft in CATALOGUE.values():
            if "space_map_fitted" in craft.sources():
                assert craft.kind == "fictional", craft.id


class TestLinks:
    """Entries point at things that already exist elsewhere in the map."""

    def test_group_slugs_resolve(self):
        for craft in CATALOGUE.values():
            slug = craft.group_slug
            if slug is None:
                continue
            if slug.startswith("lv-"):
                assert slug[len("lv-") :] in LAUNCH_VEHICLE_BY_SLUG, craft.id
            elif slug.startswith("const-"):
                assert slug[len("const-") :] in CONSTELLATION_BY_SLUG, craft.id
            else:
                pytest.fail(f"{craft.id}: unknown group namespace {slug}")

    def test_object_ids_are_registered_probes(self):
        if not REGISTRY_PATH.exists():
            pytest.skip("probe registry not present")
        known = {
            f"probe-{entry['probe_id']}"
            for entry in json.loads(REGISTRY_PATH.read_text())
        }
        for craft in CATALOGUE.values():
            for object_id in craft.object_ids:
                assert object_id in known, f"{craft.id}: {object_id}"


class TestDepartures:
    """Where a trip can start with each entry.

    The two lists below are spelled out rather than derived: an entry that
    forgot the field would otherwise read as "cannot depart at all" and quietly
    vanish from the panel's suggestions for every trip.
    """

    def test_launchers_leave_from_the_ground_and_nowhere_else(self):
        for craft in CATALOGUE.values():
            if craft.kind == "launcher":
                assert craft.departs_from == frozenset({"surface"}), craft.id

    def test_only_cargo_departs_from_nowhere(self):
        grounded = {c.id for c in CATALOGUE.values() if not c.departs_from}
        assert grounded == {"curiosity", "perseverance"}

    def test_both_departures_is_a_short_list(self):
        both = {c.id for c in CATALOGUE.values() if len(c.departs_from) == 2}
        assert both == {
            "apollo-lm",
            "starship",
            "rocinante",
            "millennium-falcon",
        }


class TestPerformance:
    """The numbers behave like performance figures."""

    def test_launchers_are_the_only_entries_with_curves(self):
        for craft in CATALOGUE.values():
            if craft.c3_curve is not None:
                assert craft.kind == "launcher", craft.id

    def test_curves_declare_exactly_one_source_of_points(self):
        for craft in CATALOGUE.values():
            curve = craft.c3_curve
            if curve is None:
                continue
            assert bool(curve.points) != bool(curve.dataset), craft.id
            if curve.dataset:
                assert curve.dataset in CURVES, craft.id

    def test_inline_curves_descend_with_energy(self):
        for craft in CATALOGUE.values():
            curve = craft.c3_curve
            if curve is None or not curve.points:
                continue
            c3s = [c3 for c3, _ in curve.points]
            payloads = [kg for _, kg in curve.points]
            assert c3s == sorted(c3s), craft.id
            assert payloads == sorted(payloads, reverse=True), craft.id
            assert payloads[-1] > 0, craft.id

    def test_saturn_v_curve_lands_where_apollo_did(self):
        # The Saturn V curve is the one traced off a chart rather than read
        # from a table, so it is pinned to the flight: Apollo 11 left orbit
        # with 45,700 kg on top of the S-IVB at a C3 of about -1.8.
        curve = CATALOGUE["saturn-v"].c3_curve
        assert curve is not None
        (below, m_below), (above, m_above) = curve.points[0], curve.points[1]
        t = (-1.8 - below) / (above - below)
        assert 44_000 < m_below + t * (m_above - m_below) < 47_000

    def test_masses_are_positive(self):
        for craft in CATALOGUE.values():
            for measured in (craft.dry_mass_kg, craft.propellant_mass_kg):
                if measured is not None:
                    assert measured.value > 0, craft.id

    @pytest.mark.parametrize(
        "craft_id,low_kms,high_kms",
        [
            # Cassini's cruise plus Saturn orbit insertion.
            ("cassini", 2.0, 3.5),
            # MESSENGER spent more than half its mass stopping at Mercury.
            ("messenger", 2.0, 3.0),
            # New Horizons never slowed down: this is course correction only.
            ("new-horizons", 0.2, 0.6),
            # The largest Δv ever flown, and the reason it took five years.
            ("dawn", 11.0, 15.0),
            # Orion's service module, one lunar-orbit insertion and return.
            ("orion", 1.0, 1.8),
            # Eleven years of flybys and a comet rendezvous, against the
            # 2.3 km/s ESA budgeted for the trip.
            ("rosetta", 2.0, 2.8),
            # A floor: the thruster datasheet quotes a minimum specific
            # impulse, so Clipper's real margin can only be better.
            ("europa-clipper", 1.5, 2.5),
            # Course correction on a probe that was thrown at the Sun.
            ("parker-solar-probe", 0.15, 0.45),
            # Down from lunar orbit and back up, understated because the real
            # thing dropped a stage in between.
            ("apollo-lm", 3.0, 4.5),
            # The SPS on a full load, a little over the 2.8 usually quoted.
            ("apollo-csm", 2.5, 3.5),
        ],
    )
    def test_derived_delta_v_matches_the_mission(self, craft_id, low_kms, high_kms):
        delta_v = delta_v_kms(CATALOGUE[craft_id])
        assert delta_v is not None
        assert low_kms <= delta_v <= high_kms, f"{craft_id}: {delta_v:.2f} km/s"

    def test_delta_v_is_none_without_all_three_inputs(self):
        # Crew Dragon's masses are known and its engine is not — nobody has
        # published a Draco specific impulse — so the panel has to say so
        # rather than round something plausible.
        assert delta_v_kms(CATALOGUE["crew-dragon"]) is None

    def test_electric_craft_are_recognisably_low_thrust(self):
        for craft in CATALOGUE.values():
            dry, propellant = craft.dry_mass_kg, craft.propellant_mass_kg
            if craft.propulsion != "electric" or craft.thrust_n is None:
                continue
            assert dry is not None and propellant is not None, craft.id
            wet = dry.value + propellant.value
            assert craft.thrust_n.value / wet < 1e-3, craft.id
