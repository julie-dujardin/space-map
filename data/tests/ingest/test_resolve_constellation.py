"""Tests for ``resolve_constellation`` — the COSPAR ``object_id_prefix``
candidate and how it interacts with name/owner/group matching."""

from space_map_data.ingest.providers.objects.enrichment import resolve_constellation


class TestCosparCandidate:
    """The object-id-prefix path tags satellites by launch core."""

    def test_debris_piece_with_no_usable_name(self):
        # Fragment whose OBJECT_NAME doesn't carry the expected prefix; only the
        # shared launch core identifies it.
        slug = resolve_constellation(99999, None, "US", set(), cospar="1979-017P")
        assert slug == "solwind-debris"

    def test_name_and_cospar_agree(self):
        slug = resolve_constellation(
            88888, "UARS DEB", "US", set(), cospar="1991-063AA"
        )
        assert slug == "uars-debris"

    def test_cospar_defaults_to_none_when_omitted(self):
        # Backwards-compatible signature: callers that pass no cospar still work.
        assert resolve_constellation(123, "STARLINK-1234", None, set()) == "starlink"

    def test_no_match_returns_none(self):
        assert resolve_constellation(404, None, None, set(), cospar="9999-999A") is None


class TestCosparConflictResolution:
    """A launch-core match wins over a generic parent-constellation name."""

    def test_parent_payload_prefers_debris_over_generic_cosmos(self):
        # "COSMOS 1408" matches the broad COSMOS name prefix, but the launch
        # core pins the specific (unpreferred "cosmos" loses to the debris slug).
        slug = resolve_constellation(
            13552, "COSMOS 1408", "CIS", set(), cospar="1982-092A"
        )
        assert slug == "cosmos-1408-debris"
