"""Resolve and download SPICE kernels from NAIF."""

import logging
import re
from pathlib import Path

import httpx
from tqdm import tqdm

logger = logging.getLogger(__name__)

NAIF_BASE_URL = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels"

# SPICE kernel types:
#   .bsp (SPK) — ephemeris: positions & velocities of bodies over time
#   .tpc (PCK) — physical constants: body radii, GM values, pole orientation & spin
#   .tls (LSK) — leapseconds: UTC ↔ ephemeris time conversion

# Fixed kernels that don't need version discovery. Values are paths relative
# to `NAIF_BASE_URL`, or fully-qualified URLs (if hosted elsewhere, like JPL's
# SSD site for the SB441 asteroid kernel).
_FIXED_KERNELS: dict[str, str] = {
    "de440.bsp": "spk/planets/de440.bsp",  # planet + Moon ephemerides
    # Full DE441 small-body perturber set: 343 main-belt asteroids + 30 KBOs,
    # covering JD -1200525.5 to 5008242.5 (year -8001 to +9000). Documented in
    # IOM 392R-21-005 (D. Farnocchia, 2021). Only hosted at JPL's SSD (not in
    # NAIF's generic_kernels tree); ~14 GB on disk. The "n16" variant (16
    # bodies, 616 MB) is the smaller alternative if disk is tight — `spkobj`
    # discovers whatever's in the file, so the rest of the pipeline auto-adapts.
    "sb441-n373.bsp": "https://ssd.jpl.nasa.gov/ftp/eph/small_bodies/asteroids_de441/sb441-n373.bsp",
    # Gravity harmonics J2/J3/J4 for the major planets — used to compute analytic
    # secular precession rates for moons that don't get full Chebyshev coverage.
    "Gravity.tpc": "pck/Gravity.tpc",
}

# Kernels where we pick the latest version from a directory listing.
# Each entry: (directory_path, regex with named groups "name" and "ver")
_LATEST_VERSION_KERNELS: list[tuple[str, str]] = [
    ("lsk", r"^(?P<name>naif(?P<ver>\d+)\.tls)$"),  # leapseconds
    ("pck", r"^(?P<name>pck(?P<ver>\d+)\.tpc)$"),  # pole/rotation constants
    ("pck", r"^(?P<name>gm_de(?P<ver>\d+)\.tpc)$"),  # GM values
]

# Satellite SPK prefixes — we download ALL .bsp files for each prefix
# to get maximum moon coverage. SPICE merges coverage across loaded kernels.
_SATELLITE_PREFIXES = ("mar", "jup", "sat", "ura", "nep", "plu")


def resolve_kernels(client: httpx.Client) -> dict[str, str]:
    """Build the full kernel map: fixed entries plus dynamic NAIF discovery."""
    logger.info("Resolving kernel list from NAIF...")
    resolved = dict(_FIXED_KERNELS)
    resolved.update(_resolve_dynamic(client))
    return resolved


def download_kernels(
    client: httpx.Client, out_dir: Path, kernels: dict[str, str]
) -> list[Path]:
    """Download `kernels` under `out_dir/kernels/<subdir>/<filename>`.

    Skips files that already exist with the expected size. Subdirs mirror
    NAIF's `generic_kernels/` layout (`lsk/`, `pck/`, `spk/planets/`, ...).
    """
    kernel_dir = out_dir / "kernels"
    kernel_dir.mkdir(exist_ok=True)
    paths: list[Path] = []

    for filename, url_path in tqdm(kernels.items(), desc="SPICE kernels", unit="file"):
        subdir = _local_subdir(filename, url_path)
        local_dir = kernel_dir / subdir if subdir else kernel_dir
        local_dir.mkdir(parents=True, exist_ok=True)
        local = local_dir / filename
        url = (
            url_path
            if url_path.startswith("http://") or url_path.startswith("https://")
            else f"{NAIF_BASE_URL}/{url_path}"
        )

        if local.exists():
            head = client.head(url)
            head.raise_for_status()
            expected_size = int(head.headers.get("content-length", 0))
            if expected_size and local.stat().st_size == expected_size:
                logger.debug("Kernel %s already downloaded", filename)
                paths.append(local)
                continue

        logger.info("Downloading %s ...", filename)
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with local.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)
        logger.info("  -> %s (%.1f MB)", local.name, local.stat().st_size / 1e6)
        paths.append(local)

    return paths


def _local_subdir(filename: str, url_path: str) -> str:
    """Pick the on-disk subdir under `kernels/` for a generic kernel.

    Mirrors NAIF's own `generic_kernels/` layout: `lsk/`, `pck/`,
    `spk/planets/`, `spk/satellites/`, `spk/asteroids/`. Mission-trajectory
    kernels are out of scope here — they go through the per-mission
    downloader and live in `missions/<MISSION>/`.
    """
    if url_path.startswith("http://") or url_path.startswith("https://"):
        # Full URL — fall back to filename heuristic for the kernels we serve
        # ourselves (SB441 asteroid kernel is the only one today).
        if filename.lower().startswith("sb441"):
            return "spk/asteroids"
        return ""
    head, _, _ = url_path.rpartition("/")
    return head


def _resolve_dynamic(client: httpx.Client) -> dict[str, str]:
    """Fetch NAIF directory listings and resolve all dynamic kernels."""
    resolved: dict[str, str] = {}

    # Latest-version kernels (lsk, pck)
    by_dir: dict[str, list[re.Pattern]] = {}
    for dir_path, pattern in _LATEST_VERSION_KERNELS:
        by_dir.setdefault(dir_path, []).append(re.compile(pattern))

    for dir_path, patterns in by_dir.items():
        hrefs = _list_directory(client, dir_path)
        for pattern in patterns:
            best_ver = -1
            best_name = ""
            for href in hrefs:
                m = pattern.match(href)
                if m:
                    ver = int(m.group("ver"))
                    if ver > best_ver:
                        best_ver = ver
                        best_name = m.group("name")
            if best_name:
                resolved[best_name] = f"{dir_path}/{best_name}"
                logger.info("Resolved kernel: %s", best_name)
            else:
                logger.warning("No match for %s in %s/", pattern.pattern, dir_path)

    # Satellite kernels: all .bsp files for each planet prefix
    hrefs = _list_directory(client, "spk/satellites")
    for prefix in _SATELLITE_PREFIXES:
        count = 0
        for href in hrefs:
            if href.startswith(prefix) and href.endswith(".bsp"):
                resolved[href] = f"spk/satellites/{href}"
                count += 1
        logger.info("Resolved %d satellite kernels for %s*", count, prefix)

    return resolved


def _list_directory(client: httpx.Client, dir_path: str) -> list[str]:
    """Fetch a NAIF directory listing and return all href values."""
    url = f"{NAIF_BASE_URL}/{dir_path}/"
    resp = client.get(url)
    resp.raise_for_status()
    return re.findall(r'href="([^"]+)"', resp.text)
