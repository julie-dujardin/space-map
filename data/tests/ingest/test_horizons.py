"""Unit tests for Horizons ingest parsing functions."""

from pathlib import Path

import pytest

from space_map_data.ingest.providers.objects.horizons import HorizonsIngestor
from space_map_data.models.object import ObjectType


def _make_ingestor() -> HorizonsIngestor:
    """Create a HorizonsIngestor without touching the database."""
    obj = object.__new__(HorizonsIngestor)
    obj.session = None
    obj.limit = None
    obj.csv_path = Path("/dev/null")
    obj.total_rows = 0
    return obj


def _make_row(**overrides) -> dict:
    """Build a minimal Horizons CSV row dict."""
    row = {
        "name": "Test Body",
        "naif_id": "399",
        "type": "planet",
        "center": "",
        "parent_naif_id": "0",
        "designation": "",
        "extra": "",
        "JDTDB": "2461110.5",
        "Calendar Date (TDB)": "A.D. 2026-Mar-11",
        "EC": "0.0167",
        "QR": "0.983",
        "IN": "0.0",
        "OM": "0.0",
        "W": "0.0",
        "Tp": "2461000.0",
        "N": "0.9856",
        "MA": "0.0",
        "TA": "0.0",
        "A": "1.0",
        "AD": "1.017",
        "PR": "365.25",
    }
    row.update(overrides)
    return row


class TestGetSpkId:
    """Tests for SPK ID computation from NAIF ID."""

    def test_pluto_special_case(self):
        ing = _make_ingestor()
        row = _make_row(naif_id="999", type="dwarf_planet")
        assert ing.get_spk_id(row) == 20134340

    def test_authoritative_type_returns_none(self):
        """Planets, moons, etc. don't have SPKIDs."""
        ing = _make_ingestor()
        for t in ("barycenter", "star", "planet", "moon"):
            row = _make_row(type=t)
            assert ing.get_spk_id(row) is None

    def test_asteroid_2m_range(self):
        """NAIF IDs 2_000_000–2_999_999 map to 20m range."""
        ing = _make_ingestor()
        row = _make_row(naif_id="2000001", type="asteroid")
        assert ing.get_spk_id(row) == 20000001

    def test_asteroid_20m_range_unchanged(self):
        """NAIF IDs already in 20m range stay as-is."""
        ing = _make_ingestor()
        row = _make_row(naif_id="20000001", type="asteroid")
        assert ing.get_spk_id(row) == 20000001

    def test_binary_asteroid_primary(self):
        """900m range maps to base SPK ID."""
        ing = _make_ingestor()
        row = _make_row(naif_id="900000617", type="asteroid")
        assert ing.get_spk_id(row) == 617

    def test_comet_naif_equals_spk(self):
        ing = _make_ingestor()
        row = _make_row(naif_id="1000012", type=ObjectType.comet)
        assert ing.get_spk_id(row) == 1000012

    def test_missing_naif_id_raises(self):
        ing = _make_ingestor()
        row = _make_row(naif_id="")
        with pytest.raises(ValueError, match="Missing NAIF ID"):
            ing.get_spk_id(row)


class TestGetCosparId:
    def test_spacecraft_returns_designation(self):
        ing = _make_ingestor()
        row = _make_row(type=ObjectType.spacecraft, designation="1977-084A")
        assert ing.get_cospar_id(row) == "1977-084A"

    def test_non_spacecraft_returns_none(self):
        ing = _make_ingestor()
        row = _make_row(type="planet", designation="something")
        assert ing.get_cospar_id(row) is None


class TestHasGarbageElements:
    """Tests for detecting unusable orbital elements."""

    def test_nan_eccentricity(self):
        ing = _make_ingestor()
        row = _make_row(EC=str(float("nan")), A="1.0", naif_id="12345")
        assert ing._has_garbage_elements(row) is True

    def test_nan_semimajor_axis(self):
        ing = _make_ingestor()
        row = _make_row(EC="0.1", A=str(float("nan")), naif_id="12345")
        assert ing._has_garbage_elements(row) is True

    def test_huge_semimajor_axis(self):
        ing = _make_ingestor()
        row = _make_row(EC="0.1", A="9.99E99", naif_id="12345")
        assert ing._has_garbage_elements(row) is True

    def test_normal_elements_pass(self):
        ing = _make_ingestor()
        row = _make_row(EC="0.0167", A="1.0", naif_id="399")
        assert ing._has_garbage_elements(row) is False

    def test_known_bad_naif_id_suppressed(self, caplog):
        """Known binary system components log at debug, not warning."""
        ing = _make_ingestor()
        row = _make_row(
            EC=str(float("nan")), A="1.0", naif_id="120000617", name="Menoetius"
        )
        import logging

        with caplog.at_level(logging.DEBUG):
            assert ing._has_garbage_elements(row) is True
        assert "known binary system" in caplog.text
