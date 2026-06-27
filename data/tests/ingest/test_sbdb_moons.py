"""Unit tests for SBDB asteroid-moon ingest helpers."""

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from space_map_data.constants.providers import ID_TYPES, make_object_id
from space_map_data.download.providers.spice.bodies.pck_extract import _canonical_naif
from space_map_data.ingest.providers.objects.sbdb_moons import (
    SBDBMoonsIngestor,
    _MAX_SAT_INDEX,
    _synth_satellite_designation,
)
from space_map_data.models.object import Object, ObjectType, OrbitalSource
from space_map_data.models.object.base import Base


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

    def _row(
        self,
        sat: dict | None = None,
        sat_row: dict | None = None,
        parent_designation: str | None = None,
    ) -> dict:
        # The method doesn't touch self — instantiate without __init__ to
        # avoid spinning up a DB session.
        ingestor = SBDBMoonsIngestor.__new__(SBDBMoonsIngestor)
        return ingestor._build_new_object_row(
            sat_id="spkid-120065803",
            synth_spkid=120_065_803,
            sat=sat or {"iau_name": "Dimorphos"},
            tree_parent_object_id="spkid-20065803",
            parent_designation=parent_designation,
            sat_row=sat_row or {"sat_index": 0},
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
        row = self._row(
            sat_row={"sat_index": 0, "a_km": 1.0}
        )  # missing most required cols
        assert row["has_position"] is False

    def test_has_position_true_with_full_keplerian(self):
        kepler = {
            "sat_index": 0,
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

    def test_nameless_moon_synthesizes_provisional_designation(self):
        # No iau_name/fullname/prov_des — reconstruct S/<year> (<parent>) <n>
        # rather than falling through to the raw object id.
        row = self._row(
            sat={"year": 2008},
            sat_row={"sat_index": 1, "year": 2008},
            parent_designation="153591",
        )
        assert row["name"] == "S/2008 (153591) 2"
        assert row["provisional_designation"] == "S/2008 (153591) 2"

    def test_real_prov_des_wins_over_synthesis(self):
        row = self._row(
            sat={"prov_des": "S/2004 (45) 1", "year": 2004},
            sat_row={"sat_index": 0, "year": 2004},
            parent_designation="45",
        )
        assert row["name"] == "S/2004 (45) 1"
        assert row["provisional_designation"] == "S/2004 (45) 1"


class TestSynthSatelliteDesignation:
    """``_synth_satellite_designation`` rebuilds the IAU provisional
    designation for moons SBDB ships without any name."""

    def test_numbered_parent_uses_number_token(self):
        assert _synth_satellite_designation("153591", 2008, 0) == "S/2008 (153591) 1"

    def test_unnumbered_parent_uses_provisional_token(self):
        assert (
            _synth_satellite_designation("1998 WW31", 2000, 0) == "S/2000 (1998 WW31) 1"
        )

    def test_missing_token_returns_none(self):
        assert _synth_satellite_designation(None, 2008, 0) is None

    def test_missing_year_returns_none(self):
        assert _synth_satellite_designation("153591", None, 0) is None


@pytest.fixture
def session(monkeypatch) -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sess = Session(engine)
    monkeypatch.setattr("space_map_data.utils.db._session", sess)
    yield sess


def _write_payload(moons_dir, filename, des, spkid, sat_name=None):
    moons_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "object": {"des": des, "spkid": spkid},
        "sat": [{"iau_name": sat_name} if sat_name else {"year": 2000}],
    }
    (moons_dir / filename).write_text(json.dumps(payload))


class TestParentResolution:
    """The ingest must resolve a parent by its permanent designation when the
    SPK-ID the satellite payload was keyed under has drifted out of the objects
    table, and must not ingest the same body twice from aliased SPK-IDs.
    """

    def _parent(self, session):
        # Objects table holds 1998 WV24 under its older SPK-ID; the payloads
        # below arrive keyed under the drifted 50-form.
        session.add(
            Object(
                id="spkid-3024247",
                name="1998 WV24",
                provisional_designation="1998 WV24",
                object_type=ObjectType.asteroid_tno,
                orbital_source=OrbitalSource.sbdb,
                spkid=3_024_247,
                parent_id="naif-10",
            )
        )
        session.commit()

    def test_resolves_parent_by_designation_after_spkid_drift(self, session, tmp_path):
        self._parent(session)
        moons = tmp_path / "sources" / "position" / "sbdb" / "moons"
        _write_payload(moons, "50024270.json", "1998 WV24", 50_024_270)

        ingestor = SBDBMoonsIngestor(tmp_path)
        ingestor.run()

        assert ingestor.designation_fallback_count == 1
        moon = session.execute(
            select(Object).where(Object.orbital_source == OrbitalSource.sbdb_moon)
        ).scalar_one()
        assert moon.parent_id == "spkid-3024247"

    def test_aliased_twin_payloads_ingest_one_body(self, session, tmp_path):
        self._parent(session)
        moons = tmp_path / "sources" / "position" / "sbdb" / "moons"
        # Same body, two payloads: one keyed by the in-table SPK-ID, one by the
        # drifted alias. Only one moon must result.
        _write_payload(moons, "3024247.json", "1998 WV24", 50_024_270)
        _write_payload(moons, "50024270.json", "1998 WV24", 50_024_270)

        ingestor = SBDBMoonsIngestor(tmp_path)
        ingestor.run()

        assert ingestor.duplicate_payloads == 1
        moons_count = session.execute(
            select(Object).where(Object.orbital_source == OrbitalSource.sbdb_moon)
        ).all()
        assert len(moons_count) == 1

    def test_unknown_parent_still_skipped(self, session, tmp_path):
        self._parent(session)
        moons = tmp_path / "sources" / "position" / "sbdb" / "moons"
        _write_payload(moons, "50999999.json", "2099 ZZ99", 50_999_999)

        ingestor = SBDBMoonsIngestor(tmp_path)
        ingestor.run()

        assert ingestor.no_parent_files == 1
        assert ingestor.new_objects == 0
