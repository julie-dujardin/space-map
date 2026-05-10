"""Unit tests for SBDB ingest parsing functions."""

import pytest

from space_map_data.ingest.providers.objects.sbdb import (
    SBDB_CLASS_MAP,
    _display_name,
    _object_type,
    _provisional_designation,
    _sbdb_dict,
    _SBDB_COLUMNS,
    _G_KM3_PER_KG_S2,
)
from space_map_data.models.object import ObjectType
from space_map_data.utils.naif import naif_id_from_spk


def _make_row(**overrides) -> dict[str, str]:
    """Build a minimal SBDB CSV row dict with sensible defaults."""
    row = {col: "" for col in [*_SBDB_COLUMNS, "class"]}
    row.update(
        spkid="20000001",
        full_name="     1 Ceres (A801 AA)",
        pdes="1",
        name="Ceres",
        prefix="",
    )
    row["class"] = "MBA"
    row.update(overrides)
    return row


class TestObjectType:
    """Tests for mapping SBDB rows to ObjectType."""

    def test_dwarf_planet_by_name(self):
        row = _make_row(name="Ceres")
        assert _object_type(row) == ObjectType.dwarf_planet

    def test_dwarf_planet_case_insensitive(self):
        row = _make_row(name="pluto")
        assert _object_type(row) == ObjectType.dwarf_planet

    def test_main_belt_asteroid(self):
        row = _make_row(name="Juno")
        row["class"] = "MBA"
        assert _object_type(row) == ObjectType.asteroid_main_belt

    def test_near_earth_asteroid(self):
        row = _make_row(name="")
        row["class"] = "APO"
        assert _object_type(row) == ObjectType.asteroid_inner

    def test_jupiter_trojan(self):
        row = _make_row(name="")
        row["class"] = "TJN"
        assert _object_type(row) == ObjectType.asteroid_trojan

    def test_comet_by_class(self):
        row = _make_row(name="", prefix="")
        row["class"] = "JFc"
        assert _object_type(row) == ObjectType.comet

    def test_comet_prefix_overrides_asteroid_class(self):
        """An object with a comet prefix but asteroid orbit class is a comet."""
        row = _make_row(name="", prefix="P")
        row["class"] = "MBA"
        assert _object_type(row) == ObjectType.comet

    def test_unknown_class_no_prefix_is_asteroid(self):
        row = _make_row(name="", prefix="")
        row["class"] = "UNKNOWN"
        assert _object_type(row) == ObjectType.asteroid

    def test_unknown_class_with_prefix_is_comet(self):
        row = _make_row(name="", prefix="C")
        row["class"] = "UNKNOWN"
        assert _object_type(row) == ObjectType.comet

    def test_all_sbdb_classes_are_mapped(self):
        """Every entry in SBDB_CLASS_MAP maps to a valid ObjectType."""
        for cls, obj_type in SBDB_CLASS_MAP.items():
            assert isinstance(obj_type, ObjectType), f"{cls} maps to non-ObjectType"


class TestComputeNaifId:
    """Tests for NAIF ID computation from SBDB SPK ID + type."""

    def test_pluto_special_case(self):
        assert naif_id_from_spk(20134340, ObjectType.dwarf_planet) == 999

    def test_numbered_asteroid(self):
        """SPK IDs 20_000_000–20_999_999 map back to 2M range."""
        assert naif_id_from_spk(20000001, ObjectType.asteroid_main_belt) == 2000001

    def test_comet_spk_equals_naif(self):
        assert naif_id_from_spk(1000012, ObjectType.comet) == 1000012

    def test_unmappable_asteroid_returns_none(self):
        """Unnumbered asteroids in the 3M+ range have no Horizons counterpart."""
        assert naif_id_from_spk(3000001, ObjectType.asteroid) is None


class TestDisplayName:
    def test_comet_uses_full_name(self):
        row = _make_row(full_name="29P/Schwassmann-Wachmann 1")
        assert (
            _display_name(row, ObjectType.comet, None) == "29P/Schwassmann-Wachmann 1"
        )

    def test_named_asteroid(self):
        row = _make_row(pdes="3173", name="McNaught")
        assert _display_name(row, ObjectType.asteroid, None) == "3173 McNaught"

    def test_unnamed_asteroid_uses_provisional(self):
        row = _make_row(pdes="", name="")
        assert _display_name(row, ObjectType.asteroid, "1996 XG32") == "1996 XG32"

    def test_unnamed_asteroid_no_provisional(self):
        row = _make_row(pdes="", name="")
        assert _display_name(row, ObjectType.asteroid, None) is None


class TestProvisionalDesignation:
    def test_extracts_from_parentheses(self):
        assert _provisional_designation("     1 Ceres (A801 AA)") == "A801 AA"

    def test_none_when_no_parens(self):
        assert _provisional_designation("29P/Schwassmann-Wachmann 1") is None

    def test_none_input(self):
        assert _provisional_designation(None) is None

    def test_empty_string(self):
        assert _provisional_designation("") is None


class TestSbdbDict:
    """Tests for the typed dict extraction from raw CSV rows."""

    def test_float_columns(self):
        row = _make_row(e="0.07957", a="2.7656")
        d = _sbdb_dict(row)
        assert d["e"] == pytest.approx(0.07957)
        assert d["a"] == pytest.approx(2.7656)

    def test_int_columns(self):
        row = _make_row(sats="0", data_arc="9520")
        d = _sbdb_dict(row)
        assert d["sats"] == 0
        assert d["data_arc"] == 9520

    def test_bool_columns(self):
        row = _make_row(neo="N", pha="Y")
        d = _sbdb_dict(row)
        assert d["neo"] is False
        assert d["pha"] is True

    def test_partial_date_columns(self):
        row = _make_row(first_obs="1995-01-05", last_obs="2021-??-??")
        d = _sbdb_dict(row)
        assert d["first_obs"] == "1995-01-05"
        assert d["last_obs"] == "2021"

    def test_mass_from_gm(self):
        row = _make_row(GM="62.6284")
        d = _sbdb_dict(row)
        assert d["GM"] == pytest.approx(62.6284)
        expected_mass = 62.6284 / _G_KM3_PER_KG_S2
        assert d["mass_kg"] == pytest.approx(expected_mass)

    def test_no_mass_when_gm_empty(self):
        row = _make_row(GM="")
        d = _sbdb_dict(row)
        assert d["GM"] is None
        assert "mass_kg" not in d

    def test_class_stored_as_class_(self):
        row = _make_row()
        row["class"] = "MBA"
        d = _sbdb_dict(row)
        assert d["class_"] == "MBA"

    def test_string_columns(self):
        row = _make_row(producer="Davide Farnocchia", equinox="J2000")
        d = _sbdb_dict(row)
        assert d["producer"] == "Davide Farnocchia"
        assert d["equinox"] == "J2000"

    def test_empty_strings_become_none(self):
        row = _make_row(producer="", extent="")
        d = _sbdb_dict(row)
        assert d["producer"] is None
        assert d["extent"] is None
