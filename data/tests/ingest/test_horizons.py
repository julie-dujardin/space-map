"""Unit tests for Horizons ingest parsing functions."""

from pathlib import Path

from space_map_data.ingest.providers.objects.horizons import HorizonsIngestor
from space_map_data.models.object import ObjectType


def _make_ingestor() -> HorizonsIngestor:
    """Create a HorizonsIngestor without touching the database."""
    obj = object.__new__(HorizonsIngestor)
    obj.session = None
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


class TestParseRow:
    def test_missing_naif_id_returns_none(self):
        ing = _make_ingestor()
        assert ing._parse_row(_make_row(naif_id="")) is None

    def test_spacecraft_cospar_from_designation(self):
        ing = _make_ingestor()
        row = _make_row(
            type=ObjectType.spacecraft, designation="1977-084A", naif_id="-32"
        )
        parsed = ing._parse_row(row)
        assert parsed is not None
        assert parsed["cospar_id"] == "1977-084A"

    def test_non_spacecraft_cospar_is_none(self):
        ing = _make_ingestor()
        row = _make_row(type="planet", designation="something")
        parsed = ing._parse_row(row)
        assert parsed is not None
        assert parsed["cospar_id"] is None
