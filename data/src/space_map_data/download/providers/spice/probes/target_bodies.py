"""Ephemerides + constants for probe-visited small bodies.

Kernels land in `spk/small-bodies/` (generic — the probe fit/benchmark
furnish them for every probe) and `pck/`. Deliberately NOT part of the
bodies downloader: that provider feeds every bsp it fetches into the
body-catalog / chebyshev extraction, and these targets must not enter it —
their npz would join the interplanetary fit-center candidate set and
invalidate every cached interplanetary fit (see
`probes.fit_centers.small_body_candidates`).

Each entry pairs with a NAIF id in `probes.small_bodies`. Targets whose
ephemeris rides inside included mission kernels (Bennu/Apophis in ORX,
Arrokoth in NEWHORIZONS, comets in DEEPIMPACT/GIOTTO/VEGA, Eros in
sb441-n373) need no entry here.
"""

import logging
from collections.abc import Mapping
from pathlib import Path

import httpx
import spiceypy

from space_map_data.constants import body_literature

from ..naif_http import stream_to
from .layout import MISSIONS_DIR

logger = logging.getLogger(__name__)

_KERNELS_ROOT = MISSIONS_DIR.parent
SMALL_BODY_SPK_DIR = _KERNELS_ROOT / "spk" / "small-bodies"
PCK_DIR = _KERNELS_ROOT / "pck"

_NAIF = "https://naif.jpl.nasa.gov/pub/naif"

TARGET_SPK_URLS: dict[str, str] = {
    # Ryugu — Hayabusa2's mission set has no Ryugu segments at all.
    "2162173_ryugu_v02.bsp": f"{_NAIF}/pds/pds4/hyb2/hyb2_spice/spice_kernels/spk/2162173_ryugu_v02.bsp",
    # Itokawa — Hayabusa's SPKs are Itokawa-relative; without this the
    # heliocentric chain fails entirely.
    "itokawa_1989_2010.bsp": f"{_NAIF}/pds/data/hay-a-spice-6-v1.0/haysp_1000/data/spk/itokawa_1989_2010.bsp",
    # 67P — Rosetta itself is HORIZONS-SYNTH; the comet needs the ESOC orbit.
    "CORB_DV_257_03___T19_00345.BSP": f"{_NAIF}/ROSETTA/kernels/spk/CORB_DV_257_03___T19_00345.BSP",
    # Didymos system for DART (+ Hera once its kernels extend past 2025-07).
    "didymos_barycenter_s205_v01.bsp": f"{_NAIF}/pds/pds4/dart/dart_spice/spice_kernels/spk/didymos_barycenter_s205_v01.bsp",
    "didymos_system_s501_v01.bsp": f"{_NAIF}/pds/pds4/dart/dart_spice/spice_kernels/spk/didymos_system_s501_v01.bsp",
    # Lucy targets (the spacecraft kernels carry only target-relative arcs).
    "lcy_100101_500216_250414_leuc_v1.bsp": f"{_NAIF}/pds/pds4/lucy/lucy_spice/spice_kernels/spk/lcy_100101_500216_250414_leuc_v1.bsp",
    "lcy_100101_500216_250414_orus_v1.bsp": f"{_NAIF}/pds/pds4/lucy/lucy_spice/spice_kernels/spk/lcy_100101_500216_250414_orus_v1.bsp",
    "lcy_170101_500824_170626_pmbi_v1.bsp": f"{_NAIF}/pds/pds4/lucy/lucy_spice/spice_kernels/spk/lcy_170101_500824_170626_pmbi_v1.bsp",
    "lcy_200101_500103_231117_donj_v1.bsp": f"{_NAIF}/pds/pds4/lucy/lucy_spice/spice_kernels/spk/lcy_200101_500103_231117_donj_v1.bsp",
    "lcy_200101_500103_231117_eury_v2.bsp": f"{_NAIF}/pds/pds4/lucy/lucy_spice/spice_kernels/spk/lcy_200101_500103_231117_eury_v2.bsp",
    "lcy_200101_500115_231117_poly_v2.bsp": f"{_NAIF}/pds/pds4/lucy/lucy_spice/spice_kernels/spk/lcy_200101_500115_231117_poly_v2.bsp",
    # Mathilde — NEAR flyby; absent from sb441.
    "math9749.bsp": f"{_NAIF}/pds/data/near-a-spice-6-v1.0/nearsp_1000/data/spk/math9749.bsp",
}

# Dinkinesh rides in a Lucy encounter kernel that also embeds the Lucy
# spacecraft; furnishing that as a generic would override the mission
# kernels (generics furnish last). Download it to a temp name and spksub
# only the Dinkinesh-wrt-Sun segments.
_DINKINESH_SRC_URL = f"{_NAIF}/pds/pds4/lucy/lucy_spice/spice_kernels/spk/lcy_230815_240201_240101_dinkinesh_rec_v2.bsp"
_DINKINESH_SUBSET = "dinkinesh_20152830_sub.bsp"
_DINKINESH_NAIF = 20152830

# Frame kernels + orientation constants the mission SPKs need at evaluation
# time: Hayabusa's SPKs are in ITOKAWA_FIXED / HAYABUSA_HP, Hayabusa2's
# proximity hpk in HYB2_HP. Placed in pck/ where the probe pipeline's
# generic collection picks up .tf/.tpc.
PCK_URLS: dict[str, str] = {
    "itokawa_fixed.tf": f"{_NAIF}/pds/data/hay-a-spice-6-v1.0/haysp_1000/data/fk/itokawa_fixed.tf",
    "hayabusa_hp.tf": f"{_NAIF}/pds/data/hay-a-spice-6-v1.0/haysp_1000/data/fk/hayabusa_hp.tf",
    "itokawa_gaskell_n3.tpc": f"{_NAIF}/pds/data/hay-a-spice-6-v1.0/haysp_1000/data/pck/itokawa_gaskell_n3.tpc",
    "hyb2_hp_v01.tf": f"{_NAIF}/pds/pds4/hyb2/hyb2_spice/spice_kernels/fk/hyb2_hp_v01.tf",
}

GM_PATCH_NAME = "smallbody_gm_patch.tpc"
# A file of its own, so that the kernel name of a GM tells it is the GM of a
# whole binary system.
GM_SYSTEMS_NAME = "smallbody_gm_systems.tpc"


def _gm_kernel(intro: str, gms: Mapping[int, body_literature.Gm]) -> str:
    """A text kernel of ``gms``, with the URL of the paper of each in its
    comments: a title can hold non-ASCII ("Pätzold"), a text kernel is ASCII."""
    ids = {naif_id: gm.spice_id or naif_id for naif_id, gm in gms.items()}
    cited = "\n".join(
        f"  BODY{ids[naif_id]}: {body_literature.REFERENCES[gm.reference].url}"
        for naif_id, gm in gms.items()
    )
    data = "\n".join(
        f"   BODY{ids[naif_id]}_GM = ( {gm.gm} )" for naif_id, gm in gms.items()
    )
    return f"KPL/PCK\n\n{intro}\n\n{cited}\n\n\\begindata\n\n{data}\n\n\\begintext\n"


GM_PATCH_CONTENT = _gm_kernel(
    "Measured GM values for probe-visited small bodies absent from every other\n"
    "PCK in this pool (gm_de440, Gravity.tpc, mission PCKs). The probe export's\n"
    "`small-bodies` zone uses mu for Kepler eligibility and period estimates.",
    body_literature.GMS,
)

GM_SYSTEMS_CONTENT = _gm_kernel(
    "GM values of probe-visited binary systems absent from every other PCK in\n"
    "this pool, from the orbit of the satellite. Each is the GM of the primary\n"
    "and the satellite together.",
    body_literature.SYSTEM_GMS,
)

# A file of its own, so that the kernel name of a GM tells it is an estimate.
GM_ESTIMATES_NAME = "smallbody_gm_estimates.tpc"

GM_ESTIMATES_CONTENT = """KPL/PCK

Estimated GM values (volume x assumed density) for probe-visited small
bodies absent from every other PCK in this pool. They are flyby targets with
Chebyshev fits, so mu only needs the right order of magnitude.

  Apophis, Halley, Tempel 1, Arrokoth, Dinkinesh, Donaldjohanson,
  Eurybates, Polymele, Leucus, Orus.

\\begindata

   BODY2099942_GM   = ( 4.07E-9 )
   BODY1000036_GM   = ( 1.5E-5 )
   BODY1000093_GM   = ( 4.8E-6 )
   BODY2486958_GM   = ( 5.0E-5 )
   BODY20152830_GM  = ( 3.3E-8 )
   BODY20052246_GM  = ( 4.7E-6 )
   BODY20003548_GM  = ( 1.0E-2 )
   BODY20015094_GM  = ( 3.3E-4 )
   BODY20011351_GM  = ( 1.3E-3 )
   BODY20021900_GM  = ( 4.7E-3 )

\\begintext
"""


def _fetch(client: httpx.Client, url: str, local: Path) -> None:
    """`stream_to` with a HEAD-based skip — these URLs are version-pinned
    frozen archives, so same-size means same-content."""
    expected = 0
    if local.exists():
        head = client.head(url)
        head.raise_for_status()
        expected = int(head.headers.get("content-length", 0))
    stream_to(client, url, local, expected)


def _subset_dinkinesh(client: httpx.Client) -> None:
    dst = SMALL_BODY_SPK_DIR / _DINKINESH_SUBSET
    if dst.exists():
        return
    tmp = SMALL_BODY_SPK_DIR / (_DINKINESH_SUBSET + ".src")
    stream_to(client, _DINKINESH_SRC_URL, tmp)
    hs = spiceypy.dafopr(str(tmp))
    hd = spiceypy.spkopn(str(dst), "dinkinesh subset (20152830 wrt 10)", 0)
    n = 0
    try:
        spiceypy.dafbfs(hs)
        while spiceypy.daffna():
            summ = spiceypy.dafgs(5)
            dc, ic = spiceypy.dafus(summ, 2, 6)
            if int(ic[0]) == _DINKINESH_NAIF and int(ic[1]) == 10:
                spiceypy.spksub(hs, summ, spiceypy.dafgn(), dc[0], dc[1], hd)
                n += 1
    finally:
        spiceypy.spkcls(hd)
        spiceypy.dafcls(hs)
        tmp.unlink(missing_ok=True)
    if n == 0:
        dst.unlink(missing_ok=True)
        logger.warning("dinkinesh subset: no %d segments found", _DINKINESH_NAIF)
    else:
        logger.info("dinkinesh subset: %d segments -> %s", n, dst.name)


def download_target_bodies(client: httpx.Client) -> tuple[int, float]:
    """Fetch every small-body target kernel + write the GM patches.

    Returns `(n_files, total_mib)` over everything now on disk.
    """
    SMALL_BODY_SPK_DIR.mkdir(parents=True, exist_ok=True)
    PCK_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, url in TARGET_SPK_URLS.items():
        local = SMALL_BODY_SPK_DIR / name
        try:
            _fetch(client, url, local)
        except httpx.HTTPError as exc:
            logger.warning("target-body download failed for %s: %s", name, exc)
            continue
        paths.append(local)
    try:
        _subset_dinkinesh(client)
        if (SMALL_BODY_SPK_DIR / _DINKINESH_SUBSET).exists():
            paths.append(SMALL_BODY_SPK_DIR / _DINKINESH_SUBSET)
    except (httpx.HTTPError, spiceypy.exceptions.SpiceyError) as exc:
        logger.warning("dinkinesh subset failed: %s", exc)
    for name, url in PCK_URLS.items():
        local = PCK_DIR / name
        try:
            _fetch(client, url, local)
        except httpx.HTTPError as exc:
            logger.warning("target-body PCK download failed for %s: %s", name, exc)
            continue
        paths.append(local)
    for name, content in (
        (GM_PATCH_NAME, GM_PATCH_CONTENT),
        (GM_SYSTEMS_NAME, GM_SYSTEMS_CONTENT),
        (GM_ESTIMATES_NAME, GM_ESTIMATES_CONTENT),
    ):
        gm_path = PCK_DIR / name
        if not gm_path.exists() or gm_path.read_text() != content:
            gm_path.write_text(content)
        paths.append(gm_path)
    total_mib = sum(p.stat().st_size for p in paths) / 1024 / 1024
    return len(paths), total_mib
