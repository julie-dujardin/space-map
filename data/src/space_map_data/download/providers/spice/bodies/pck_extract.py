"""Read body-keyed PCK pool variables (orientation, radii, GM, harmonics).

All functions enumerate the SPICE pool for `BODY*_<KEY>` matches and emit
rows keyed by the canonical NAIF ID. Mission PCKs use non-standard NAIF
conventions for asteroids; `_canonical_naif` normalizes those — see its
docstring for the rules.
"""

import logging
import re

import spiceypy

logger = logging.getLogger(__name__)


def extract_orientation() -> list[dict]:
    """Extract PCK orientation data for all bodies that have it.

    Returns the full IAU rotation polynomial:
      α(T) = pole_ra_0 + pole_ra_1·T   (T in Julian centuries since J2000)
      δ(T) = pole_dec_0 + pole_dec_1·T
      W(d) = w0 + w1·d + w2·d²         (d in days since J2000)

    Nutation/precession sums are extracted separately (see `extract_nutation`).
    Queries the kernel pool for all BODY*_POLE_RA variables rather than
    iterating a fixed set, so asteroids and comets with orientation data
    in the PCK are included automatically.
    """
    # Find all body IDs with POLE_RA in the kernel pool. Negative IDs
    # (spacecraft + instruments) are excluded — see `extract_radii` for
    # the rationale; the same generic-wins + canonical-naif policy applies.
    matches = spiceypy.gnpool("BODY*_POLE_RA", 0, 5000)
    naif_ids: set[int] = set()
    for var in matches:
        m = re.match(r"BODY(\d+)_POLE_RA", var)
        if m:
            naif_ids.add(int(m.group(1)))

    rows_by_canonical: dict[int, dict] = {}
    for naif_id in sorted(naif_ids):
        canonical = _canonical_naif(naif_id)
        if canonical is None:
            continue
        if canonical in rows_by_canonical:
            continue
        try:
            pole_ra = spiceypy.bodvrd(str(naif_id), "POLE_RA", 3)[1]
            pole_dec = spiceypy.bodvrd(str(naif_id), "POLE_DEC", 3)[1]
            pm = spiceypy.bodvrd(str(naif_id), "PM", 3)[1]
        except spiceypy.exceptions.SpiceyError:
            continue
        rows_by_canonical[canonical] = {
            "naif_id": canonical,
            "pole_ra_0": pole_ra[0],
            "pole_ra_1": pole_ra[1],
            "pole_dec_0": pole_dec[0],
            "pole_dec_1": pole_dec[1],
            "w0": pm[0],
            "w1": pm[1],
            "w2": pm[2],
        }
    return sorted(rows_by_canonical.values(), key=lambda r: r["naif_id"])


def extract_nutation() -> tuple[
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
                values = spiceypy.bodvrd(str(naif_id), f"NUT_PREC_{key}", n_elements)[1]
            except spiceypy.exceptions.SpiceyError as exc:
                logger.warning("Failed reading %s: %s", var, exc)
                continue
            # Coerce numpy.float64 → float so orjson can serialize.
            coefficients.setdefault(naif_id, {"ra": [], "dec": [], "pm": []})[kind] = [
                float(v) for v in values
            ]

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
            values = spiceypy.bodvrd(str(owner_id), "NUT_PREC_ANGLES", n_elements)[1]
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


def extract_radii() -> list[dict]:
    """Extract PCK triaxial radii (a, b, c in km) for all bodies that have them.

    Enumerated independently from orientation — a body can have radii
    without pole data, and vice versa. Only positive NAIF IDs are kept:
    negative IDs are spacecraft and instrument footprints (e.g. JUNO MWR
    antennae publish `BODY-28000xxx_RADII` for beam dimensions), not body
    shapes. Same filter applies in `extract_orientation`.

    Numbered asteroids are emitted under the canonical NAIF convention
    (`2_000_000 + n`). The Lucy mission's per-target PCKs use the SBDB
    spkid form (`20_000_000 + n`, e.g. `BODY20052246_RADII` for
    Donaldjohanson); we map those down so downstream `Object.naif_id`
    lookups match. If both forms are present in the pool, the NAIF-
    canonical one wins (preserves the generic-PCK > mission-PCK policy).
    """
    matches = spiceypy.gnpool("BODY*_RADII", 0, 5000)
    naif_ids: set[int] = set()
    for var in matches:
        m = re.match(r"BODY(\d+)_RADII", var)
        if m:
            naif_ids.add(int(m.group(1)))

    rows_by_canonical: dict[int, dict] = {}
    for naif_id in sorted(naif_ids):
        canonical = _canonical_naif(naif_id)
        if canonical is None:
            continue
        if canonical in rows_by_canonical:
            continue  # NAIF-canonical form was already emitted first
        try:
            radii = spiceypy.bodvrd(str(naif_id), "RADII", 3)[1]
        except spiceypy.exceptions.SpiceyError:
            continue
        rows_by_canonical[canonical] = {
            "naif_id": canonical,
            "radius_a_km": radii[0],
            "radius_b_km": radii[1],
            "radius_c_km": radii[2],
        }
    return sorted(rows_by_canonical.values(), key=lambda r: r["naif_id"])


def extract_gms() -> list[dict]:
    """Extract PCK gravitational parameters (GM, km^3/s^2) for every body.

    Sourced from `gm_de440.tpc`. SPICE has no GM for the SSB (naif 0), but
    downstream consumers walk the parent chain through it for chebyshev-only
    bodies — so we synthesize a row for naif 0 reusing the Sun's GM (the
    SSB-relative motion of bodies orbiting the Sun is what matters there).
    """
    matches = spiceypy.gnpool("BODY*_GM", 0, 5000)
    naif_ids: set[int] = set()
    for var in matches:
        m = re.match(r"BODY(-?\d+)_GM", var)
        if m:
            naif_ids.add(int(m.group(1)))

    rows: list[dict] = []
    skipped: list[int] = []
    for naif_id in sorted(naif_ids):
        try:
            gm = spiceypy.bodvrd(str(naif_id), "GM", 1)[1][0]
        except spiceypy.exceptions.SpiceyError:
            skipped.append(naif_id)
            continue
        rows.append({"naif_id": naif_id, "gm_km3_s2": gm})

    if skipped:
        logger.warning(
            "GM extraction skipped %d bodies (bodvrd failed): %s",
            len(skipped),
            skipped,
        )

    try:
        gm_sun = spiceypy.bodvrd("10", "GM", 1)[1][0]
        rows.insert(0, {"naif_id": 0, "gm_km3_s2": gm_sun})
    except spiceypy.exceptions.SpiceyError:
        logger.warning("Could not read Sun GM; SSB row not synthesized")

    return rows


def extract_gravity_field() -> list[dict]:
    """Extract per-body gravity harmonics + equatorial radius from the PCK pool.

    Reads BODY<n>_J2/J3/J4 (from `Gravity.tpc`) and the equatorial radius
    BODY<n>_RADII[0] (from the standard PCK). Used downstream to compute
    analytic J2 secular precession rates Ω̇ and ω̇ for moons that don't
    get full Chebyshev coverage.

    A row is emitted for every body with at least one of J2/J3/J4 defined,
    even if the equatorial radius is missing — the consumer decides how to
    handle a missing R_eq.
    """
    naif_ids: set[int] = set()
    for key in ("J2", "J3", "J4"):
        for var in spiceypy.gnpool(f"BODY*_{key}", 0, 1000):
            m = re.match(rf"BODY(-?\d+)_{key}$", var)
            if m:
                naif_ids.add(int(m.group(1)))

    rows = []
    for naif_id in sorted(naif_ids):
        row: dict[str, int | float | None] = {"naif_id": naif_id}
        for key in ("J2", "J3", "J4"):
            try:
                row[key.lower()] = float(spiceypy.bodvrd(str(naif_id), key, 1)[1][0])
            except spiceypy.exceptions.SpiceyError:
                row[key.lower()] = None
        try:
            row["r_eq_km"] = float(spiceypy.bodvrd(str(naif_id), "RADII", 3)[1][0])
        except spiceypy.exceptions.SpiceyError:
            row["r_eq_km"] = None
        rows.append(row)
    return rows


def _canonical_naif(naif_id: int) -> int | None:
    """Normalize numbered-asteroid NAIF IDs to the canonical form used by Object rows.

    Some mission PCKs use non-standard NAIF ID conventions for asteroids:

    * **Lucy / DART** for the binary primary use `9_<spkid>` (e.g.
      `BODY920000617_RADII` = Patroclus, `BODY920065803_RADII` = Didymos).
      Map down to NAIF `2_000_000 + n` (Patroclus → 2000617).
    * **Lucy** for solo asteroids uses the bare SBDB spkid `20_000_000 + n`
      (e.g. `BODY20052246_RADII` for Donaldjohanson #52246) — likely an
      oversight, since Bennu/Ryugu/etc. use the standard NAIF form. Map
      down to `2_000_000 + n` (Donaldjohanson → 2052246).
    * **Lucy / DART** for the binary secondary use `1_<spkid>` (e.g.
      `BODY120000617_RADII` = Menoetius, `BODY120065803_RADII` = Dimorphos).
      SBDB moon ingest creates Object rows with `naif_id == spkid` in this
      range, so the value passes through unchanged.
    """
    # Binary primary: 9_20XXXXXX → 2_XXXXXX. Same offset as the solo form
    # plus a leading "9", so subtract (9-2) * 10^8 + 18M = 918_000_000.
    if 920_000_000 <= naif_id < 930_000_000:
        return naif_id - 918_000_000
    # Binary secondary: 1_20XXXXXX — sbdb_moons ingest assigns the same
    # value to Object.naif_id, so we pass it through.
    # Solo asteroid SBDB spkid form: 20_000_000 + n → 2_000_000 + n.
    if 20_000_000 <= naif_id < 30_000_000:
        return naif_id - 18_000_000
    return naif_id
