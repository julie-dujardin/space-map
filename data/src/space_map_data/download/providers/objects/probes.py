"""Download spacecraft-trajectory SPKs from NAIF, ESA, and the NAIF PDS archives.

A `MissionSource` is one mission's SPK directory on some upstream server.
Sources come from three families:

  * NAIF operational tree  — `https://naif.jpl.nasa.gov/pub/naif/<MISSION>/kernels/spk/`
  * ESA mirror             — `https://spiftp.esac.esa.int/data/SPICE/<MISSION>/kernels/spk/`
  * NAIF PDS3 / PDS4       — historical archives at `pub/naif/pds/data/<dataset>/<vol>/data/spk/`
    and `pub/naif/pds/pds4/<mission>/<bundle>/spice_kernels/spk/`. Each
    PDS dataset is curated explicitly via `PDS3_DATASETS` / `PDS4_BUNDLES`
    since their directory layout varies and they're frozen archives.

`MISSION_INCLUDE` whitelists files per mission so we don't mirror entire
NAIF archives — the goal is the *canonical* reconstructed trajectory per
mission, refit into our Chebyshev / Kepler-with-drift format downstream.
`SKIP_PATTERNS` drops generic-ephemeris (planet DE, sb441) and stationary
post-impact / crash-site debris kernels.

Output: per-mission `_index.json` at `spice/kernels/missions/<MISSION>/_index.json`
recording each file's size + target NAIF IDs. The ingest step (see
`ingest/providers/objects/probes.py`) reads these indexes and creates
Object rows with `id_type=PROBE`.
"""

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import httpx
import spiceypy

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)

NAIF_BASE = "https://naif.jpl.nasa.gov/pub/naif"
ESA_BASE = "https://spiftp.esac.esa.int/data/SPICE"
NAIF_PDS_BASE = "https://naif.jpl.nasa.gov/pub/naif/pds"

# Probe kernels share the SPICE on-disk tree because the runtime needs both
# generic kernels (lsk/pck/de/satellite ephemerides) and mission-trajectory
# kernels furnished together. Kept here as a constant so trace / sizing /
# export can also import it.
MISSIONS_DIR = DOWNLOAD_DIR / PROVIDERS.SPICE / "kernels" / "missions"

PDS3_DATASETS: dict[str, str] = {
    "NEWHORIZONS": "nh-j_p_ss-spice-6-v1.0",
    "MESSENGER": "mess-e_v_h-spice-6-v1.0",
    "MGS": "mgs-m-spice-6-v1.0",
    "LRO": "lro-l-spice-6-v1.0",
    "NEAR": "near-a-spice-6-v1.0",
    "GRAIL": "grail-l-spice-6-v1.0",
    "HAYABUSA": "hay-a-spice-6-v1.0",
}

PDS4_BUNDLES: dict[str, str] = {
    "DART": "dart/dart_spice",
    # JAXA Hayabusa2 (NAIF -37) — DARTS v1.0 bundle mirrored at NAIF, 2025-03-12.
    "HYB2": "hyb2/hyb2_spice",
    # JAXA Akatsuki / PLANET-C (NAIF -5) — DARTS v4.0 bundle mirrored at NAIF.
    "VCO": "vco/vco_spice",
    # NASA CLPS lunar landers — single combined bundle for Peregrine (-244),
    # IM-1 Odysseus (-370011), IM-2 Athena (-370021), Blue Ghost 1 (-2711).
    "CLPS": "clps/clps_spice",
}

# JAXA DARTS — kernels that don't have a NAIF mirror. SELENE/Kaguya is the
# only such case today; the rest of JAXA's SPICE archive (Hayabusa2, Akatsuki,
# original Hayabusa) is mirrored on NAIF and handled via the PDS3/PDS4 plumbing.
DARTS_BASE = "https://data.darts.isas.jaxa.jp/pub"
DARTS_SOURCES: dict[str, str] = {
    "SELENE": f"{DARTS_BASE}/spice/SELENE/kernels_ORG/spk/",
}

# Conservative per-mission whitelists. Empty tuple = mission disabled; no entry =
# accept all .bsp files (modulo SKIP_PATTERNS). Tightened over time as we
# validate each mission's trajectory extraction.
MISSION_INCLUDE: dict[str, tuple[str, ...]] = {
    # --- Operational-tree missions ---
    # 2020-reprocessed reconstruction (~156 files, ~2.7 GiB). The PDS3 archive
    # `co-s_j_e_v-spice-6-v1.0` carries the same data more cleanly if this
    # turns out too heavy.
    "CASSINI": (r"^200128RU_SCPSE_\d+_\d+\.bsp$",),
    "EXOMARS2016": (r"^em16_tgo_mlt_\d+_\d+_v\d+\.bsp$",),
    "ExoMars2016": (r"^em16_tgo_mlt_\d+_\d+_v\d+\.bsp$",),
    "DAWN": (r"^Dawn_ephem_\d+\.bsp$",),
    # MPO+MMO+MTM composite during cruise (`bc_mcs_mct_*`), and post-separation
    # MMO/MPO long-term plans (`bc_mmo_mlt_*`, `bc_mpo_mlt_*`) plus their
    # post-2028 SLT extensions. Each MLT iteration covers a different date
    # span (different planning epochs), so we keep all matches rather than
    # lex-last; SPICE's last-furnish-wins handles overlap fine.
    "BEPICOLOMBO": (
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
    # NAIF's actual M01 (Mars Odyssey) files are split across cruise +
    # aerobraking + 27+ science extensions; the file `m01_full.bsp` does NOT
    # exist on NAIF (the previous pattern matched zero files).
    "M01": (
        r"^m01_cruise\.bsp$",
        r"^m01_ab(?:_v\d+)?\.bsp$",
        r"^m01_ext\d+\.bsp$",
        r"^m01_map\d+\.bsp$",
        r"^m01_map_rec\.bsp$",
    ),
    # `juice_orbc_<iter>_<start>_<end>_v<N>.bsp` — iteration ID and version
    # both bump over time; previous `000104..._v01` hardcode would silently
    # break on the next ESA release.
    "JUICE": (r"^juice_orbc_\d+_\d+_\d+_v\d+\.bsp$",),
    "LUCY": (r"^lcy_\d+_330\d+_.*sconly_v\d+\.bsp$",),
    # Latest L-version on NAIF is L025; the previous L030 hardcode matched
    # zero files. Generalised to match any L-version so future bumps don't
    # silently break this.
    "SOLAR-ORBITER": (r"^solo_ANC_soc-orbit_\d+-\d+_L\d+_V\d+_\d+_V\d+\.bsp$",),
    "JWST": (r"^jwst_(?:rec|pred)\.bsp$",),
    # ESA `kernels/mk/hera_plan.tm` is the canonical "use these SPKs" file
    # and points at two iterating series: `hera_fcp_*` (Flight Control
    # Product, reconstructed flight, launch → ~present) and `hera_flp_*`
    # (Forward-Looking Product, planned trajectory through ~rendezvous).
    # Both increment a 6-digit iteration on every release; MISSION_LATEST_ONLY
    # keeps just the lex-last of each. The previous `HERA_NomTrajDCP3VCF_v01`
    # pattern caught a 3-day Didymos sub-phase kernel, too short to fit even
    # one interplanetary sub-chunk (7d) so HERA never reached the export.
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
    # NAIF/{VEX,VENUS-EXPRESS,ROSETTA,MPF}/kernels/spk/ are empty on the
    # operational tree; real data lives in PDS3 archives (vex-e_v-spice-6-v2.0,
    # ros-e_m_a_c-spice-6-v1.0, mpf-m-spice-6-v1.0). Adding those is a
    # follow-up extension to `PDS3_DATASETS`.
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
    # Pre-launch `europaclipper_recon_*` pattern never matched any published
    # file; real layout is `ref_trj_*_scpse.bsp` (full-mission references)
    # plus dozens of incremental `trj_*_OD\d+_v\d+.bsp` arc reconstructions.
    "EUROPACLIPPER": (r"^ref_trj_\d+_\d+_21F31_MEGA_L\d+_A\d+_LP\d+_V\d+_scpse\.bsp$",),
    "MARS2020": (r"^m2020_cruise_od\d+_v\d+\.bsp$",),
    "MSL": (r"^msl_cruise_v\d+\.bsp$",),
    "THEMIS": (),  # Earth-orbit constellation; tracked via celestrak instead
    "SMAP": (),  # Earth-orbit; celestrak
    # Newly enabled (previously skipped or accept-all). Patterns picked from a
    # fresh sweep of each NAIF/ESA `kernels/spk/` listing.
    "SIRTF": (r"^spk_191101_200134_220101_short\.bsp$",),  # Spitzer warm phase
    "CHANDRA": (r"^chandra_merged\.bsp$",),
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
    "HST": (r"^hst\.bsp$",),
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
    "XMM": (
        r"^xmm_horizons_\d+_\d+_v\d+\.bsp$",
        r"^xmm_ssm_\d+_\d+_v\d+\.bsp$",
    ),
    "LPF": (r"^lpfcmd\.bsp$",),  # LISA Pathfinder
    "HUYGENS": (
        r"^\d+AP_OPK_\d+_\d+\.BSP$",
        r"^HUYGENS_(?:COAST|ENTRY|DESCENT|LANDED)_V\d+\.BSP$",
    ),
    "COMET-INTERCEPTOR": (r"^CI_SC[AB][12]?_v\d+\.bsp$",),
    # Pre-launch trajectory study with many variant scenarios (T1/T4/ET1/HEO,
    # NorthVOI/SouthVOI/LPO, etc). Permissive: every EnVision_*.bsp under
    # this dir is a trajectory candidate; SKIP_PATTERNS already drops
    # `_struct_` and other non-trajectory files.
    "ENVISION": (r"^EnVision_[A-Za-z0-9_]+(?:_v\d+)?\.bsp$",),
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

# Top-level dirs at the mirror roots that don't contain mission trajectories.
NAIF_MISSIONS_TO_SKIP: frozenset[str] = frozenset(
    {
        # Not real probe trajectories.
        "TDRSS",  # geostationary relay fleet — celestrak
        "GNS",  # Galileo NavSat / GNSS — celestrak
        "SDU",  # Stardust sample-return capsule — PDS3 archive
        "FIDO",  # Mars-yard rover prototype (Earth surface)
        "ROCKY7",  # Mars-yard rover prototype (Earth surface)
        "MSR",  # Mars Sample Return — pre-decisional / canceled
        "MGN",  # Magellan — no SPKs published anywhere on NAIF
        # Dirs that exist at the NAIF root but whose `kernels/spk/` 404s
        # because the canonical kernels live on a PDS3/PDS4 archive (or on
        # DARTS for SELENE). Without skipping, every run logs a 404 warning
        # for these. Each entry is fetched via PDS3_DATASETS / PDS4_BUNDLES /
        # DARTS_SOURCES — keep the two lists in sync.
        "CLEMENTINE",  # no PDS dataset wired yet (clem1-l-spice-6-v1.0)
        "DART",  # PDS4
        "DS1",  # no PDS dataset wired yet (ds1-a_c-spice-6-v1.0)
        "GRAIL",  # PDS3
        "HAYABUSA",  # PDS3
        "LRO",  # PDS3
        "MESSENGER",  # PDS3
        "MGS",  # PDS3
        "MPF",  # no PDS dataset wired yet (mpf-m-spice-6-v1.0)
        "NEAR",  # PDS3
        "NEWHORIZONS",  # PDS3
        "SELENE",  # DARTS
        "SPP",  # Parker Solar Probe — no SPKs published at NAIF
        # Tree housekeeping.
        "cosmographia",
        "deprecated_kernels",
        "generic_kernels",
        "misc",
        "pds",
        "self_training",
        "toolkit",
        "toolkit_docs",
        "utilities",
    }
)
ESA_MISSIONS_TO_SKIP: frozenset[str] = frozenset(
    {
        "esa_generic",
        "GNSS",  # European GNSS constellation — celestrak
        "ExoMarsRSP",  # Russian-led, canceled 2022 (only test/sim kernels)
        # Aliases for missions already mirrored under their NAIF directory
        # name. Skipping the ESA-hyphenated form avoids downloading the same
        # SPK files twice and producing two probe_ids for one spacecraft.
        "SMART-1",  # → NAIF SMART1
        "ExoMars2016",  # → NAIF EXOMARS2016
        "MARS-EXPRESS",  # → NAIF MEX
        "GIOTTO",  # → NAIF GIOTTO (same merged file on both mirrors)
        "JWST",  # → NAIF JWST (canonical jwst_rec/jwst_pred there)
    }
)


@dataclass(frozen=True)
class FileEntry:
    name: str
    url: str
    size_bytes: int


@dataclass(frozen=True)
class MissionSource:
    server: str
    mission: str
    spk_url: str


def _list_dir(client: httpx.Client, url: str) -> list[str]:
    """List Apache-style directory hrefs at `url`, with one retry.

    NAIF and ESA both occasionally serve a 404 for a directory that succeeds on
    immediate retry (server-side cache miss / index regeneration). A single
    1-second retry catches these without masking persistently-missing dirs.
    """
    last_exc: httpx.HTTPError | None = None
    for attempt in range(2):
        try:
            resp = client.get(url, timeout=60.0)
            resp.raise_for_status()
            return [
                h
                for h in re.findall(r'href="([^"?/][^"]*)"', resp.text)
                if h not in {"..", "."}
            ]
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(1.0)
    logger.warning("listing failed for %s: %s", url, last_exc)
    return []


def _list_mirror_sources(
    client: httpx.Client, server: str, base_url: str, skip: frozenset[str]
) -> list[MissionSource]:
    out: list[MissionSource] = []
    for h in _list_dir(client, base_url + "/"):
        if not h.endswith("/") or h.startswith(("http://", "https://")):
            continue
        mission = h.rstrip("/")
        if mission in skip or mission.startswith("."):
            continue
        out.append(MissionSource(server, mission, f"{base_url}/{mission}/kernels/spk/"))
    return sorted(out, key=lambda s: s.mission)


def _list_pds3_sources(client: httpx.Client) -> list[MissionSource]:
    out: list[MissionSource] = []
    for mission, dataset in PDS3_DATASETS.items():
        dataset_url = f"{NAIF_PDS_BASE}/data/{dataset}/"
        vol_dir: str | None = None
        for href in _list_dir(client, dataset_url):
            if not href.endswith("/") or href.startswith(("http://", "https://")):
                continue
            if re.match(r"^[a-z0-9_]+_\d{4}/$", href):
                vol_dir = href.rstrip("/")
                break
        if vol_dir is None:
            logger.warning("no PDS3 volume found for %s under %s", mission, dataset_url)
            continue
        out.append(
            MissionSource(
                "NAIF-PDS3",
                mission,
                f"{NAIF_PDS_BASE}/data/{dataset}/{vol_dir}/data/spk/",
            )
        )
    return out


def _list_pds4_sources() -> list[MissionSource]:
    return [
        MissionSource(
            "NAIF-PDS4",
            mission,
            f"{NAIF_PDS_BASE}/pds4/{bundle}/spice_kernels/spk/",
        )
        for mission, bundle in PDS4_BUNDLES.items()
    ]


def _list_darts_sources() -> list[MissionSource]:
    """JAXA DARTS missions that aren't mirrored on NAIF.

    Today this is just SELENE/Kaguya — JAXA's other SPICE bundles (Hayabusa2,
    Akatsuki) are mirrored at NAIF and handled via `_list_pds4_sources`.
    """
    return [
        MissionSource("JAXA-DARTS", mission, spk_url)
        for mission, spk_url in DARTS_SOURCES.items()
    ]


def _list_mission_spks(client: httpx.Client, source: MissionSource) -> list[FileEntry]:
    """Return kept (size-known) SPK entries for `source`.

    Parallel HEAD requests via asyncio because some missions list hundreds
    of small daily kernels (e.g. Cassini, MEX).
    """
    raw = [h for h in _list_dir(client, source.spk_url) if h.lower().endswith(".bsp")]
    hrefs = [h for h in raw if not any(p.match(h) for p in SKIP_PATTERNS)]
    if source.mission in MISSION_INCLUDE:
        include_pats = tuple(
            re.compile(p, re.IGNORECASE) for p in MISSION_INCLUDE[source.mission]
        )
        if include_pats:
            pre_filter = len(hrefs)
            if source.mission in MISSION_LATEST_ONLY:
                kept: list[str] = []
                for pat in include_pats:
                    matches = sorted(h for h in hrefs if pat.match(h))
                    if matches:
                        kept.append(matches[-1])
                hrefs = kept
            else:
                hrefs = [h for h in hrefs if any(p.match(h) for p in include_pats)]
            # Catches the M01/SOLAR-ORBITER-style bug where a hardcoded version
            # number in the regex drifts past the latest published kernel and
            # silently matches zero files.
            if pre_filter and not hrefs:
                logger.warning(
                    "%s/%s: MISSION_INCLUDE matched 0 of %d candidate .bsp "
                    "files — pattern likely stale",
                    source.server,
                    source.mission,
                    pre_filter,
                )
        else:
            hrefs = []
    if not hrefs:
        return []

    async def _all_sizes() -> list[int]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as ac:
            limits = asyncio.Semaphore(16)

            async def one(href: str) -> int:
                async with limits:
                    try:
                        r = await ac.head(f"{source.spk_url}{href}")
                        r.raise_for_status()
                        return int(r.headers.get("content-length", 0))
                    except httpx.HTTPError:
                        return 0

            return await asyncio.gather(*(one(h) for h in hrefs))

    sizes = asyncio.run(_all_sizes())
    return [
        FileEntry(name=h, url=f"{source.spk_url}{h}", size_bytes=s)
        for h, s in zip(hrefs, sizes, strict=True)
    ]


def _stream_to(client: httpx.Client, url: str, dest: Path, expected_size: int) -> None:
    """Stream `url` to `dest`. Skip if size already matches `expected_size`."""
    if dest.exists() and expected_size and dest.stat().st_size == expected_size:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url, timeout=600.0) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)
    tmp.replace(dest)


def _spk_targets(path: Path) -> list[int]:
    """Unique NAIF target IDs in `path` (sorted).

    Uses spiceypy.spkobj rather than jplephem because the latter only handles
    SPK types 2/3/13; older missions (Viking, Helios, early Mariners, some
    Pioneer files) use type 1 modified-difference arrays which jplephem reads
    as "this SPK file has been damaged".
    """
    try:
        ids = spiceypy.spkobj(str(path))
    except spiceypy.exceptions.SpiceyError as exc:
        logger.warning("SPK open failed for %s: %s", path.name, exc)
        return []
    return sorted(int(naif) for naif in ids)


class ProbesDownloader(Downloader):
    """Mirror per-mission spacecraft SPK kernels (NAIF / ESA / NAIF-PDS).

    `out_dir` is forced to live under the SPICE provider tree because the
    chunk-builder furnishes generic kernels (lsk, pck, planet/satellite SPKs)
    and probe SPKs together; keeping both under `spice/kernels/` lets the
    furnish step walk one tree.
    """

    name = PROVIDERS.SPICE_PROBES

    def __init__(self, client: httpx.Client) -> None:
        # Skip the base class' `out_dir = DOWNLOAD_DIR / self.name` — we point
        # at the SPICE tree's `kernels/missions/` instead.
        self.client = client
        self.out_dir = MISSIONS_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_sources(self) -> list[MissionSource]:
        sources: list[MissionSource] = []
        sources += _list_mirror_sources(
            self.client, "NAIF", NAIF_BASE, NAIF_MISSIONS_TO_SKIP
        )
        sources += _list_mirror_sources(
            self.client, "ESA", ESA_BASE, ESA_MISSIONS_TO_SKIP
        )
        sources += _list_pds3_sources(self.client)
        sources += _list_pds4_sources()
        sources += _list_darts_sources()
        return sources

    def _process_mission(self, source: MissionSource, max_mib: float | None) -> dict:
        files = _list_mission_spks(self.client, source)
        if not files:
            return {"mission": source.mission, "skipped": False, "mib": 0.0, "files": 0}
        total = sum(f.size_bytes for f in files)
        mib = total / 1024 / 1024
        if max_mib is not None and mib > max_mib:
            logger.warning(
                "%s/%s: %.1f MiB exceeds --max-mib=%.0f, skipping",
                source.server,
                source.mission,
                mib,
                max_mib,
            )
            return {"mission": source.mission, "skipped": True, "mib": mib}

        mission_dir = self.out_dir / source.mission
        mission_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "%s/%s: %d files (%.1f MiB)",
            source.server,
            source.mission,
            len(files),
            mib,
        )

        coverage_by_naif: dict[int, list[str]] = defaultdict(list)
        file_records: list[dict] = []
        for f in files:
            local = mission_dir / f.name
            try:
                _stream_to(self.client, f.url, local, f.size_bytes)
            except httpx.HTTPError as exc:
                logger.warning("download failed for %s: %s", f.name, exc)
                continue
            targets = _spk_targets(local)
            for t in targets:
                coverage_by_naif[t].append(f.name)
            file_records.append(
                {"name": f.name, "size_bytes": local.stat().st_size, "targets": targets}
            )

        index = {
            "server": source.server,
            "mission": source.mission,
            "spk_url": source.spk_url,
            "files": file_records,
            "targets": {
                str(naif): sorted(set(names))
                for naif, names in sorted(coverage_by_naif.items())
            },
        }
        (mission_dir / "_index.json").write_text(
            json.dumps(index, indent=2, sort_keys=True)
        )
        return {
            "mission": source.mission,
            "skipped": False,
            "mib": sum(r["size_bytes"] for r in file_records) / 1024 / 1024,
            "files": len(file_records),
        }

    def download(
        self,
        limit: int | None = None,
        *,
        missions: list[str] | None = None,
        max_mib: float | None = None,
        **_: object,
    ) -> None:
        """Fetch every whitelisted SPK for every selected mission.

        `limit` is ignored (it's a record-count cap that doesn't map cleanly
        to a file-count cap — the natural cap is `max_mib`). `missions`
        restricts to specific local mission names across all servers.
        """
        selected = set(missions) if missions else None
        sources = self._resolve_sources()

        results: list[dict] = []
        for source in sources:
            if selected is not None and source.mission not in selected:
                continue
            results.append(self._process_mission(source, max_mib))

        total_files = sum(r.get("files", 0) for r in results if not r.get("skipped"))
        total_mib = sum(r.get("mib", 0.0) for r in results if not r.get("skipped"))
        logger.info(
            "ProbesDownloader: %d missions, %d files, %.1f MiB",
            sum(1 for r in results if r.get("files")),
            total_files,
            total_mib,
        )

        self._save_metadata(
            url=f"{NAIF_BASE}|{ESA_BASE}|{NAIF_PDS_BASE}",
            record_count=total_files,
            complete=False,
            missions=len([r for r in results if r.get("files")]),
            total_mib=round(total_mib, 1),
        )
