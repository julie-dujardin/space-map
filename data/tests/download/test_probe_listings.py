"""Per-mission SPK selection: include patterns, latest-only, metakernel gating."""

import httpx
import pytest

from space_map_data.download.providers.spice.probes import listings
from space_map_data.download.providers.spice.probes.listings import (
    apply_mission_filter,
    list_mission_spks,
    metakernel_spks,
)
from space_map_data.download.providers.spice.probes.mission_patterns import (
    MISSION_INCLUDE,
    MISSION_LATEST_ONLY,
)
from space_map_data.download.providers.spice.probes.sources import MissionSource

SPK_URL = "https://naif.example/pub/naif/EXOMARS2016/kernels/spk/"
MK_URL = "https://naif.example/pub/naif/EXOMARS2016/kernels/mk/em16_ops.tm"

TGO_LISTING = [
    "em16_tgo_mlt_20171205_20230115_v01.bsp",
    "em16_tgo_fcp_028_01_20160314_20170115_v01.bsp",
    "em16_tgo_cog_457_01_20260430_20261010_v01.bsp",
    "em16_tgo_fsp_048_01_20160314_20181231_v02.bsp",
    "em16_tgo_fsp_048_01_20160314_20181231_v03.bsp",
    "em16_tgo_fsp_049_01_20160314_20181231_v01.bsp",
    "em16_tgo_fsp_065_01_20181120_20190429_v03.bsp",
    "em16_tgo_fsp_457_01_20260526_20261107_v01.bsp",
]

EM16_OPS = r"""KPL/MK

   The kernels below are examples only:
      '$KERNELS/spk/em16_tgo_fsp_049_01_20160314_20181231_v01.bsp'

   \begindata

     PATH_VALUES       = ( '..' )
     PATH_SYMBOLS      = ( 'KERNELS' )
     KERNELS_TO_LOAD   = (
                           '$KERNELS/spk/em16_tgo_cog_457_01_20260430_20261010_v01.bsp'
                           '$KERNELS/spk/em16_tgo_fsp_048_01_20160314_20181231_v03.bsp'
                           '$KERNELS/spk/em16_tgo_fsp_065_01_20181120_20190429_v03.bsp'
                           '$KERNELS/spk/em16_tgo_fsp_457_01_20260526_20261107_v01.bsp'
                           '$KERNELS/spk/de432s.bsp'
                         )

   \begintext

   '$KERNELS/spk/em16_tgo_mlt_20171205_20230115_v01.bsp' is not loaded.
"""


def _listing_html(names: list[str]) -> str:
    return "".join(f'<a href="{n}">{n}</a>\n' for n in names)


def _client(mk_status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == SPK_URL:
            return httpx.Response(200, text=_listing_html(TGO_LISTING))
        if url == MK_URL:
            return httpx.Response(mk_status, text=EM16_OPS)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _no_head_requests(monkeypatch):
    monkeypatch.setattr(listings, "head_sizes_async", lambda urls: [1] * len(urls))


def test_metakernel_spks_reads_only_data_sections():
    assert metakernel_spks(EM16_OPS) == {
        "em16_tgo_cog_457_01_20260430_20261010_v01.bsp",
        "em16_tgo_fsp_048_01_20160314_20181231_v03.bsp",
        "em16_tgo_fsp_065_01_20181120_20190429_v03.bsp",
        "em16_tgo_fsp_457_01_20260526_20261107_v01.bsp",
        "de432s.bsp",
    }


def test_tgo_keeps_only_the_metakernel_fsp_chain():
    source = MissionSource("NAIF", "EXOMARS2016", SPK_URL)
    files = list_mission_spks(_client(), source)
    assert [f.name for f in files.trajectory] == [
        "em16_tgo_fsp_048_01_20160314_20181231_v03.bsp",
        "em16_tgo_fsp_065_01_20181120_20190429_v03.bsp",
        "em16_tgo_fsp_457_01_20260526_20261107_v01.bsp",
    ]
    assert files.landed == []


def test_unreachable_metakernel_selects_nothing():
    # Falling back to the patterns alone would pull every weekly fsp issue.
    source = MissionSource("NAIF", "EXOMARS2016", SPK_URL)
    files = list_mission_spks(_client(mk_status=404), source)
    assert files.trajectory == [] and files.landed == []


def _select(mission: str, hrefs: list[str]) -> list[str]:
    return apply_mission_filter(
        hrefs, MISSION_INCLUDE, mission, mission in MISSION_LATEST_ONLY
    )


def test_euclid_takes_newest_iteration_not_launch_predict():
    hrefs = [
        "euclid_flp_00080_20230701_20311005_v01.bsp",
        "euclid_flp_00081_20230701_20311005_v01.bsp",
        "euclid_flp_20230701_20311012_v02.bsp",
    ]
    assert _select("EUCLID", hrefs) == ["euclid_flp_00081_20230701_20311005_v01.bsp"]


def test_solar_orbiter_takes_newest_long_term_issue():
    hrefs = [
        "solo_ANC_soc-orbit_20200210-20301117_L000_V0_00000_V01.bsp",
        "solo_ANC_soc-orbit_20200210-20301120_L025_V1_00534_V04.bsp",
        "solo_ANC_soc-orbit_20200210-20301120_L026_V1_00554_V01.bsp",
        "solo_ANC_soc-orbit-stp_20200210-20301120_431_V1_00582_V01.bsp",
    ]
    assert _select("SOLAR-ORBITER", hrefs) == [
        "solo_ANC_soc-orbit_20200210-20301120_L026_V1_00554_V01.bsp"
    ]


def test_europa_clipper_takes_nav_deliveries_but_not_maneuver_designs():
    kept = [
        "ref_trj_241014_340903_21F31_MEGA_L241014_A300411_LP05_V7_scpse.bsp",
        "trj_241014-241103-dco2410142047-postLaunch-OD001-v1.bsp",
        "trj_250318-251018-dco2506180204-cruise008-final-OD064-v1.bsp",
        "trj_260709-260820-dco2609030539-cruise016-reconstruct-OD091-v1.bsp",
        "trj_260808-270123-dco2609230549-cruise019-predict-OD092-v1.bsp",
    ]
    dropped = [
        "trj_241018-250101-dco2410261931-TCM1-PRELIM-v1.bsp",
        "trj_250104-250311-dco2502082037-MGAAPR1-FINAL-OD039-v1.bsp",
        "trj_250104-250401-dco2502191029-MFB-FINAL-PREDICT-OD041-v1.bsp",
        "trj_260401-261230-dco2607291439-EGATRG2-FINAL-OD089-v1.bsp",
        "trj_260401-261230-dco2607291439-EGATRG2-FINAL-OD089-v1-noburn.bsp",
        "trj_250318-250611-dco2506112124-OVRO-all-tests-reconstruction-OD063-v1.bsp",
    ]
    assert _select("EUROPACLIPPER", kept + dropped) == kept
