"""Read body-keyed PCK pool variables (orientation, radii, GM, harmonics).

All functions enumerate the SPICE pool for `BODY*_<KEY>` matches and emit
rows keyed by the canonical NAIF ID. Mission PCKs use non-standard NAIF
conventions for asteroids; `_canonical_naif` normalizes those — see its
docstring for the rules.
"""

import logging
import re
from pathlib import Path

import spiceypy

from space_map_data.utils.naif import nut_prec_owner

logger = logging.getLogger(__name__)

# pck00011 Galileo-flyby asteroid ids → SBDB-canonical naif (2_000_000 + number).
_GALILEO_ERA_NAIF = {9511010: 2000951, 2431010: 2000243}

# The rank of each id form of a numbered body in a GM kernel: the canonical id,
# then the SBDB spkid, then the primary of a binary (`9_20xxxxxx`). `gm_de440`
# gives the spkid to the system of a binary. The probe export fits its chunks
# with that GM, and the frontend reads it under the canonical id.
_GM_FORM_CANONICAL, _GM_FORM_SPKID, _GM_FORM_PRIMARY = range(3)


def _data_lines(text: str) -> str:
    """The data blocks of a text kernel, without its comment blocks."""
    lines: list[str] = []
    in_data = False
    for line in text.splitlines():
        marker = line.strip()
        if marker.startswith("\\begindata"):
            in_data = True
        elif marker.startswith("\\begintext"):
            in_data = False
        elif in_data:
            lines.append(line)
    return "\n".join(lines)


def defining_kernels(key: str) -> dict[int, str]:
    """The file name of the loaded text kernel that sets ``BODY<n>_<key>``, by n.

    SPICE keeps the value of the kernel loaded last, so the last file wins.
    """
    assignment = re.compile(rf"BODY(-?\d+)_{key}\s*\+?=")
    out: dict[int, str] = {}
    for index in range(spiceypy.ktotal("TEXT")):
        path = Path(spiceypy.kdata(index, "TEXT", fillen=1024)[0])
        data = _data_lines(path.read_text(errors="replace"))
        for match in assignment.finditer(data):
            out[int(match.group(1))] = path.name
    return out


def extract_orientation() -> list[dict]:
    """Extract PCK orientation data (full IAU rotation polynomial) for all bodies that have it.

      α(T) = pole_ra_0 + pole_ra_1·T   (T in Julian centuries since J2000)
      δ(T) = pole_dec_0 + pole_dec_1·T
      W(d) = w0 + w1·d + w2·d²         (d in days since J2000)

    Nutation/precession sums are extracted separately (see `extract_nutation`).
    Queries the pool for BODY*_POLE_RA rather than a fixed set, so any
    asteroid/comet with orientation data in the PCK is picked up automatically.
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
    dict[int, dict[str, list[float]]], dict[int, list[float]], dict[int, int]
]:
    """Extract PCK nutation/precession terms for the full IAU rotation model.

    Per body:
      α += Σ ra[i]  · sin(θ_i(T))
      δ += Σ dec[i] · cos(θ_i(T))
      W += Σ pm[i]  · sin(θ_i(T))
    where θ_i(T) is a polynomial in T (Julian centuries) with degree+1
    coefficients per angle in `angles` (degrees, deg/century, deg/century²).

    The angles array is defined once per "owner" body: the planetary system
    barycenter (1..9). A body's owner is `naif_id // 100`, or `naif_id` when
    < 100. The polynomial degree is 1 unless the kernel sets
    `BODY<owner>_MAX_PHASE_DEGREE`. pck00011 sets 2 for Mars.

    Returns (coefficients, angles, phase_degrees):
      coefficients:  {naif_id: {"ra": [...], "dec": [...], "pm": [...]}}
      angles:        {owner_naif_id: [θ₀_1, θ₁_1, (θ₂_1,) θ₀_2, ...]}
      phase_degrees: {owner_naif_id: degree}, only for owners the kernel sets
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

    phase_degrees: dict[int, int] = {}
    # A kernel before pck00011 sets no degree, and gnpool raises when nothing matches.
    try:
        degree_vars = spiceypy.gnpool("BODY*_MAX_PHASE_DEGREE", 0, 1000)
    except spiceypy.exceptions.NotFoundError:
        degree_vars = []
    for var in degree_vars:
        m = re.match(r"BODY(-?\d+)_MAX_PHASE_DEGREE$", var)
        if not m:
            continue
        owner_id = int(m.group(1))
        degree = spiceypy.bodvrd(str(owner_id), "MAX_PHASE_DEGREE", 1)[1][0]
        phase_degrees[owner_id] = int(degree)

    # Sanity-check: every body with coefficients should have a resolvable owner,
    # and per-channel arrays may not exceed the angle count (they may be shorter —
    # bodies often use only the first few system angles).
    for naif_id, coeffs in coefficients.items():
        owner_id = nut_prec_owner(naif_id)
        if owner_id not in angles:
            logger.warning(
                "NUT_PREC coefficients for body %d reference owner %d which "
                "has no NUT_PREC_ANGLES; rotation sums for this body will be "
                "ignored downstream",
                naif_id,
                owner_id,
            )
            continue
        stride = phase_degrees.get(owner_id, 1) + 1
        n_angles = len(angles[owner_id]) // stride
        for kind in ("ra", "dec", "pm"):
            if len(coeffs[kind]) > n_angles:
                logger.warning(
                    "Body %d NUT_PREC_%s has %d coefficients but owner %d only "
                    "defines %d angles; extra coefficients will be ignored",
                    naif_id,
                    kind.upper(),
                    len(coeffs[kind]),
                    owner_id,
                    n_angles,
                )

    return coefficients, angles, phase_degrees


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
    ``kernel`` is the file name of the kernel that sets the value.
    """
    kernels = defining_kernels("RADII")
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
            "kernel": kernels.get(naif_id),
        }
    return sorted(rows_by_canonical.values(), key=lambda r: r["naif_id"])


def extract_gms() -> list[dict]:
    """Extract PCK gravitational parameters (GM, km^3/s^2) for every body.

    Rows are keyed by the canonical NAIF id, as `extract_radii` keys them. A
    body that a kernel gives in several id forms keeps the GM of its best form
    (`_GM_FORM_CANONICAL` first), so a binary keeps the GM of its system. A GM
    of 0 is no value. ``kernel`` is the file name of the kernel that sets the
    value. When the kept GM is that of a binary system and the kernel also
    gives its primary (`9_20xxxxxx`), ``primary_gm_km3_s2`` and
    ``primary_kernel`` are the GM of the primary alone and its kernel.

    SPICE has no GM for the SSB (naif 0), but downstream consumers walk the
    parent chain through it for chebyshev-only bodies. So a row for naif 0
    takes the Sun's GM, with no kernel: it is not a body value.
    """
    kernels = defining_kernels("GM")
    matches = spiceypy.gnpool("BODY*_GM", 0, 5000)
    naif_ids: set[int] = set()
    for var in matches:
        m = re.match(r"BODY(-?\d+)_GM", var)
        if m:
            naif_ids.add(int(m.group(1)))

    best: dict[int, tuple[int, int, dict]] = {}
    primaries: dict[int, tuple[float, str | None]] = {}
    skipped: list[int] = []
    for naif_id in sorted(naif_ids):
        try:
            gm = spiceypy.bodvrd(str(naif_id), "GM", 1)[1][0]
        except spiceypy.exceptions.SpiceyError:
            skipped.append(naif_id)
            continue
        if gm == 0:
            logger.debug("GM of %d is 0 in %s: no value", naif_id, kernels.get(naif_id))
            continue
        canonical = _canonical_naif(naif_id)
        if canonical is None:
            continue
        form = _gm_form(naif_id, canonical)
        if form == _GM_FORM_PRIMARY:
            primaries[canonical] = (gm, kernels.get(naif_id))
        row = {"naif_id": canonical, "gm_km3_s2": gm, "kernel": kernels.get(naif_id)}
        kept = best.get(canonical)
        if kept is None or form < kept[0]:
            if kept is not None:
                logger.debug("GM of %d replaces that of %d", naif_id, kept[1])
            best[canonical] = (form, naif_id, row)
        else:
            logger.debug("GM of %d loses to that of %d", naif_id, kept[1])

    if skipped:
        logger.warning(
            "GM extraction skipped %d bodies (bodvrd failed): %s",
            len(skipped),
            skipped,
        )

    rows: list[dict] = []
    for canonical, (form, _, row) in sorted(best.items()):
        primary = primaries.get(canonical) if form != _GM_FORM_PRIMARY else None
        primary_gm, primary_kernel = primary or (None, None)
        rows.append(
            {**row, "primary_gm_km3_s2": primary_gm, "primary_kernel": primary_kernel}
        )
    sun = best.get(10)
    if sun is not None:
        rows.insert(
            0,
            {
                "naif_id": 0,
                "gm_km3_s2": sun[2]["gm_km3_s2"],
                "kernel": None,
                "primary_gm_km3_s2": None,
                "primary_kernel": None,
            },
        )
    else:
        logger.warning("Could not read Sun GM; SSB row not synthesized")
    return rows


def _gm_form(naif_id: int, canonical: int) -> int:
    """The rank of the id form ``naif_id`` among the forms of ``canonical``."""
    if 920_000_000 <= naif_id < 930_000_000:
        return _GM_FORM_PRIMARY
    if naif_id == canonical:
        return _GM_FORM_CANONICAL
    return _GM_FORM_SPKID


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

    Some mission PCKs use non-standard asteroid NAIF conventions:

    * **Lucy / DART** binary primary: `9_<spkid>` (e.g. `BODY920000617_RADII` =
      Patroclus) → NAIF `2_000_000 + n` (Patroclus → 2000617).
    * **Lucy** solo asteroids: bare SBDB spkid `20_000_000 + n` (e.g.
      `BODY20052246_RADII` for Donaldjohanson, likely an oversight since
      Bennu/Ryugu use the standard form) → `2_000_000 + n`.
    * **Lucy / DART** binary secondary: `1_<spkid>` (e.g. Dimorphos) — passes
      through unchanged, since SBDB moon ingest assigns Object.naif_id == spkid
      in this range.
    """
    # Galileo-era asteroid ids in pck00011 (Gaspra, Ida) predate the SBDB
    # 2_000_000 + number convention; map explicitly so their pole data lands on
    # the Object rows. Ambiguous to generalise (2431010 also reads as canonical
    # asteroid #431010), so the pair is enumerated.
    galileo = _GALILEO_ERA_NAIF.get(naif_id)
    if galileo is not None:
        return galileo
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
