"""Tests for ``resolve_constellation`` — name/owner/group matching and how it
resolves conflicts between them."""

from space_map_data.ingest.providers.objects.enrichment import resolve_constellation


class TestNameMatching:
    """Debris constellations are identified by their OBJECT_NAME prefix."""

    def test_debris_matched_by_name(self):
        assert (
            resolve_constellation(16029, "SOLWIND DEB", "US", set()) == "solwind-debris"
        )

    def test_constellation_matched_by_name(self):
        assert resolve_constellation(123, "STARLINK-1234", None, set()) == "starlink"

    def test_no_match_returns_none(self):
        assert resolve_constellation(404, None, None, set()) is None


class TestLaunchPeers:
    """A launch's rocket body / co-passengers resolve by their own name, not by
    the payload's debris cloud."""

    def test_rocket_body_keeps_its_family(self):
        # Atlas R/B from the Solwind launch — atlas, not solwind-debris.
        assert resolve_constellation(11279, "ATLAS R/B", "US", set()) == "atlas"

    def test_intact_payload_is_not_debris(self):
        # The intact COSMOS 1408 satellite resolves to the generic Cosmos series,
        # not the cosmos-1408-debris cloud created when it was later destroyed.
        assert resolve_constellation(13552, "COSMOS 1408", "CIS", set()) == "cosmos"
