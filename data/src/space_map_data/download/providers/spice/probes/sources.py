"""Discover per-mission SPK directories across NAIF, ESA, and PDS archives.

A `MissionSource` is one mission's SPK directory on some upstream server.
Sources come from three families:

  * NAIF operational tree  — `https://naif.jpl.nasa.gov/pub/naif/<MISSION>/kernels/spk/`
  * ESA mirror             — `https://spiftp.esac.esa.int/data/SPICE/<MISSION>/kernels/spk/`
  * NAIF PDS3 / PDS4       — historical archives at `pub/naif/pds/data/<dataset>/<vol>/data/spk/`
    and `pub/naif/pds/pds4/<mission>/<bundle>/spice_kernels/spk/`. Each
    PDS dataset is curated explicitly via `PDS3_DATASETS` / `PDS4_BUNDLES`
    since their directory layout varies and they're frozen archives.
"""

import logging
import re
from dataclasses import dataclass

import httpx

from ..naif_http import list_naif_dir

logger = logging.getLogger(__name__)

NAIF_BASE = "https://naif.jpl.nasa.gov/pub/naif"
ESA_BASE = "https://spiftp.esac.esa.int/data/SPICE"
NAIF_PDS_BASE = "https://naif.jpl.nasa.gov/pub/naif/pds"
DARTS_BASE = "https://data.darts.isas.jaxa.jp/pub"

PDS3_DATASETS: dict[str, str] = {
    # The op tree only has `Dawn_ephem_2018.bsp`, which starts 2013 (no
    # cruise, no Vesta) and parks Dawn at Ceres two years early; the PDS3
    # `dawn_rec_*` series is the full launch→EOM reconstruction.
    "DAWN": "dawn-m_a-spice-6-v1.0",
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
DARTS_SOURCES: dict[str, str] = {
    "SELENE": f"{DARTS_BASE}/spice/SELENE/kernels_ORG/spk/",
}

# Top-level dirs at the NAIF mirror root that don't contain mission trajectories.
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
        "DAWN",  # PDS3
        "DS1",  # no PDS dataset wired yet (ds1-a_c-spice-6-v1.0)
        "GRAIL",  # PDS3
        "HAYABUSA",  # PDS3
        "LRO",  # PDS3
        "MESSENGER",  # PDS3
        "MGS",  # PDS3
        # Mars Pathfinder has no usable SPK (NAIF's 3-minute EDL kernel cuts
        # off ~7 km up); Sojourner never got a NAIF ID. Same archive-gap
        # bucket as most Luna/Venera, Chang'e/Yutu, Zhurong, Tianwen-1
        # lander, Beagle 2, Schiaparelli, Hope, Mangalyaan, MPL/DS2,
        # Fobos-Grunt, etc. — these come in via `probes/landing_events.py`,
        # which reads the curated `sources/position/probe-events/*.json`
        # files and emits static METHOD_LANDED records without an SPK.
        "MPF",
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
class MissionSource:
    server: str
    mission: str
    spk_url: str


def discover_mirror_sources(
    client: httpx.Client, server: str, base_url: str, skip: frozenset[str]
) -> list[MissionSource]:
    """Enumerate per-mission SPK dirs from a NAIF/ESA-style mirror root."""
    out: list[MissionSource] = []
    for h in list_naif_dir(client, base_url + "/"):
        if not h.endswith("/") or h.startswith(("http://", "https://")):
            continue
        mission = h.rstrip("/")
        if mission in skip or mission.startswith("."):
            continue
        out.append(MissionSource(server, mission, f"{base_url}/{mission}/kernels/spk/"))
    return sorted(out, key=lambda s: s.mission)


def discover_pds3_sources(client: httpx.Client) -> list[MissionSource]:
    """Resolve PDS3 archive paths.

    Each PDS3 dataset has a single volume subdir (`<dataset>_NNNN/`) whose
    name varies per dataset, so we list the dataset root and pick the first
    matching volume — no PDS3 dataset has multiple volumes for us today.
    """
    out: list[MissionSource] = []
    for mission, dataset in PDS3_DATASETS.items():
        dataset_url = f"{NAIF_PDS_BASE}/data/{dataset}/"
        vol_dir: str | None = None
        for href in list_naif_dir(client, dataset_url):
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


def discover_pds4_sources() -> list[MissionSource]:
    """PDS4 bundle paths are static — no upstream listing needed."""
    return [
        MissionSource(
            "NAIF-PDS4",
            mission,
            f"{NAIF_PDS_BASE}/pds4/{bundle}/spice_kernels/spk/",
        )
        for mission, bundle in PDS4_BUNDLES.items()
    ]


def discover_darts_sources() -> list[MissionSource]:
    """JAXA DARTS missions that aren't mirrored on NAIF.

    Today this is just SELENE/Kaguya — JAXA's other SPICE bundles (Hayabusa2,
    Akatsuki) are mirrored at NAIF and handled via `discover_pds4_sources`.
    """
    return [
        MissionSource("JAXA-DARTS", mission, spk_url)
        for mission, spk_url in DARTS_SOURCES.items()
    ]


def discover_all_sources(client: httpx.Client) -> list[MissionSource]:
    """All mission SPK directories across every supported upstream."""
    sources: list[MissionSource] = []
    sources += discover_mirror_sources(client, "NAIF", NAIF_BASE, NAIF_MISSIONS_TO_SKIP)
    sources += discover_mirror_sources(client, "ESA", ESA_BASE, ESA_MISSIONS_TO_SKIP)
    sources += discover_pds3_sources(client)
    sources += discover_pds4_sources()
    sources += discover_darts_sources()
    return sources
