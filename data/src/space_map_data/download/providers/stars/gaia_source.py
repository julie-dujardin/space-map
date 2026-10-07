"""Download the positionable stars of Gaia DR3.

`gaia_source` has 1.81 billion sources in 3,386 chunks. A star is positionable
when its parallax is more than 5 times the parallax error, which gives a
distance to better than 20%. About 192 million sources pass.

Writes, below sources/stars/gaia/gdr3/:
- gaia_source/GaiaSource_<pixels>.parquet   the kept rows of one chunk
- gaia_source/columns.json                  type, unit and description of each column
- gaia_source/_MD5SUM.txt                   the upstream chunk list
- gaia_source/metadata.json
- _citation.txt, _disclaimer.txt, _license.txt, _readme.txt

Licence: CC BY-NC 3.0 IGO, credit ESA/Gaia/DPAC.
https://www.cosmos.esa.int/web/gaia-users/license
"""

import logging

import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.providers.stars import gaia_bulk
from space_map_data.download.providers.stars.gaia_bulk import (
    BULK_URL,
    ChunkedTableDownloader,
    ChunkJob,
    fetch_note,
)

logger = logging.getLogger(__name__)

RELEASE = "gdr3"
TABLE_PATH = f"{RELEASE}/gaia_source"
CHUNK_PREFIX = "GaiaSource_"
RELEASE_NOTES = ("_citation.txt", "_disclaimer.txt", "_license.txt", "_readme.txt")

MIN_PARALLAX_OVER_ERROR = 5.0

# The dropped columns are pipeline diagnostics, correlations, fluxes that
# duplicate the magnitudes, and angles that follow from ra and dec.
COLUMNS = (
    "source_id",
    "ra",
    "ra_error",
    "dec",
    "dec_error",
    "parallax",
    "parallax_error",
    "parallax_over_error",
    "pmra",
    "pmra_error",
    "pmdec",
    "pmdec_error",
    "radial_velocity",
    "radial_velocity_error",
    "rv_nb_transits",
    "rv_expected_sig_to_noise",
    "vbroad",
    "vbroad_error",
    "phot_g_mean_mag",
    "phot_bp_mean_mag",
    "phot_rp_mean_mag",
    "phot_g_mean_flux_over_error",
    "phot_bp_mean_flux_over_error",
    "phot_rp_mean_flux_over_error",
    "phot_bp_rp_excess_factor",
    "grvs_mag",
    "grvs_mag_error",
    # Enough to apply a published astrometric quality filter later.
    "ruwe",
    "astrometric_params_solved",
    "astrometric_excess_noise",
    "astrometric_excess_noise_sig",
    "visibility_periods_used",
    "ipd_frac_multi_peak",
    "ipd_gof_harmonic_amplitude",
    "duplicated_source",
    # Inputs of the parallax zero-point correction.
    "nu_eff_used_in_astrometry",
    "pseudocolour",
    "phot_variable_flag",
    "non_single_star",
    "in_qso_candidates",
    "in_galaxy_candidates",
    "has_xp_continuous",
    "has_xp_sampled",
    "has_rvs",
    "has_epoch_photometry",
    "has_epoch_rv",
    "classprob_dsc_combmod_quasar",
    "classprob_dsc_combmod_galaxy",
    "classprob_dsc_combmod_star",
    "teff_gspphot",
    "teff_gspphot_lower",
    "teff_gspphot_upper",
    "logg_gspphot",
    "logg_gspphot_lower",
    "logg_gspphot_upper",
    "mh_gspphot",
    "mh_gspphot_lower",
    "mh_gspphot_upper",
    "distance_gspphot",
    "distance_gspphot_lower",
    "distance_gspphot_upper",
    "azero_gspphot",
    "azero_gspphot_lower",
    "azero_gspphot_upper",
    "ag_gspphot",
    "ag_gspphot_lower",
    "ag_gspphot_upper",
    "ebpminrp_gspphot",
    "ebpminrp_gspphot_lower",
    "ebpminrp_gspphot_upper",
    "libname_gspphot",
)


def select_positionable(
    table: pa.Table, job: ChunkJob
) -> tuple[pa.Table, dict[str, float]]:
    kept = table.filter(pc.field("parallax_over_error") > MIN_PARALLAX_OVER_ERROR)
    without_parallax = table["parallax"].null_count
    return kept, {
        "rows_without_parallax": without_parallax,
        "rows_below_threshold": table.num_rows - without_parallax - kept.num_rows,
        "min_parallax_over_error": MIN_PARALLAX_OVER_ERROR,
    }


class GaiaSourceDownloader(ChunkedTableDownloader):
    name = PROVIDERS.GAIA_SOURCE
    table_path = TABLE_PATH
    columns = COLUMNS
    count_keys = ("rows_without_parallax", "rows_below_threshold")
    select = staticmethod(select_positionable)

    def selection(self) -> dict[str, object]:
        return super().selection() | {
            "min_parallax_over_error": MIN_PARALLAX_OVER_ERROR
        }

    def is_current(self, stats: dict) -> bool:
        return stats["min_parallax_over_error"] == MIN_PARALLAX_OVER_ERROR

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        for note in RELEASE_NOTES:
            content = fetch_note(self.client, f"{BULK_URL}/{RELEASE}/{note}")
            (gaia_bulk.OUT_DIR / RELEASE / note).write_bytes(content)
        super().download(limit, **kwargs)
