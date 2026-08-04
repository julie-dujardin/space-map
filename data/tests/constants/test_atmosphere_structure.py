"""Atmosphere vertical structure: table invariants, and a cross-check of the
published layer boundaries against the downloaded PSG reference profiles."""

import math

import pytest

from space_map_data.constants.atmosphere.facts import ATMOSPHERE_FACTS
from space_map_data.constants.atmosphere.references import ATMOSPHERE_FACT_SOURCES
from space_map_data.constants.atmosphere.structure import (
    ATMOSPHERE_STRUCTURE,
    DATUMS,
    LAYER_ROLES,
    NOTES,
    BodyStructure,
)
from space_map_data.download.providers.psg import BODIES as PSG_BODIES
from space_map_data.download.providers.psg import read_profile

BODY_IDS = sorted(ATMOSPHERE_STRUCTURE)

_ONE_BAR_PA = 1.0e5


def _source_keys(body: BodyStructure) -> set[str]:
    keys = {body.homopause_source} if body.homopause_source else set()
    if body.scale_height_source:
        keys.add(body.scale_height_source)
    if body.datum_temperature_source:
        keys.add(body.datum_temperature_source)
    for layer in body.layers:
        keys.add(layer.source)
        if layer.pressure_source:
            keys.add(layer.pressure_source)
        if layer.altitude_source:
            keys.add(layer.altitude_source)
        keys |= {s.source for s in layer.composition}
    return keys


class TestTable:
    """Per-body layer stacks."""

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_vocabularies_are_closed(self, object_id: str):
        body = ATMOSPHERE_STRUCTURE[object_id]
        assert body.datum in DATUMS
        assert body.note is None or body.note in NOTES
        for layer in body.layers:
            assert layer.role in LAYER_ROLES
            assert layer.note is None or layer.note in NOTES

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_every_number_is_cited(self, object_id: str):
        for key in _source_keys(ATMOSPHERE_STRUCTURE[object_id]):
            assert key in ATMOSPHERE_FACT_SOURCES, f"{object_id}: no such source {key}"

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_layers_stack_outwards(self, object_id: str):
        """Each layer is described by its top and the next one starts there, so
        an out-of-order altitude or a pressure that rises with height would
        draw a cross-section inside out."""
        body = ATMOSPHERE_STRUCTURE[object_id]
        altitudes = [layer.top_km for layer in body.layers if layer.top_km is not None]
        assert altitudes == sorted(altitudes)
        pressures = [
            layer.top_pressure_pa
            for layer in body.layers
            if layer.top_pressure_pa is not None
        ]
        assert pressures == sorted(pressures, reverse=True)

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_published_widths_bracket_the_shipped_value(self, object_id: str):
        """The point value is what gets drawn and the range is the honest
        spread around it, so a range that misses it would draw a boundary the
        source never places there."""
        for layer in ATMOSPHERE_STRUCTURE[object_id].layers:
            for value, span in (
                (layer.top_km, layer.top_km_range),
                (layer.top_temperature_k, layer.top_temperature_range_k),
            ):
                if span is None:
                    continue
                low, high = span
                assert low < high
                assert value is not None
                assert low <= value <= high

    def test_no_source_is_credited_for_nothing(self):
        """The registry feeds credits.json, so a key nothing cites ships a work
        into the credits page that contributed no number to the site."""
        used: set[str] = set()
        for facts in ATMOSPHERE_FACTS.values():
            used |= {s.source for s in facts.composition}
            if facts.pressure is not None:
                used.add(facts.pressure.source)
            if facts.type_source is not None:
                used.add(facts.type_source)
        for body in ATMOSPHERE_STRUCTURE.values():
            used |= _source_keys(body)
        assert sorted(set(ATMOSPHERE_FACT_SOURCES) - used) == []

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_the_homopause_is_placed_on_one_axis_or_the_other(self, object_id: str):
        """Either coordinate answers, but a cited homopause with no value and a
        value with no citation are both half a fact."""
        body = ATMOSPHERE_STRUCTURE[object_id]
        placed = body.homopause_km is not None or body.homopause_pressure_pa is not None
        assert placed == (body.homopause_source is not None)

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_only_a_surfaceless_body_states_its_datum_temperature(self, object_id: str):
        """The base of the lowest layer is the body's surface reading wherever
        it has a surface, and the export takes it from there. Restating it here
        would be a second copy of a measured number, free to drift from the one
        the temperature scale draws."""
        body = ATMOSPHERE_STRUCTURE[object_id]
        assert (body.datum_temperature_k is not None) == (body.datum == "one_bar")
        assert (body.datum_temperature_source is not None) == (
            body.datum_temperature_k is not None
        )

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_the_body_has_conditions_to_go_with_its_layers(self, object_id: str):
        """A cross-section with no pressure or composition beside it is half a
        panel; `facts.py` is where the other half lives."""
        assert object_id in ATMOSPHERE_FACTS

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_layer_composition_uses_the_bodys_unit(self, object_id: str):
        """Per-layer species are shares in the body's own composition unit, so
        a volume fraction can never exceed 1."""
        if ATMOSPHERE_FACTS[object_id].composition_unit != "volume_fraction":
            return
        for layer in ATMOSPHERE_STRUCTURE[object_id].layers:
            assert all(0.0 < s.value <= 1.0 for s in layer.composition)


# PSG has no template for Pluto, Triton or the Sun, and the check needs a
# temperature turning point to compare against — Venus and Mars have none in
# the troposphere, which is the whole reason Robinson & Catling exclude them.
_TROPOPAUSE_CHECK = ["naif-399", "naif-599", "naif-699", "naif-799", "naif-899"]


class TestAgainstPSGProfiles:
    """Cross-check against the downloaded PSG reference profiles.

    Skipped where the download is absent — these are a check on the curated
    numbers, not a reason to fail a machine that has not pulled the data.
    """

    @pytest.mark.parametrize("object_id", _TROPOPAUSE_CHECK)
    def test_tropopause_sits_at_the_profiles_temperature_minimum(self, object_id: str):
        try:
            levels = read_profile(object_id)
        except FileNotFoundError:
            pytest.skip(f"no PSG profile downloaded for {object_id}")

        tropopause = next(
            layer
            for layer in ATMOSPHERE_STRUCTURE[object_id].layers
            if layer.role == "troposphere"
        )
        coldest = min(levels, key=lambda level: level.temperature_k)
        assert tropopause.top_pressure_pa is not None
        # Within a factor of three, which is the honest width of the claim:
        # PSG's profile is one latitude and season, the tabulated boundary is a
        # global nominal, and on Earth alone those differ by 2.3× (226 hPa at
        # the US-Standard 11 km, 100 hPa at the tropical cold point). What this
        # catches is a boundary in the wrong layer, not a disagreement.
        ratio = coldest.pressure_pa / tropopause.top_pressure_pa
        assert 1 / 3 <= ratio <= 3.0, (
            f"{object_id}: profile is coldest at {coldest.pressure_pa:.4g} Pa, "
            f"table puts the tropopause at {tropopause.top_pressure_pa:.4g} Pa"
        )

    @pytest.mark.parametrize(
        "object_id", ["naif-599", "naif-699", "naif-799", "naif-899"]
    )
    def test_the_1_bar_temperature_matches_the_profile(self, object_id: str):
        """The giants' datum temperature against an independent model of the
        same level. 15% is the honest width: PSG's templates are models rather
        than the Voyager occultations these values come from, and they disagree
        by 10 K on Jupiter."""
        try:
            levels = read_profile(object_id)
        except FileNotFoundError:
            pytest.skip(f"no PSG profile downloaded for {object_id}")

        stated = ATMOSPHERE_STRUCTURE[object_id].datum_temperature_k
        assert stated is not None
        rows = sorted(levels, key=lambda level: level.pressure_pa)
        below = max(
            (level for level in rows if level.pressure_pa <= _ONE_BAR_PA),
            key=lambda level: level.pressure_pa,
        )
        above = min(
            (level for level in rows if level.pressure_pa >= _ONE_BAR_PA),
            key=lambda level: level.pressure_pa,
        )
        # Temperature runs linear in log pressure between two levels, which is
        # what a scale height is.
        span = math.log(above.pressure_pa / below.pressure_pa)
        fraction = math.log(_ONE_BAR_PA / below.pressure_pa) / span if span else 0.0
        modelled = below.temperature_k + fraction * (
            above.temperature_k - below.temperature_k
        )
        assert modelled == pytest.approx(stated, rel=0.15), (
            f"{object_id}: table says {stated} K at 1 bar, profile gives "
            f"{modelled:.1f} K"
        )

    @pytest.mark.parametrize("object_id", sorted(PSG_BODIES.values()))
    def test_profile_spans_the_bodys_reference_level(self, object_id: str):
        """A profile that stops short of the level `facts.py` quotes can say
        nothing about the layer that level sits in. The 10% slack is at the
        bottom, where a surface body's profile ends right at the quoted
        pressure and the two come from separate datasets — MERRA-2 puts
        Earth's sea level at 1.006 bar against NSSDCA's 1.014."""
        try:
            levels = read_profile(object_id)
        except FileNotFoundError:
            pytest.skip(f"no PSG profile downloaded for {object_id}")

        pressure = ATMOSPHERE_FACTS[object_id].pressure
        assert pressure is not None
        assert levels[0].pressure_pa >= pressure.pascals * 0.9
        assert levels[-1].pressure_pa < pressure.pascals
