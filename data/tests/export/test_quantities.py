"""Tests for space_map_data.export.quantities."""

import pytest

from space_map_data.export.quantities import UnitConverter


def _p31_stmt(qid: str, rank: str = "normal") -> dict:
    return {
        "rank": rank,
        "mainsnak": {"datavalue": {"value": {"id": qid}}},
    }


def _p2370_stmt(amount: str, unit_qid: str, rank: str = "normal") -> dict:
    return {
        "rank": rank,
        "mainsnak": {
            "datavalue": {
                "value": {
                    "amount": amount,
                    "unit": f"http://www.wikidata.org/entity/{unit_qid}",
                },
            },
        },
    }


class TestStripTrailingZeros:
    """UnitConverter._strip_trailing_zeros"""

    def test_integer_float(self):
        assert UnitConverter._strip_trailing_zeros(1.0) == 1

    def test_keeps_significant(self):
        assert UnitConverter._strip_trailing_zeros(1.5) == 1.5

    def test_small_value(self):
        assert UnitConverter._strip_trailing_zeros(0.001) == 0.001

    def test_large_value(self):
        assert UnitConverter._strip_trailing_zeros(1e10) == 1e10


class TestP31Qids:
    def test_extracts_ids(self):
        claims = {"P31": [_p31_stmt("Q100"), _p31_stmt("Q200")]}
        assert UnitConverter._p31_qids(claims) == {"Q100", "Q200"}

    def test_skips_deprecated(self):
        claims = {"P31": [_p31_stmt("Q100"), _p31_stmt("Q200", rank="deprecated")]}
        assert UnitConverter._p31_qids(claims) == {"Q100"}

    def test_empty(self):
        assert UnitConverter._p31_qids({}) == set()


class TestExtractP2370:
    def test_normal(self):
        claims = {"P2370": [_p2370_stmt("+1000", "Q11573")]}
        result = UnitConverter._extract_p2370(claims)
        assert result == (1000.0, "Q11573")

    def test_skips_deprecated(self):
        claims = {"P2370": [_p2370_stmt("+1000", "Q11573", rank="deprecated")]}
        assert UnitConverter._extract_p2370(claims) is None

    def test_unitless_skipped(self):
        """unit='1' means dimensionless — no base unit to convert to."""
        claims = {
            "P2370": [
                {
                    "rank": "normal",
                    "mainsnak": {
                        "datavalue": {
                            "value": {"amount": "+1", "unit": "1"},
                        },
                    },
                }
            ]
        }
        assert UnitConverter._extract_p2370(claims) is None

    def test_missing(self):
        assert UnitConverter._extract_p2370({}) is None


def _make_unit_entity(
    label: str, p31_qids: list[str], factor: str, base_qid: str
) -> dict:
    """Build a minimal Wikidata entity dict that UnitConverter.__init__ can consume."""
    return {
        "labels": {"en": label},
        "descriptions": {},
        "aliases": {},
        "sitelinks": {},
        "claims": {
            "P31": [_p31_stmt(qid) for qid in p31_qids],
            "P2370": [_p2370_stmt(factor, base_qid)],
        },
    }


class FakeCache:  # duck-typed stand-in for WikidataEntityCache
    """Minimal duck-typed cache for UnitConverter construction."""

    def __init__(self, units: dict):
        self._units = units

    def unit_items(self):
        return self._units

    def property_items(self):
        return {}


def _build_mass_converter() -> UnitConverter:
    """Build a converter with a small mass ladder: kilogram and gram.

    The factors are relative to a shared implicit base (gram→kg, kg→gram).
    UnitConverter sorts by factor descending, so kg (1000) comes before gram (0.001).
    best_unit picks the first entry where value_in_base / factor > 1.1.
    """
    units = {
        "Q11570": _make_unit_entity(  # kilogram
            "kilogram",
            ["Q3647172", "Q223662"],  # mass + SI base unit
            "+1000",
            "Q41803",  # base: gram
        ),
        "Q41803": _make_unit_entity(  # gram
            "gram",
            ["Q3647172", "Q208469"],  # mass + SI derived unit
            "+0.001",
            "Q11570",  # base: kilogram (avoids synthetic "metre" entry)
        ),
    }
    return UnitConverter(FakeCache(units))  # type: ignore[arg-type]


class TestBestUnit:
    def test_picks_largest_above_threshold(self):
        conv = _build_mass_converter()
        # Ladder: kg(factor=1000) > gram(factor=0.001).
        # value_in_base=5000 → 5000/1000=5 (>1.1) → picks kilogram.
        result = conv.best_unit(5000, "mass")
        assert result is not None
        assert result["unit"] == "kilogram"
        assert result["value"] == 5.0

    def test_falls_back_to_smallest(self):
        conv = _build_mass_converter()
        result = conv.best_unit(0.0000001, "mass")
        assert result is not None
        assert result["unit"] in ("gram", "kilogram")

    def test_unknown_qty_type(self):
        conv = _build_mass_converter()
        assert conv.best_unit(100, "temperature") is None

    def test_negative_value_picks_by_magnitude(self):
        # Regression: ``value > 1.1`` would always be false for negatives, so
        # an elevation of -90 m used to tumble down to the smallest unit
        # (e.g. attometre × 1e19) instead of staying as -90 m.
        conv = _build_mass_converter()
        result = conv.best_unit(-5000, "mass")
        assert result is not None
        assert result["unit"] == "kilogram"
        assert result["value"] == -5.0

    def test_negative_value_threshold_is_magnitude(self):
        # |value/factor| just above 1.1 should still pick the larger unit
        # the same as positive values do.
        conv = _build_mass_converter()
        result = conv.best_unit(-1200, "mass")
        assert result is not None
        assert result["unit"] == "kilogram"
        assert result["value"] == -1.2


class TestConvert:
    def test_known_unit(self):
        conv = _build_mass_converter()
        result = conv.convert(5.0, "Q11570")  # 5 kilogram
        assert result is not None
        assert result["value"] > 0

    def test_unknown_unit(self):
        conv = _build_mass_converter()
        assert conv.convert(5.0, "Q999999") is None

    def test_tracks_used_units(self):
        conv = _build_mass_converter()
        conv.convert(5.0, "Q11570")
        assert len(conv.used_units) > 0


class TestConvertToBase:
    def test_converts_to_base(self):
        conv = _build_mass_converter()
        # convert_to_base returns value * factor. kg has factor=1000.
        result = conv.convert_to_base(5.0, "Q11570")
        assert result is not None
        assert result == pytest.approx(5000.0)

    def test_type_mismatch(self):
        conv = _build_mass_converter()
        assert conv.convert_to_base(5.0, "Q11570", expected_type="length") is None

    def test_unknown_qid(self):
        conv = _build_mass_converter()
        assert conv.convert_to_base(5.0, "Q999999") is None
