"""Activity facts: vocabulary and citation invariants across the three tables,
and a cross-check of Earth's volcano counts against the downloaded catalogue."""

import json

import pytest

from space_map_data.constants.activity.magnetism import MAGNETIC_FIELDS
from space_map_data.constants.activity.references import ACTIVITY_SOURCES
from space_map_data.constants.activity.schema import (
    FIELD_KINDS,
    STATUSES,
    TECTONIC_STYLES,
    TIDAL_ROLES,
    VOLCANISM_KINDS,
    BodyActivity,
    MagneticField,
    Measurement,
    TidalHeating,
)
from space_map_data.constants.activity.tidal import TIDAL_HEATING
from space_map_data.constants.activity.volcanism import GEOLOGIC_ACTIVITY
from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.utils.paths import SOURCES_DIR

ACTIVITY_IDS = sorted(GEOLOGIC_ACTIVITY)
TIDAL_IDS = sorted(TIDAL_HEATING)
FIELD_IDS = sorted(MAGNETIC_FIELDS)
ALL_IDS = sorted(set(ACTIVITY_IDS) | set(TIDAL_IDS) | set(FIELD_IDS))


def _measurements(entry: BodyActivity | TidalHeating | MagneticField):
    """Every Measurement anywhere in one body's record, whatever table."""
    parts = (
        (entry.volcanism, entry.tectonics)
        if isinstance(entry, BodyActivity)
        else (entry,)
    )
    for part in parts:
        if part is None:
            continue
        for field in part:
            if isinstance(field, Measurement):
                yield field


def _source_keys() -> set[str]:
    keys: set[str] = set()
    for activity in GEOLOGIC_ACTIVITY.values():
        keys |= set(activity.volcanism.status_sources)
        if activity.tectonics:
            keys |= set(activity.tectonics.sources)
        keys |= {m.source for m in _measurements(activity)}
    for tidal in TIDAL_HEATING.values():
        keys |= set(tidal.role_sources)
        if tidal.resonance_source:
            keys.add(tidal.resonance_source)
        keys |= {m.source for m in _measurements(tidal)}
    for field in MAGNETIC_FIELDS.values():
        keys |= set(field.kind_sources)
        keys |= {m.source for m in _measurements(field)}
    return keys


class TestVocabularies:
    """Every categorical value has to be one the frontend has a string for; an
    unrecognised one renders as a raw key or as nothing at all."""

    @pytest.mark.parametrize("object_id", ACTIVITY_IDS)
    def test_volcanism_terms_are_known(self, object_id: str):
        activity = GEOLOGIC_ACTIVITY[object_id]
        assert activity.volcanism.kind in VOLCANISM_KINDS
        assert activity.volcanism.status in STATUSES
        if activity.tectonics:
            assert activity.tectonics.style in TECTONIC_STYLES
            assert activity.tectonics.status in STATUSES

    @pytest.mark.parametrize("object_id", TIDAL_IDS)
    def test_tidal_roles_are_known(self, object_id: str):
        assert TIDAL_HEATING[object_id].role in TIDAL_ROLES

    @pytest.mark.parametrize("object_id", FIELD_IDS)
    def test_field_kinds_are_known(self, object_id: str):
        assert MAGNETIC_FIELDS[object_id].kind in FIELD_KINDS


class TestCitations:
    """The credits page renders `ACTIVITY_SOURCES`; a `source` string with no
    entry there ships a number with nothing behind it."""

    def test_every_source_is_citable(self):
        assert _source_keys() <= set(ACTIVITY_SOURCES)

    def test_no_reference_is_orphaned(self):
        assert set(ACTIVITY_SOURCES) <= _source_keys()

    @pytest.mark.parametrize("key", sorted(ACTIVITY_SOURCES))
    def test_references_carry_a_panel_note(self, key: str):
        """The object panel's credit line has room for the note and not the
        contribution; an empty one leaves the reader a bare title."""
        assert ACTIVITY_SOURCES[key].note


class TestMeasurements:
    """`Measurement` exists so a bound never reads as a value."""

    @pytest.mark.parametrize(
        "object_id, table",
        [(i, GEOLOGIC_ACTIVITY) for i in ACTIVITY_IDS]
        + [(i, TIDAL_HEATING) for i in TIDAL_IDS]
        + [(i, MAGNETIC_FIELDS) for i in FIELD_IDS],
    )
    def test_ranges_bracket_their_value(self, object_id: str, table: dict):
        for measurement in _measurements(table[object_id]):
            if measurement.range is None:
                continue
            low, high = measurement.range
            assert low <= high
            # An upper limit's value is the limit, free to sit at the edge of
            # its own bracket.
            assert low <= measurement.value <= high


class TestCrossTable:
    """The three tables describe the same bodies and have to agree."""

    @pytest.mark.parametrize("object_id", ALL_IDS)
    def test_a_body_is_spelled_the_way_the_rest_of_the_constants_spell_it(
        self, object_id: str
    ):
        """A mismatched id fails silently: Vesta's NAIF id 2000004 differs from
        its SBDB export id, so `naif-2000004` matched nothing and no other test
        caught it. Widen `interior/bodies.py`'s 23 ids rather than drop this."""
        assert object_id in INTERIOR_FACTS

    @pytest.mark.parametrize("object_id", TIDAL_IDS)
    def test_a_tide_names_a_body_that_raises_it(self, object_id: str):
        """`raised_by` is rendered as a link, so it has to be an object id and
        never the body itself."""
        tidal = TIDAL_HEATING[object_id]
        assert tidal.raised_by.startswith("naif-")
        assert tidal.raised_by != object_id
        assert object_id not in tidal.resonance_with

    @pytest.mark.parametrize("object_id", TIDAL_IDS)
    def test_a_live_tide_names_what_sustains_it(self, object_id: str):
        """Eccentricity tides damp out fast; a body still dissipating without a
        resonance behind it is either a data error or needs a note."""
        tidal = TIDAL_HEATING[object_id]
        if tidal.role not in {"dominant", "significant"}:
            return
        assert tidal.resonance_with or tidal.note

    @pytest.mark.parametrize("object_id", ACTIVITY_IDS)
    def test_a_body_loses_at_least_the_heat_its_tide_makes(self, object_id: str):
        """Tidal input can't exceed radiated heat loss, or the body would be
        cooling faster than it's heated. Equal on Io; a twelfth on Earth."""
        power = GEOLOGIC_ACTIVITY[object_id].volcanism.endogenic_power_w
        tidal = TIDAL_HEATING.get(object_id)
        if power is None or tidal is None or tidal.power_w is None:
            return
        assert tidal.power_w.value <= power.value * 1.01


class TestAgainstTheVolcanoCatalogue:
    """Earth's counts are the one place in this package where the source is a
    database that moves, so they are checked against it rather than trusted."""

    @staticmethod
    def _statistics() -> dict:
        path = SOURCES_DIR / "activity" / "gvp" / "statistics.json"
        if not path.exists():
            pytest.skip("GVP catalogue not downloaded")
        return json.loads(path.read_text())

    @pytest.mark.parametrize(
        "field, key",
        [
            ("known_centres", "holocene_volcanoes"),
            ("eruptions_per_year", "mean_eruptions_active_per_year"),
        ],
    )
    def test_earth_counts_match_the_catalogue(self, field: str, key: str):
        """Rolled up from the downloaded record; drift means the constant is
        stale (update `as_of`) or the roll-up in `gvp.py` changed meaning."""
        stats = self._statistics()
        measurement = getattr(GEOLOGIC_ACTIVITY["naif-399"].volcanism, field)
        assert measurement.value == pytest.approx(stats[key], rel=0.02)

    def test_the_catalogue_still_reproduces_gvps_own_summary(self):
        """Trustworthy only because it reproduces GVP's own published figures —
        self-consistency alone wouldn't catch a wrong derivation."""
        stats = self._statistics()
        assert stats["mean_new_eruptions_per_year"] == pytest.approx(35, rel=0.03)
        assert stats["mean_volcanoes_active_per_year"] == pytest.approx(73, rel=0.03)
        assert stats["confirmed_holocene_eruptions"] == pytest.approx(9910, rel=0.02)


class TestMagnetism:
    """Field entries."""

    @pytest.mark.parametrize("object_id", FIELD_IDS)
    def test_remanence_comes_with_a_date_for_the_dynamo(self, object_id: str):
        """A crustal field is the fossil of a dynamo, and "when did it stop" is
        the only question a reader has about it."""
        field = MAGNETIC_FIELDS[object_id]
        if field.kind != "remanent":
            return
        assert field.dynamo_ended_years is not None
