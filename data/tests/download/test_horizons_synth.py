"""Unit tests for the Horizons synthetic-SPK download helpers."""

from unittest.mock import MagicMock

import httpx
import numpy as np
import pytest

from space_map_data.download.providers.spice.synth import horizons_api, index, refine


class TestTimeHelpers:
    """Round-trip checks for the JD/ET/ISO conversions."""

    def test_jd_to_iso_at_j2000(self):
        # J2000 epoch is 2000-01-01 12:00 TT, which we round down to date.
        assert horizons_api._jd_to_iso(2451545.0) == "2000-01-01"

    def test_jd_to_iso_at_voyager_launch(self):
        # 1977-AUG-20 15:32 TDB → JD 2443376.148...
        assert horizons_api._jd_to_iso(2443376.148) == "1977-08-20"

    def test_et_jd_round_trip(self):
        for jd in (2451545.0, 2443376.148, 2461110.5, 2415020.5):
            et = (jd - 2451545.0) * 86400.0
            assert horizons_api._et_to_jd(et) == pytest.approx(jd)


class TestCoarseStepFor:
    """Cadence tiering by span length."""

    def test_short_window_uses_1h(self):
        # Apollo S-IVB stages have ~20-day coverage.
        assert refine._coarse_step_for(20) == "1 h"
        assert refine._coarse_step_for(60) == "1 h"

    def test_year_window_uses_1d(self):
        # Tianwen-1 has ~6 months, NISAR ~year.
        assert refine._coarse_step_for(61) == "1 d"
        assert refine._coarse_step_for(180) == "1 d"
        assert refine._coarse_step_for(365) == "1 d"

    def test_long_window_uses_7d(self):
        # Voyager 2 spans 122 years.
        assert refine._coarse_step_for(366) == "7 d"
        assert refine._coarse_step_for(122 * 365) == "7 d"


_SAMPLE_CSV = """\
API VERSION: 1.2
API SOURCE: NASA/JPL Horizons API

[header text]

$$SOE
2460676.500000000, A.D. 2025-Jan-01 00:00:00.0000,  5.734902866007734E+09, -8.913897076915403E+09, -1.781075837096583E+10,  4.218560195726143E+00, -4.071034191379132E+00, -1.411082680475604E+01,
2460677.500000000, A.D. 2025-Jan-02 00:00:00.0000,  5.735267349281271E+09, -8.914248813766993E+09, -1.781197754541512E+10,  4.218552617767505E+00, -4.071022558716548E+00, -1.411080396628405E+01,
$$EOE
"""


class TestParseHorizonsCsv:
    def test_extracts_two_samples(self):
        samples = horizons_api._parse_horizons_csv(_SAMPLE_CSV)
        assert len(samples) == 2

    def test_first_sample_state_matches_csv(self):
        samples = horizons_api._parse_horizons_csv(_SAMPLE_CSV)
        # JD 2460676.5 = 2025-01-01 00:00 TDB. ET = (jd - J2000) * 86400.
        assert samples[0].et == pytest.approx((2460676.5 - 2451545.0) * 86400.0)
        # State vector x, y, z, vx, vy, vz.
        assert samples[0].state[0] == pytest.approx(5.734902866007734e9)
        assert samples[0].state[5] == pytest.approx(-1.411082680475604e1)

    def test_missing_block_returns_empty(self):
        assert horizons_api._parse_horizons_csv("no SOE block here") == []

    def test_malformed_lines_skipped(self):
        text = "$$SOE\nnot-a-csv-row\n2460676.5, foo, 1, 2, 3, 4, 5, 6\n$$EOE\n"
        samples = horizons_api._parse_horizons_csv(text)
        # First row has non-numeric values; second has 8 numeric-looking parts
        # (but parts[1] is "foo" which we don't parse). Only well-formed rows
        # pass; expect 1 sample.
        assert len(samples) == 1


_TWO_CHUNK_CSV = """\
header1
$$SOE
2460676.5, A.D. 2025-Jan-01 00:00:00.0,  1.0,  2.0,  3.0,  0.1,  0.2,  0.3,
2460677.5, A.D. 2025-Jan-02 00:00:00.0,  4.0,  5.0,  6.0,  0.4,  0.5,  0.6,
$$EOE
header2
$$SOE
2460677.5, A.D. 2025-Jan-02 00:00:00.0,  4.0,  5.0,  6.0,  0.4,  0.5,  0.6,
2460678.5, A.D. 2025-Jan-03 00:00:00.0,  7.0,  8.0,  9.0,  0.7,  0.8,  0.9,
$$EOE
"""


class TestParseChunks:
    def test_dedups_adjacent_overlap(self):
        # The 2025-Jan-02 sample appears at the end of chunk 1 and start of
        # chunk 2 (Horizons' inclusive-stop quirk for chunked fetches). The
        # parser should drop the duplicate.
        samples = horizons_api._parse_chunks(_TWO_CHUNK_CSV)
        assert len(samples) == 3
        # Strictly increasing epochs.
        ets = [s.et for s in samples]
        assert ets == sorted(set(ets))


# NAIF ID is right-aligned within a 9-char column [0:9]; the real Horizons
# MB file pads each ID with leading spaces accordingly. Get this wrong (e.g.
# 7 leading spaces before "-32") and `-32` truncates to `-3`.
_SAMPLE_MB = """\
   ID#      Name                               Designation  IAU/aliases/other
  -------  ---------------------------------- -----------  -------------------
      -32  Voyager 2 (spacecraft)
       -3  Mars Orbiter Mission (spacecraft)
      -25  Lunar Prospector (LP) (spacecraft)
  -937001  2017 PDC (simulation)
  -999789  2023 NM (debris)
 -9901492  Luna-25 STAGE (spacecraft)
-54054450  Surveyor-2 Centaur RB
  -999742  LISA Pathfinder Propulsion Module
      399  Earth
"""


class TestParseHorizonsSpacecraft:
    def test_keeps_real_spacecraft(self):
        out = index._parse_horizons_spacecraft(_SAMPLE_MB)
        ids = {n for n, _ in out}
        assert -32 in ids
        assert -3 in ids
        assert -25 in ids

    def test_drops_simulations(self):
        out = index._parse_horizons_spacecraft(_SAMPLE_MB)
        ids = {n for n, _ in out}
        assert -937001 not in ids

    def test_drops_debris(self):
        out = index._parse_horizons_spacecraft(_SAMPLE_MB)
        ids = {n for n, _ in out}
        assert -999789 not in ids

    def test_drops_stages_and_boosters(self):
        out = index._parse_horizons_spacecraft(_SAMPLE_MB)
        ids = {n for n, _ in out}
        assert -9901492 not in ids  # Luna-25 STAGE
        assert -54054450 not in ids  # Centaur RB
        assert -999742 not in ids  # Propulsion Module

    def test_drops_positive_ids(self):
        out = index._parse_horizons_spacecraft(_SAMPLE_MB)
        ids = {n for n, _ in out}
        assert 399 not in ids


_VOYAGER_OBJ = {
    "result": (
        "*******************************************************************************\n"
        " Revised: Aug 19, 2022   Voyager 2 Spacecraft (interplanetary) / (Sun)     -32\n"
        "                        http://www.jpl.nasa.gov/missions/voyager-2/\n"
    ),
    "signature": {"source": "NASA/JPL Horizons API", "version": "1.2"},
}


class TestFetchObjData:
    def test_parses_revised_and_name(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = _VOYAGER_OBJ
        mock_resp.raise_for_status.return_value = None
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_resp

        obj = horizons_api.fetch_obj_data(client, -32)
        assert obj.revised == "Aug 19, 2022"
        assert "Voyager 2" in obj.name

    def test_unknown_revised_falls_back(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": "no header here"}
        mock_resp.raise_for_status.return_value = None
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = mock_resp

        obj = horizons_api.fetch_obj_data(client, -42)
        assert obj.revised == "unknown"
        assert obj.name == "NAIF -42"


class TestIdentifyRefinementWindows:
    # Single-body stub Hill table — value is irrelevant for window-logic tests
    # since the proximity check below uses a body at (0,0,0) or 1e20 km away.
    _STUB_HILL = {199: 1.0e6}

    def _make_samples(self, n: int, day_step: float = 7.0) -> list[horizons_api.Sample]:
        """N samples spaced `day_step` apart starting at ET 0."""
        return [
            horizons_api.Sample(et=i * day_step * 86400.0, state=(0, 0, 0, 0, 0, 0))
            for i in range(n)
        ]

    def test_no_proximity_no_windows(self):
        samples = self._make_samples(20)
        # Stub `get_body_pos` returns a body 10^20 km away — always far.
        far_away = np.array([1e20, 0, 0])
        windows = refine._identify_refinement_windows(
            samples,
            get_body_pos=lambda _b, _t: far_away,
            coverage_start_iso="2000-01-01",
            coverage_end_iso="2010-01-01",
            hill_table=self._STUB_HILL,
        )
        assert windows == []

    def test_proximity_at_one_sample(self):
        samples = self._make_samples(20)

        # Body coincides with spacecraft at sample 10 only.
        def get_body_pos(_b, et):
            if et == samples[10].et:
                return np.array([0.0, 0.0, 0.0])
            return np.array([1e20, 0.0, 0.0])

        windows = refine._identify_refinement_windows(
            samples,
            get_body_pos=get_body_pos,
            coverage_start_iso="2000-01-01",
            coverage_end_iso="2010-01-01",
            hill_table=self._STUB_HILL,
        )
        assert len(windows) == 1

    def test_two_separate_windows(self):
        samples = self._make_samples(30)

        # Body close at samples 5..7 and 20..22.
        def get_body_pos(_b, et):
            for idx in (5, 6, 7, 20, 21, 22):
                if et == samples[idx].et:
                    return np.array([0.0, 0.0, 0.0])
            return np.array([1e20, 0.0, 0.0])

        windows = refine._identify_refinement_windows(
            samples,
            get_body_pos=get_body_pos,
            coverage_start_iso="2000-01-01",
            coverage_end_iso="2010-01-01",
            hill_table=self._STUB_HILL,
        )
        assert len(windows) == 2

    def test_windows_clamped_to_coverage(self):
        # First sample is at coverage start; padding would push the window
        # boundary one week before — should be clamped.
        samples = self._make_samples(5)

        def get_body_pos(_b, et):
            if et == samples[0].et:
                return np.array([0.0, 0.0, 0.0])
            return np.array([1e20, 0.0, 0.0])

        windows = refine._identify_refinement_windows(
            samples,
            get_body_pos=get_body_pos,
            coverage_start_iso="2000-01-01",
            coverage_end_iso="2010-01-01",
            hill_table=self._STUB_HILL,
        )
        # Start must be on or after 2000-01-02 (coverage_start + 1d margin).
        assert windows[0][0] >= "2000-01-02"


class TestComputeMajorBodyHillKm:
    """Cross-check the computed Hill table against published values.

    Reference: NASA fact-sheet Hill radii (in km) — accurate to 1% or so once
    you allow for the J2000 osculating-element snapshot wobbling slightly from
    each body's mean orbit. Re-uses the LSK + de440 furnished by the caller
    via `_furnish_planets`; this test class furnishes them itself.
    """

    @pytest.fixture(autouse=True)
    def _spice(self):
        # Clear the cache so each test recomputes against freshly-furnished kernels.
        refine._HILL_CACHE = None
        paths = refine._furnish_planets()
        yield
        for p in paths:
            import spiceypy

            spiceypy.unload(str(p))
        refine._HILL_CACHE = None

    def test_planet_hill_radii_match_published(self):
        hill = refine.compute_major_body_hill_km()
        # Published Hill radii (Mkm) from standard references. Moon's
        # osculating-element snapshot at J2000 wobbles ~7% off the mean orbit
        # so it gets a looser tolerance than the planets.
        expected_mkm = {
            199: (0.22, 0.05),
            299: (1.01, 0.05),
            399: (1.50, 0.05),
            301: (0.061, 0.10),
            4: (1.08, 0.05),
            5: (53.1, 0.05),
            6: (65.0, 0.05),
            7: (70.0, 0.05),
            8: (116.0, 0.05),
        }
        for body, (want, tol) in expected_mkm.items():
            got_mkm = hill[body] / 1e6
            assert abs(got_mkm - want) / want < tol, (
                f"body {body}: computed {got_mkm:.3f} Mkm vs published {want} Mkm"
            )

    def test_sun_entry_satisfies_alias_condition(self):
        # Sun "Hill" × REFINE_HILL_FACTOR = r_trigger. At that distance the
        # chord swept by a circular orbit in one coarse step should equal
        # _SUN_REFINE_CHORD_TO_R × r_trigger.
        hill = refine.compute_major_body_hill_km()
        gm_sun = refine._gm_table_km3_s2()[10]
        r_trigger = hill[10] * refine.REFINE_HILL_FACTOR
        import math

        v_circ = math.sqrt(gm_sun / r_trigger)
        chord = v_circ * refine._COARSE_STEP_S
        assert chord / r_trigger == pytest.approx(
            refine._SUN_REFINE_CHORD_TO_R, rel=1e-6
        )

    def test_sun_entry_catches_psp_perihelion_region(self):
        # PSP coarse samples around perihelion sit at ~22 Mkm from the Sun
        # (see horizons-synth/-96/coarse_*.csv). The trigger threshold must
        # exceed that distance, but not so much that it triggers on every
        # interplanetary cruise — bound it at ~70 Mkm (otherwise we'd refine
        # every probe inside Mercury's orbit).
        hill = refine.compute_major_body_hill_km()
        trigger_mkm = hill[10] * refine.REFINE_HILL_FACTOR / 1e6
        assert 22 < trigger_mkm < 70, (
            f"Sun trigger {trigger_mkm:.1f} Mkm outside expected 22..70 Mkm range"
        )


class TestQidDedupedSynthNaifs:
    """Cross-mission deduplication of HORIZONS-SYNTH probes by Wikidata QID."""

    @staticmethod
    def _missions_dir_with(tmp_path, names):
        """Create stub mission dirs with empty `_index.json` for each name."""
        missions = tmp_path / "spice" / "kernels" / "missions"
        missions.mkdir(parents=True)
        for n in names:
            (missions / n).mkdir()
            (missions / n / "_index.json").write_text("{}")
        return missions

    def test_dedups_synth_naif_against_spk_backed_agency(self, tmp_path, monkeypatch):
        # INTEGRAL case: ESA SPK at -275, Horizons synth at -198, both Q50021.
        self._missions_dir_with(tmp_path, ["INTEGRAL"])
        monkeypatch.setattr(index, "DOWNLOAD_DIR", tmp_path)
        cache = {
            "INTEGRAL/-275": {
                "mission": "INTEGRAL",
                "naif_id": -275,
                "wikidata_qid": "Q50021",
            },
            "HORIZONS-SYNTH/-198": {
                "mission": "HORIZONS-SYNTH",
                "naif_id": -198,
                "wikidata_qid": "Q50021",
            },
        }
        assert index.qid_deduped_synth_naifs(cache) == {-198}

    def test_ignores_metadata_only_buckets(self, tmp_path, monkeypatch):
        # EVENTS-DB has no `missions/EVENTS-DB/` SPK dir, so it must not act
        # as an agency match — Tianwen-1's only ephemeris is the synth.
        self._missions_dir_with(tmp_path, ["INTEGRAL"])  # arbitrary; not the match
        monkeypatch.setattr(index, "DOWNLOAD_DIR", tmp_path)
        cache = {
            "EVENTS-DB/-90000051": {
                "mission": "EVENTS-DB",
                "naif_id": -90000051,
                "wikidata_qid": "Q49011",
            },
            "HORIZONS-SYNTH/-86": {
                "mission": "HORIZONS-SYNTH",
                "naif_id": -86,
                "wikidata_qid": "Q49011",
            },
        }
        assert index.qid_deduped_synth_naifs(cache) == set()

    def test_no_match_when_qids_differ(self, tmp_path, monkeypatch):
        self._missions_dir_with(tmp_path, ["JUNO"])
        monkeypatch.setattr(index, "DOWNLOAD_DIR", tmp_path)
        cache = {
            "JUNO/-61": {
                "mission": "JUNO",
                "naif_id": -61,
                "wikidata_qid": "Q186287",
            },
            "HORIZONS-SYNTH/-227": {
                "mission": "HORIZONS-SYNTH",
                "naif_id": -227,
                "wikidata_qid": "Q15839",  # Kepler, no collision
            },
        }
        assert index.qid_deduped_synth_naifs(cache) == set()

    def test_empty_cache_returns_empty_set(self, tmp_path, monkeypatch):
        self._missions_dir_with(tmp_path, ["INTEGRAL"])
        monkeypatch.setattr(index, "DOWNLOAD_DIR", tmp_path)
        assert index.qid_deduped_synth_naifs({}) == set()

    def test_synth_without_qid_is_kept(self, tmp_path, monkeypatch):
        # Brand-new synth entries lack a curated QID — never dedup them.
        self._missions_dir_with(tmp_path, ["INTEGRAL"])
        monkeypatch.setattr(index, "DOWNLOAD_DIR", tmp_path)
        cache = {
            "INTEGRAL/-275": {
                "mission": "INTEGRAL",
                "naif_id": -275,
                "wikidata_qid": "Q50021",
            },
            "HORIZONS-SYNTH/-198": {
                "mission": "HORIZONS-SYNTH",
                "naif_id": -198,
                "wikidata_qid": None,
            },
        }
        assert index.qid_deduped_synth_naifs(cache) == set()
