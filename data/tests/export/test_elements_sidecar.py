"""Tests for space_map_data.export.position.elements.sidecar."""

from space_map_data.export.position.elements.sidecar import has_localized_digest


class TestHasLocalizedDigest:
    """The gate-bit digest invalidates a part when its has_localized set changes."""

    def test_flip_changes_digest(self):
        ids = ["spkid-1", "spkid-2", "spkid-3"]
        before = has_localized_digest(ids, {"spkid-1": True})
        after = has_localized_digest(ids, {"spkid-1": True, "spkid-2": True})
        assert before != after

    def test_stable_when_unchanged(self):
        ids = ["spkid-1", "spkid-2"]
        gate = {"spkid-1": True}
        assert has_localized_digest(ids, gate) == has_localized_digest(ids, gate)

    def test_missing_id_treated_as_false(self):
        ids = ["spkid-1", "spkid-2"]
        assert has_localized_digest(ids, {}) == has_localized_digest(
            ids, {"spkid-1": False, "spkid-2": False}
        )

    def test_order_is_significant(self):
        gate = {"a": True}
        assert has_localized_digest(["a", "b"], gate) != has_localized_digest(
            ["b", "a"], gate
        )
