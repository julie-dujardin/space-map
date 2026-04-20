"""Download SPICE kernels and extract orbital elements + orientation data."""

import csv
import logging
import math
import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import orjson
import spiceypy
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.objects.chebyshev import extract_chebyshev
from space_map_data.models.object import ObjectType
from space_map_data.utils.naif import MajorBody, classify_object
from space_map_data.utils.paths import CONFIG_FILE

logger = logging.getLogger(__name__)

_NAIF_BASE_URL = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels"

# SPICE kernel types:
#   .bsp (SPK) — ephemeris: positions & velocities of bodies over time
#   .tpc (PCK) — physical constants: body radii, GM values, pole orientation & spin
#   .tls (LSK) — leapseconds: UTC ↔ ephemeris time conversion

# TODO(moons-elements-improvement): non-whitelisted moons currently ship a
# single-epoch Keplerian row (via the standard elements export). Their Ω and ω
# drift visibly over years from J2 precession — Phobos' nodes regress ~160°/yr,
# inner Uranus/Neptune moons precess 30–200°/yr — and the single-epoch orbit
# decorrelates from truth after a few years.
#
# The proper fix is frame-aware Chebyshev-style propagation WITHOUT shipping
# polynomial coefficients (too big for the hundreds of skipped moons). Two
# pieces are needed:
#
#  1. Extraction: augment bodies.csv (or a sibling file) with analytic J2
#     secular rates per moon. The standard formulas,
#         Ω̇ = -(3/2) · n · J2 · (R_eq/a)² · cos(i) / (1-e²)²
#         ω̇ =  (3/4) · n · J2 · (R_eq/a)² · (5cos²i - 1) / (1-e²)²
#     REQUIRE `i` to be the orbit's inclination to the parent's EQUATORIAL
#     plane, not to the ecliptic. We extract elements in ECLIPJ2000 (ecliptic),
#     so computing with `cos(i_ecliptic)` produces physically wrong rates —
#     tested and found to make propagation worse than plain Kepler, worst for
#     Uranus (98° obliquity → sign flips in cos(i)).
#
#  2. Frame transform: two reasonable shapes
#     (a) Ship elements in parent-equatorial frame plus the pole orientation
#         (already in PCK: POLE_RA/POLE_DEC/PM). Frontend rotates per-frame.
#         Body-equatorial J2 rates plug in directly. Cleanest but changes
#         existing-moon-elements frame semantics — touches the frontend.
#     (b) Keep ecliptic elements; compute Ω̇/ω̇ in the body-equatorial frame,
#         then transform the rate vector back to ecliptic with the pole.
#         Doesn't change existing semantics but the transformation is
#         non-trivial (the three rates — nodal, apsidal, mean-anomaly — aren't
#         independent under a tilted-frame change; need the full osculating-
#         element time-derivative machinery).
#
# J2 coefficients live in NAIF's `pck/Gravity.tpc` kernel (NOT in the standard
# pck00011.tpc), as `BODY<n>_J2` / `BODY<n>_J3` / `BODY<n>_J4` variables.
# Equatorial radii are in the normal PCK's `BODY<n>_RADII` (first element).
#
# When we pick this up: add Gravity.tpc to _FIXED_KERNELS, extract J2+R_eq +
# the pole orientation (already extracted — see _extract_orientation) into a
# sidecar file, rework the moons elements export to use approach (a) or (b).
# Validate against spkezr at +1y / +5y / +20y — must beat plain Kepler by at
# least 5× for the fast inner moons or the added complexity isn't worth it.

# Fixed kernels that don't need version discovery. Values are paths relative
# to `_NAIF_BASE_URL`, or fully-qualified URLs (if hosted elsewhere, like JPL's
# SSD site for the SB441 asteroid kernel).
_FIXED_KERNELS: dict[str, str] = {
    "de440.bsp": "spk/planets/de440.bsp",  # planet + Moon ephemerides
    # 16 largest asteroids used as perturbers in DE441 — Ceres, Vesta, Pallas,
    # etc. Only hosted at JPL's SSD (not in NAIF's generic_kernels tree); gives
    # us high-accuracy Chebyshev coverage for the major asteroids.
    "sb441-n16.bsp": "https://ssd.jpl.nasa.gov/ftp/eph/small_bodies/asteroids_de441/sb441-n16.bsp",
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


def _resolve_kernels(client: httpx.Client) -> dict[str, str]:
    """Fetch NAIF directory listings and resolve all needed kernels.

    Returns {filename: relative_url_path}.
    """
    resolved: dict[str, str] = {}

    # --- Latest-version kernels (lsk, pck) ---
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

    # --- Satellite kernels: all .bsp files for each planet prefix ---
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
    url = f"{_NAIF_BASE_URL}/{dir_path}/"
    resp = client.get(url)
    resp.raise_for_status()
    return re.findall(r'href="([^"]+)"', resp.text)


# AU in km
_AU_KM = 149_597_870.7


_CHEBYSHEV_DEFAULTS: dict[str, int | float] = {
    "start_year": 1950,
    "end_year": 2050,
    "chunk_years": 5,  # major / major_asteroids zones
    "moon_chunk_years": 0.5,  # moons/<parent>/<main|inner> zones
}


def _load_chebyshev_config() -> dict[str, int | float]:
    """Read [chebyshev] settings from config.toml, falling back to defaults."""
    if not CONFIG_FILE.exists():
        return dict(_CHEBYSHEV_DEFAULTS)
    with CONFIG_FILE.open("rb") as f:
        config = tomllib.load(f)
    section = config.get("chebyshev", {})
    return {
        # year bounds are integers; chunk lengths may be fractional
        k: (
            int(section.get(k, v))
            if k in ("start_year", "end_year")
            else float(section.get(k, v))
        )
        for k, v in _CHEBYSHEV_DEFAULTS.items()
    }


# Barycenters that don't appear in SPK but we need (0=SSB, 1-9=planet barycenters, 10=Sun)
_EXTRA_NAIF_IDS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

# Types we extract elements for (skip asteroids/comets — those stay in SBDB)
_ELEMENT_TYPES = frozenset(
    {
        ObjectType.barycenter,
        ObjectType.star,
        ObjectType.planet,
        ObjectType.dwarf_planet,
        ObjectType.moon,
    }
)


@dataclass
class _HorizonsAlias:
    name: str | None = None
    designation: str | None = None
    iau_roman_designation: str | None = None
    naif_id_extended: int | None = None


_ROMAN_RE = re.compile(r"^[JSUNM][IVXLCDM]+$")
_EXT_NAIF_RE = re.compile(r"^[0-9]{4,5}$")


def _load_horizons_names(download_dir: Path) -> dict[int, _HorizonsAlias]:
    """Parse Horizons major_bodies.txt into {naif_id: HorizonsAlias}.

    Horizons publishes names for recently-named moons (e.g. 557 Eirene) that
    the bundled SPICE name table doesn't know about, so we use it as the
    primary name source and fall back to SPICE's `bodc2n` only when absent.
    The IAU/aliases column also carries the Roman-numeral IAU designation and
    the 5-digit extended NAIF ID that SPICE uses for irregular-moon kernels.
    """
    path = download_dir / PROVIDERS.HORIZONS / "major_bodies.txt"
    result: dict[int, _HorizonsAlias] = {}
    if not path.exists():
        logger.warning("Horizons major_bodies.txt not found at %s", path)
        return result

    # Fixed-width columns from the separator line:
    #   cols  2–8  = ID, 11–44 = Name, 46–56 = Designation, 59+ = IAU/aliases
    with path.open() as f:
        in_data = False
        for line in f:
            if line.startswith("  -------"):
                in_data = True
                continue
            if not in_data or len(line) < 11:
                continue
            id_str = line[0:9].strip()
            if not id_str.lstrip("-").isdigit():
                continue
            naif_id = int(id_str)
            alias = _HorizonsAlias(
                name=line[11:45].strip() or None,
                designation=(line[46:57].strip() if len(line) > 46 else "") or None,
            )
            for token in line[59:].split() if len(line) > 59 else ():
                if alias.iau_roman_designation is None and _ROMAN_RE.match(token):
                    alias.iau_roman_designation = token
                elif alias.naif_id_extended is None and _EXT_NAIF_RE.match(token):
                    alias.naif_id_extended = int(token)
            result[naif_id] = alias
    logger.info("Loaded %d names from Horizons major_bodies.txt", len(result))
    return result


def _resolve_name(
    naif_id: int, horizons_map: dict[int, _HorizonsAlias]
) -> _HorizonsAlias:
    """Resolve name + cross-reference aliases for a body.

    Prefers Horizons (properly cased, broader name coverage); falls back to
    SPICE's built-in name table; returns name=None when neither has one.
    """
    alias = horizons_map.get(naif_id) or _HorizonsAlias()
    if alias.name is None:
        try:
            alias.name = spiceypy.bodc2n(naif_id)
        except spiceypy.exceptions.SpiceyError:
            pass
    return alias


def _dominant_partner_mu(gm_self: float, candidate_naifs: list[int]) -> float | None:
    """Effective mu for the heavier member of a two-body pair around their barycenter.

    When a massive body (planet, Sun) orbits its own system barycenter, its
    motion is driven not by GM of the barycenter but by the gravity of the
    next-heaviest member. The two-body reduction yields
      mu_eff = GM_partner^3 / (GM_self + GM_partner)^2
    which produces the correct Kepler ellipse matching the partner's period.
    Returns None if no candidate has a known GM.
    """
    best_gm = 0.0
    for naif in candidate_naifs:
        try:
            gm = spiceypy.bodvrd(str(naif), "GM", 1)[1][0]
        except spiceypy.exceptions.SpiceyError:
            continue
        if gm > best_gm:
            best_gm = gm
    if best_gm <= 0:
        return None
    return best_gm**3 / (gm_self + best_gm) ** 2


def _state_to_elements(
    state: list[float], et: float, gm: float
) -> dict[str, float] | None:
    """Convert a SPICE state vector to Keplerian elements in AU/deg/day units.

    Returns None if the orbit is degenerate (e.g. a barycenter at its own center).
    """
    try:
        elts = spiceypy.oscelt(state, et, gm)
    except spiceypy.exceptions.SpiceyError:
        return None

    rp = elts[0]  # periapsis distance [km]
    ecc = elts[1]  # eccentricity
    inc = elts[2]  # inclination [rad]
    lnode = elts[3]  # longitude of ascending node [rad]
    argp = elts[4]  # argument of periapsis [rad]
    m0 = elts[5]  # mean anomaly at epoch [rad]
    # elts[6] = epoch of periapsis [s past J2000]
    mu = elts[7]  # GM [km^3/s^2]

    if ecc >= 1.0 or rp <= 0:
        # Hyperbolic/parabolic or degenerate — shouldn't happen for bound orbits
        return None

    a_km = rp / (1 - ecc)
    if a_km <= 0:
        return None

    a_au = a_km / _AU_KM

    # Mean motion: n = sqrt(mu / a^3) in rad/s -> deg/day
    n_rad_s = math.sqrt(mu / (a_km**3))
    n_deg_day = math.degrees(n_rad_s) * 86400

    return {
        "A": a_au,
        "EC": ecc,
        "IN": math.degrees(inc),
        "OM": math.degrees(lnode),
        "W": math.degrees(argp),
        "MA": math.degrees(m0),
        "N": n_deg_day,
    }


class SpiceDownloader(Downloader):
    name = PROVIDERS.SPICE

    def _build_kernel_list(self) -> dict[str, str]:
        """Build the full kernel map: fixed + dynamically resolved from NAIF."""
        logger.info("Resolving kernel list from NAIF...")
        resolved = dict(_FIXED_KERNELS)
        resolved.update(_resolve_kernels(self.client))
        return resolved

    def _download_kernels(self, kernels: dict[str, str]) -> list[Path]:
        """Download SPICE kernels, skipping files that already exist with correct size."""
        kernel_dir = self.out_dir / "kernels"
        kernel_dir.mkdir(exist_ok=True)
        paths: list[Path] = []

        for filename, url_path in tqdm(
            kernels.items(), desc="SPICE kernels", unit="file"
        ):
            local = kernel_dir / filename
            url = (
                url_path
                if url_path.startswith("http://") or url_path.startswith("https://")
                else f"{_NAIF_BASE_URL}/{url_path}"
            )

            if local.exists():
                # Check size via HEAD request
                head = self.client.head(url)
                head.raise_for_status()
                expected_size = int(head.headers.get("content-length", 0))
                if expected_size and local.stat().st_size == expected_size:
                    logger.debug("Kernel %s already downloaded", filename)
                    paths.append(local)
                    continue

            logger.info("Downloading %s ...", filename)
            with self.client.stream("GET", url) as resp:
                resp.raise_for_status()
                with local.open("wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
            logger.info("  -> %s (%.1f MB)", local.name, local.stat().st_size / 1e6)
            paths.append(local)

        return paths

    def _enumerate_spk_bodies(self, kernel_paths: list[Path]) -> set[int]:
        """Get all body NAIF IDs covered by loaded SPK kernels."""
        all_ids: set[int] = set()
        for path in kernel_paths:
            if not path.suffix == ".bsp":
                continue
            ids = spiceypy.spkobj(str(path))
            for naif_id in ids:
                all_ids.add(int(naif_id))
        return all_ids

    @staticmethod
    def _extract_orientation() -> list[dict]:
        """Extract PCK orientation data for all bodies that have it.

        Returns the full IAU rotation polynomial:
          α(T) = pole_ra_0 + pole_ra_1·T   (T in Julian centuries since J2000)
          δ(T) = pole_dec_0 + pole_dec_1·T
          W(d) = w0 + w1·d + w2·d²         (d in days since J2000)

        Nutation/precession sums are extracted separately (see _extract_nutation).
        Queries the kernel pool for all BODY*_POLE_RA variables rather than
        iterating a fixed set, so asteroids and comets with orientation data
        in the PCK are included automatically.
        """
        # Find all body IDs with POLE_RA in the kernel pool
        matches = spiceypy.gnpool("BODY*_POLE_RA", 0, 1000)
        naif_ids: set[int] = set()
        for var in matches:
            m = re.match(r"BODY(-?\d+)_POLE_RA", var)
            if m:
                naif_ids.add(int(m.group(1)))

        rows = []
        for naif_id in sorted(naif_ids):
            try:
                pole_ra = spiceypy.bodvrd(str(naif_id), "POLE_RA", 3)[1]
                pole_dec = spiceypy.bodvrd(str(naif_id), "POLE_DEC", 3)[1]
                pm = spiceypy.bodvrd(str(naif_id), "PM", 3)[1]
            except spiceypy.exceptions.SpiceyError:
                continue
            rows.append(
                {
                    "naif_id": naif_id,
                    "pole_ra_0": pole_ra[0],
                    "pole_ra_1": pole_ra[1],
                    "pole_dec_0": pole_dec[0],
                    "pole_dec_1": pole_dec[1],
                    "w0": pm[0],
                    "w1": pm[1],
                    "w2": pm[2],
                }
            )
        return rows

    @staticmethod
    def _extract_nutation() -> tuple[
        dict[int, dict[str, list[float]]], dict[int, list[float]]
    ]:
        """Extract PCK nutation/precession terms for the full IAU rotation model.

        Per body:
          α += Σ ra[i]  · sin(θ_i(T))
          δ += Σ dec[i] · cos(θ_i(T))
          W += Σ pm[i]  · sin(θ_i(T))
        where θ_i(T) = angles[2i] + angles[2i+1]·T (degrees, deg/century, T = Julian centuries).

        The angles array is defined once per "owner" body — typically the
        planetary system barycenter (1..9). In pck00011 the owners are
        BODY{1,3,4,5,6,7,8}_NUT_PREC_ANGLES; bodies derive their owner as
        `naif_id // 100` (or `naif_id` itself when < 100).

        Returns (coefficients, angles):
          coefficients: {naif_id: {"ra": [...], "dec": [...], "pm": [...]}}
          angles:       {owner_naif_id: [θ₀_1, θ₁_1, θ₀_2, θ₁_2, ...]}
        """
        coefficients: dict[int, dict[str, list[float]]] = {}
        for kind, key in (("ra", "RA"), ("dec", "DEC"), ("pm", "PM")):
            matches = spiceypy.gnpool(f"BODY*_NUT_PREC_{key}", 0, 1000)
            for var in matches:
                m = re.match(rf"BODY(-?\d+)_NUT_PREC_{key}$", var)
                if not m:
                    continue
                naif_id = int(m.group(1))
                # dtpool returns (found, n_elements, type) — use it to size the fetch
                n_elements, _type = spiceypy.dtpool(var)[:2]
                if n_elements <= 0:
                    continue
                try:
                    values = spiceypy.bodvrd(
                        str(naif_id), f"NUT_PREC_{key}", n_elements
                    )[1]
                except spiceypy.exceptions.SpiceyError as exc:
                    logger.warning("Failed reading %s: %s", var, exc)
                    continue
                # Coerce numpy.float64 → float so orjson can serialize.
                coefficients.setdefault(naif_id, {"ra": [], "dec": [], "pm": []})[
                    kind
                ] = [float(v) for v in values]

        angles: dict[int, list[float]] = {}
        for var in spiceypy.gnpool("BODY*_NUT_PREC_ANGLES", 0, 1000):
            m = re.match(r"BODY(-?\d+)_NUT_PREC_ANGLES$", var)
            if not m:
                continue
            owner_id = int(m.group(1))
            n_elements, _type = spiceypy.dtpool(var)[:2]
            if n_elements <= 0:
                continue
            try:
                values = spiceypy.bodvrd(str(owner_id), "NUT_PREC_ANGLES", n_elements)[
                    1
                ]
            except spiceypy.exceptions.SpiceyError as exc:
                logger.warning("Failed reading %s: %s", var, exc)
                continue
            angles[owner_id] = [float(v) for v in values]

        # Sanity-check: every body with coefficients should have a resolvable owner,
        # and per-channel arrays may not exceed the angle count (they may be shorter —
        # bodies often use only the first few system angles).
        for naif_id, coeffs in coefficients.items():
            owner_id = naif_id // 100 if naif_id >= 100 else naif_id
            if owner_id not in angles:
                logger.warning(
                    "NUT_PREC coefficients for body %d reference owner %d which "
                    "has no NUT_PREC_ANGLES; rotation sums for this body will be "
                    "ignored downstream",
                    naif_id,
                    owner_id,
                )
                continue
            n_angles = len(angles[owner_id]) // 2
            for kind in ("ra", "dec", "pm"):
                if len(coeffs[kind]) > n_angles:
                    logger.warning(
                        "Body %d NUT_PREC_%s has %d coefficients but owner %d only "
                        "defines %d angle pairs; extra coefficients will be ignored",
                        naif_id,
                        kind.upper(),
                        len(coeffs[kind]),
                        owner_id,
                        n_angles,
                    )

        return coefficients, angles

    @staticmethod
    def _extract_radii() -> list[dict]:
        """Extract PCK triaxial radii (a, b, c in km) for all bodies that have them.

        Enumerated independently from orientation — a body can have radii
        without pole data, and vice versa.
        """
        matches = spiceypy.gnpool("BODY*_RADII", 0, 1000)
        naif_ids: set[int] = set()
        for var in matches:
            m = re.match(r"BODY(-?\d+)_RADII", var)
            if m:
                naif_ids.add(int(m.group(1)))

        rows = []
        for naif_id in sorted(naif_ids):
            try:
                radii = spiceypy.bodvrd(str(naif_id), "RADII", 3)[1]
            except spiceypy.exceptions.SpiceyError:
                continue
            rows.append(
                {
                    "naif_id": naif_id,
                    "radius_a_km": radii[0],
                    "radius_b_km": radii[1],
                    "radius_c_km": radii[2],
                }
            )
        return rows

    def download(
        self, limit: int | None = None, epoch: date | None = None, **kwargs: object
    ) -> None:
        if epoch is None:
            epoch = date.today()
        epoch_jd = epoch.toordinal() + 1721424.5
        logger.info("Using epoch %s (JD %.1f)", epoch.isoformat(), epoch_jd)

        # Step 1: Resolve and download kernels
        kernels = self._build_kernel_list()
        kernel_paths = self._download_kernels(kernels)

        # Step 2: Load all kernels
        for path in kernel_paths:
            spiceypy.furnsh(str(path))

        try:
            self._extract_data(epoch, epoch_jd, kernel_paths)
        finally:
            spiceypy.kclear()

    def _extract_data(
        self, epoch: date, epoch_jd: float, kernel_paths: list[Path]
    ) -> None:
        # Convert epoch to SPICE ephemeris time (seconds past J2000)
        et = spiceypy.str2et(epoch.isoformat())

        # Step 3: Enumerate all bodies from SPK kernels
        spk_ids = self._enumerate_spk_bodies(kernel_paths)
        all_ids = spk_ids | set(_EXTRA_NAIF_IDS)

        # Step 4: Classify all bodies. We keep a broad list here because the
        # Chebyshev extractor downstream wants asteroids too (sb441-n16s); the
        # Keplerian element extraction then filters to `_ELEMENT_TYPES` only.
        horizons_names = _load_horizons_names(self.out_dir.parent)
        all_bodies: list[MajorBody] = []
        for naif_id in sorted(all_ids):
            alias = _resolve_name(naif_id, horizons_names)
            try:
                obj_type, parent_id = classify_object(
                    naif_id, alias.name or "", alias.name or "", None
                )
            except ValueError:
                logger.warning(
                    "Skipping unclassifiable body %d (%s)", naif_id, alias.name
                )
                continue

            all_bodies.append(
                MajorBody(
                    name=alias.name,
                    naif_id=naif_id,
                    parent_naif_id=parent_id,
                    object_type=obj_type,
                    designation=alias.designation,
                    iau_roman_designation=alias.iau_roman_designation,
                    naif_id_extended=alias.naif_id_extended,
                )
            )

        bodies = [b for b in all_bodies if b.object_type in _ELEMENT_TYPES]
        logger.info("Classified %d bodies for element extraction", len(bodies))

        # Step 5: Extract orbital elements
        fieldnames = [
            "name",
            "provisional_designation",
            "iau_roman_designation",
            "naif_id_extended",
            "naif_id",
            "type",
            "parent_naif_id",
            "JDTDB",
            "A",
            "EC",
            "IN",
            "OM",
            "W",
            "MA",
            "N",
        ]
        rows: list[dict] = []

        # Pre-fetch Sun GM — used for bodies orbiting the SSB (which has no GM)
        gm_sun = spiceypy.bodvrd("10", "GM", 1)[1][0]

        _ZERO_ROW = {"A": 0, "EC": 0, "IN": 0, "OM": 0, "W": 0, "MA": 0, "N": 0}

        for body in tqdm(bodies, desc="SPICE elements", unit="body"):
            # SSB is the coordinate origin — no orbit to compute
            if body.naif_id == 0:
                rows.append(
                    {
                        "name": body.name,
                        "provisional_designation": body.designation,
                        "iau_roman_designation": body.iau_roman_designation,
                        "naif_id_extended": body.naif_id_extended,
                        "naif_id": body.naif_id,
                        "type": body.object_type,
                        "parent_naif_id": body.parent_naif_id,
                        "JDTDB": f"{epoch_jd:.1f}",
                        **_ZERO_ROW,
                    }
                )
                continue

            # Get the gravitational parameter governing this orbit.
            # SSB (0) has no GM in SPICE — use the Sun's GM instead,
            # since the Sun dominates the system mass.
            if body.naif_id == 10:
                # Sun orbiting the SSB: heaviest member of a many-body dance
                # dominated by Jupiter. Using GM_sun (the Sun's self-gravity)
                # would give ecc≈1 for the same reason as planet-around-
                # barycenter. Use Jupiter-barycenter as the effective partner.
                gm = _dominant_partner_mu(
                    spiceypy.bodvrd("10", "GM", 1)[1][0],
                    list(range(1, 10)),  # planetary barycenters
                )
                if gm is None:
                    gm = gm_sun
            elif body.parent_naif_id == 0:
                if body.object_type == ObjectType.barycenter and 1 <= body.naif_id <= 9:
                    # Planetary-system barycenter around SSB: lighter partner
                    # of the Sun in a two-body reduction, giving
                    #   mu_eff = GM_sun^3 / (GM_sun + GM_system)^2
                    # (barely differs from GM_sun but is the correct value).
                    try:
                        gm_sys = spiceypy.bodvrd(str(body.naif_id), "GM", 1)[1][0]
                        gm = gm_sun**3 / (gm_sun + gm_sys) ** 2
                    except spiceypy.exceptions.SpiceyError:
                        gm = gm_sun
                else:
                    gm = gm_sun
            elif body.object_type in (ObjectType.planet, ObjectType.dwarf_planet) and (
                1 <= body.parent_naif_id <= 9
            ):
                # Planet orbiting its own system barycenter: it's the heavier
                # member of a two-body dance with its dominant moon, not an
                # orbit in a GM(barycenter) field. Using GM(barycenter) with
                # the tiny ~km/day velocity produces ecc≈1. The correct mu
                # for the planet's orbit around the barycenter is
                #   mu_eff = GM_moon^3 / (GM_planet + GM_moon)^2
                try:
                    gm_planet = spiceypy.bodvrd(str(body.naif_id), "GM", 1)[1][0]
                except spiceypy.exceptions.SpiceyError:
                    gm_planet = None
                moon_candidates = [
                    n
                    for n in range(
                        body.parent_naif_id * 100 + 1, body.parent_naif_id * 100 + 99
                    )
                    if n != body.naif_id
                ]
                gm = (
                    _dominant_partner_mu(gm_planet, moon_candidates)
                    if gm_planet is not None
                    else None
                )
                if gm is None:
                    logger.debug(
                        "No dominant moon for %s (%d); using zero elements",
                        body.name,
                        body.naif_id,
                    )
                    rows.append(
                        {
                            "name": body.name,
                            "provisional_designation": body.designation,
                            "iau_roman_designation": body.iau_roman_designation,
                            "naif_id_extended": body.naif_id_extended,
                            "naif_id": body.naif_id,
                            "type": body.object_type,
                            "parent_naif_id": body.parent_naif_id,
                            "JDTDB": f"{epoch_jd:.1f}",
                            **_ZERO_ROW,
                        }
                    )
                    continue
            else:
                try:
                    gm = spiceypy.bodvrd(str(body.parent_naif_id), "GM", 1)[1][0]
                except spiceypy.exceptions.SpiceyError:
                    logger.warning(
                        "No GM for parent %d of %s (%d), skipping",
                        body.parent_naif_id,
                        body.name,
                        body.naif_id,
                    )
                    continue

            # Get state vector relative to parent
            try:
                state, _ = spiceypy.spkezr(
                    str(body.naif_id),
                    et,
                    "ECLIPJ2000",
                    "NONE",
                    str(body.parent_naif_id),
                )
            except spiceypy.exceptions.SpiceyError:
                logger.warning(
                    "Cannot get state for %s (%d), skipping",
                    body.name,
                    body.naif_id,
                )
                continue

            elts = _state_to_elements(list(state), et, gm)
            if elts is None:
                # Planet nearly coincident with its barycenter (moons too small
                # to shift the center of mass appreciably) — use zero elements.
                logger.debug(
                    "Degenerate orbit for %s (%d), using zero elements",
                    body.name,
                    body.naif_id,
                )
                elts = _ZERO_ROW
            elif (
                body.object_type in (ObjectType.planet, ObjectType.dwarf_planet)
                and 1 <= body.parent_naif_id <= 9
                and elts["EC"] > 0.6
            ):
                # The single-dominant-moon mu approximation failed — likely a
                # system with multiple comparable moons (Uranus, Jupiter) whose
                # barycenter wobble is not well-described by a Kepler orbit.
                logger.info(
                    "Non-Keplerian barycenter wobble for %s (%d), zeroing (got ecc=%.3f)",
                    body.name,
                    body.naif_id,
                    elts["EC"],
                )
                elts = _ZERO_ROW

            rows.append(
                {
                    "name": body.name,
                    "provisional_designation": body.designation,
                    "iau_roman_designation": body.iau_roman_designation,
                    "naif_id_extended": body.naif_id_extended,
                    "naif_id": body.naif_id,
                    "type": body.object_type,
                    "parent_naif_id": body.parent_naif_id,
                    "JDTDB": f"{epoch_jd:.1f}",
                    **elts,
                }
            )

        # Write bodies CSV
        out_file = self.out_dir / "bodies.csv"
        with out_file.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Saved %d bodies -> %s", len(rows), out_file.name)

        # Step 7: Extract orientation data
        orientation_rows = self._extract_orientation()
        orientation_file = self.out_dir / "orientation.csv"
        with orientation_file.open("w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "naif_id",
                    "pole_ra_0",
                    "pole_ra_1",
                    "pole_dec_0",
                    "pole_dec_1",
                    "w0",
                    "w1",
                    "w2",
                ],
            )
            writer.writeheader()
            writer.writerows(orientation_rows)
        logger.info(
            "Saved %d orientation records -> %s",
            len(orientation_rows),
            orientation_file.name,
        )

        # Step 8: Extract NUT_PREC nutation/precession terms
        nut_prec_coeffs, nut_prec_angles = self._extract_nutation()
        # Keys serialized as strings — orjson refuses int keys at top level
        nut_prec_file = self.out_dir / "nut_prec.json"
        nut_prec_file.write_bytes(
            orjson.dumps(
                {
                    str(naif_id): coeffs
                    for naif_id, coeffs in sorted(nut_prec_coeffs.items())
                }
            )
        )
        nut_prec_angles_file = self.out_dir / "nut_prec_angles.json"
        nut_prec_angles_file.write_bytes(
            orjson.dumps(
                {
                    str(owner_id): vals
                    for owner_id, vals in sorted(nut_prec_angles.items())
                }
            )
        )
        logger.info(
            "Saved nutation terms: %d bodies, %d angle owners",
            len(nut_prec_coeffs),
            len(nut_prec_angles),
        )

        # Step 9: Extract triaxial radii
        radii_rows = self._extract_radii()
        radii_file = self.out_dir / "radii.csv"
        with radii_file.open("w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["naif_id", "radius_a_km", "radius_b_km", "radius_c_km"],
            )
            writer.writeheader()
            writer.writerows(radii_rows)
        logger.info("Saved %d radii records -> %s", len(radii_rows), radii_file.name)

        # Step 10: Extract Chebyshev polynomial ephemeris for the Chebyshev
        # body set — core bodies (planets, Sun, dwarves, barycenters) plus the
        # 16 sb441-n16 asteroids plus the whitelisted surface-feature moons.
        # Runs here so furnshed kernels stay in memory.
        cheb_cfg = _load_chebyshev_config()
        cheb_count = extract_chebyshev(
            self.out_dir,
            all_bodies,
            kernel_paths,
            int(cheb_cfg["start_year"]),
            int(cheb_cfg["end_year"]),
        )

        self._save_metadata(
            _NAIF_BASE_URL,
            len(rows),
            complete=False,
            epoch=epoch.isoformat(),
            epoch_jd=f"{epoch_jd:.1f}",
            orientation_count=len(orientation_rows),
            nut_prec_body_count=len(nut_prec_coeffs),
            nut_prec_angle_owner_count=len(nut_prec_angles),
            radii_count=len(radii_rows),
            chebyshev_body_count=cheb_count,
            chebyshev_moon_chunk_years=cheb_cfg["moon_chunk_years"],
            chebyshev_start_year=cheb_cfg["start_year"],
            chebyshev_end_year=cheb_cfg["end_year"],
            chebyshev_chunk_years=cheb_cfg["chunk_years"],
        )
