"""Tests for the IAU nomenclature feature claim spec."""

from space_map_data.export.nomenclature.wikidata_claims import (
    FEATURE_ENTITY_REF_CLAIMS,
    FEATURE_GLOBAL_CLAIMS,
    FEATURE_PID_TO_KEY,
    extract_feature_claims,
)


def _qty_snak(amount: str, unit: str = "1") -> dict:
    unit_url = f"http://www.wikidata.org/entity/{unit}" if unit != "1" else "1"
    return {
        "snaktype": "value",
        "datavalue": {
            "value": {"amount": amount, "unit": unit_url},
            "type": "quantity",
        },
    }


def _entity_snak(qid: str) -> dict:
    return {
        "snaktype": "value",
        "datavalue": {
            "value": {
                "entity-type": "item",
                "numeric-id": int(qid[1:]),
                "id": qid,
            },
            "type": "wikibase-entityid",
        },
    }


def _stmt(snak: dict, rank: str = "normal") -> dict:
    return {"mainsnak": snak, "rank": rank, "type": "statement"}


class TestFeatureSpec:
    """FEATURE_GLOBAL_CLAIMS / FEATURE_ENTITY_REF_CLAIMS / FEATURE_PID_TO_KEY"""

    def test_pid_to_key_covers_all_claims(self):
        for claim in (*FEATURE_GLOBAL_CLAIMS, *FEATURE_ENTITY_REF_CLAIMS):
            assert FEATURE_PID_TO_KEY[claim.pid] == claim.key

    def test_no_duplicate_pids(self):
        pids = [c.pid for c in (*FEATURE_GLOBAL_CLAIMS, *FEATURE_ENTITY_REF_CLAIMS)]
        assert len(pids) == len(set(pids))

    def test_named_after_is_an_entity_ref(self):
        """The frontend resolves named_after refs per-language → not a global."""
        global_keys = {c.key for c in FEATURE_GLOBAL_CLAIMS}
        ref_keys = {c.key for c in FEATURE_ENTITY_REF_CLAIMS}
        assert "named_after" in ref_keys
        assert "named_after" not in global_keys


class TestExtractFeatureClaims:
    """extract_feature_claims — single entry point for the feature spec."""

    def test_extracts_quantities_and_refs(self):
        claims = {
            "P2043": [_stmt(_qty_snak("130", "Q828224"))],  # length, nautical mile
            "P4511": [_stmt(_qty_snak("2000", "Q11573"))],  # depth, metre
            "P31": [_stmt(_entity_snak("Q1068071"))],
            "P138": [_stmt(_entity_snak("Q720861"))],
            "P276": [_stmt(_entity_snak("Q3055646"))],
        }
        result = extract_feature_claims(claims, "Q21211223")
        assert result["length"] == {"value": 130.0, "unit": "Q828224"}
        assert result["vertical_depth"] == {"value": 2000.0, "unit": "Q11573"}
        assert result["instance_of"] == ["Q1068071"]
        assert result["named_after"] == ["Q720861"]
        assert result["location"] == ["Q3055646"]

    def test_skips_p2076_temperature_route(self):
        """Features never carry P2076 — make sure the object-only routing is gated off."""
        claims = {
            "P2076": [
                _stmt(_qty_snak("100", "Q11579"))
            ],  # would route to "temperature"
        }
        result = extract_feature_claims(claims, "Qfoo")
        assert "temperature" not in result
        assert "min_temperature" not in result
        assert "max_temperature" not in result

    def test_drops_deprecated_statements(self):
        claims = {
            "P138": [
                _stmt(_entity_snak("Q1"), rank="deprecated"),
                _stmt(_entity_snak("Q2")),
            ],
        }
        result = extract_feature_claims(claims, "Qfoo")
        assert result["named_after"] == ["Q2"]

    def test_empty_claims_returns_empty(self):
        assert extract_feature_claims({}, "Qfoo") == {}

    def test_partial_overlap_with_object_keys(self):
        """length / width keys are shared with the object spec — same shape."""
        claims = {"P2043": [_stmt(_qty_snak("50", "Q11573"))]}
        result = extract_feature_claims(claims, "Qfoo")
        assert result["length"] == {"value": 50.0, "unit": "Q11573"}
