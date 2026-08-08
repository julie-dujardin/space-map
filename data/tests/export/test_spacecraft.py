"""Tests for `v1/spacecraft.json`.

The shape checks are cheap; the ones worth having are about the two things the
export decides rather than copies — that a Δv is never shipped without the
inputs behind it, and that thinning a hundred-point curve down to a dozen does
not move the answer.
"""

import pytest

from space_map_data.constants.spacecraft import CATALOGUE
from space_map_data.export.spacecraft import (
    _load_curve,
    _thin,
    build_name_bundles,
    build_spacecraft,
)
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.utils.paths import SOURCES_LAUNCH_PERFORMANCE_DIR


@pytest.fixture(scope="module")
def payload():
    if not SOURCES_LAUNCH_PERFORMANCE_DIR.exists():
        pytest.skip("launch-performance curves not downloaded")
    return build_spacecraft()


class TestShape:
    """Every entry is complete enough to render."""

    def test_one_entry_per_catalogue_vehicle(self, payload):
        assert len(payload["vehicles"]) == len(CATALOGUE)
        assert {v["id"] for v in payload["vehicles"]} == set(CATALOGUE)

    def test_departures_ship_on_every_entry(self, payload):
        # Including the empty ones. The panel reads an absent field as an old
        # export and stops filtering; it must never see one from this writer.
        for vehicle in payload["vehicles"]:
            assert isinstance(vehicle["departs_from"], list), vehicle["id"]
            assert set(vehicle["departs_from"]) <= {"surface", "orbit"}, vehicle["id"]
        by_id = {v["id"]: v for v in payload["vehicles"]}
        assert by_id["sls-block-1"]["departs_from"] == ["surface"]
        assert by_id["orion"]["departs_from"] == ["orbit"]
        assert by_id["starship"]["departs_from"] == ["orbit", "surface"]
        assert by_id["curiosity"]["departs_from"] == []

    def test_every_source_key_resolves(self, payload):
        sources = payload["sources"]

        def keys(node):
            if isinstance(node, dict):
                if "source" in node and isinstance(node["source"], str):
                    yield node["source"]
                if "cross_check" in node:
                    yield node["cross_check"]
                if "capability_source" in node:
                    yield node["capability_source"]
                for value in node.values():
                    yield from keys(value)
            elif isinstance(node, list):
                for item in node:
                    yield from keys(item)

        for key in keys(payload["vehicles"]):
            assert key in sources, key


class TestNames:
    """Every vehicle can be labelled, and no two rows read alike."""

    @pytest.fixture(scope="class")
    def bundles(self):
        return build_name_bundles(WikidataEntityCache())

    def test_every_locale_names_every_vehicle_with_an_item(self, bundles):
        # The two ships Wikidata has no item for are named by the frontend's
        # own message keys; everything else is named here, in all twelve.
        expected = {c.id for c in CATALOGUE.values() if c.qid}
        for lang, bundle in bundles.items():
            assert set(bundle) == expected, lang
            assert all(entry["name"] for entry in bundle.values()), lang

    def test_configurations_of_one_rocket_are_told_apart(self, bundles):
        # Three Falcon Heavy entries share a QID and therefore a label. What
        # separates them in the picker is `variant`, so (name, variant) has to
        # be unique — otherwise the list shows the same row three times.
        variants = {c.id: c.variant for c in CATALOGUE.values()}
        for lang, bundle in bundles.items():
            rows = [(e["name"], variants[craft_id]) for craft_id, e in bundle.items()]
            assert len(set(rows)) == len(rows), lang

    def test_variants_are_slugs(self):
        for craft in CATALOGUE.values():
            for qualifier in craft.variant:
                assert qualifier == qualifier.lower().strip(), craft.id
                assert " " not in qualifier, craft.id


class TestDerivedDeltaV:
    """A Δv nobody can check is worse than no Δv at all."""

    def test_never_shipped_without_its_inputs(self, payload):
        for vehicle in payload["vehicles"]:
            if "delta_v_kms" not in vehicle:
                continue
            for field in ("dry_mass_kg", "propellant_mass_kg", "isp_s"):
                assert field in vehicle, f"{vehicle['id']}: {field}"

    def test_absent_where_an_input_is(self, payload):
        by_id = {v["id"]: v for v in payload["vehicles"]}
        assert "delta_v_kms" not in by_id["rosetta"]
        assert "delta_v_kms" not in by_id["apollo-csm"]

    def test_matches_the_rocket_equation(self, payload):
        for vehicle in payload["vehicles"]:
            if "delta_v_kms" not in vehicle:
                continue
            from math import log

            wet = (
                vehicle["dry_mass_kg"]["value"] + vehicle["propellant_mass_kg"]["value"]
            )
            expected = (
                vehicle["isp_s"]["value"]
                * 9.80665
                * log(wet / vehicle["dry_mass_kg"]["value"])
            ) / 1000.0
            assert vehicle["delta_v_kms"] == pytest.approx(expected, abs=1e-3)


class TestCurves:
    """Thinning is lossy on purpose, and bounded."""

    def test_launchers_only(self, payload):
        for vehicle in payload["vehicles"]:
            if "c3_curve" in vehicle:
                assert vehicle["kind"] == "launcher", vehicle["id"]

    def test_points_descend_with_energy(self, payload):
        for vehicle in payload["vehicles"]:
            curve = vehicle.get("c3_curve")
            if curve is None:
                continue
            points = curve["points"]
            assert len(points) >= 2, vehicle["id"]
            c3s = [c3 for c3, _ in points]
            payloads = [kg for _, kg in points]
            assert c3s == sorted(c3s), vehicle["id"]
            assert payloads == sorted(payloads, reverse=True), vehicle["id"]

    def test_thinned_curve_reproduces_every_dropped_point(self):
        # 0.5% of the payload at that energy — below the precision any of the
        # sources quote, and the check that a 100-point curve can ship as 15.
        for dataset in ("atlas-v551", "falcon-heavy-expendable", "vulcan-vc6"):
            full = _load_curve(dataset)
            thinned = _thin(full)
            assert len(thinned) < len(full)
            for c3, kg in full:
                lo = max(i for i, (x, _) in enumerate(thinned) if x <= c3 or i == 0)
                hi = min(lo + 1, len(thinned) - 1)
                (c3_lo, kg_lo), (c3_hi, kg_hi) = thinned[lo], thinned[hi]
                if c3_hi == c3_lo:
                    predicted = kg_lo
                else:
                    predicted = kg_lo + (kg_hi - kg_lo) * (c3 - c3_lo) / (c3_hi - c3_lo)
                assert abs(predicted - kg) <= 0.005 * max(kg, 1.0) + 1.0, (
                    f"{dataset} at C3={c3}"
                )

    def test_digitised_vulcan_agrees_with_ula(self, payload):
        # ULA's own user's guide: 7,600 kg to C3 = 20 on a VC6S. The digitised
        # curve is only trustworthy because it reproduces that.
        curve = next(
            v["c3_curve"] for v in payload["vehicles"] if v["id"] == "vulcan-vc6"
        )
        points = curve["points"]
        lo = max(i for i, (c3, _) in enumerate(points) if c3 <= 20.0)
        (c3_lo, kg_lo), (c3_hi, kg_hi) = points[lo], points[lo + 1]
        at_20 = kg_lo + (kg_hi - kg_lo) * (20.0 - c3_lo) / (c3_hi - c3_lo)
        assert at_20 == pytest.approx(7600.0, rel=0.02)

    def test_sls_matches_the_mission_planners_guide(self, payload):
        # Table 4-1: Block 1 delivers 27.2 t through TLI (C3 = -0.99) and
        # 3.6 t at C3 = 100, which is roughly Jupiter direct.
        curve = next(
            v["c3_curve"] for v in payload["vehicles"] if v["id"] == "sls-block-1"
        )
        by_c3 = dict(curve["points"])
        assert by_c3[-0.99] == 27200
        assert by_c3[100.0] == 3600
