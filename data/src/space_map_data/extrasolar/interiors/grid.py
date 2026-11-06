"""The MIST v2.5 tracks as tables over the HR diagram, one for each [Fe/H].

The model points are binned on a grid of (log Teff, log L). For each [Fe/H]
the tables hold, in each cell, the sum of these over the points at or past
the cell on both axes: the count, the prior weight, the weight times each of
QUANTITIES and its square, the weight of each stage, and the weight at 0 of
each of AT_ZERO. So the sums over any box of cells cost four reads. The sums run from the hot, bright corner, where
the points are sparse, so that the sums of a sparse box stay small. The prior
is the Kroupa (2001) initial mass function times the time that the point
stands for, up to AGE_LIMIT, and its sum over each [Fe/H] is 1.

The tracks run from the zero-age main sequence to the start of the
thermally pulsing AGB. Between two grid masses, MASS_STEPS - 1 tracks are
interpolated at equal EEP, linearly in log mass, so the points fill the
diagram between the tracks. Where one of the two is fully convective and the
other is not, the envelope and the core come from the nearer track.

MIST writes 0 for every `conv_env_*` column when a star has no outer
convection zone. On some EEPs its outer zone is a zone deep inside the star,
often of no thickness. A point whose outer zone has its top below
SURFACE_ZONE_TOP has no surface zone, and the tables put its envelope base at
the surface. A fully convective point has its envelope base at the centre and
its whole mass in its convective core.

`ready` checks the stellar-models download against its manifest and its
download record. It builds the tables in a directory named by a hash of
their inputs: the URL, size and SHA-256 of each tarball and the build
parameters. A download of the same bytes again keeps the directory. The
directory moves into place when it is whole, so it never changes, and two
versions do not write over each other. The process that calls `ready` holds
a shared lease on its directory until it exits. `ready` deletes the other
directories of the grid that no process holds.
`load` maps the tables read-only, so the export's workers share one copy.
"""

import fcntl
import hashlib
import json
import logging
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import IO

import numpy as np

from space_map_data.extrasolar.interiors.schema import GROUP, MIST
from space_map_data.utils.paths import CACHE_DIR, SOURCES_CATALOGUES_DIR

logger = logging.getLogger(__name__)

TRACKS_DIR = SOURCES_CATALOGUES_DIR / GROUP / MIST.key
# The download record of the catalogue downloader, beside the tarballs.
DOWNLOAD_RECORD = "metadata.json"
TABLES_ROOT = CACHE_DIR / "interiors"
# Raise when the tables change, so that `ready` builds them again.
VERSION = 3

# Primary EEPs (Dotter 2016, Table 2).
ZAMS, TAMS, RGB_TIP, TACHEB, TPAGB = 202, 454, 605, 707, 808
STAGES = (
    "main_sequence",
    # The subgiants too: no EEP divides them from the giant branch.
    "red_giant_branch",
    "core_helium_burning",
    "asymptotic_giant_branch",
)
# The first EEP of each stage, then the end of the last.
STAGE_EEPS = (ZAMS, TAMS, RGB_TIP, TACHEB, TPAGB + 1)
AGE_LIMIT = 13.8e9
MASS_STEPS = 4

LOG_TEFF_AXIS = (3.30, 4.80, 0.005)
LOG_L_AXIS = (-4.0, 7.0, 0.02)

# The track columns that the tables read.
TRACK_COLUMNS = (
    "star_age",
    "star_mass",
    "log_L",
    "log_Teff",
    "log_R",
    "he_core_mass",
    "mass_conv_core",
    "center_h1",
    "center_he4",
    "log_center_T",
    "log_center_Rho",
    "conv_env_bot_mass",
    "conv_env_bot_radius",
    "conv_env_top_radius",
)
# The lowest top of a surface convection zone, as a fraction of the radius.
SURFACE_ZONE_TOP = 0.9
# Masses in solar masses, the radius in log R☉, the envelope base as fractions
# of the star's radius and mass, the centre in log K and log g/cm³, the centre
# abundances as mass fractions.
QUANTITIES = (
    "mass",
    "log_radius",
    "envelope_base_radius",
    "envelope_base_mass",
    "log_centre_temperature",
    "log_centre_density",
    "convective_core_mass",
    "helium_core_mass",
    "centre_x",
    "centre_y",
)
# The quantities that are 0 for a fully convective point only.
AT_ZERO = ("envelope_base_radius", "envelope_base_mass")
NO_STAGE = 255
# The channels of the sums.
COUNT, WEIGHT = 0, 1
FIRST = slice(2, 2 + len(QUANTITIES))
SECOND = slice(FIRST.stop, FIRST.stop + len(QUANTITIES))
STAGE = slice(SECOND.stop, SECOND.stop + len(STAGES))
ZERO = slice(STAGE.stop, STAGE.stop + len(AT_ZERO))
CHANNELS = ZERO.stop


def _axis(axis: tuple[float, float, float]) -> np.ndarray:
    low, high, step = axis
    return low + step * np.arange(round((high - low) / step) + 1)


@dataclass(frozen=True)
class Tracks:
    """The tracks of one [Fe/H]: TRACK_COLUMNS at each EEP from ZAMS to
    TPAGB, NaN past the end of a track. `star_age` is log10 of years."""

    feh: float
    masses: np.ndarray
    values: np.ndarray


def read_tarball(path: Path) -> Tracks:
    """The tracks of one EEP tarball."""
    masses, rows, feh = [], [], None
    with tarfile.open(path, "r:xz") as tar:
        for member in tar:
            if not member.name.endswith(".track.eep"):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            mass, track_feh, values = _read_track(handle.read().decode())
            if feh is not None and track_feh != feh:
                raise ValueError(f"{path.name}: tracks of [Fe/H] {feh} and {track_feh}")
            feh = track_feh
            masses.append(mass)
            rows.append(values)
    if feh is None:
        raise ValueError(f"{path.name}: no tracks")
    order = np.argsort(masses)
    return Tracks(feh, np.array(masses)[order], np.stack(rows)[order])


def _read_track(text: str) -> tuple[float, float, np.ndarray]:
    """Initial mass, [Fe/H] and TRACK_COLUMNS of one `.track.eep` file."""
    lines = text.splitlines()
    header = [line for line in lines if line.startswith("#")]

    def below(label: str) -> list[str]:
        """The values in the header line under the one that holds `label`."""
        at = next(i for i, line in enumerate(header) if label in line)
        return header[at + 1].split()

    feh = float(below("[Fe/H]")[3])
    mass = float(below("initial_mass")[1])
    first_eep = int(next(h for h in header if h.startswith("# EEPs:")).split()[2])
    names = header[-1].lstrip("#").split()
    body = " ".join(line for line in lines if line and not line.startswith("#"))
    data = np.array(body.split(), np.float64).reshape(-1, len(names))
    columns = data[:, [names.index(name) for name in TRACK_COLUMNS]]
    columns[:, 0] = np.log10(columns[:, 0])
    column = {name: columns[:, i] for i, name in enumerate(TRACK_COLUMNS)}
    radius = 10 ** column["log_R"]
    no_zone = column["conv_env_top_radius"] < SURFACE_ZONE_TOP * radius
    column["conv_env_bot_mass"][no_zone] = column["star_mass"][no_zone]
    column["conv_env_bot_radius"][no_zone] = radius[no_zone]
    out = np.full((TPAGB - ZAMS + 1, len(TRACK_COLUMNS)), np.nan)
    start = ZAMS - first_eep
    part = columns[start : start + out.shape[0]]
    out[: len(part)] = part
    return mass, feh, out


def kroupa(mass: np.ndarray) -> np.ndarray:
    """The Kroupa (2001) IMF per unit mass, continuous at 0.5 M☉."""
    return np.where(mass < 0.5, (mass / 0.5) ** -1.3, (mass / 0.5) ** -2.3)


@dataclass(frozen=True)
class Points:
    """Every model point of one [Fe/H], with its prior weight."""

    log_teff: np.ndarray
    log_l: np.ndarray
    weight: np.ndarray
    stage: np.ndarray
    # (points, QUANTITIES)
    quantities: np.ndarray


def _structure(values: np.ndarray) -> np.ndarray:
    """The envelope base as fractions of the radius and the mass, and the
    convective core as a fraction of the mass, (..., 3)."""
    column = {name: values[..., i] for i, name in enumerate(TRACK_COLUMNS)}
    star_mass = column["star_mass"]
    return np.stack(
        [
            np.clip(column["conv_env_bot_radius"] / 10 ** column["log_R"], 0, 1),
            np.clip(column["conv_env_bot_mass"] / star_mass, 0, 1),
            column["mass_conv_core"] / star_mass,
        ],
        axis=-1,
    )


def points(tracks: Tracks) -> Points:
    """The points of the tracks and of the tracks between them."""
    log_mass = np.log10(tracks.masses)
    steps = np.arange(MASS_STEPS) / MASS_STEPS
    low = np.repeat(np.arange(log_mass.size - 1), MASS_STEPS)
    share = np.tile(steps, log_mass.size - 1)
    fine_log_mass = np.r_[
        (1 - share) * log_mass[low] + share * log_mass[low + 1], log_mass[-1]
    ]
    values = np.concatenate(
        [
            (1 - share)[:, None, None] * tracks.values[low]
            + share[:, None, None] * tracks.values[low + 1],
            tracks.values[-1:],
        ]
    )
    mass = 10**fine_log_mass
    edges = np.r_[mass[0], (mass[1:] + mass[:-1]) / 2, mass[-1]]
    prior = kroupa(mass) * np.diff(edges)

    column = {name: values[..., i] for i, name in enumerate(TRACK_COLUMNS)}
    age = 10 ** column["star_age"]
    with np.errstate(invalid="ignore"):
        duration = np.gradient(age, axis=1)
    weight = prior[:, None] * np.where(age <= AGE_LIMIT, duration, 0.0)
    weight = np.where(np.isfinite(weight) & (weight > 0), weight, 0.0)

    with np.errstate(invalid="ignore"):
        structure = _structure(values)
        own = _structure(tracks.values)
    # The whole mass is in the convective zone.
    fully = own[..., 1] == 0
    nearer = np.where(share < 0.5, low, low + 1)
    across = (fully[low] != fully[low + 1])[..., None]
    structure[:-1] = np.where(across, own[nearer], structure[:-1])

    star_mass = column["star_mass"]
    quantities = np.stack(
        [
            star_mass,
            column["log_R"],
            structure[..., 0],
            structure[..., 1],
            column["log_center_T"],
            column["log_center_Rho"],
            structure[..., 2] * star_mass,
            column["he_core_mass"],
            column["center_h1"],
            column["center_he4"],
        ],
        axis=-1,
    )
    eep = ZAMS + np.arange(values.shape[1])
    stage = np.searchsorted(STAGE_EEPS, eep, side="right") - 1
    keep = (weight > 0) & np.all(np.isfinite(quantities), axis=-1)
    return Points(
        column["log_Teff"][keep],
        column["log_L"][keep],
        weight[keep],
        np.broadcast_to(stage, keep.shape)[keep].astype(np.uint8),
        quantities[keep],
    )


@dataclass(frozen=True)
class Tables:
    """The tables of every [Fe/H] of the grid, in ascending [Fe/H]."""

    feh: np.ndarray
    # (feh, log Teff + 1, log L + 1, CHANNELS); the last row and column are 0.
    sums: np.ndarray


def table(found: Points) -> np.ndarray:
    """The sums of one [Fe/H]."""
    shape = (_axis(LOG_TEFF_AXIS).size, _axis(LOG_L_AXIS).size)
    i = np.rint((found.log_teff - LOG_TEFF_AXIS[0]) / LOG_TEFF_AXIS[2]).astype(int)
    j = np.rint((found.log_l - LOG_L_AXIS[0]) / LOG_L_AXIS[2]).astype(int)
    inside = (i >= 0) & (i < shape[0]) & (j >= 0) & (j < shape[1])
    cell = (i * shape[1] + j)[inside]
    weight = found.weight[inside] / found.weight[inside].sum()
    q = found.quantities[inside]

    def binned(values: np.ndarray) -> np.ndarray:
        return np.bincount(cell, values, minlength=shape[0] * shape[1]).reshape(shape)

    cells = np.stack(
        [binned(np.ones(cell.size)), binned(weight)]
        + [binned(weight * q[:, k]) for k in range(q.shape[1])]
        + [binned(weight * q[:, k] ** 2) for k in range(q.shape[1])]
        + [binned(weight * (found.stage[inside] == s)) for s in range(len(STAGES))]
        + [binned(weight * (q[:, QUANTITIES.index(name)] == 0)) for name in AT_ZERO],
        axis=-1,
    )
    sums = cells[::-1, ::-1].cumsum(axis=0).cumsum(axis=1)[::-1, ::-1]
    return np.pad(sums, ((0, 1), (0, 1), (0, 0)))


def build_tables(all_tracks: list[Tracks]) -> Tables:
    """The tables of `all_tracks`, which hold one [Fe/H] each."""
    if len(all_tracks) < 2:
        raise ValueError("the grid needs two [Fe/H] at least")
    all_tracks = sorted(all_tracks, key=lambda tracks: tracks.feh)
    return Tables(
        np.array([tracks.feh for tracks in all_tracks]),
        np.stack([table(points(tracks)) for tracks in all_tracks]),
    )


class GridError(Exception):
    """The stellar-models download is missing or does not match its manifest."""


_ARRAYS = ("feh", "sums")
MANIFEST = "manifest.json"
_DOWNLOAD = "run space-map-download --sources stellar_model_catalogues"
# The SHA-256 of each tarball below the tables root, by path, with the size
# and mtime that it holds for.
CHECKSUMS = "checksums.json"
# The lease file of a directory holds a shared lock while a process reads it.
LEASE = ".lease"
_LEASES: dict[Path, IO] = {}


def _problem(
    name: str, wanted: dict[str, str], files: dict[str, dict], on_disk: dict[str, int]
) -> str | None:
    if name not in wanted:
        return "not in the manifest"
    if name not in files or name not in on_disk:
        return "not downloaded"
    if files[name]["url"] != wanted[name]:
        return "a URL other than the manifest's"
    if files[name]["bytes"] != on_disk[name]:
        return "a size other than its download record's"
    return None


def _sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def checksums(paths: list[Path], root: Path) -> dict[Path, str]:
    """The SHA-256 of each file of `paths`, from the CHECKSUMS file of
    `root` while its size and mtime hold."""
    record = root / CHECKSUMS
    known = json.loads(record.read_text()) if record.exists() else {}
    out, changed = {}, False
    for path in paths:
        stat = path.stat()
        entry = known.get(str(path))
        if entry is None or (entry["bytes"], entry["mtime_ns"]) != (
            stat.st_size,
            stat.st_mtime_ns,
        ):
            logger.info("checksum of %s", path.name)
            entry = {
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": _sha256(path),
            }
            known[str(path)], changed = entry, True
        out[path] = entry["sha256"]
    if changed:
        root.mkdir(parents=True, exist_ok=True)
        partial = record.with_name(f".{CHECKSUMS}.{os.getpid()}")
        partial.write_text(json.dumps(known, indent=1, sort_keys=True))
        partial.replace(record)
    return out


def _manifest(tracks_dir: Path, root: Path) -> dict:
    """What the tables of `tracks_dir` are built from. The tarballs must be
    the manifest's, each with the URL and size of its download record."""
    record_path = tracks_dir.parent / DOWNLOAD_RECORD
    if not record_path.exists():
        raise GridError(f"no download record {record_path}: {_DOWNLOAD}")
    record = json.loads(record_path.read_text()).get("catalogues", {}).get(MIST.key)
    if record is None:
        raise GridError(f"{record_path} has no {MIST.key}: {_DOWNLOAD}")
    wanted = {remote.name: remote.url for remote in MIST.urls}
    files = record["files"]
    on_disk = {path.name: path.stat().st_size for path in tracks_dir.glob("*.txz")}
    problems = [
        f"{name}: {why}"
        for name in sorted(wanted.keys() | files.keys() | on_disk.keys())
        if (why := _problem(name, wanted, files, on_disk))
    ]
    if problems:
        raise GridError(
            f"{tracks_dir} does not hold the MIST tarballs: "
            + "; ".join(problems)
            + f". {_DOWNLOAD}"
        )
    digests = checksums([tracks_dir / name for name in sorted(wanted)], root)
    return {
        "version": VERSION,
        "files": {
            name: {
                "url": files[name]["url"],
                "bytes": files[name]["bytes"],
                "sha256": digests[tracks_dir / name],
            }
            for name in sorted(wanted)
        },
        "log_teff_axis": LOG_TEFF_AXIS,
        "log_l_axis": LOG_L_AXIS,
        "mass_steps": MASS_STEPS,
        "age_limit": AGE_LIMIT,
    }


def save(tables: Tables, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in _ARRAYS:
        np.save(out / f"{name}.npy", getattr(tables, name))


def build(tracks_dir: Path, out: Path) -> None:
    """Write the tables of the tarballs in `tracks_dir` to `out`."""
    all_tracks = []
    for path in sorted(tracks_dir.glob("*.txz")):
        tracks = read_tarball(path)
        logger.info(
            "%s: [Fe/H] %+.2f, %d tracks", path.name, tracks.feh, tracks.masses.size
        )
        all_tracks.append(tracks)
    save(build_tables(all_tracks), out)


def table_dir(manifest: dict, tracks_dir: Path, root: Path) -> Path:
    """The directory of the tables of `manifest`."""
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode())
    return root / f"{tracks_dir.name}-{digest.hexdigest()[:16]}"


def _lease(out: Path) -> None:
    """Hold a shared lease on `out` until the process exits."""
    if out in _LEASES:
        return
    handle = open(out.with_name(out.name + LEASE), "a")  # noqa: SIM115
    fcntl.flock(handle, fcntl.LOCK_SH)
    _LEASES[out] = handle


def _prune(root: Path, prefix: str, keep: Path) -> None:
    """Delete the table directories of `prefix` other than `keep` that no
    process holds. A lease file stays, so that a reader that opens it now
    locks the file that the next pruner locks."""
    for old in sorted(root.glob(f"{prefix}-*")):
        if old == keep or not old.is_dir():
            continue
        with open(old.with_name(old.name + LEASE), "a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            logger.info("deleting the superseded grid tables %s", old)
            shutil.rmtree(old)


def ready(tracks_dir: Path, root: Path) -> Path:
    """The directory below `root` with the tables of the tarballs in
    `tracks_dir`, built when it is missing, with a lease on it. Raises
    GridError when the download is not whole."""
    manifest = _manifest(tracks_dir, root)
    out = table_dir(manifest, tracks_dir, root)
    root.mkdir(parents=True, exist_ok=True)
    _lease(out)
    if not out.exists():
        _build_once(tracks_dir, out, manifest)
    _prune(root, tracks_dir.name, out)
    return out


def _build_once(tracks_dir: Path, out: Path, manifest: dict) -> None:
    root = out.parent
    with open(root / f"{out.name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if out.exists():
            return
        # A build that died under this lock left these.
        for stale in root.glob(f".{out.name}.*"):
            shutil.rmtree(stale)
        logger.info("building the grid tables in %s", out)
        building = Path(tempfile.mkdtemp(prefix=f".{out.name}.", dir=root))
        building.chmod(0o755)
        try:
            build(tracks_dir, building)
            (building / MANIFEST).write_text(json.dumps(manifest, indent=1))
            building.rename(out)
        except BaseException:
            shutil.rmtree(building, ignore_errors=True)
            raise


@cache
def load(out: Path) -> Tables:
    """The tables at `out`, mapped read-only. `ready` never rewrites a
    directory, so a map stays current."""
    return Tables(*(np.load(out / f"{name}.npy", mmap_mode="r") for name in _ARRAYS))
