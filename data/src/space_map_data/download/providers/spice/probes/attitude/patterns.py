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

TODO(phase 2): seed the 13 other missions the sweep benchmarked
successfully (CASSINI, DAWN, JUNO, EUROPACLIPPER, ORX, SMAP, SIRTF,
LADEE, MCO, INTEGRAL, PHSRM, GAIA, SOLAR-ORBITER). Patterns and frames
captured below in commented-out form for the addition pass.

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


PATTERNS: dict[str, AttitudePattern] = {
    "MRO": AttitudePattern(
        ck_glob="mro_sc_psp_*.bc",
        fk_glob="mro_v*.tf",
        sclk_glob="MRO_SCLKSCET.*.tsc",
        frame_name="MRO_SPACECRAFT",
    ),
    # Phase 2 entries (validated by the sweep — uncomment after Phase 1 land):
    #
    # "JUNO": AttitudePattern("juno_sc_rec_*.bc", "juno_v*.tf",
    #                         "JNO_SCLKSCET.*.tsc", "JUNO_SPACECRAFT"),
    # "CASSINI": AttitudePattern("*ra.bc", "cas_v*.tf",
    #                            "cas*.tsc", "CASSINI_SC_COORD"),
    # "DAWN": AttitudePattern("dawn_sc_*.bc", "dawn_v*.tf",
    #                         "dawn_sclkscet_*.tsc", "DAWN_SPACECRAFT"),
    # "EUROPACLIPPER": AttitudePattern("clipper_sc_*.bc", "clipper_v*.tf",
    #                                  "europaclipper_*.tsc", "EUROPAM_SPACECRAFT"),
    # "ORX": AttitudePattern("orx_*.bc", "orx_v*.tf",
    #                        "ORX_SCLKSCET.*.tsc", "ORX_SPACECRAFT"),
    # "SMAP": AttitudePattern("smap_at_*.bc", "smap_pf_v*.tf",
    #                         "smap_cl_v*.tsc", "SMAP_SC"),
    # "SIRTF": AttitudePattern("ts*.bc", "sirtf_v*.tf",
    #                          "STF_SCLKSCET.*.tsc", "SIRTF_SC_BUS"),
    # "LADEE": AttitudePattern("ladee_*.bc", "ladee_frames_*.tf",
    #                          "ladee_clkcor_*.tsc", "LADEE_SC_PROP"),
    # "MCO": AttitudePattern("mco_*.bc", "mco*.tf",
    #                        "MCO_SCLKSCET.*.tsc", "MCO_SPACECRAFT"),
    # "INTEGRAL": AttitudePattern("integral_sc_*.bc", "integral_v*.tf",
    #                             "integral_fict_*.tsc", "INTEGRAL_SPACECRAFT"),
    # "PHSRM": AttitudePattern("phsrm_sc_*.bc", "phsrm_v*.tf",
    #                          "phsrm_*.tsc", "PHSRM_SPACECRAFT"),
    # "GAIA": AttitudePattern("gaia_sc_*.bc", "gaia_v*.tf",
    #                         "gaia_fict_*.tsc", "GAIA_SPACECRAFT"),
    # "SOLAR-ORBITER": AttitudePattern("solo_ANC_soc-default-att-stp_*.bc",
    #                                  "solo_ANC_soc-sc-fk_V*.tf",
    #                                  "solo_ANC_soc-sclk_*.tsc", "SOLO_PRF"),
}


def pattern_for(mission: str) -> AttitudePattern | None:
    """Return the attitude pattern for `mission`, or None if not curated."""
    return PATTERNS.get(mission)
