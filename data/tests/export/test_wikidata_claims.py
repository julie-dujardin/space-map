"""Tests for space_map_data.export.objects.wikidata_claims."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from space_map_data.export.wikidata import active_statements
from space_map_data.export.objects.wikidata_claims import (
    MultipleClaimValues,
    extract_claims,
    radius_km_from_claims,
    resolve_entity_ref,
    resolve_unit,
    _all_entity_qids,
    _all_strings,
    _all_times,
    _has_nasa_ref_url,
    _is_sourced_to,
    _parse_quantity,
    _qualifier_qid,
    _single_entity_qid,
    _single_quantity,
    _single_time,
    _stmt_value,
)


# ---------------------------------------------------------------------------
# Helpers to build realistic Wikidata claim structures
# ---------------------------------------------------------------------------


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


def _time_snak(time: str, precision: int = 11) -> dict:
    return {
        "snaktype": "value",
        "datavalue": {
            "value": {
                "time": time,
                "timezone": 0,
                "before": 0,
                "after": 0,
                "precision": precision,
                "calendarmodel": "http://www.wikidata.org/entity/Q1985727",
            },
            "type": "time",
        },
    }


def _string_snak(val: str) -> dict:
    return {"snaktype": "value", "datavalue": {"value": val, "type": "string"}}


def _monolingualtext_snak(text: str, language: str) -> dict:
    return {
        "snaktype": "value",
        "datavalue": {
            "value": {"text": text, "language": language},
            "type": "monolingualtext",
        },
    }


def _stmt(
    snak: dict,
    *,
    rank: str = "normal",
    qualifiers: dict | None = None,
    references: list | None = None,
) -> dict:
    result: dict[str, Any] = {
        "mainsnak": snak,
        "type": "statement",
        "rank": rank,
    }
    if qualifiers is not None:
        result["qualifiers"] = qualifiers
    if references is not None:
        result["references"] = references
    return result


def _p248_ref(qid: str) -> dict:
    """Reference block citing a source via P248 (stated in)."""
    return {
        "snaks": {"P248": [_entity_snak(qid)]},
    }


def _p854_ref(url: str) -> dict:
    """Reference block with a reference URL (P854)."""
    return {
        "snaks": {"P854": [_string_snak(url)]},
    }


class TestActiveStmts:
    """active_statements"""

    def test_filters_deprecated(self):
        claims = {
            "P1": [
                _stmt(_qty_snak("+1"), rank="normal"),
                _stmt(_qty_snak("+2"), rank="deprecated"),
            ]
        }
        result = active_statements(claims, "P1")
        assert len(result) == 1
        assert result[0]["rank"] == "normal"

    def test_prefers_preferred(self):
        claims = {
            "P1": [
                _stmt(_qty_snak("+1"), rank="normal"),
                _stmt(_qty_snak("+2"), rank="preferred"),
                _stmt(_qty_snak("+3"), rank="normal"),
            ]
        }
        result = active_statements(claims, "P1")
        assert len(result) == 1
        assert result[0]["rank"] == "preferred"

    def test_falls_back_to_normal_when_no_preferred(self):
        claims = {
            "P1": [
                _stmt(_qty_snak("+1"), rank="normal"),
                _stmt(_qty_snak("+2"), rank="normal"),
            ]
        }
        assert len(active_statements(claims, "P1")) == 2

    def test_missing_property_returns_empty(self):
        assert active_statements({}, "P1") == []

    def test_all_deprecated_returns_empty(self):
        claims = {
            "P1": [
                _stmt(_qty_snak("+1"), rank="deprecated"),
                _stmt(_qty_snak("+2"), rank="deprecated"),
            ]
        }
        assert active_statements(claims, "P1") == []


class TestStmtValue:
    """_stmt_value"""

    def test_extracts_value(self):
        s = _stmt(_qty_snak("+42"))
        assert _stmt_value(s)["amount"] == "+42"

    def test_missing_datavalue_returns_none(self):
        assert _stmt_value({"mainsnak": {"snaktype": "novalue"}}) is None

    def test_empty_stmt_returns_none(self):
        assert _stmt_value({}) is None


class TestQualifierQid:
    """_qualifier_qid"""

    def test_extracts_qualifier(self):
        s = _stmt(
            _qty_snak("+1"),
            qualifiers={"P518": [_entity_snak("Q202785")]},
        )
        assert _qualifier_qid(s, "P518") == "Q202785"

    def test_missing_qualifier_returns_none(self):
        s = _stmt(_qty_snak("+1"))
        assert _qualifier_qid(s, "P518") is None

    def test_wrong_qualifier_prop_returns_none(self):
        s = _stmt(
            _qty_snak("+1"),
            qualifiers={"P518": [_entity_snak("Q202785")]},
        )
        assert _qualifier_qid(s, "P1480") is None


class TestReferenceParsing:
    """_is_sourced_to / _has_nasa_ref_url"""

    def test_is_sourced_to_positive(self):
        s = _stmt(
            _qty_snak("+1"),
            references=[_p248_ref("Q4026990")],
        )
        assert _is_sourced_to(s, "Q4026990") is True

    def test_is_sourced_to_negative(self):
        s = _stmt(
            _qty_snak("+1"),
            references=[_p248_ref("Q4026990")],
        )
        assert _is_sourced_to(s, "Q999") is False

    def test_is_sourced_to_no_refs(self):
        s = _stmt(_qty_snak("+1"))
        assert _is_sourced_to(s, "Q4026990") is False

    def test_has_nasa_ref_url_positive(self):
        s = _stmt(
            _qty_snak("+1"),
            references=[
                _p854_ref(
                    "https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html"
                )
            ],
        )
        assert _has_nasa_ref_url(s) is True

    def test_has_nasa_ref_url_negative(self):
        s = _stmt(
            _qty_snak("+1"),
            references=[_p854_ref("https://example.com/data")],
        )
        assert _has_nasa_ref_url(s) is False


class TestAllStrings:
    """_all_strings"""

    def test_extracts_strings(self):
        claims = {
            "P18": [
                _stmt(_string_snak("Blue Marble.jpg")),
                _stmt(_string_snak("Earth from space.png")),
            ]
        }
        assert _all_strings(claims, "P18") == [
            "Blue Marble.jpg",
            "Earth from space.png",
        ]

    def test_skips_non_strings(self):
        claims = {"P18": [_stmt(_qty_snak("+1"))]}
        assert _all_strings(claims, "P18") == []

    def test_skips_empty_strings(self):
        claims = {"P18": [_stmt(_string_snak(""))]}
        assert _all_strings(claims, "P18") == []


class TestTimeClaims:
    """_all_times / _single_time"""

    def test_all_times_single(self):
        claims = {"P575": [_stmt(_time_snak("+1801-01-01T00:00:00Z", precision=9))]}
        assert _all_times(claims, "P575") == ["+1801-01-01T00:00:00Z"]

    def test_all_times_deduplicates_by_precision(self):
        """When multiple times at different precisions, keep only the most precise."""
        claims = {
            "P575": [
                _stmt(_time_snak("+1801-01-01T00:00:00Z", precision=9)),  # year
                _stmt(_time_snak("+1801-03-28T00:00:00Z", precision=11)),  # day
            ]
        }
        result = _all_times(claims, "P575")
        assert result == ["+1801-03-28T00:00:00Z"]

    def test_all_times_keeps_equal_precision(self):
        claims = {
            "P575": [
                _stmt(_time_snak("+1801-03-28T00:00:00Z", precision=11)),
                _stmt(_time_snak("+1802-01-01T00:00:00Z", precision=11)),
            ]
        }
        assert len(_all_times(claims, "P575")) == 2

    def test_single_time_returns_value(self):
        claims = {"P619": [_stmt(_time_snak("+1990-04-24T00:00:00Z"))]}
        assert _single_time(claims, "P619", "Q1") == "+1990-04-24T00:00:00Z"

    def test_single_time_empty(self):
        assert _single_time({}, "P619", "Q1") is None

    def test_single_time_raises_on_multiple(self):
        claims = {
            "P619": [
                _stmt(_time_snak("+1990-04-24T00:00:00Z", precision=11)),
                _stmt(_time_snak("+1991-01-01T00:00:00Z", precision=11)),
            ]
        }
        with pytest.raises(MultipleClaimValues, match="launch_date.*Q1"):
            _single_time(claims, "P619", "Q1")

    def test_single_time_inception_picks_earliest(self):
        # Predecessor founding (1884) + restructuring (1991) — the older
        # date wins so the group page shows the longer history.
        claims = {
            "P571": [
                _stmt(_time_snak("+1884-00-00T00:00:00Z", precision=9)),
                _stmt(_time_snak("+1991-00-00T00:00:00Z", precision=9)),
            ]
        }
        assert _single_time(claims, "P571", "Q1") == "+1884-00-00T00:00:00Z"


class TestParseQuantity:
    """_parse_quantity"""

    def test_dimensionless(self):
        dv = {"amount": "+26.59", "unit": "1"}
        assert _parse_quantity(dv) == 26.59

    def test_with_unit(self):
        dv = {
            "amount": "+5972.37",
            "unit": "http://www.wikidata.org/entity/Q613726",
        }
        result = _parse_quantity(dv)
        assert result == {"value": 5972.37, "unit": "Q613726"}

    def test_negative_amount(self):
        dv = {"amount": "-89.2", "unit": "http://www.wikidata.org/entity/Q25267"}
        result = _parse_quantity(dv)
        assert result == {"value": -89.2, "unit": "Q25267"}

    def test_bad_amount_returns_none(self):
        assert _parse_quantity({"amount": "not-a-number", "unit": "1"}) is None

    def test_no_amount_returns_none(self):
        assert _parse_quantity({"unit": "1"}) is None


class TestSingleQuantity:
    """_single_quantity — disambiguation logic"""

    def test_single_value(self):
        claims = {"P2054": [_stmt(_qty_snak("+5.513", "Q13147228"))]}
        result = _single_quantity(claims, "P2054", needs_unit=True, qid="Q2")
        assert result == {"value": 5.513, "unit": "Q13147228"}

    def test_empty(self):
        assert _single_quantity({}, "P2054", needs_unit=True, qid="Q2") is None

    def test_needs_unit_skips_dimensionless(self):
        claims = {"P2054": [_stmt(_qty_snak("+5.513"))]}
        assert _single_quantity(claims, "P2054", needs_unit=True, qid="Q2") is None

    def test_no_needs_unit_keeps_dimensionless(self):
        # P1457 absolute magnitude: dimensionless
        claims = {"P1457": [_stmt(_qty_snak("+3.3"))]}
        result = _single_quantity(claims, "P1457", needs_unit=False, qid="Q2")
        assert result == 3.3

    def test_deduplicates_identical_values(self):
        claims = {
            "P2054": [
                _stmt(_qty_snak("+5.513", "Q13147228")),
                _stmt(_qty_snak("+5.513", "Q13147228")),
            ]
        }
        result = _single_quantity(claims, "P2054", needs_unit=True, qid="Q2")
        assert result == {"value": 5.513, "unit": "Q13147228"}

    def test_radius_prefers_mean(self):
        """P2120 with mean qualifier (P518 = Q202785) should be preferred."""
        claims = {
            "P2120": [
                _stmt(
                    _qty_snak("+6378.137", "Q828224"),
                    qualifiers={"P518": [_entity_snak("Q23538")]},  # equatorial
                ),
                _stmt(
                    _qty_snak("+6371", "Q828224"),
                    qualifiers={"P518": [_entity_snak("Q202785")]},  # average
                ),
            ]
        }
        result = _single_quantity(claims, "P2120", needs_unit=True, qid="Q2")
        assert result == {"value": 6371.0, "unit": "Q828224"}

    def test_prefers_trusted_source(self):
        """Prefer value sourced from JPL SBDB (Q4026990)."""
        claims = {
            "P2067": [
                _stmt(_qty_snak("+100", "Q11570")),
                _stmt(
                    _qty_snak("+99", "Q11570"),
                    references=[_p248_ref("Q4026990")],
                ),
            ]
        }
        result = _single_quantity(claims, "P2067", needs_unit=True, qid="Q99999")
        assert result == {"value": 99.0, "unit": "Q11570"}

    def test_prefers_nasa_ref_url(self):
        claims = {
            "P2054": [
                _stmt(_qty_snak("+5.0", "Q13147228")),
                _stmt(
                    _qty_snak("+5.513", "Q13147228"),
                    references=[
                        _p854_ref(
                            "https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html"
                        )
                    ],
                ),
            ]
        }
        result = _single_quantity(claims, "P2054", needs_unit=True, qid="Q99999")
        assert result == {"value": 5.513, "unit": "Q13147228"}

    def test_pick_first_override(self):
        """Q18325885 P1215 is in _PICK_FIRST set."""
        claims = {
            "P1215": [
                _stmt(_qty_snak("+26.59")),
                _stmt(_qty_snak("+27.0")),
            ]
        }
        result = _single_quantity(claims, "P1215", needs_unit=False, qid="Q18325885")
        assert result == 26.59

    def test_average_override(self):
        """Q319 P1215 is in _AVERAGE set."""
        claims = {
            "P1215": [
                _stmt(_qty_snak("-1.61")),
                _stmt(_qty_snak("-2.94")),
            ]
        }
        result = _single_quantity(claims, "P1215", needs_unit=False, qid="Q319")
        assert result == pytest.approx((-1.61 + -2.94) / 2)

    def test_discard_override(self):
        """Q147561 P7015 is in _DISCARD set."""
        claims = {
            "P7015": [
                _stmt(_qty_snak("+0.003", "Q1051665")),
                _stmt(_qty_snak("+0.005", "Q1051665")),
            ]
        }
        result = _single_quantity(claims, "P7015", needs_unit=True, qid="Q147561")
        assert result is None

    def test_raises_on_unresolvable_multiple(self):
        claims = {
            "P2054": [
                _stmt(_qty_snak("+5.0", "Q13147228")),
                _stmt(_qty_snak("+6.0", "Q13147228")),
            ]
        }
        with pytest.raises(MultipleClaimValues, match="density"):
            _single_quantity(claims, "P2054", needs_unit=True, qid="Q99999")

    def test_width_picks_max_soho(self):
        """Q320638 SOHO: width 2.7m (body) vs 9.5m (solar panel span) — pick max."""
        claims = {
            "P2049": [
                _stmt(
                    _qty_snak("+2.7", "Q11573"),
                    qualifiers={"P518": [_entity_snak("Q372881")]},  # body
                ),
                _stmt(
                    _qty_snak("+9.5", "Q11573"),
                    qualifiers={"P1706": [_entity_snak("Q7556726")]},  # solar panel
                ),
            ]
        }
        result = _single_quantity(claims, "P2049", needs_unit=True, qid="Q320638")
        assert result == {"value": 9.5, "unit": "Q11573"}

    def test_length_picks_max_iss(self):
        """Q193538 ISS: length 141ft (pressurized) vs 151ft (with arrays) — pick max."""
        claims = {
            "P2043": [
                _stmt(
                    _qty_snak("+141", "Q174728"),
                    qualifiers={"P518": [_entity_snak("Q1128004")]},  # pressurized
                ),
                _stmt(
                    _qty_snak("+151", "Q174728"),
                    qualifiers={"P518": [_entity_snak("Q7556726")]},  # overall
                ),
            ]
        }
        result = _single_quantity(claims, "P2043", needs_unit=True, qid="Q193538")
        assert result == {"value": 151.0, "unit": "Q174728"}

    def test_preferred_criterion_qualifier(self):
        """P2067 prefers Q2333272 (launch mass) via P1013 qualifier."""
        claims = {
            "P2067": [
                _stmt(_qty_snak("+100", "Q11570")),
                _stmt(
                    _qty_snak("+80", "Q11570"),
                    qualifiers={"P1013": [_entity_snak("Q2333272")]},
                ),
            ]
        }
        result = _single_quantity(claims, "P2067", needs_unit=True, qid="Q99999")
        assert result == {"value": 80.0, "unit": "Q11570"}


class TestEntityQids:
    """Entity QID extraction."""

    def test_all_entity_qids(self):
        claims = {
            "P31": [
                _stmt(_entity_snak("Q3504248")),
                _stmt(_entity_snak("Q17362350")),
            ]
        }
        assert _all_entity_qids(claims, "P31") == ["Q3504248", "Q17362350"]

    def test_single_entity_qid(self):
        claims = {"P744": [_stmt(_entity_snak("Q123456"))]}
        assert _single_entity_qid(claims, "P744", "Q1") == "Q123456"

    def test_single_entity_qid_empty(self):
        assert _single_entity_qid({}, "P744", "Q1") is None

    def test_single_entity_qid_deduplicates(self):
        claims = {
            "P744": [
                _stmt(_entity_snak("Q123456")),
                _stmt(_entity_snak("Q123456")),
            ]
        }
        assert _single_entity_qid(claims, "P744", "Q1") == "Q123456"

    def test_single_entity_qid_raises_on_multiple(self):
        claims = {
            "P744": [
                _stmt(_entity_snak("Q123")),
                _stmt(_entity_snak("Q456")),
            ]
        }
        with pytest.raises(MultipleClaimValues, match="asteroid_family.*Q1"):
            _single_entity_qid(claims, "P744", "Q1")


class TestExtractClaims:
    """extract_claims — integration."""

    def test_extracts_quantity_with_unit(self):
        claims = {"P2067": [_stmt(_qty_snak("+5972.37", "Q613726"))]}
        result = extract_claims(claims, "Q2")
        assert result["mass"] == {"value": 5972.37, "unit": "Q613726"}

    def test_extracts_dimensionless_quantity(self):
        claims = {"P1457": [_stmt(_qty_snak("+3.3"))]}
        result = extract_claims(claims, "Q2")
        assert result["absolute_magnitude"] == 3.3

    def test_extracts_image(self):
        claims = {"P18": [_stmt(_string_snak("Earth.jpg"))]}
        result = extract_claims(claims, "Q2")
        assert result["image"] == ["Earth.jpg"]

    def test_extracts_website(self):
        claims = {"P856": [_stmt(_string_snak("https://hubble.nasa.gov/"))]}
        result = extract_claims(claims, "Q2")
        assert result["website"] == ["https://hubble.nasa.gov/"]

    def test_extracts_launch_date(self):
        claims = {"P619": [_stmt(_time_snak("+1990-04-24T00:00:00Z"))]}
        result = extract_claims(claims, "Q2513")
        assert result["launch_date"] == "+1990-04-24T00:00:00Z"

    def test_launch_date_picks_earliest(self):
        """Q5100935 Tiangong: multiple P619 statements; pick the earliest."""
        claims = {
            "P619": [
                _stmt(
                    _time_snak("+2021-04-29T00:00:00Z", precision=11),
                    qualifiers={"P518": [_entity_snak("Q5170154")]},  # Tianhe
                ),
                _stmt(
                    _time_snak("+2022-07-24T00:00:00Z", precision=11),
                    qualifiers={"P518": [_entity_snak("Q106658038")]},  # Wentian
                ),
            ]
        }
        result = extract_claims(claims, "Q5100935")
        assert result["launch_date"] == "+2021-04-29T00:00:00Z"

    def test_launch_date_uses_p4241_refine_date(self):
        """Q5100935 Tiangong: P4241 qualifier resolves to a more precise launch time."""
        claims = {
            "P619": [
                _stmt(
                    _time_snak("+2021-04-29T00:00:00Z", precision=11),
                    qualifiers={
                        "P4241": [_entity_snak("Q95018095")],
                        "P518": [_entity_snak("Q5170154")],
                    },
                ),
                _stmt(
                    _time_snak("+2022-07-24T00:00:00Z", precision=11),
                    qualifiers={"P4241": [_entity_snak("Q95033742")]},
                ),
            ]
        }
        cache = MagicMock()
        cache.get_referenced.return_value = {
            "labels": {},
            "descriptions": {},
            "aliases": {},
            "sitelinks": {},
            "claims": {
                "P619": [_stmt(_time_snak("+2021-04-29T03:23:15Z", precision=14))],
            },
        }
        result = extract_claims(claims, "Q5100935", wikidata_entities=cache)
        assert result["launch_date"] == "+2021-04-29T03:23:15Z"
        cache.get_referenced.assert_any_call("Q95018095")

    def test_launch_date_p4241_falls_back_to_p585(self):
        """When the refine-date entity has no P619, fall back to P585."""
        claims = {
            "P619": [
                _stmt(
                    _time_snak("+2021-04-29T00:00:00Z", precision=11),
                    qualifiers={"P4241": [_entity_snak("Q95018095")]},
                ),
            ]
        }
        cache = MagicMock()
        cache.get_referenced.return_value = {
            "labels": {},
            "descriptions": {},
            "aliases": {},
            "sitelinks": {},
            "claims": {
                "P585": [_stmt(_time_snak("+2021-04-29T03:23:15Z", precision=14))],
            },
        }
        result = extract_claims(claims, "Q5100935", wikidata_entities=cache)
        assert result["launch_date"] == "+2021-04-29T03:23:15Z"

    def test_launch_date_p4241_entity_missing(self):
        """When the refine-date entity isn't in the cache, fall back to mainsnak time."""
        claims = {
            "P619": [
                _stmt(
                    _time_snak("+2021-04-29T00:00:00Z", precision=11),
                    qualifiers={"P4241": [_entity_snak("Q95018095")]},
                ),
            ]
        }
        cache = MagicMock()
        cache.get_referenced.return_value = None
        result = extract_claims(claims, "Q5100935", wikidata_entities=cache)
        assert result["launch_date"] == "+2021-04-29T00:00:00Z"

    def test_launch_date_p4241_ignored_when_less_precise(self):
        """Refine-date entity time is only used when more precise than the mainsnak."""
        claims = {
            "P619": [
                _stmt(
                    _time_snak("+2021-04-29T03:23:15Z", precision=14),
                    qualifiers={"P4241": [_entity_snak("Q95018095")]},
                ),
            ]
        }
        cache = MagicMock()
        cache.get_referenced.return_value = {
            "labels": {},
            "descriptions": {},
            "aliases": {},
            "sitelinks": {},
            "claims": {
                "P619": [_stmt(_time_snak("+2021-04-29T00:00:00Z", precision=11))],
            },
        }
        result = extract_claims(claims, "Q5100935", wikidata_entities=cache)
        assert result["launch_date"] == "+2021-04-29T03:23:15Z"

    def test_extracts_discovery_dates(self):
        claims = {
            "P575": [
                _stmt(_time_snak("+1801-01-01T00:00:00Z", precision=9)),
                _stmt(_time_snak("+1801-03-28T00:00:00Z", precision=11)),
            ]
        }
        result = extract_claims(claims, "Q3134")
        # Only the most precise should remain
        assert result["discovery_date"] == ["+1801-03-28T00:00:00Z"]

    def test_discovery_date_uses_p4241_refine_date(self):
        """P4241 (refine date) refinement applies to any time claim, not just P619."""
        claims = {
            "P575": [
                _stmt(
                    _time_snak("+2014-01-15T00:00:00Z", precision=11),
                    qualifiers={"P4241": [_entity_snak("Q42")]},
                ),
            ]
        }
        cache = MagicMock()
        cache.get_referenced.return_value = {
            "labels": {},
            "descriptions": {},
            "aliases": {},
            "sitelinks": {},
            "claims": {
                "P585": [_stmt(_time_snak("+2014-01-15T22:00:00Z", precision=14))],
            },
        }
        result = extract_claims(claims, "Q1", wikidata_entities=cache)
        assert result["discovery_date"] == ["+2014-01-15T22:00:00Z"]

    def test_extracts_entity_refs_multiple(self):
        claims = {
            "P31": [
                _stmt(_entity_snak("Q3504248")),
                _stmt(_entity_snak("Q6999")),  # in ignored set
            ]
        }
        result = extract_claims(claims, "Q2")
        assert result["instance_of"] == ["Q3504248"]

    def test_extracts_entity_refs_single(self):
        claims = {"P744": [_stmt(_entity_snak("Q123456"))]}
        result = extract_claims(claims, "Q2")
        assert result["asteroid_family"] == "Q123456"

    def test_p2076_temperature_routing_no_qualifier(self):
        """P2076 without P1480 qualifier defaults to 'temperature'."""
        claims = {"P2076": [_stmt(_qty_snak("+15", "Q25267"))]}
        result = extract_claims(claims, "Q2")
        assert result["temperature"] == {"value": 15.0, "unit": "Q25267"}

    def test_p2076_min_temperature_qualifier(self):
        """P2076 with P1480=Q10585806 (minimum) routes to min_temperature."""
        claims = {
            "P2076": [
                _stmt(
                    _qty_snak("+15", "Q25267"),
                    qualifiers={"P1480": [_entity_snak("Q10585806")]},
                ),
            ]
        }
        result = extract_claims(claims, "Q2")
        assert result["min_temperature"] == {"value": 15.0, "unit": "Q25267"}

    def test_p7422_takes_priority_over_p2076_min(self):
        """P7422 (min temp) from GLOBAL_CLAIMS should take priority via setdefault."""
        claims = {
            "P7422": [_stmt(_qty_snak("-89.2", "Q25267"))],
            "P2076": [
                _stmt(
                    _qty_snak("-50", "Q25267"),
                    qualifiers={"P1480": [_entity_snak("Q10585806")]},  # minimum
                ),
            ],
        }
        result = extract_claims(claims, "Q2")
        assert result["min_temperature"] == {"value": -89.2, "unit": "Q25267"}

    def test_sun_temperature_preferred_rank(self):
        """Q525 Sun: preferred P2076 statement (15.71M K) wins over normal ones."""
        claims = {
            "P2076": [
                _stmt(_qty_snak("+15710000", "Q11579"), rank="preferred"),
                _stmt(_qty_snak("+5772", "Q11579"), rank="normal"),
                _stmt(_qty_snak("+2000000", "Q11579"), rank="normal"),
            ]
        }
        result = extract_claims(claims, "Q525")
        assert result["temperature"] == {"value": 15710000.0, "unit": "Q11579"}
        assert "min_temperature" not in result
        assert "max_temperature" not in result

    def test_earth_temperature_with_p7422_p6591(self):
        """Q2 Earth: P2076 for avg, P7422 for min, P6591 for max."""
        claims = {
            "P2076": [_stmt(_qty_snak("+15", "Q25267"))],
            "P7422": [_stmt(_qty_snak("-89.2", "Q25267"))],
            "P6591": [_stmt(_qty_snak("+56.7", "Q25267"))],
        }
        result = extract_claims(claims, "Q2")
        assert result["temperature"] == {"value": 15.0, "unit": "Q25267"}
        assert result["min_temperature"] == {"value": -89.2, "unit": "Q25267"}
        assert result["max_temperature"] == {"value": 56.7, "unit": "Q25267"}

    def test_venus_temperature_p1480_mean(self):
        """Q313 Venus: two P2076 stmts route to temperature; NASA source wins."""
        claims = {
            "P2076": [
                _stmt(
                    _qty_snak("+464", "Q25267"),
                    qualifiers={"P1480": [_entity_snak("Q2796622")]},  # mean
                    references=[
                        _p854_ref(
                            "https://nssdc.gsfc.nasa.gov/planetary/factsheet/venusfact.html"
                        ),
                        _p248_ref("Q6952408"),
                    ],
                ),
                _stmt(_qty_snak("+474", "Q25267")),
            ]
        }
        result = extract_claims(claims, "Q313")
        assert result["temperature"] == {"value": 464.0, "unit": "Q25267"}

    def test_mars_temperature_mixed_p1480(self):
        """Q111 Mars: P2076 without qualifier is avg, others have P1480 min/max."""
        claims = {
            "P2076": [
                _stmt(_qty_snak("-63", "Q25267")),
                _stmt(
                    _qty_snak("-143", "Q25267"),
                    qualifiers={"P1480": [_entity_snak("Q10585806")]},  # minimum
                ),
                _stmt(
                    _qty_snak("+35", "Q25267"),
                    qualifiers={"P1480": [_entity_snak("Q10578722")]},  # maximum
                ),
            ]
        }
        result = extract_claims(claims, "Q111")
        assert result["temperature"] == {"value": -63.0, "unit": "Q25267"}
        assert result["min_temperature"] == {"value": -143.0, "unit": "Q25267"}
        assert result["max_temperature"] == {"value": 35.0, "unit": "Q25267"}

    def test_bennu_temperature_p5102_qualifier(self):
        """Q11558 Bennu: P2076 uses P5102 instead of P1480 for nature-of-value."""
        claims = {
            "P2076": [
                _stmt(
                    _qty_snak("+236", "Q11579"),
                    qualifiers={"P5102": [_entity_snak("Q10585806")]},  # minimum
                ),
                _stmt(
                    _qty_snak("+259", "Q11579"),
                    qualifiers={"P5102": [_entity_snak("Q202785")]},  # average
                ),
                _stmt(
                    _qty_snak("+279", "Q11579"),
                    qualifiers={"P5102": [_entity_snak("Q10578722")]},  # maximum
                ),
            ]
        }
        result = extract_claims(claims, "Q11558")
        assert result["temperature"] == {"value": 259.0, "unit": "Q11579"}
        assert result["min_temperature"] == {"value": 236.0, "unit": "Q11579"}
        assert result["max_temperature"] == {"value": 279.0, "unit": "Q11579"}

    def test_vesta_temperature_p518_qualifier(self):
        """Q3030 Vesta: P2076 uses P518 (applies to part) for min/max routing."""
        claims = {
            "P2076": [
                _stmt(
                    _qty_snak("+85", "Q11579"),
                    qualifiers={"P518": [_entity_snak("Q10585806")]},  # minimum
                ),
                _stmt(
                    _qty_snak("+270", "Q11579"),
                    qualifiers={"P518": [_entity_snak("Q10578722")]},  # maximum
                ),
            ]
        }
        result = extract_claims(claims, "Q3030")
        assert result["min_temperature"] == {"value": 85.0, "unit": "Q11579"}
        assert result["max_temperature"] == {"value": 270.0, "unit": "Q11579"}
        assert "temperature" not in result

    def test_empty_claims(self):
        assert extract_claims({}, "Q2") == {}

    def test_skips_falsy_values(self):
        """Empty lists/None values should not appear in result."""
        claims = {"P856": []}  # no statements
        result = extract_claims(claims, "Q2")
        assert "website" not in result


class TestResolveEntityRef:
    """resolve_entity_ref"""

    def _mock_cache(self, data: dict | None) -> MagicMock:
        cache = MagicMock()
        if data is not None:
            data.setdefault("aliases", {})
            data.setdefault("claims", {})
        cache.get_referenced.return_value = data
        return cache

    def test_resolves_name_and_wikipedia(self):
        cache = self._mock_cache(
            {
                "labels": {"en": "Ceres"},
                "sitelinks": {"en": "Ceres (dwarf planet)"},
            }
        )
        result = resolve_entity_ref("Q3134", "en", cache)
        assert result is not None
        assert result.to_dict() == {
            "name": "Ceres",
            "wikipedia": "https://en.wikipedia.org/wiki/Ceres%20%28dwarf%20planet%29",
        }

    def test_resolves_name_only(self):
        cache = self._mock_cache(
            {
                "labels": {"en": "Hubble"},
                "sitelinks": {},
            }
        )
        result = resolve_entity_ref("Q2513", "en", cache)
        assert result is not None
        assert result.to_dict() == {"name": "Hubble"}

    def test_returns_none_when_not_found(self):
        cache = self._mock_cache(None)
        assert resolve_entity_ref("Q999", "en", cache) is None

    def test_returns_none_when_no_label(self):
        cache = self._mock_cache(
            {
                "labels": {},
                "sitelinks": {"en": "Something"},
            }
        )
        assert resolve_entity_ref("Q999", "en", cache) is None

    def test_short_name_from_alias(self):
        """A shorter alias is exported as short_name alongside the full label."""
        cache = self._mock_cache(
            {
                "labels": {"en": "Some Long Name"},
                "aliases": {"en": ["SLN"]},
                "sitelinks": {},
            }
        )
        result = resolve_entity_ref("Q1", "en", cache)
        assert result is not None
        assert result.name == "Some Long Name"
        assert result.short_name == "SLN"

    def test_uses_p1813_short_name(self):
        """P1813 (short name) is exported as short_name; full label stays as name."""
        cache = self._mock_cache(
            {
                "labels": {"en": "National Aeronautics and Space Administration"},
                "sitelinks": {},
                "claims": {
                    "P1813": [_stmt(_monolingualtext_snak("NASA", "en"))],
                },
            }
        )
        result = resolve_entity_ref("Q23548", "en", cache)
        assert result is not None
        assert result.name == "National Aeronautics and Space Administration"
        assert result.short_name == "NASA"

    def test_uses_shortest_alias(self):
        """When no P1813 exists, the shortest alias is used as short_name."""
        cache = self._mock_cache(
            {
                "labels": {"en": "Kennedy Space Center Launch Complex 39B"},
                "aliases": {"en": ["LC39B", "LC-39B", "Launch Complex 39B"]},
                "sitelinks": {},
            }
        )
        result = resolve_entity_ref("Q24256506", "en", cache)
        assert result is not None
        assert result.name == "Kennedy Space Center Launch Complex 39B"
        assert result.short_name == "LC39B"

    def test_p1813_preferred_over_longer_alias(self):
        """P1813 short name is considered alongside aliases; shortest wins."""
        cache = self._mock_cache(
            {
                "labels": {"en": "Some Very Long Organization Name Here"},
                "aliases": {"en": ["SVLON", "SV"]},
                "claims": {
                    "P1813": [_stmt(_monolingualtext_snak("SVL", "en"))],
                },
                "sitelinks": {},
            }
        )
        result = resolve_entity_ref("Q1", "en", cache)
        assert result is not None
        assert result.name == "Some Very Long Organization Name Here"
        assert result.short_name == "SV"

    def test_p1813_wrong_language_ignored(self):
        """P1813 in a different language should not be used."""
        cache = self._mock_cache(
            {
                "labels": {"fr": "Très long nom d'organisation spatiale"},
                "aliases": {"fr": ["TLNO"]},
                "claims": {
                    "P1813": [_stmt(_monolingualtext_snak("SHORTENG", "en"))],
                },
                "sitelinks": {},
            }
        )
        result = resolve_entity_ref("Q1", "fr", cache)
        assert result is not None
        assert result.name == "Très long nom d'organisation spatiale"
        assert result.short_name == "TLNO"

    def test_no_shorter_form_keeps_original(self):
        """When all aliases are longer, no short_name is set."""
        long_name = "A Moderately Long Name Here"
        cache = self._mock_cache(
            {
                "labels": {"en": long_name},
                "aliases": {"en": ["An Even Longer Alternative Name"]},
                "sitelinks": {},
            }
        )
        result = resolve_entity_ref("Q1", "en", cache)
        assert result is not None
        assert result.name == long_name
        assert result.short_name is None

    def test_no_aliases_no_short_name(self):
        """When there are no aliases or P1813, no short_name is set."""
        cache = self._mock_cache(
            {
                "labels": {"en": "International Space Station"},
                "sitelinks": {},
            }
        )
        result = resolve_entity_ref("Q1", "en", cache)
        assert result is not None
        assert result.name == "International Space Station"
        assert result.short_name is None


class TestResolveUnit:
    """resolve_unit"""

    def _mock_cache(self, data: dict | None) -> MagicMock:
        cache = MagicMock()
        cache.get_referenced.return_value = data
        return cache

    def test_resolves_unit(self):
        cache = self._mock_cache({"labels": {"en": "Kilogram"}})
        assert resolve_unit("Q11570", cache) == "kilogram"

    def test_normalizes_spaces(self):
        cache = self._mock_cache({"labels": {"en": "Gram Per Cubic Centimetre"}})
        assert resolve_unit("Q13147228", cache) == "gram_per_cubic_centimetre"

    def test_returns_none_when_not_found(self):
        cache = self._mock_cache(None)
        assert resolve_unit("Q999", cache) is None

    def test_returns_none_when_no_en_label(self):
        cache = self._mock_cache({"labels": {"fr": "kilogramme"}})
        assert resolve_unit("Q11570", cache) is None


class TestRadiusKmFromClaims:
    """radius_km_from_claims"""

    def _mock_units(self, metres: float | None) -> MagicMock:
        units = MagicMock()
        units.convert_to_base.return_value = metres
        return units

    def test_converts_to_km(self):
        claims = {"P2120": [_stmt(_qty_snak("+6371", "Q828224"))]}
        units = self._mock_units(6_371_000.0)
        result = radius_km_from_claims(claims, units, "Q2")
        assert result == pytest.approx(6371.0)
        units.convert_to_base.assert_called_once_with(
            6371.0, "Q828224", expected_type="length"
        )

    def test_returns_none_when_no_claim(self):
        units = self._mock_units(None)
        assert radius_km_from_claims({}, units, "Q2") is None

    def test_returns_none_when_unit_unknown(self):
        claims = {"P2120": [_stmt(_qty_snak("+100", "Q999"))]}
        units = self._mock_units(None)
        assert radius_km_from_claims(claims, units, "Q2") is None
