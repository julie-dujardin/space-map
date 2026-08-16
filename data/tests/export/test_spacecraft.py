"""Tests for `v1/spacecraft.json`: a Δv never ships without its inputs, and thinning a curve doesn't move the answer."""

import pytest

from space_map_data.constants.spacecraft import CATALOGUE, solver_can_judge
from space_map_data.export.spacecraft import (
    _load_curve,
    _thin,
    build_name_bundles,
    build_spacecraft,
)
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.utils.paths import SOURCES_LAUNCH_PERFORMANCE_DIR


@pytest.fixture(scope="module")
def curves_downloaded():
    if not SOURCES_LAUNCH_PERFORMANCE_DIR.exists():
        pytest.skip("launch-performance curves not downloaded")


@pytest.fixture(scope="module")
def payload(curves_downloaded):
    return build_spacecraft()


class TestShape:
    """Every entry is complete enough to render."""

    def test_only_judgeable_vehicles_ship(self, payload):
        # Drop list is pinned: a new entry landing on it should be a decision, not an accident.
        exported = {v["id"] for v in payload["vehicles"]}
        assert exported == {c.id for c in CATALOGUE.values() if solver_can_judge(c)}
        assert set(CATALOGUE) - exported == {
            "new-glenn",
            "long-march-5",
            "crew-dragon",
            "starship",
        }

    def test_departures_ship_on_every_entry(self, payload):
        # Including empty ones — the panel reads an absent field as an old export and stops filtering.
        for vehicle in payload["vehicles"]:
            assert isinstance(vehicle["departs_from"], list), vehicle["id"]
            assert set(vehicle["departs_from"]) <= {"surface", "orbit"}, vehicle["id"]
        by_id = {v["id"]: v for v in payload["vehicles"]}
        assert by_id["sls-block-1"]["departs_from"] == ["surface"]
        assert by_id["orion"]["departs_from"] == ["orbit"]
        assert by_id["apollo-lm"]["departs_from"] == ["orbit", "surface"]
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

    def test_configurations_of_one_rocket_are_told_apart(self, bundles):
        # Falcon Heavy entries share a QID and label; `variant` is what tells them apart in the picker.
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
        # Flyable craft missing a Δv input are dropped before writing; only cargo like a rover survives here.
        by_id = {v["id"]: v for v in payload["vehicles"]}
        assert "dry_mass_kg" in by_id["curiosity"]
        assert "delta_v_kms" not in by_id["curiosity"]

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

    def test_thinned_curve_reproduces_every_dropped_point(self, curves_downloaded):
        # Tolerance is 0.5% of payload — below the precision any source quotes.
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
        # ULA's user's guide: 7,600 kg to C3 = 20 on a VC6S. Digitised curve must reproduce it.
        curve = next(
            v["c3_curve"] for v in payload["vehicles"] if v["id"] == "vulcan-vc6"
        )
        points = curve["points"]
        lo = max(i for i, (c3, _) in enumerate(points) if c3 <= 20.0)
        (c3_lo, kg_lo), (c3_hi, kg_hi) = points[lo], points[lo + 1]
        at_20 = kg_lo + (kg_hi - kg_lo) * (20.0 - c3_lo) / (c3_hi - c3_lo)
        assert at_20 == pytest.approx(7600.0, rel=0.02)

    def test_sls_matches_the_mission_planners_guide(self, payload):
        # Table 4-1: Block 1 delivers 27.2 t through TLI (C3 = -0.99), 3.6 t at C3 = 100 (roughly Jupiter direct).
        curve = next(
            v["c3_curve"] for v in payload["vehicles"] if v["id"] == "sls-block-1"
        )
        by_c3 = dict(curve["points"])
        assert by_c3[-0.99] == 27200
        assert by_c3[100.0] == 3600
