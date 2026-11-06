"""The published tables the model reads, as stored under `sources/galaxy-model/`, and
the Magellanic Clouds of the Local Volume Database."""

import csv
import re
from dataclasses import dataclass

import numpy as np

from space_map_data.galaxy.geometry import R0
from space_map_data.utils.paths import SOURCES_DIR

GALAXY_MODEL_DIR = SOURCES_DIR / "galaxy-model"
LIAN_DIR = GALAXY_MODEL_DIR / "lian-2024"
HARRIS_FILE = GALAXY_MODEL_DIR / "harris-2010" / "mwgc.dat"
LVDB_FILE = SOURCES_DIR / "catalogues" / "galaxies" / "lvdb" / "comb_all.csv"

LIAN_R0 = 8200.0
LIAN_BIN_PC = 1000.0
# Lian's age bins, in Gyr.
LIAN_AGES = ((0, 2), (2, 4), (4, 6), (6, 8), (8, 10), (10, 12))


@dataclass(frozen=True)
class LianProfiles:
    """Lian et al. 2024: face-on surface brightness in 1 kpc rings to 17 kpc, scaled to
    R0 = 8,277 pc with the light of each ring kept. L_sun per pc^2 of each band."""

    # The middle of each ring (pc).
    radius: np.ndarray
    # Ring edges (pc).
    edges: np.ndarray
    bolometric: np.ndarray
    r: np.ndarray
    h: np.ndarray
    # Bolometric, by age bin, shape (rings, 6).
    ages: np.ndarray


def lian_profiles() -> LianProfiles:
    scale = R0 / LIAN_R0
    multiband = np.loadtxt(LIAN_DIR / "mw-sbp-multiband.txt", skiprows=1)
    by_age = np.loadtxt(LIAN_DIR / "mw-sbp.txt", skiprows=1)
    # The multiband file holds L_sun per kpc^2; the age file log10 L_sun per pc^2,
    # with -99 for no stars.
    per_pc2 = multiband[:, (0, 2, 4)] / 1e6 / scale**2
    ages = np.where(by_age[:, :6] > -90, 10.0 ** by_age[:, :6], 0.0) / scale**2
    rings = len(multiband)
    edges = np.arange(rings + 1) * LIAN_BIN_PC * scale
    return LianProfiles(
        0.5 * (edges[1:] + edges[:-1]),
        edges,
        per_pc2[:, 0],
        per_pc2[:, 1],
        per_pc2[:, 2],
        ages,
    )


@dataclass(frozen=True)
class Clusters:
    """Harris 1996 (2010 edition), Part II; NaN where the catalogue has no value."""

    metallicity: np.ndarray
    reddening: np.ndarray
    absolute_v: np.ndarray
    b_v: np.ndarray


def harris_clusters() -> Clusters:
    lines = HARRIS_FILE.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if "Part II" in line)
    header = next(
        i
        for i in range(start, len(lines))
        if "[Fe/H]" in lines[i] and "B-V" in lines[i]
    )
    full = next(i for i in range(header + 1, len(lines)) if lines[i].strip())
    # The first row has every field; their right edges place the fields of the rest.
    ends = [m.end() for m in re.finditer(r"\S+", lines[full])][1:]
    names = ("NGC", "ID", "feh", "wt", "ebv", "vhb", "dm", "vt", "mv", "ub", "bv")
    keys = names[2:]
    edges = ends[1 : 1 + len(keys)]

    def field(line: str, end: int) -> float:
        text = line[max(end - 6, 0) : end].strip()
        try:
            return float(text)
        except ValueError:
            return np.nan

    rows = []
    for line in lines[full:]:
        if not line.strip():
            continue
        if line.startswith("___"):
            break
        rows.append([field(line, end) for end in edges])
    table = np.array(rows)
    column = {key: table[:, i] for i, key in enumerate(keys)}
    return Clusters(column["feh"], column["ebv"], column["mv"], column["bv"])


@dataclass(frozen=True)
class CloudRow:
    ra_deg: float
    dec_deg: float
    distance_pc: float
    absolute_v: float
    half_light_pc: float
    reference_distance: str


def lvdb_cloud(key: str) -> CloudRow:
    """A Magellanic Cloud as the Local Volume Database holds it."""
    with LVDB_FILE.open(newline="") as handle:
        row = next(r for r in csv.DictReader(handle) if r["key"] == key)
    return CloudRow(
        float(row["ra"]),
        float(row["dec"]),
        float(row["distance"]) * 1000.0,
        float(row["M_V"]),
        float(row["rhalf_sph_physical"]),
        row["ref_distance"],
    )
