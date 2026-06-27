"""Tests for small-body surface-colour resolution."""

import re

import pytest

from space_map_data.export import small_body_color as sbc
from space_map_data.export.small_body_color import (
    _taxon_key,
    resolve_moon_color,
    resolve_small_body_color,
)

HEX = re.compile(r"^#[0-9a-f]{6}$")


class TestTaxonKey:
    """SBDB spec_B/spec_T codes map onto the Bus-DeMeo by_taxon keys."""

    def test_exact_bus_demeo(self) -> None:
        assert _taxon_key("S") == "S"
        assert _taxon_key("Sl") == "Sl"
        assert _taxon_key("Xk") == "Xk"

    def test_strips_uncertainty_marker(self) -> None:
        assert _taxon_key("S:") == "S"
        assert _taxon_key(" C : ") == "C"

    def test_tholen_alias(self) -> None:
        assert _taxon_key("M") == "Xk"
        assert _taxon_key("E") == "Xe"
        assert _taxon_key("G") == "Cgh"
        assert _taxon_key("F") == "B"

    def test_compound_reduces_to_leading_complex(self) -> None:
        assert _taxon_key("CX") == "C"
        assert _taxon_key("XC") == "X"
        assert _taxon_key("PC") == "X"  # P aliases to X

    def test_unknown_is_none(self) -> None:
        assert _taxon_key("") is None
        assert _taxon_key("ZZ") is None


class TestResolveColor:
    """Priority + method: spectrum/photometry > taxonomy > albedo > none."""

    def test_per_body_wins_with_method(self) -> None:
        # Vesta ships a measured TCT spectrum; spec/albedo are ignored.
        c, method = resolve_small_body_color("20000004", "V", 0.42)
        assert c is not None and HEX.match(c)
        assert method == "spectrum"
        assert resolve_small_body_color("20000004", None, None) == (c, "spectrum")

    def test_class_brightness_tracks_albedo(self) -> None:
        (dark, m1) = resolve_small_body_color("0", "C", 0.04)
        (bright, m2) = resolve_small_body_color("0", "C", 0.30)
        assert dark is not None and bright is not None
        assert HEX.match(dark) and HEX.match(bright)
        assert m1 == m2 == "taxonomy"
        assert int(bright[1:3], 16) > int(dark[1:3], 16)

    def test_featureless_x_is_near_neutral(self) -> None:
        # X-complex carries no hue, so its channels stay close together.
        hexcol, _ = resolve_small_body_color("0", "X", 0.1)
        assert hexcol is not None
        r, g, b = (int(x, 16) for x in re.findall("..", hexcol[1:]))
        assert max(r, g, b) - min(r, g, b) < 20

    def test_class_without_albedo_uses_default(self) -> None:
        hexcol, method = resolve_small_body_color("0", "S", None)
        assert hexcol is not None and HEX.match(hexcol) and method == "taxonomy"

    def test_albedo_grey_without_spec(self) -> None:
        hexcol, method = resolve_small_body_color("0", None, 0.1)
        assert hexcol is not None and HEX.match(hexcol) and method == "albedo"

    def test_nothing_known_is_none(self) -> None:
        assert resolve_small_body_color("0", None, None) == (None, None)


class TestResolveMoonColor:
    """Moons resolve by NAIF id: a measured TCT spectrum, else a neutral grey
    scaled by their Horizons geometric albedo. No hue (taxonomy) tier."""

    def test_spectrum_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A measured spectrum beats the albedo tier even when both exist.
        monkeypatch.setattr(
            sbc,
            "_table",
            lambda: {
                "neutral_linear": [1.0, 1.0, 1.0],
                "by_naif": {"spectrum": {"607": "#a1b2c3"}},
            },
        )
        monkeypatch.setattr(sbc, "_moon_albedos", lambda: {"607": 0.2})
        assert resolve_moon_color(607) == ("#a1b2c3", "spectrum")

    def test_albedo_grey_when_no_spectrum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sbc,
            "_table",
            lambda: {"neutral_linear": [1.0, 1.0, 1.0], "by_naif": {"spectrum": {}}},
        )
        monkeypatch.setattr(sbc, "_moon_albedos", lambda: {"609": 0.081})
        hexcol, method = resolve_moon_color(609)
        assert method == "albedo"
        assert hexcol is not None and HEX.match(hexcol)

    def test_albedo_brightness_tracks_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sbc,
            "_table",
            lambda: {"neutral_linear": [1.0, 1.0, 1.0], "by_naif": {"spectrum": {}}},
        )
        monkeypatch.setattr(sbc, "_moon_albedos", lambda: {"1": 0.04, "2": 0.6})
        (dark, _), (bright, _) = resolve_moon_color(1), resolve_moon_color(2)
        assert dark is not None and bright is not None
        assert int(bright[1:3], 16) > int(dark[1:3], 16)

    def test_unmeasured_moon_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sbc, "_table", lambda: {"by_naif": {"spectrum": {}}})
        monkeypatch.setattr(sbc, "_moon_albedos", lambda: {})
        assert resolve_moon_color(699) == (None, None)

    def test_none_naif_is_none(self) -> None:
        assert resolve_moon_color(None) == (None, None)

    def test_missing_by_naif_block_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pre-regeneration JSON has no by_naif key; resolve must not KeyError.
        monkeypatch.setattr(sbc, "_table", lambda: {"by_spkid": {}})
        monkeypatch.setattr(sbc, "_moon_albedos", lambda: {})
        assert resolve_moon_color(607) == (None, None)


@pytest.fixture(autouse=True)
def _reset_stats() -> None:
    sbc._stats.clear()
