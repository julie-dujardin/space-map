"""Per-mission CK / FK / SCLK download patterns and spacecraft frame name.

Each entry tells the attitude downloader which files to fetch from a
mission's NAIF/ESA `kernels/{ck,fk,sclk}/` directory and which frame name
the resulting kernel set should expose to `pxform`.

Patterns are `fnmatch` globs:

  * `ck_glob` — every matching CK is downloaded; together they form the
    spacecraft-bus attitude history. The extractor furnishes them all
    and asks the kernel pool for the union coverage.
  * `fk_glob` — the spacecraft body FK. We pick the lexicographically
    last match (NAIF version-numbered FKs sort correctly that way).
  * `sclk_glob` — the spacecraft clock kernel; same lex-last rule.

`frame_name` is what we hand to `pxform("J2000", <frame>, et)`. NAIF
convention is `<MISSION>_SPACECRAFT` but older or smaller missions use
their own names (Cassini's `CASSINI_SC_COORD`, Solar Orbiter's
`SOLO_PRF`).

`estimated_total_mib` orders the downloader's per-mission pass so small
missions land first under a global cap. Values are rough — sweep-observed
sample sizes × estimated file counts. Off by a factor of 2 in either
direction is fine; the cap check stops us before damage.

A mission maps to one `AttitudePattern`, or a list when one upstream dir
holds several spacecraft (Voyager 1/2, Viking Orbiter 1/2) — each gets its
own frame/FK/SCLK and an entry in the index's `spacecraft` array.

TODO(phase 3): PDS3 (Cassini, NEAR, NH, Messenger, MGS, LRO, GRAIL,
HAYABUSA) + PDS4 (DART, HYB2, VCO, CLPS) attitude — different upstream
paths, parallel to the SPK PDS discovery in `sources.py`.

TODO: over-cap bus reconstruction (>10 GiB) — MAVEN, MEX, M01,
Chandrayaan-1, ExoMars2016, BepiColombo; ship a recent-years subset.

TODO: skip Mars surface missions (MARS2020, MSL, INSIGHT, MER, Phoenix) —
their CKs are arm/mast/HGA articulation, not bus attitude.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AttitudePattern:
    """Download recipe for one mission's SC-bus attitude kernels."""

    ck_glob: str
    fk_glob: str
    sclk_glob: str
    frame_name: str
    # Rough total CK download size, used to order missions ascending under
    # a global cap. ±50 % accuracy is fine — the cap stops us anyway.
    estimated_total_mib: int
    # Optional negative filter applied after `ck_glob`. Used when fnmatch
    # can't express the desired set in one pattern (e.g. INTEGRAL ships
    # both per-year files and huge cumulative-from-launch dumps that
    # share the same prefix; the latter are redundant and excluded here).
    ck_exclude_glob: str | None = None


# Per-mission glob conventions, after sweep observation:
#
#   * Reconstructed bus CKs are what we want for shipped attitude — they're
#     the post-flight true record. Predicted CKs (`*_p`, `*_pred_`, `_pa_`,
#     `_pb_`) duplicate the same windows with less accuracy.
#   * Instrument-articulation CKs share the mission's CK dir but carry
#     non-bus frames (HGA pointing, solar array, camera gimbals). The bus
#     glob below avoids them by sticking to mission-specific naming.
#   * For still-flying missions where reconstructed isn't published yet
#     (Europa Clipper, late JUNO), predicted is the best we can ship; we
#     accept both rather than skip the mission.
PATTERNS: dict[str, AttitudePattern | list[AttitudePattern]] = {
    "GAIA": AttitudePattern(
        # State-machine reconstructed bus attitude, one file per year.
        ck_glob="gaia_sc_ssm_*.bc",
        fk_glob="gaia_v*.tf",
        sclk_glob="gaia_fict_*.tsc",
        frame_name="GAIA_SPACECRAFT",
        estimated_total_mib=1_500,
    ),
    "ORX": AttitudePattern(
        # `_r_` = reconstructed, `_v01` = first revision. v02+ are localised
        # refits over specific windows (~30 % of files, ~80 GiB) — losing
        # them costs us the most-recent attitude correction in a few arcs
        # but keeps the dataset tractable. v01 alone is ~167 GiB across
        # 3.5 k files, so the per-file cap below stops us cleanly.
        ck_glob="orx_r_??????_??????_v01.bc",
        fk_glob="orx_v*.tf",
        sclk_glob="ORX_SCLKSCET.*.tsc",
        frame_name="ORX_SPACECRAFT",
        estimated_total_mib=170_000,
    ),
    "MCO": AttitudePattern(
        # Lost mission — only 3 CKs exist; no filter needed.
        ck_glob="mco_*.bc",
        fk_glob="mco*.tf",
        sclk_glob="MCO_SCLKSCET.*.tsc",
        frame_name="MCO_SPACECRAFT",
        estimated_total_mib=300,
    ),
    "SIRTF": AttitudePattern(
        # Spitzer reconstructed attitude — `ts*.bc` is the standard naming.
        ck_glob="ts*.bc",
        fk_glob="sirtf_v*.tf",
        sclk_glob="STF_SCLKSCET.*.tsc",
        frame_name="SIRTF_SC_BUS",
        estimated_total_mib=500,
    ),
    "PHSRM": AttitudePattern(
        ck_glob="phsrm_sc_*.bc",
        fk_glob="phsrm_v*.tf",
        sclk_glob="phsrm_*.tsc",
        frame_name="PHSRM_SPACECRAFT",
        estimated_total_mib=500,
    ),
    "INTEGRAL": AttitudePattern(
        # Per-year reconstructed bus attitude. Exclude the eight cumulative-
        # from-launch dumps (~500 MB each) that all start at 20021017 and
        # overlap with the per-year set.
        ck_glob="integral_sc_ssm_*.bc",
        ck_exclude_glob="integral_sc_ssm_20021017_*.bc",
        fk_glob="integral_v*.tf",
        sclk_glob="integral_fict_*.tsc",
        frame_name="INTEGRAL_SPACECRAFT",
        estimated_total_mib=500,
    ),
    "EUROPACLIPPER": AttitudePattern(
        # Still in cruise — no `_rec_` yet, so we take both `_pa_` (predicted)
        # and any future `_rec_` files. Versioned filename matches both.
        ck_glob="clipper_sc_*_v??.bc",
        fk_glob="clipper_v*.tf",
        sclk_glob="europaclipper_*.tsc",
        frame_name="EUROPAM_SPACECRAFT",
        estimated_total_mib=2_000,
    ),
    "LADEE": AttitudePattern(
        # LADEE used `<YYJJJ_YYJJJ_vNN>.bc` where YYJJJ is 5 chars (2-digit
        # year + 3-digit day-of-year), e.g. `ladee_14030_14108_v04.bc`.
        # The leading `1` excludes test/cal CKs from non-flight years.
        ck_glob="ladee_1????_1????_v??.bc",
        fk_glob="ladee_frames_*.tf",
        sclk_glob="ladee_clkcor_*.tsc",
        frame_name="LADEE_SC_PROP",
        estimated_total_mib=2_000,
    ),
    "CASSINI": AttitudePattern(
        # `*ra.bc` is the "reconstructed attitude" suffix — already filtered.
        ck_glob="*ra.bc",
        fk_glob="cas_v*.tf",
        sclk_glob="cas*.tsc",
        frame_name="CASSINI_SC_COORD",
        estimated_total_mib=2_000,
    ),
    "SOLAR-ORBITER": AttitudePattern(
        # `att-stp` = attitude step (per-period reconstructed). Skips `att-pred-stp`.
        ck_glob="solo_ANC_soc-default-att-stp_*.bc",
        fk_glob="solo_ANC_soc-sc-fk_V*.tf",
        sclk_glob="solo_ANC_soc-sclk_*.tsc",
        frame_name="SOLO_PRF",
        estimated_total_mib=8_000,
    ),
    "SMAP": AttitudePattern(
        # `at` = attitude, versioned (`_vNN`) = pick latest revisions.
        ck_glob="smap_at_*_v??.bc",
        fk_glob="smap_pf_v*.tf",
        sclk_glob="smap_cl_v*.tsc",
        frame_name="SMAP_SC",
        estimated_total_mib=20_000,
    ),
    "JUNO": AttitudePattern(
        # `_rec_` already means reconstructed; no predicted in this set.
        ck_glob="juno_sc_rec_*.bc",
        fk_glob="juno_v*.tf",
        sclk_glob="JNO_SCLKSCET.*.tsc",
        frame_name="JUNO_SPACECRAFT",
        estimated_total_mib=15_000,
    ),
    "DAWN": AttitudePattern(
        # Weekly reconstructed bus CKs are date-shaped `dawn_sc_YYMMDD_YYMMDD`
        # (+ `_vN` revisions). Excludes `_ql` quicklooks; `fstb3_ert` test
        # files don't fit the date shape. FK is `dawn_v??` — a bare `dawn_v*`
        # would lex-last-pick the Vesta frames kernel (`dawn_vesta_v00.tf`).
        ck_glob="dawn_sc_??????_??????*.bc",
        ck_exclude_glob="*_ql*.bc",
        fk_glob="dawn_v??.tf",
        sclk_glob="DAWN_203_SCLKSCET.*.tsc",
        frame_name="DAWN_SPACECRAFT",
        estimated_total_mib=20_000,
    ),
    "MRO": AttitudePattern(
        # MRO files end either `..._YYDDD_YYDDD.bc` (reconstructed) or
        # `..._YYDDD_YYDDDp.bc` (predicted). The `??????_??????.bc` shape
        # (no extra char before `.bc`) excludes the predicted suffix.
        ck_glob="mro_sc_psp_??????_??????.bc",
        fk_glob="mro_v*.tf",
        sclk_glob="MRO_SCLKSCET.*.tsc",
        frame_name="MRO_SPACECRAFT",
        estimated_total_mib=80_000,
    ),
    "HUYGENS": AttitudePattern(
        # Titan descent probe; all segments small.
        ck_glob="HUYGENS_*.BC",
        fk_glob="HUYGENS_V*.TF",
        sclk_glob="HUYGENS_FICT_*.TSC",
        frame_name="HUYGENS_PROBE",
        estimated_total_mib=140,
    ),
    "DEEPIMPACT": AttitudePattern(
        # Flyby bus; `_p` is predicted, `dii_*` is the separate impactor.
        ck_glob="dif_sc_*.bc",
        ck_exclude_glob="*_p.bc",
        fk_glob="di_v*.tf",
        sclk_glob="DIF_SCLKSCET.*.tsc",
        frame_name="DIF_SPACECRAFT",
        estimated_total_mib=1_000,
    ),
    "ROSETTA": AttitudePattern(
        # `[MR]E` matches both measured (`ROS_SC_MES`) and reconstructed
        # (`ROS_SC_REC`) bus.
        ck_glob="ROS_SC_[MR]E*.BC",
        fk_glob="ROS_V*.TF",
        sclk_glob="ROS_*STEP.TSC",
        frame_name="ROS_SPACECRAFT",
        estimated_total_mib=1_100,
    ),
    "JUICE": AttitudePattern(
        # `_meas_` measured bus; skips `_crema_` plans + instrument pointings.
        ck_glob="juice_sc_meas_*.bc",
        fk_glob="juice_v*.tf",
        sclk_glob="juice_step_*.tsc",
        frame_name="JUICE_SPACECRAFT",
        estimated_total_mib=2_000,
    ),
    "LUCY": AttitudePattern(
        # `lcy_sc_r_` reconstructed bus; excludes `_rel` and `_ipp_`.
        ck_glob="lcy_sc_r_*.bc",
        fk_glob="lucy_v*.tf",
        sclk_glob="LUCY_SCLKSCET.*.tsc",
        frame_name="LUCY_SPACECRAFT",
        estimated_total_mib=2_100,
    ),
    "PSYCHE": AttitudePattern(
        # `_sc_rec_` bus; skips `_sc_pred_`, solar-array, EP-gimbal CKs.
        ck_glob="psyche_sc_rec_*.bc",
        fk_glob="psyche_fk_v*.tf",
        sclk_glob="PSYC_255_SCLKSCET.*.tsc",
        frame_name="PSYC_SPACECRAFT",
        estimated_total_mib=4_000,
    ),
    "VEX": AttitudePattern(
        # Venus Express; `ATNV_MEASURED` reconstructed bus, one file/year.
        ck_glob="ATNV_MEASURED_*.BC",
        fk_glob="VEX_V*.TF",
        sclk_glob="VEX_*STEP.TSC",
        frame_name="VEX_SPACECRAFT",
        estimated_total_mib=5_000,
    ),
    "HERA": AttitudePattern(
        # `hera_sc_meas_` measured bus; Milani/Juventas cubesats excluded.
        ck_glob="hera_sc_meas_*.bc",
        fk_glob="hera_v*.tf",
        sclk_glob="hera_step_*.tsc",
        frame_name="HERA_SPACECRAFT",
        estimated_total_mib=7_000,
    ),
    "VOYAGER": [
        # Two craft per dir. `vgr#_super` is bus; `vg#_*_qmw_*` is scan platform.
        AttitudePattern(
            ck_glob="vgr1_super*.bc",
            fk_glob="vg1_v*.tf",
            sclk_glob="vg1*.tsc",
            frame_name="VG1_SC_BUS",
            estimated_total_mib=40,
        ),
        AttitudePattern(
            ck_glob="vgr2_super*.bc",
            fk_glob="vg2_v*.tf",
            sclk_glob="vg2*.tsc",
            frame_name="VG2_SC_BUS",
            estimated_total_mib=40,
        ),
    ],
    "VIKING": [
        # Two orbiters per dir. CKs only cover the scan platform (-27000 /
        # -30000); Viking has no bus attitude, so we target the platform.
        AttitudePattern(
            ck_glob="vo1_*_ck2.bc",
            fk_glob="vo1_v*.tf",
            sclk_glob="vo1_*.tsc",
            frame_name="VO1_PLATFORM",
            estimated_total_mib=4,
        ),
        AttitudePattern(
            ck_glob="vo2_*_ck2.bc",
            fk_glob="vo2_v*.tf",
            sclk_glob="vo2_*.tsc",
            frame_name="VO2_PLATFORM",
            estimated_total_mib=4,
        ),
    ],
}


def patterns_for(mission: str) -> list[AttitudePattern]:
    """Attitude patterns for `mission` as a list (empty if not curated)."""
    entry = PATTERNS.get(mission)
    if entry is None:
        return []
    if isinstance(entry, AttitudePattern):
        return [entry]
    return entry
