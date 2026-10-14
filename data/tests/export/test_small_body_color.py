"""Tests for the resolution of surface colours."""

import re

import pytest

from space_map_data.constants.geometric_albedos import GEOMETRIC_ALBEDOS
from space_map_data.export import small_body_color as sbc
from space_map_data.export.small_body_color import (
    SurfaceColor,
    _encode,
    albedo_beyond_hex,
    _taxon_key,
    resolve_major_body_color,
    resolve_small_body_color,
)

HEX = re.compile(r"^#[0-9a-f]{6}$")
NEUTRAL = [1.0, 1.0, 1.0]


def _linear(hexcol: str) -> list[float]:
    out = []
    for i in (1, 3, 5):
        s = int(hexcol[i : i + 2], 16) / 255
        out.append(s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4)
    return out


def _luminance(hexcol: str | None) -> float:
    assert hexcol is not None
    r, g, b = _linear(hexcol)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _table(**by_naif: dict) -> dict:
    return {
        "neutral_linear": NEUTRAL,
        "by_taxon": {"C": NEUTRAL},
        "by_spkid": {"spectrum": {}, "photometry": {}},
        "by_naif": {"spectrum": by_naif},
    }


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


class TestEncode:
    """The luminance of the colour is the albedo, while a hex can hold it."""

    @pytest.mark.parametrize("albedo", [0.05, 0.12, 0.43, 0.7])
    def test_luminance_is_the_albedo(self, albedo: float) -> None:
        hexcol = _encode(sbc._table()["by_taxon"]["S"], albedo)
        assert _luminance(hexcol) == pytest.approx(albedo, rel=0.03)

    def test_too_bright_keeps_the_hue(self) -> None:
        chroma = [1.2, 0.95, 0.9]
        r, g, b = _linear(_encode(chroma, 1.375))
        assert r == pytest.approx(1)
        assert g / r == pytest.approx(0.95 / 1.2, rel=0.01)
        assert b / r == pytest.approx(0.9 / 1.2, rel=0.01)


class TestNeutralHue:
    """A flat reflectance spectrum is grey: TCT renders sunlight white."""

    def test_flat_spectrum_has_equal_channels(self) -> None:
        r, g, b = sbc._table()["neutral_linear"]
        assert r == pytest.approx(g, abs=1e-5) and g == pytest.approx(b, abs=1e-5)

    def test_neutral_colour_is_grey(self) -> None:
        r, g, b = re.findall("..", _encode(sbc._table()["neutral_linear"], 0.3)[1:])
        assert r == g == b


class TestAlbedoBeyondHex:
    """A small body writes its albedo only where the hex cannot hold it."""

    def test_held_albedo_is_none(self) -> None:
        surface = SurfaceColor(_encode(NEUTRAL, 0.42), "albedo", 0.42)
        assert albedo_beyond_hex(surface) is None

    def test_clipped_albedo_is_written(self) -> None:
        surface = SurfaceColor(_encode([1.2, 0.95, 0.9], 0.96), "spectrum", 0.96)
        assert albedo_beyond_hex(surface) == 0.96

    def test_eris_draws_at_its_albedo(self) -> None:
        # Through the hex, or through the field where the hex cannot hold it.
        surface = resolve_small_body_color("spkid-20136199", "20136199", None, None)
        drawn = albedo_beyond_hex(surface) or _luminance(surface.color)
        assert drawn == pytest.approx(surface.geometric_albedo, rel=0.02)

    def test_rounding_of_a_dark_hex_is_not_clipping(self) -> None:
        surface = SurfaceColor(_encode(NEUTRAL, 0.014), "albedo", 0.014)
        assert albedo_beyond_hex(surface) is None

    def test_no_albedo_is_none(self) -> None:
        assert albedo_beyond_hex(SurfaceColor("#808080", "taxonomy", None)) is None


class TestResolveColor:
    """Hue: spectrum/photometry > taxonomy > neutral. Brightness: SBDB albedo,
    else the albedo of the TCT entry, else the default."""

    def test_sbdb_albedo_sets_the_brightness(self) -> None:
        surface = resolve_small_body_color("spkid-20000004", "20000004", "V", 0.42)
        assert surface.color is not None and HEX.match(surface.color)
        assert surface.method == "spectrum"
        assert surface.geometric_albedo == 0.42
        assert _luminance(surface.color) == pytest.approx(0.42, rel=0.03)

    def test_published_albedo_wins(self) -> None:
        # Pluto has an SBDB row with no albedo, and a TCT entry far too bright.
        surface = resolve_small_body_color("naif-999", "20134340", None, None)
        assert surface.geometric_albedo == GEOMETRIC_ALBEDOS["naif-999"].value

    def test_tct_albedo_without_sbdb(self) -> None:
        tct = sbc._table()["by_spkid"]["spectrum"]["20000004"]["albedo"]
        surface = resolve_small_body_color("spkid-20000004", "20000004", None, None)
        assert surface.method == "spectrum"
        assert surface.geometric_albedo == tct
        assert _luminance(surface.color) == pytest.approx(tct, rel=0.03)

    def test_hue_without_albedo_takes_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        table = _table()
        table["by_spkid"]["photometry"] = {"7": {"chroma": NEUTRAL}}
        monkeypatch.setattr(sbc, "_table", lambda: table)
        surface = resolve_small_body_color("spkid-7", "7", None, None)
        assert surface.method == "photometry"
        assert surface.geometric_albedo is None
        assert _luminance(surface.color) == pytest.approx(sbc._DEFAULT_ALBEDO, rel=0.03)

    def test_class_brightness_tracks_albedo(self) -> None:
        dark = resolve_small_body_color("spkid-0", "0", "C", 0.04)
        bright = resolve_small_body_color("spkid-0", "0", "C", 0.30)
        assert dark.method == bright.method == "taxonomy"
        assert _luminance(bright.color) > _luminance(dark.color)

    def test_featureless_x_is_near_neutral(self) -> None:
        # X-complex carries no hue, so its channels stay close together.
        hexcol = resolve_small_body_color("spkid-0", "0", "X", 0.1).color
        assert hexcol is not None
        r, g, b = (int(x, 16) for x in re.findall("..", hexcol[1:]))
        assert max(r, g, b) - min(r, g, b) < 20

    def test_class_without_albedo_uses_default(self) -> None:
        surface = resolve_small_body_color("spkid-0", "0", "S", None)
        assert surface.method == "taxonomy" and surface.geometric_albedo is None
        assert _luminance(surface.color) == pytest.approx(sbc._DEFAULT_ALBEDO, rel=0.03)

    def test_albedo_grey_without_spec(self) -> None:
        surface = resolve_small_body_color("spkid-0", "0", None, 0.1)
        assert surface.color is not None and HEX.match(surface.color)
        assert surface.method == "albedo"

    def test_nothing_known_is_none(self) -> None:
        assert resolve_small_body_color("spkid-0", "0", None, None) == (
            None,
            None,
            None,
        )


class TestResolveMajorBodyColor:
    """Moons: hue from TCT, brightness from a published albedo, else Horizons,
    else the TCT entry. No albedo means no colour. Planets: the albedo alone."""

    def test_published_albedo_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            sbc, "_table", lambda: _table(**{"602": {"chroma": NEUTRAL, "albedo": 1}})
        )
        monkeypatch.setattr(sbc, "_moon_albedos", lambda: {"602": 0.5})
        surface = resolve_major_body_color(602)
        assert surface.method == "spectrum"
        assert surface.geometric_albedo == GEOMETRIC_ALBEDOS["naif-602"].value

    def test_horizons_before_tct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            sbc, "_table", lambda: _table(**{"607": {"chroma": NEUTRAL, "albedo": 0.4}})
        )
        monkeypatch.setattr(sbc, "_moon_albedos", lambda: {"607": 0.2})
        surface = resolve_major_body_color(607)
        assert surface.geometric_albedo == 0.2
        assert _luminance(surface.color) == pytest.approx(0.2, rel=0.03)

    def test_tct_albedo_last(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            sbc, "_table", lambda: _table(**{"607": {"chroma": NEUTRAL, "albedo": 0.4}})
        )
        monkeypatch.setattr(sbc, "_moon_albedos", lambda: {})
        assert resolve_major_body_color(607).geometric_albedo == 0.4

    def test_neutral_grey_when_no_spectrum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sbc, "_table", lambda: _table())
        monkeypatch.setattr(sbc, "_moon_albedos", lambda: {"609": 0.081})
        surface = resolve_major_body_color(609)
        assert surface.method == "albedo"
        assert _luminance(surface.color) == pytest.approx(0.081, rel=0.03)

    def test_planet_has_its_albedo_and_no_colour(self) -> None:
        # The map of a planet keeps its own hue, so the export gives no colour.
        surface = resolve_major_body_color(499)
        assert surface.color is None and surface.method is None
        assert surface.geometric_albedo == GEOMETRIC_ALBEDOS["naif-499"].value

    def test_hue_without_albedo_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            sbc, "_table", lambda: _table(**{"518": {"chroma": NEUTRAL}})
        )
        monkeypatch.setattr(sbc, "_moon_albedos", lambda: {})
        assert resolve_major_body_color(518) == (None, None, None)

    def test_none_naif_is_none(self) -> None:
        assert resolve_major_body_color(None) == (None, None, None)


class TestGeometricAlbedos:
    """The published table holds whole-body values with a source each."""

    def test_values_and_references(self) -> None:
        for object_id, entry in GEOMETRIC_ALBEDOS.items():
            assert object_id.startswith("naif-")
            assert 0.01 < entry.value < 2
            assert entry.reference.title and entry.reference.url.startswith("https://")


@pytest.fixture(autouse=True)
def _reset_stats() -> None:
    sbc._stats.clear()
