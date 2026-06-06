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

TODO(phase 3): PDS3 (Cassini, NEAR, NH, Messenger, MGS, LRO, GRAIL,
HAYABUSA) and PDS4 (DART, HYB2, VCO, CLPS) mission attitude — those
live at different upstream paths, parallel to the existing SPK PDS
discovery in `sources.py`.

TODO(phase 3, per-mission triage): MAVEN, MARS2020, MSL, INSIGHT, MEX,
LUCY, JUICE, BEPICOLOMBO, HERA — sweep picked wrong CKs (instrument
articulation, not bus attitude). Each needs a hand-curated `ck_glob`
matching the actual bus pattern.
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
PATTERNS: dict[str, AttitudePattern] = {
    "GAIA": AttitudePattern(
        # State-machine reconstructed bus attitude, one file per year.
        ck_glob="gaia_sc_ssm_*.bc",
        fk_glob="gaia_v*.tf",
        sclk_glob="gaia_fict_*.tsc",
        frame_name="GAIA_SPACECRAFT",
        estimated_total_mib=1_500,
    ),
    "ORX": AttitudePattern(
        # `_r_` = reconstructed; per-orbit-arc files. Skips `_p_` predicted
        # (each of which has many ~tcm/ort/intsci variants per window).
        ck_glob="orx_r_*.bc",
        fk_glob="orx_v*.tf",
        sclk_glob="ORX_SCLKSCET.*.tsc",
        frame_name="ORX_SPACECRAFT",
        estimated_total_mib=2_000,
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
        # Skip `dawn_sc_pred_*` (predicted attitude during planning).
        ck_glob="dawn_sc_rec_*.bc",
        fk_glob="dawn_v*.tf",
        sclk_glob="dawn_sclkscet_*.tsc",
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
}


def pattern_for(mission: str) -> AttitudePattern | None:
    """Return the attitude pattern for `mission`, or None if not curated."""
    return PATTERNS.get(mission)
