"""SPICE downloader: fetch kernels, compute elements, dump per-body sidecars."""

import csv
import logging
import math
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import orjson
import spiceypy
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.objects.chebyshev import extract_chebyshev
from space_map_data.models.object import ObjectType
from space_map_data.utils.time import DAYS_PER_YEAR, year_to_jd
from space_map_data.utils.naif import (
    CHEBYSHEV_MOON_WHITELIST,
    MajorBody,
    classify_object,
)

from ..naif_http import spk_targets
from ..probes.layout import MISSIONS_DIR
from .elements import (
    METHOD_C_RESIDUAL_WARN_ARCMIN,
    MOON_CHUNK_YEARS,
    dominant_partner_mu,
    fit_moon_chunked_elements,
    fit_moon_mean_elements,
    load_chebyshev_config,
    state_to_elements,
)
from .kernels import NAIF_BASE_URL, download_kernels, resolve_kernels
from .major_bodies import fetch_major_bodies
from .names import load_horizons_names, resolve_name
from .pck_extract import (
    extract_gms,
    extract_gravity_field,
    extract_nutation,
    extract_orientation,
    extract_radii,
)

logger = logging.getLogger(__name__)

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

_ZERO_ROW = {
    "A": 0,
    "EC": 0,
    "IN": 0,
    "OM": 0,
    "W": 0,
    "MA": 0,
    "N": 0,
    "OM_DOT": 0,
    "W_DOT": 0,
}

_BODY_FIELDNAMES = [
    "name",
    "provisional_designation",
    "iau_roman_designation",
    "naif_id_extended",
    "naif_id",
    "type",
    "parent_id",
    "JDTDB",
    "A",
    "EC",
    "IN",
    "OM",
    "W",
    "MA",
    "N",
    "OM_DOT",
    "W_DOT",
]
_ORIENTATION_FIELDNAMES = [
    "naif_id",
    "pole_ra_0",
    "pole_ra_1",
    "pole_dec_0",
    "pole_dec_1",
    "w0",
    "w1",
    "w2",
]
_RADII_FIELDNAMES = ["naif_id", "radius_a_km", "radius_b_km", "radius_c_km"]
_GRAVITY_FIELDNAMES = ["naif_id", "j2", "j3", "j4", "r_eq_km"]
_GM_FIELDNAMES = ["naif_id", "gm_km3_s2"]


def _make_row(body: MajorBody, epoch_jd: float, elts: dict) -> dict:
    """Build a bodies.csv row from a classified body and its element dict."""
    return {
        "name": body.name,
        "provisional_designation": body.designation,
        "iau_roman_designation": body.iau_roman_designation,
        "naif_id_extended": body.naif_id_extended,
        "naif_id": body.naif_id,
        "type": body.object_type,
        "parent_id": body.parent_id,
        "JDTDB": f"{epoch_jd:.1f}",
        **elts,
    }


class SpiceDownloader(Downloader):
    name = PROVIDERS.SPICE

    def download(
        self, limit: int | None = None, epoch: date | None = None, **kwargs: object
    ) -> None:
        if epoch is None:
            epoch = date.today()
        epoch_jd = epoch.toordinal() + 1721424.5
        logger.info("Using epoch %s (JD %.1f)", epoch.isoformat(), epoch_jd)

        fetch_major_bodies(self.client, self.out_dir)

        kernels = resolve_kernels(self.client)
        kernel_paths = download_kernels(self.client, self.out_dir, kernels)

        # Mission PCKs furnish first so the generic kernel pool (pck00011,
        # gm_de440, Gravity.tpc) overrides any incidental planet/Sun entries —
        # IAU/WGCCRE values are the most rigorous synthesis. Mission-PCK values
        # survive only for bodies the generic kernels don't define (Bennu,
        # Ryugu, Didymos, Donaldjohanson, Dinkinesh, Arrokoth, …), which is
        # the whole point of bringing them in.
        mission_pcks = (
            sorted(MISSIONS_DIR.glob("*/*.tpc")) if MISSIONS_DIR.exists() else []
        )
        for path in mission_pcks:
            spiceypy.furnsh(str(path))
        if mission_pcks:
            logger.info(
                "Furnished %d mission PCKs from %d missions",
                len(mission_pcks),
                len({p.parent.name for p in mission_pcks}),
            )

        for path in kernel_paths:
            spiceypy.furnsh(str(path))

        try:
            self._extract_data(epoch, epoch_jd, kernel_paths)
        finally:
            spiceypy.kclear()

    def _extract_data(
        self, epoch: date, epoch_jd: float, kernel_paths: list[Path]
    ) -> None:
        et = spiceypy.str2et(epoch.isoformat())

        all_bodies = self._classify_bodies(kernel_paths)
        bodies = [b for b in all_bodies if b.object_type in _ELEMENT_TYPES]
        logger.info("Classified %d bodies for element extraction", len(bodies))

        rows, moon_chunk_targets = self._extract_orbital_rows(bodies, et, epoch_jd)
        self._write_csv("bodies.csv", _BODY_FIELDNAMES, rows)

        # Time-chunked Method C fits for non-whitelisted moons: one sidecar
        # .npz per moon with per-chunk secular elements, consumed by the
        # elements export to write per-chunk binary files.
        chunk_count = self._extract_moon_chunks(moon_chunk_targets)
        logger.info(
            "Time-chunked Method C fits: %d moons × ~%d chunks",
            len(moon_chunk_targets),
            chunk_count,
        )

        orientation_rows = extract_orientation()
        self._write_csv("orientation.csv", _ORIENTATION_FIELDNAMES, orientation_rows)

        nut_prec_coeffs, nut_prec_angles = extract_nutation()
        self._write_nutation(nut_prec_coeffs, nut_prec_angles)

        gravity_rows = extract_gravity_field()
        self._write_csv("gravity.csv", _GRAVITY_FIELDNAMES, gravity_rows)
        radii_rows = extract_radii()
        self._write_csv("radii.csv", _RADII_FIELDNAMES, radii_rows)
        gm_rows = extract_gms()
        self._write_csv("gm.csv", _GM_FIELDNAMES, gm_rows)

        # Chebyshev runs here so furnshed kernels stay in memory. Body set =
        # core bodies (planets, Sun, dwarves, barycenters) + sb441-n373
        # perturber asteroids + whitelisted surface-feature moons.
        cheb_cfg = load_chebyshev_config()
        cheb_count = extract_chebyshev(
            self.out_dir,
            all_bodies,
            kernel_paths,
            int(cheb_cfg["start_year"]),
            int(cheb_cfg["end_year"]),
        )

        self._save_metadata(
            NAIF_BASE_URL,
            len(rows),
            complete=False,
            epoch=epoch.isoformat(),
            epoch_jd=f"{epoch_jd:.1f}",
            orientation_count=len(orientation_rows),
            nut_prec_body_count=len(nut_prec_coeffs),
            nut_prec_angle_owner_count=len(nut_prec_angles),
            radii_count=len(radii_rows),
            gm_count=len(gm_rows),
            gravity_count=len(gravity_rows),
            chebyshev_body_count=cheb_count,
            chebyshev_start_year=cheb_cfg["start_year"],
            chebyshev_end_year=cheb_cfg["end_year"],
            chebyshev_chunk_years=cheb_cfg["chunk_years"],
        )

    def _classify_bodies(self, kernel_paths: list[Path]) -> list[MajorBody]:
        """Enumerate SPK bodies + classify each via NAIF/Horizons aliases.

        Returns the full list (incl. asteroids/comets the Chebyshev extractor
        needs); caller filters by object_type for element extraction.
        """
        spk_ids = self._enumerate_spk_bodies(kernel_paths)
        all_ids = spk_ids | set(_EXTRA_NAIF_IDS)
        horizons_names = load_horizons_names(self.out_dir)

        bodies: list[MajorBody] = []
        for naif_id in sorted(all_ids):
            alias = resolve_name(naif_id, horizons_names)
            try:
                obj_type, parent_id = classify_object(
                    naif_id, alias.name or "", alias.name or ""
                )
            except ValueError:
                logger.warning(
                    "Skipping unclassifiable body %d (%s)", naif_id, alias.name
                )
                continue
            bodies.append(
                MajorBody(
                    name=alias.name,
                    naif_id=naif_id,
                    parent_id=parent_id,
                    object_type=obj_type,
                    designation=alias.designation,
                    iau_roman_designation=alias.iau_roman_designation,
                    naif_id_extended=alias.naif_id_extended,
                )
            )
        return bodies

    def _extract_orbital_rows(
        self, bodies: list[MajorBody], et: float, epoch_jd: float
    ) -> tuple[list[dict], list[tuple[int, int, float]]]:
        """Compute Keplerian elements per body for bodies.csv.

        Returns (rows, moon_chunk_targets). Moon-chunk targets are the
        non-whitelisted moons whose single-epoch Method C fit succeeded —
        the caller passes them to `_extract_moon_chunks` for the sidecar
        windowed-fit pass.
        """
        rows: list[dict] = []
        moon_chunk_targets: list[tuple[int, int, float]] = []
        gm_sun = spiceypy.bodvrd("10", "GM", 1)[1][0]

        for body in tqdm(bodies, desc="SPICE elements", unit="body"):
            # SSB is the coordinate origin — no orbit to compute
            if body.naif_id == 0:
                rows.append(_make_row(body, epoch_jd, _ZERO_ROW))
                continue

            gm = self._orbital_gm(body, gm_sun)
            if gm is None:
                continue  # skip: parent GM missing (already logged)
            if gm == 0.0:
                rows.append(_make_row(body, epoch_jd, _ZERO_ROW))
                continue

            try:
                state, _ = spiceypy.spkezr(
                    str(body.naif_id), et, "ECLIPJ2000", "NONE", str(body.parent_id)
                )
            except spiceypy.exceptions.SpiceyError:
                logger.warning(
                    "Cannot get state for %s (%d), skipping", body.name, body.naif_id
                )
                continue

            elts = self._fit_or_snapshot(
                body, state, et, gm, epoch_jd, moon_chunk_targets
            )
            rows.append(_make_row(body, epoch_jd, elts))

        return rows, moon_chunk_targets

    @staticmethod
    def _orbital_gm(body: MajorBody, gm_sun: float) -> float | None:
        """Pick the GM that drives `body`'s orbit around its parent.

        Returns the gm value, or `0.0` when the geometry has no Kepler
        reduction (planet around system barycenter with no dominant moon) and
        the caller should ship a zero-elements row, or `None` to skip the
        body entirely (parent GM missing).
        """
        # Sun orbiting the SSB: heaviest member of a many-body dance dominated
        # by Jupiter. Using GM_sun (the Sun's self-gravity) would give ecc≈1
        # for the same reason as planet-around-barycenter. Use the dominant
        # planetary-barycenter partner.
        if body.naif_id == 10:
            return dominant_partner_mu(gm_sun, list(range(1, 10))) or gm_sun

        if body.parent_id == 0:
            if body.object_type == ObjectType.barycenter and 1 <= body.naif_id <= 9:
                # Planetary-system barycenter around SSB: lighter partner of
                # the Sun in a two-body reduction,
                #   mu_eff = GM_sun^3 / (GM_sun + GM_system)^2
                # (barely differs from GM_sun but is the correct value).
                try:
                    gm_sys = spiceypy.bodvrd(str(body.naif_id), "GM", 1)[1][0]
                    return gm_sun**3 / (gm_sun + gm_sys) ** 2
                except spiceypy.exceptions.SpiceyError:
                    return gm_sun
            return gm_sun

        if (
            body.object_type in (ObjectType.planet, ObjectType.dwarf_planet)
            and 1 <= body.parent_id <= 9
        ):
            # Planet orbiting its own system barycenter: heavier member of a
            # two-body dance with its dominant moon, not an orbit in a
            # GM(barycenter) field. Using GM(barycenter) with the tiny ~km/day
            # velocity produces ecc≈1. The correct mu is
            #   mu_eff = GM_moon^3 / (GM_planet + GM_moon)^2
            try:
                gm_planet = spiceypy.bodvrd(str(body.naif_id), "GM", 1)[1][0]
            except spiceypy.exceptions.SpiceyError:
                gm_planet = None
            moon_candidates = [
                n
                for n in range(body.parent_id * 100 + 1, body.parent_id * 100 + 99)
                if n != body.naif_id
            ]
            gm = (
                dominant_partner_mu(gm_planet, moon_candidates)
                if gm_planet is not None
                else None
            )
            if gm is None:
                logger.debug(
                    "No dominant moon for %s (%d); using zero elements",
                    body.name,
                    body.naif_id,
                )
                return 0.0
            return gm

        try:
            return spiceypy.bodvrd(str(body.parent_id), "GM", 1)[1][0]
        except spiceypy.exceptions.SpiceyError:
            logger.warning(
                "No GM for parent %d of %s (%d), skipping",
                body.parent_id,
                body.name,
                body.naif_id,
            )
            return None

    @staticmethod
    def _fit_or_snapshot(
        body: MajorBody,
        state: list[float],
        et: float,
        gm: float,
        epoch_jd: float,
        moon_chunk_targets: list[tuple[int, int, float]],
    ) -> dict:
        """Resolve elements for `body`: Method C fit when applicable, else snapshot.

        For non-whitelisted moons of major planets, tries the secular
        Keplerian fit first (captures J2/J4 drift) and records the body as a
        moon-chunk target on success. Falls through to a single-epoch
        osculating snapshot otherwise. Returns the element dict (zero-row
        when the geometry is degenerate).
        """
        if (
            body.object_type == ObjectType.moon
            and (body.name or "").lower() not in CHEBYSHEV_MOON_WHITELIST
            and 1 <= body.parent_id <= 9
        ):
            fit = fit_moon_mean_elements(body.naif_id, body.parent_id, et, gm)
            if fit is not None:
                elts, res_rms = fit
                moon_chunk_targets.append((body.naif_id, body.parent_id, gm))
                res_arcmin = math.degrees(res_rms) * 60
                if res_arcmin > METHOD_C_RESIDUAL_WARN_ARCMIN:
                    logger.warning(
                        "%s (%d): mean-element fit residual %.0f′ exceeds %.0f′ "
                        "— linear secular model inadequate (likely close-in "
                        "shepherd, co-orbital, or mean-motion resonance). "
                        "Shipping fitted elements but ~1e5 km position error "
                        "expected; body would benefit from Chebyshev whitelist.",
                        body.name,
                        body.naif_id,
                        res_arcmin,
                        METHOD_C_RESIDUAL_WARN_ARCMIN,
                    )
                return elts

        snap = state_to_elements(list(state), et, gm)
        if snap is None:
            # Planet nearly coincident with its barycenter (moons too small to
            # shift the center of mass) — use zero elements.
            logger.debug(
                "Degenerate orbit for %s (%d), using zero elements",
                body.name,
                body.naif_id,
            )
            return dict(_ZERO_ROW)
        if (
            body.object_type in (ObjectType.planet, ObjectType.dwarf_planet)
            and 1 <= body.parent_id <= 9
            and snap["EC"] > 0.6
        ):
            # Single-dominant-moon mu approximation failed — likely a system
            # with multiple comparable moons (Uranus, Jupiter) whose
            # barycenter wobble isn't a Kepler orbit.
            logger.info(
                "Non-Keplerian barycenter wobble for %s (%d), zeroing (got ecc=%.3f)",
                body.name,
                body.naif_id,
                snap["EC"],
            )
            return dict(_ZERO_ROW)
        # Pure osculating snapshot — no secular drift terms apply.
        return {**snap, "OM_DOT": 0.0, "W_DOT": 0.0}

    def _enumerate_spk_bodies(self, kernel_paths: list[Path]) -> set[int]:
        """Get all body NAIF IDs covered by loaded SPK kernels."""
        all_ids: set[int] = set()
        for path in kernel_paths:
            if path.suffix == ".bsp":
                all_ids |= spk_targets(path)
        return all_ids

    def _extract_moon_chunks(
        self,
        targets: list[tuple[int, int, float]],
    ) -> int:
        """Compute time-chunked Method C secular elements for non-whitelisted moons.

        For each (naif_id, parent_id, mu) target, fits a per-chunk linear
        secular model on a 6-month grid spanning the configured Chebyshev
        year range. Writes one `.npz` per moon under `moon_chunks/<naif_id>.npz`
        with arrays `chunk_midpoints_jd` (shape (n_chunks,)) and `elements`
        (shape (n_chunks, 9)).

        Returns the per-moon chunk count (uniform across all moons).
        """
        cheb_cfg = load_chebyshev_config()
        start_year = int(cheb_cfg["start_year"])
        end_year = int(cheb_cfg["end_year"])
        chunk_years = MOON_CHUNK_YEARS
        chunk_days = chunk_years * DAYS_PER_YEAR

        n_chunks = max(1, math.ceil((end_year - start_year) / chunk_years))
        start_jd = year_to_jd(start_year)
        chunk_midpoints_jd = [
            start_jd + (i + 0.5) * chunk_days for i in range(n_chunks)
        ]

        out_dir = self.out_dir / "moon_chunks"
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(exist_ok=True)

        skipped = 0
        for naif_id, parent_id, mu in tqdm(targets, desc="Moon chunks", unit="body"):
            result = fit_moon_chunked_elements(
                naif_id, parent_id, mu, chunk_midpoints_jd
            )
            if result is None:
                skipped += 1
                continue
            midpoints, elements = result
            np.savez(
                out_dir / f"{naif_id}.npz",
                chunk_midpoints_jd=midpoints,
                elements=elements.astype(np.float32),
                meta=np.array([naif_id, parent_id, n_chunks], dtype=np.int64),
            )

        if skipped:
            logger.warning(
                "Moon chunks: %d/%d targets skipped (degenerate orbit or "
                "missing SPK coverage in fit window)",
                skipped,
                len(targets),
            )
        return n_chunks

    def _write_csv(self, name: str, fieldnames: list[str], rows: list[dict]) -> None:
        """Write `rows` to `out_dir/name` as CSV with the given fieldnames."""
        path = self.out_dir / name
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Saved %d records -> %s", len(rows), name)

    def _write_nutation(
        self,
        coefficients: dict[int, dict[str, list[float]]],
        angles: dict[int, list[float]],
    ) -> None:
        """Dump PCK nutation terms as two JSON files (orjson refuses int keys)."""
        (self.out_dir / "nut_prec.json").write_bytes(
            orjson.dumps(
                {
                    str(naif_id): coeffs
                    for naif_id, coeffs in sorted(coefficients.items())
                }
            )
        )
        (self.out_dir / "nut_prec_angles.json").write_bytes(
            orjson.dumps(
                {str(owner_id): vals for owner_id, vals in sorted(angles.items())}
            )
        )
        logger.info(
            "Saved nutation terms: %d bodies, %d angle owners",
            len(coefficients),
            len(angles),
        )
