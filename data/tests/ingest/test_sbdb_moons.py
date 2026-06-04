"""Unit tests for SBDB asteroid-moon ingest helpers."""

from space_map_data.constants.providers import ID_TYPES, make_object_id
from space_map_data.download.providers.spice.bodies.pck_extract import _canonical_naif
from space_map_data.ingest.providers.objects.sbdb_moons import (
    SBDBMoonsIngestor,
    _MAX_SAT_INDEX,
)
from space_map_data.models.object import ObjectType, OrbitalSource


class TestSyntheticSpkid:
    """The synthetic SPK-ID formula for asteroid moons:
    ``synth_spkid = (sat_index + 1) * 100_000_000 + parent_spkid``.

    Mirrors the SPICE NAIF convention for binary asteroid satellites
    (``BODY1<spkid>``, ``BODY2<spkid>``, ...) so catalogued binaries get
    JPL-compatible IDs by construction.
    """

    def test_dimorphos_matches_jpl_naif(self):
        # Didymos = SPK 20065803; Dimorphos is its first satellite.
        # JPL catalogues Dimorphos as NAIF 120065803.
        parent_spkid = 20_065_803
        sat_index = 0
        synth = (sat_index + 1) * 100_000_000 + parent_spkid
        assert synth == 120_065_803

    def test_dactyl_matches_jpl_naif(self):
        # Ida = SPK 20000243; Dactyl is its first satellite, JPL NAIF 120000243.
        parent_spkid = 20_000_243
        synth = (0 + 1) * 100_000_000 + parent_spkid
        assert synth == 120_000_243

    def test_second_moon_prefix(self):
        # Hypothetical: sat_index 1 → leading digit 2.
        synth = (1 + 1) * 100_000_000 + 20_000_087  # Sylvia
        assert synth == 220_000_087

    def test_id_string_format(self):
        # The full Object.id string for asteroid moons.
        assert make_object_id(ID_TYPES.SPKID, 120_065_803) == "spkid-120065803"

    def test_max_sat_index_keeps_prefix_below_nine(self):
        # Prefix 9 is reserved for the SPICE binary-primary slot — the
        # cap must guarantee we never land in 920xxxxxx territory.
        synth = (_MAX_SAT_INDEX + 1) * 100_000_000 + 20_000_001
        assert synth < 900_000_000


class TestCanonicalNaifSatelliteRange:
    """``_canonical_naif`` must pass binary-satellite NAIF IDs through
    unchanged — SBDB-moon Object rows carry ``naif_id == spkid`` in this
    range, so PCK rows keyed on the raw 1xxxxxxxx value join correctly.
    """

    def test_dimorphos_passes_through(self):
        assert _canonical_naif(120_065_803) == 120_065_803

    def test_menoetius_passes_through(self):
        # Lucy / Patroclus binary secondary.
        assert _canonical_naif(120_000_617) == 120_000_617

    def test_binary_primary_still_normalizes(self):
        # 920000617 (Patroclus mission PCK) → 2000617 (NAIF canonical).
        assert _canonical_naif(920_000_617) == 2_000_617


class TestBuildNewObjectRow:
    """``_build_new_object_row`` sets both ``spkid`` and ``naif_id`` to the
    synthetic value so spkid-based queries and PCK (naif-keyed) lookups
    both find the row.
    """

    def _row(self, sat: dict | None = None, sat_row: dict | None = None) -> dict:
        # The method doesn't touch self — instantiate without __init__ to
        # avoid spinning up a DB session.
        ingestor = SBDBMoonsIngestor.__new__(SBDBMoonsIngestor)
        return ingestor._build_new_object_row(
            sat_id="spkid-120065803",
            synth_spkid=120_065_803,
            sat=sat or {"iau_name": "Dimorphos"},
            tree_parent_object_id="spkid-20065803",
            sat_row=sat_row or {},
        )

    def test_spkid_and_naif_id_are_both_set(self):
        row = self._row()
        assert row["spkid"] == 120_065_803
        assert row["naif_id"] == 120_065_803

    def test_parent_id_passes_through(self):
        row = self._row()
        assert row["parent_id"] == "spkid-20065803"

    def test_object_type_is_moon(self):
        row = self._row()
        assert row["object_type"] == ObjectType.moon

    def test_orbital_source_is_sbdb_moon(self):
        row = self._row()
        assert row["orbital_source"] == OrbitalSource.sbdb_moon.value

    def test_has_position_false_without_full_keplerian(self):
        row = self._row(sat_row={"a_km": 1.0})  # missing most required cols
        assert row["has_position"] is False

    def test_has_position_true_with_full_keplerian(self):
        kepler = {
            "epoch_jd": 2460000.0,
            "a_km": 1.0,
            "e": 0.0,
            "i": 0.0,
            "om": 0.0,
            "w": 0.0,
            "ma": 0.0,
            "n": 1.0,
        }
        row = self._row(sat_row=kepler)
        assert row["has_position"] is True

    def test_name_prefers_iau_name(self):
        row = self._row(sat={"iau_name": "Dimorphos", "fullname": "(65803) Didymos I"})
        assert row["name"] == "Dimorphos"

    def test_name_falls_back_to_fullname(self):
        row = self._row(sat={"fullname": "(65803) Didymos I"})
        assert row["name"] == "(65803) Didymos I"
