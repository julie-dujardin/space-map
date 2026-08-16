"""Curated per-mission .bsp filename whitelists and skip patterns.

`MISSION_INCLUDE` whitelists files per mission so we don't mirror entire
NAIF archives — the goal is the *canonical* reconstructed trajectory per
mission, refit into our Chebyshev / Kepler-with-drift format downstream.
Empty tuple = mission disabled; no entry = accept all .bsp files (modulo
SKIP_PATTERNS).

`LANDED_INCLUDE` is the parallel surface/post-touchdown whitelist; files
matching it are routed to LANDED_MISSIONS_DIR instead of MISSIONS_DIR.
LANDED wins over MISSION_INCLUDE in `listings.list_mission_spks`.

`MISSION_LATEST_ONLY` flags missions where each MISSION_INCLUDE pattern
matches multiple cumulative versions; keep only the lex-last per pattern.

`SKIP_PATTERNS` drops generic-ephemeris (planet DE, sb441) and stationary
post-impact / crash-site debris kernels.
"""

import re

# Conservative per-mission whitelists, validated against each mission's
# trajectory extraction.
MISSION_INCLUDE: dict[str, tuple[str, ...]] = {
    # --- Operational-tree missions ---
    # 2020-reprocessed reconstruction (~156 files, ~2.7 GiB). The PDS3 archive
    # `co-s_j_e_v-spice-6-v1.0` carries the same data more cleanly if this
    # turns out too heavy.
    "CASSINI": (r"^200128RU_SCPSE_\d+_\d+\.bsp$",),
    "EXOMARS2016": (r"^em16_tgo_mlt_\d+_\d+_v\d+\.bsp$",),
    "ExoMars2016": (r"^em16_tgo_mlt_\d+_\d+_v\d+\.bsp$",),
    "DAWN": (r"^Dawn_ephem_\d+\.bsp$",),
    # `bc_mpo_fcp_*` is the flown trajectory (launch→2027, ops-updated); the
    # mct/mlt planning series disagrees with it by hours/thousands of km at
    # the swingbys. `fcp` is a recon token so it out-furnishes them wherever
    # it covers; mlt/slt still supply post-2027 planning coverage. Each MLT
    # iteration covers a different date span, so keep all matches rather
    # than lex-last. Per-swingby `bc_mpo_fcp_*SwingbyMTP_*` files are
    # excluded — redundant with the full-arc fcp.
    "BEPICOLOMBO": (
        r"^bc_mpo_fcp_\d+_\d+_\d+_v\d+\.bsp$",
        r"^bc_mcs_mct_\d+_\d+_\d+_v\d+\.bsp$",
        r"^bc_mmo_mlt_\d+_\d+_\d+_v\d+\.bsp$",
        r"^bc_mpo_mlt_\d+_\d+_\d+_v\d+\.bsp$",
        r"^bc_mmo_slt_extension_\d+_\d+_v\d+\.bsp$",
        r"^bc_mpo_slt_extension_\d+_\d+_v\d+\.bsp$",
    ),
    # `spk_ref_*` is the long-arc trajectory reference predict (~7 yr); lex-last
    # picks the most recent issue, which extends past `juno_pred_orbit`.
    "JUNO": (
        r"^juno_rec_orbit\.bsp$",
        r"^juno_pred_orbit\.bsp$",
        r"^spk_ref_\d{6}_\d{6}_\d{6}\.bsp$",
    ),
    # ESA `MEX/` 404s — canonical dir is `MARS-EXPRESS/` (NAIF `MEX/` mirrors
    # the same archive). Kept patterns:
    #   * `MEX_ROB_*` — yearly reconstruction, frozen at 2013-12-31
    #   * `ORMF_*`    — flight predict, full-mission, latest extends to 2032
    # The `ORMM__YYMMDDHHMMSS_NNNNN.BSP` monthly reconstructions (269 files
    # 2003→present, continuous coverage) are EXCLUDED: 269 small segments
    # in one furnish pool blow out SPICE's DAF cache and make classify_trace
    # run for 30+ min on MEX alone. Re-add via either (a) HORIZONS-SYNTH
    # precedence wins for the 2014-2018 gap, or (b) per-mission spkmerge in
    # the download pipeline to collapse 269 BSPs into 1.
    "MEX": (
        r"^MEX_ROB_\d+_\d+_\d+\.BSP$",
        r"^ORMF_T\d+_\d{6}_\d{6}_\d+\.BSP$",
    ),
    "MARS-EXPRESS": (
        r"^MEX_ROB_\d+_\d+_\d+\.BSP$",
        r"^ORMF_T\d+_\d{6}_\d{6}_\d+\.BSP$",
    ),
    "MRO": (r"^mro_cruise\.bsp$", r"^mro_psp\d*\.bsp$"),
    "MER": (r"^mer[12]_cruise.*\.bsp$", r"^mer[12]_edl_rcb_v\d+\.bsp$"),
    # Mars Odyssey files are split across cruise + aerobraking + 27+ science
    # extensions; there is no single `m01_full.bsp`.
    "M01": (
        r"^m01_cruise\.bsp$",
        r"^m01_ab(?:_v\d+)?\.bsp$",
        r"^m01_ext\d+\.bsp$",
        r"^m01_map\d+\.bsp$",
        r"^m01_map_rec\.bsp$",
    ),
    # `juice_orbc_<iter>_<start>_<end>_v<N>.bsp` — iteration ID and version
    # both bump on every ESA release, so match generically rather than pin them.
    "JUICE": (r"^juice_orbc_\d+_\d+_\d+_v\d+\.bsp$",),
    "LUCY": (r"^lcy_\d+_330\d+_.*sconly_v\d+\.bsp$",),
    # Match any L-version so future NAIF bumps don't need re-pinning.
    "SOLAR-ORBITER": (r"^solo_ANC_soc-orbit_\d+-\d+_L\d+_V\d+_\d+_V\d+\.bsp$",),
    "JWST": (r"^jwst_(?:rec|pred)\.bsp$",),
    # ESA `kernels/mk/hera_plan.tm` is the canonical "use these SPKs" file
    # and points at two iterating series: `hera_fcp_*` (Flight Control
    # Product, reconstructed flight, launch → ~present) and `hera_flp_*`
    # (Forward-Looking Product, planned trajectory through ~rendezvous).
    # Both increment a 6-digit iteration on every release; MISSION_LATEST_ONLY
    # keeps just the lex-last of each. Must resolve to a multi-arc kernel, not
    # a short sub-phase one — a span under one interplanetary sub-chunk (7d)
    # never reaches the export.
    "HERA": (
        r"^hera_fcp_\d+_\d+_\d+_v\d+\.bsp$",
        r"^hera_flp_\d+_\d+_\d+_v\d+\.bsp$",
    ),
    # `_rec_*` are per-arc reconstructions (must keep all); `_ref_*` are
    # long-arc references to mission EOM (Psyche arrival 2029-06).
    "PSYCHE": (
        r"^psyche_rec_\d+-\d+_\d+_v\d+\.bsp$",
        r"^psyche_ref_\d+-\d+_\d+_v\d+\.bsp$",
    ),
    # `gaia_<launch>_<asof>_v\d+` is the cumulative reconstruction; `_rec_`
    # and `_pre_` are weekly chunks (LATEST_ONLY picks the latest each); `_flp_`
    # is the long-arc flight predict (to 2125).
    "GAIA": (
        r"^gaia_\d+_\d+_v\d+\.bsp$",
        r"^gaia_rec_\d+_\d+_v\d+\.bsp$",
        r"^gaia_pre_\d+_\d+_v\d+\.bsp$",
        r"^gaia_flp_\d+_\d+_v\d+\.bsp$",
    ),
    # NAIF/{VEX,VENUS-EXPRESS,ROSETTA}/kernels/spk/ are empty on the
    # operational tree; real data lives in PDS3 archives (vex-e_v-spice-6-v2.0,
    # ros-e_m_a_c-spice-6-v1.0). Adding those is a follow-up extension to
    # `PDS3_DATASETS`. MPF is similar but its PDS3 dataset doesn't exist —
    # see the `landed-events` TODO below for the shared no-SPK path.
    "VEX": (),
    "VENUS-EXPRESS": (),
    "ROSETTA": (),
    # OSIRIS-REx / OSIRIS-APEX. NAIF moved from `refodNNN` to plain `odNNN`
    # after Bennu departure (and ODs now carry maneuver tags like `od401-C-
    # TCM18-P-TCM19B`). `_pgaa\d+_dayNNmNN_*` are the multi-year long-arc
    # references for the primary mission.
    "ORX": (
        r"^orx_\d+_\d+_\d+_(?:refod|od)\d+[A-Za-z0-9_-]*_v\d+\.bsp$",
        r"^orx_\d+_\d+_pgaa\d+_day\d+m\d+(?:_v\d+)?\.bsp$",
        r"^spk_orx_\d+_\d+_pgaa\d+_day\d+m\d+_v\d+\.bsp$",
    ),
    # Chandrayaan-1 has either a single 712 MiB predict or 2300+ daily 3.5 MiB
    # kernels (~8 GiB cumulative). Disabled pending a cost/value decision.
    "CHANDRAYAAN-1": (),
    # Cumulative reconstruction + quarterly deltas. NAIF updates the cumulative
    # quarterly; deltas catch the case where the cumulative lags.
    "MAVEN": (
        r"^maven_orb_rec\.bsp$",
        r"^maven_orb_rec_\d{6}_\d{6}_v\d+\.bsp$",
    ),
    # `ref_trj_*_scpse.bsp` full-mission references; per-arc `trj_*_OD\d+_v\d+.bsp`
    # reconstructions are not matched here.
    "EUROPACLIPPER": (r"^ref_trj_\d+_\d+_21F31_MEGA_L\d+_A\d+_LP\d+_V\d+_scpse\.bsp$",),
    "MARS2020": (r"^m2020_cruise_od\d+_v\d+\.bsp$",),
    "MSL": (r"^msl_cruise_v\d+\.bsp$",),
    "THEMIS": (),  # Earth-orbit constellation; tracked via celestrak instead
    "SMAP": (),  # Earth-orbit; celestrak
    # Newly enabled (previously skipped or accept-all). Patterns picked from a
    # fresh sweep of each NAIF/ESA `kernels/spk/` listing.
    "SIRTF": (r"^spk_191101_200134_220101_short\.bsp$",),  # Spitzer warm phase
    "CHANDRA": (),  # Earth-orbit (HEO); tracked via celestrak (norad_satcat-25867)
    "APOLLO": (r"^apollo15-1\.bsp$", r"^a16_subsat_ssd_lp150q\.bsp$"),
    "MPL": (r"^mpl_cruise\.bsp$",),  # Mars Polar Lander (lost during EDL)
    "PHSRM": (r"^phsrm_\d+_\d+_\d+_nom\d+\.bsp$",),  # Phobos-Grunt (planned)
    "PHOBOS88": (r"^p88mrg\.bsp$", r"^iam_r2\.bsp$"),  # Phobos 2
    "LPM": (r"^lp_ask_\d+-\d+\.bsp$",),  # Lunar Prospector
    "GLL": (r"^gll_951120_021126_raj2021\.bsp$",),  # Galileo, 2021 reanalysis
    "HELIOS": (
        r"^\d+R_helios[12]_\d+_\d+\.bsp$",
        r"^\d+AP_helios[12]_\d+_\d+\.bsp$",
    ),
    "HST": (),  # Earth-orbit; tracked via celestrak (norad_satcat-20580)
    "IUE": (r"^IUE\.bsp$",),
    # InSight cruise + the two MarCO CubeSats that rode along to Mars.
    "INSIGHT": (
        r"^insight_cru_ops_v\d+\.bsp$",
        r"^marco[ab]_\d+_\d+_\d+_v\d+\.bsp$",
    ),
    "PHOENIX": (r"^phx_cruise\.bsp$", r"^phx_edl_rec_traj\.bsp$"),
    "LADEE": (r"^ladee_r_\d+_\d+_(?:pha|loa|sci)_v\d+\.bsp$",),
    "DEEPIMPACT": (
        r"^di_finalenc_nav_v\d+\.bsp$",
        r"^dif_dixi_nav_v\d+\.bsp$",
        r"^dif_epoch_nav_v\d+\.bsp$",
    ),
    "CONTOUR": (
        r"^contour\.traj\.\d+\.noplephem-\d+\.bsp$",
        r"^contour_phasing\.bsp$",
    ),
    "STEREO": (r"^STEREO-A_merged\.bsp$",),  # STEREO-B failed 2014
    "ULYSSES": (r"^ulysses_\d+_\d+_\d+\.bsp$",),
    "VEGA": (r"^vega\..*\.bsp$",),
    "VIKING": (r"^vo[12]_rcon\.bsp$",),  # orbiters only; landers are surface
    "VOYAGER": (r"^[Vv]oyager_[12]\.[A-Za-z0-9.+_]+merged\.bsp$",),
    "MCO": (r"^mco_cruise\.bsp$",),  # Mars Climate Orbiter (lost)
    "M2": (r"^m2_\d+_\d+_ja_v\d+\.bsp$",),  # Mariner 2
    "M9": (r"^m9\.bsp$",),  # Mariner 9
    "M10": (r"^M10_archive_\d+\.bsp$",),  # Mariner 10
    "GIOTTO": (r"^giotto_\d+_\d+\.bsp$",),
    "LUNARORBITER": (
        r"^lo[123]_ssd_lp150q\.bsp$",
        r"^lo4_ssd_lp150q_v2\.bsp$",
        r"^lo5_ssd_lp150q\.bsp$",
    ),
    "PIONEER6": (r"^pio6-a\.bsp$",),
    "PIONEER8": (r"^pioneer8-seti\.bsp$",),
    "PIONEER10": (r"^p10-a\.bsp$",),
    "PIONEER11": (r"^p11-a\.bsp$", r"^p11_sat336\.bsp$"),
    "PIONEER12": (r"^pvo_\d+_\d+_ssd\d+\.bsp$",),  # Pioneer Venus Orbiter
    "NOZOMI": (r"^planetb_pb98\.bsp$",),
    # ESA-only missions (newly enabled).
    "EUCLID": (r"^euclid_flp_\d{8}_\d{8}_v\d+\.bsp$",),
    # Each `integral_sc_ssm_20021017_<asof>_v<NN>.bsp` re-spans launch→that
    # date; only the lex-last filename is needed (see `MISSION_LATEST_ONLY`).
    "INTEGRAL": (r"^integral_sc_ssm_20021017_\d+_v\d+\.bsp$",),
    "XMM": (),  # Earth-orbit (HEO); tracked via celestrak (norad_satcat-25989)
    "LPF": (r"^lpfcmd\.bsp$",),  # LISA Pathfinder
    # LANDED phase moved to LANDED_INCLUDE so the trajectory pipeline doesn't
    # classify Huygens-on-Titan as a flying-then-landed sequence — surface
    # samples belong in the lat/lng export, not in the chunk fit.
    "HUYGENS": (
        r"^\d+AP_OPK_\d+_\d+\.BSP$",
        r"^HUYGENS_(?:COAST|ENTRY|DESCENT)_V\d+\.BSP$",
    ),
    "COMET-INTERCEPTOR": (r"^CI_SC[AB][12]?_v\d+\.bsp$",),
    # Pre-launch trajectory study with ~14 variant scenarios (T1/T4/ET1/HEO,
    # NorthVOI/SouthVOI/LPO, ML007/008/014, …). They overlap in time, all
    # target NAIF -668, and disagree on position — SPICE's last-loaded-wins
    # then makes the fit compare against an arbitrary scenario. We pin to
    # the ESA baseline: T1 (Trajectory 1, 2032 launch), NorthVOI insertion,
    # ML014 (latest planning iteration). LPO covers the post-VOI early
    # science orbit (2032-12 → 2033-05) and NorthVOI covers the established
    # science orbit (2034-07 → 2038-09). Aerobraking window 2033-2034 is
    # left as a gap. Update this list if ESA's mission planning baseline
    # changes — the other files (T4, ET1, HEO, ML008, …) are alternative
    # scenarios from pre-launch trade studies, not consecutive refinements.
    "ENVISION": (
        r"^EnVision_T1_2032_N_LPO_ML014_\d+_\d+_v\d+\.bsp$",
        r"^EnVision_T1_2032_NorthVOI_ML014_\d+_\d+_v\d+\.bsp$",
    ),
    "RAMSES": (r"^ramses_study_LPO_\d+(?:_CEP)?_\d+_\d+_v\d+\.bsp$",),
    # M-MATISSE has both short summary IPO1 LD21 files AND per-phase
    # (EEM/T2/T4, year, LD, FDC/DLC, IPO1/IPO2) detailed kernels.
    "M-MATISSE": (
        r"^mmatisse_(?:henri|marguerite)_ipo1_LD21_\d+_\d+_v\d+\.bsp$",
        r"^mmatisse_(?:henri|marguerite)_\d{4}_[A-Za-z0-9]+_LD\d+_(?:FDC|DLC)_IPO\d+_\d+_\d+_v\d+\.bsp$",
    ),
    # --- PDS3 archive missions ---
    "NEWHORIZONS": (
        r"^nh_recon_e2j_v\d+\.bsp$",
        r"^nh_recon_j2sep07_prelimv\d+\.bsp$",
        # Cruise-era OD reconstructions (od077 ≈ 2007 → 2009, od117 ≈ 2011 →
        # 2014). Fills the 7-year gap between Jupiter departure and Pluto
        # approach that the recon_e2j / recon_pluto pair leaves open.
        r"^nh_recon_od\d+_v\d+\.bsp$",
        r"^nh_recon_pluto_od\d+_v\d+\.bsp$",
        r"^nh_recon_arrokoth_od\d+_v\d+\.bsp$",
        r"^nh_pred_alleph_od\d+\.bsp$",
        r"^nh_pred_od\d+\.bsp$",
    ),
    "MESSENGER": (
        # Cumulative cruise+orbital long-arc, OD431 v_2.
        r"^msgr_040803_150430_150430_od431sc_2\.bsp$",
    ),
    "MGS": (
        r"^mgs_crus\.bsp$",
        r"^mgs_ab\d+\.bsp$",
        r"^mgs_spo\d+\.bsp$",
        r"^mgs_map\d+\.bsp$",
        r"^mgs_ext\d+\.bsp$",
    ),
    "LRO": (r"^lrorg_\d+_\d+_v\d+\.bsp$",),
    "NEAR": (
        r"^near_cruise_nav_v\d+\.bsp$",
        r"^near_erosorbit_nav_v\d+\.bsp$",
        r"^near_eroslanded_nav_v\d+\.bsp$",
    ),
    "GRAIL": (r"^grail_\d+_\d+_nav_v\d+\.bsp$",),
    "HAYABUSA": (
        r"^hay_jaxa_\d+_\d+_v\d+n?\.bsp$",
        r"^hayabusa_itokawarendezvous_v\d+\.bsp$",
    ),
    # --- PDS4 archive missions ---
    "DART": (
        # Pre-impact reconstruction. The _imp_ variant is skipped via
        # SKIP_PATTERNS (parks debris at Dimorphos through 2099).
        r"^dart_\d+_\d+_\d+_\d+_rec_v\d+\.bsp$",
    ),
    "HYB2": (
        # Long-arc reconstructed Hayabusa2 trajectory (cruise + Ryugu
        # proximity); the per-MASCOT/opnav/struct kernels are skipped.
        r"^hyb2_\d{8}-\d{8}_\d+[hm]_final_ver\d+\.bsp$",
        r"^hyb2_asteroid_to_earth_\d+_v\d+\.bsp$",
    ),
    "VCO": (
        # Akatsuki / PLANET-C per-year reconstruction, 2010 launch onward.
        r"^vco_\d{4}_v\d+\.bsp$",
    ),
    "CLPS": (
        # Four landers share one PDS4 bundle. Cruise + EDL kernels for each;
        # static *_atls_*, *_ls_*, *_struct_* placeholders are excluded.
        r"^clps_to2ab_apm1_cru_rec_\d+_\d+_v\d+\.bsp$",  # Peregrine cruise
        r"^clps_to2im_im1_cru_rec_\d+_\d+_v\d+\.bsp$",  # IM-1 cruise
        r"^clps_to2im_im1_edl_rec_\d+_v\d+\.bsp$",  # IM-1 EDL
        r"^clps_prime1_im2_cru_rec_\d+_\d+_v\d+\.bsp$",  # IM-2 cruise
        r"^clps_prime1_im2_edl_rec_\d+_v\d+\.bsp$",  # IM-2 EDL
        r"^clps_to19d_bgm1_cru_rec_\d+_\d+_v\d+\.bsp$",  # BG-1 cruise
        r"^clps_to19d_bgm1_edl_rec_\d+_v\d+\.bsp$",  # BG-1 EDL
    ),
    # --- DARTS-only missions ---
    "SELENE": (r"^SEL_M_\d+_\d+_SGM[HI]_\d+\.BSP$",),  # Kaguya
}


# Surface / post-touchdown kernels. Parallel to MISSION_INCLUDE but routed
# to `LANDED_MISSIONS_DIR` instead of `MISSIONS_DIR`. Each mission's full
# kernel listing is filtered against MISSION_INCLUDE *and* LANDED_INCLUDE
# in one pass; files matching here are excluded from the trajectory bucket
# regardless of MISSION_INCLUDE state.
#
# Three kernel flavors per mission to keep in mind:
#   * `*_atls_ops*_v*.bsp`  — spacecraft NAIF (-189, -84, -76, -168) pinned
#     at landing site post-touchdown. The actual "where is the probe sitting".
#   * `*_ls_ops*_iau2000_v*.bsp` — landing-site NAIF (×100 + 900) reference,
#     fixed IAU2000 coords. Same lat/lng as the atls kernel but under a
#     SPICE-internal NAIF, useful as a cross-check.
#   * `*_surf_rover_(tlm|loc)_*_v*.bsp` — sol-range slices of the rover's
#     actual surface track. Telemetry is more accurate than location;
#     SPICE last-loaded-wins picks whichever is loaded later.
#
# Excludes the `_gc_` pre-flight planning variants, `_nom_*` nominal
# planning, `_struct_*` instrument FKs, `_still_at_ls_v*` pre-launch
# placeholders (which would otherwise span 2000→2099 at the landing site
# and inflate sample counts).
LANDED_INCLUDE: dict[str, tuple[str, ...]] = {
    # Static landers
    "INSIGHT": (
        r"^insight_atls_ops\d+_v\d+\.bsp$",
        r"^insight_ls_ops\d+_iau2000_v\d+\.bsp$",
    ),
    "PHOENIX": (
        r"^phx_ls_to_lander_v\d+\.bsp$",
        r"^phx_ls_ops\d+_iau2000_v\d+\.bsp$",
        r"^phx_spk-land_\d+_\d+_\d+(?:_eph)?\.bsp$",
    ),
    "VIKING": (r"^vl[12]\.bsp$",),  # NAIF -327 (Viking 1), -330 (Viking 2)
    "HUYGENS": (r"^HUYGENS_LANDED_V\d+\.BSP$",),  # NAIF -150 on Titan
    # Active/historic rovers. `*_surf_rover_tlm_*` is intentionally excluded:
    # it carries instrument-FK target NAIFs (-76501..-76620 etc.) in a mission
    # frame (-76910 / -168910) that we don't load the FK for, and the rover-
    # body NAIF (-76, -168) is fully covered by `*_surf_rover_loc_*` segments
    # in IAU_MARS. Same for MER: the `surf_iddg` kernels carry joint angle
    # data in an unknown mission frame; only `_ls_` (landing-site position)
    # is useful here since the rover-body NAIF (-253, -254) has no separate
    # trajectory kernel in the archive — MER positions reduce to the static
    # landing site.
    "MSL": (
        r"^msl_atls_ops\d+_v\d+\.bsp$",
        r"^msl_ls_ops\d+_iau2000_v\d+\.bsp$",
        r"^msl_surf_rover_loc_\d+_\d+_v\d+\.bsp$",
        r"^msl_surf_rover_loc_runout\.bsp$",  # future-prediction tail
    ),
    "MARS2020": (
        r"^m2020_atls_ops\d+_v\d+\.bsp$",
        r"^m2020_ls_ops\d+_iau2000_v\d+\.bsp$",
        r"^m2020_surf_rover_loc_\d+_\d+_v\d+\.bsp$",
        r"^m2020_surf_rover_loc_runout\.bsp$",
    ),
    # MER `rvr_rpf` ("rover position fix") gives the only rover-body (-253,
    # -254) trajectory in the archive — two short kernels per rover (~2 and
    # ~5 days respectively), spanning the first ~3 months post-landing. After
    # those, only `_ls_` (static landing site) and `iddg` (joint-angle
    # telemetry, ignored — mission frame -253000 we don't load) are available.
    "MER": (
        r"^mer[12]_ls_\d+_iau2000_v\d+\.bsp$",
        r"^mer[12]_rvr_rpf_\d+\.bsp$",
    ),
}

# Missions where each MISSION_INCLUDE regex matches multiple cumulative
# versions and we only want the lex-last filename per pattern. Use for
# `mission_<launch>_<asof>_v<NN>.bsp` series where each kernel fully respans
# the prior coverage.
MISSION_LATEST_ONLY: frozenset[str] = frozenset(
    {
        # Each pattern in these missions is a forward-extending cumulative
        # series — lex-last is the most recent issue and supersedes prior
        # iterations. (BepiColombo MMO/MPO MLT explicitly doesn't qualify:
        # different MLT iterations cover *different* date windows, so we
        # keep all matches.)
        "INTEGRAL",
        "HERA",
        "GAIA",
        "JUNO",
        "JUICE",
    }
)

SKIP_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^de\d+s?\.bsp$",
        r"^mar\d+.*\.bsp$",
        r"^jup\d+.*\.bsp$",
        r"^sat\d+.*\.bsp$",
        r"^ura\d+.*\.bsp$",
        r"^nep\d+.*\.bsp$",
        r"^plu\d+.*\.bsp$",
        r"^sb441.*\.bsp$",
        r"^outerplanets.*\.bsp$",
        r"^marsat.*\.bsp$",
        r"^earthstns.*\.bsp$",
        r"^estrack.*\.bsp$",
        r"^new_norcia.*\.bsp$",
        r"^earthnpole.*\.bsp$",
        r"^stations?\.bsp$",
        r"^[a-z0-9_-]+_struct.*\.bsp$",
        r"^[a-z0-9_-]+_aspera.*\.bsp$",
        r"^[a-z0-9_-]+_pfs_.*\.bsp$",
        r"^[a-z0-9_-]+_relay.*\.bsp$",
        r"^vesta_.*\.bsp$",
        r"^tempel.*\.bsp$",
        r"^c\d{4}.*\.bsp$",
        # Post-mission stationary debris ephemerides (LADEE _imp_, DART _imp_,
        # GRAIL _crashsite_) span decades parked at the impact site. No
        # trajectory value and they pollute coverage-based classification.
        r"^[a-z0-9_-]+_imp_v\d+\.bsp$",
        r"^[a-z0-9_-]+_crashsite_v\d+\.bsp$",
    )
)
