"""The Gaia or Hipparcos star that a host without a Gaia DR3 id or HIP number is.

Such a host matches no star by id, and its catalogue gives no G
magnitude for the position match in most cases, so it would become a second
star beside its Gaia or Hipparcos twin. A twin is the only star within
`RADIUS` of the host, positioned by Gaia or Hipparcos, whose parallax
agrees with the catalogue's parallax or distance and whose magnitude agrees
with the catalogue's G, V or K. The host then claims the twin's DR3 id or
HIP number. As in the position match, a twin farther than `NEAR` needs an
agreeing magnitude. So does a twin of a companion star (B, C, …): catalogues
often give it the position and parallax of its primary.

The candidates are the stars of the registry and of the passes before the
hosts, and their values are those the table merge would give them, so a first
ingest finds the same twins as the next one.
"""

import math
from collections import Counter
from collections.abc import Container, Iterable
from dataclasses import dataclass, field

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import IngestRun
from space_map_data.extrasolar.sources.gaia import GAIA_DR3, GAIA_DR3_NAMED
from space_map_data.extrasolar.sources.hipparcos import HIPPARCOS, HIPPARCOS_1997
from space_map_data.extrasolar.sources.names import IAU_WGSN
from space_map_data.extrasolar.sources.simbad import SIMBAD
from space_map_data.extrasolar.tables import POINT_SOURCE

RADIUS = 5.0
NEAR = 3.0
PARALLAX_SIGMA = 3.0
# Catalogue distances are often photometric or older than Gaia.
DISTANCE_TOLERANCE = 0.2
MAG_TOLERANCE = 0.5
# Riello et al. 2021, table 8: G − V and G − Ks as polynomials in BP − RP,
# lowest power first, with their ranges of BP − RP (table 7).
G_MINUS_V = ((-0.02704, 0.01424, -0.2156, 0.01426), (-0.5, 5.0))
G_MINUS_K = ((-0.0981, 2.089, -0.1579), (-0.5, 2.5))

TWIN_SOURCES = (GAIA_DR3.name, GAIA_DR3_NAMED.name, HIPPARCOS.name)
# Stars that count as candidates but are never twins.
OTHER_SOURCES = (IAU_WGSN.name, SIMBAD.name, HIPPARCOS_1997.name)
CLAIMS = (
    (GAIA_DR3.catalogue, GAIA_DR3.release),
    (HIPPARCOS.catalogue, HIPPARCOS.release),
)
COLUMNS = [
    "parallax",
    "parallax_error",
    "phot_g_mean_mag",
    "phot_bp_mean_mag",
    "phot_rp_mean_mag",
    "v_mag",
]

type Claim = tuple[str, str, str]


@dataclass(frozen=True)
class Target:
    """A host to find a twin for, with its J2016.0 position."""

    key: int
    name: str
    ra: float
    dec: float
    parallax: float | None = None
    parallax_error: float | None = None
    distance: float | None = None
    g_mag: float | None = None
    v_mag: float | None = None
    k_mag: float | None = None
    companion: bool = False


@dataclass(frozen=True)
class Twin:
    claim: Claim
    separation: float
    # The checks that agreed.
    checks: tuple[str, ...]


@dataclass
class Found:
    twins: dict[int, Twin] = field(default_factory=dict)
    # The lone candidates that another host holds, by target.
    held: dict[int, Twin] = field(default_factory=dict)
    # The targets with a lone candidate that is no twin, and why.
    refused: list[str] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)

    def listed(self, targets: Iterable[Target]) -> list[str]:
        names = {target.key: target.name for target in targets}
        return [
            f"{names[key]} → {'/'.join(twin.claim)} ({twin.separation:.2f}″,"
            f" {', '.join(twin.checks)})"
            for key, twin in sorted(self.twins.items(), key=lambda kv: names[kv[0]])
        ]


def find(run: IngestRun, targets: list[Target], held: Container[Claim] = ()) -> Found:
    """The twin of each target that has one.

    A candidate that `held` names by its claim belongs to another host: a
    target never takes it.
    """
    found = Found()
    nearby = _nearby(run, targets)
    lone = {
        target.key: stars[0]
        for target in targets
        if len(stars := nearby.get(target.key, [])) == 1
    }
    for target in targets:
        count = len(nearby.get(target.key, []))
        found.counts[
            f"stars within {RADIUS:g}″: {min(count, 2)}{'+' * (count > 1)}"
        ] += 1
    rows, claims = _candidates(run, {key for key, _, _ in lone.values()})

    wanted: Counter = Counter()
    picked: dict[int, Twin] = {}
    for target in targets:
        if target.key not in lone:
            continue
        key, separation, source = lone[target.key]
        claim = claims.get(key)
        row = rows.get(key)
        why = None
        if source not in TWIN_SOURCES or claim is None or row is None:
            why = f"positioned by {source}"
        elif claim in held:
            why = "another host holds it"
            found.held[target.key] = Twin(claim, separation, ())
        else:
            checks, failed = _checks(target, row)
            if failed:
                why = "disagrees: " + ", ".join(failed)
            elif not checks:
                why = "nothing to compare"
            elif separation > NEAR and checks == ("parallax",):
                why = f"farther than {NEAR:g}″ with no magnitude"
            elif target.companion and checks == ("parallax",):
                why = "a companion star with no magnitude"
            else:
                picked[target.key] = Twin(claim, separation, checks)
                wanted[claim] += 1
                continue
        found.counts[f"lone candidate refused: {why.split(':')[0]}"] += 1
        star = "/".join(claim) if claim else f"a {source} star"
        found.refused.append(f"{target.name} → {star} ({separation:.2f}″): {why}")
    names = {target.key: target.name for target in targets}
    for key, twin in picked.items():
        if wanted[twin.claim] > 1:
            found.counts["lone candidate refused: several hosts want it"] += 1
            found.refused.append(
                f"{names[key]} → {'/'.join(twin.claim)}: several hosts want it"
            )
        else:
            found.twins[key] = twin
    found.counts["twins"] = len(found.twins)
    return found


def _nearby(
    run: IngestRun, targets: list[Target]
) -> dict[int, list[tuple[int, float, str]]]:
    """The stars within RADIUS of each target, as (key, separation, source),
    but literature stars: those are hosts themselves, this target among
    them."""
    if not targets:
        return {}
    ra = np.array([t.ra for t in targets])
    dec = np.array([t.dec for t in targets])
    row, low, high = sky.disc_ranges(ra, dec, np.full(ra.size, RADIUS))
    by_region: dict[int, set[int]] = {}
    for at, a, b in zip(row.tolist(), low.tolist(), high.tolist()):
        for region in sky.regions_of_ranges(np.array([a]), np.array([b])):
            by_region.setdefault(region, set()).add(at)
    found: dict[int, list[tuple[int, float, str]]] = {}
    for region in sorted(by_region):
        objects = run.objects(region)
        keep = pc.is_in(objects["source"], pa.array(TWIN_SOURCES + OTHER_SOURCES))
        objects = objects.filter(keep)
        if not objects.num_rows:
            continue
        order = np.argsort(objects["dec"].to_numpy())
        star_dec = objects["dec"].to_numpy()[order]
        star_ra = objects["ra"].to_numpy()[order]
        star_key = objects["key"].to_numpy()[order]
        source = objects["source"].take(pa.array(order)).to_pylist()
        reach = RADIUS / 3600
        for at in sorted(by_region[region]):
            lo, hi = np.searchsorted(star_dec, [dec[at] - reach, dec[at] + reach])
            separation = sky.separation(
                ra[at], dec[at], star_ra[lo:hi], star_dec[lo:hi]
            )
            for j in np.flatnonzero(separation <= RADIUS).tolist():
                found.setdefault(targets[at].key, []).append(
                    (int(star_key[lo + j]), float(separation[j]), source[lo + j])
                )
    return found


def _candidates(
    run: IngestRun, keys: set[int]
) -> tuple[dict[int, dict], dict[int, Claim]]:
    """The Point source values of these stars, merged by source order as the
    table merges them, and the DR3 id or HIP number each holds, DR3 first."""
    rows: dict[int, dict] = {}
    claims: dict[int, Claim] = {}
    if not keys:
        return rows, claims
    groups = [group for group in POINT_SOURCE.groups if set(group.names) & set(COLUMNS)]
    found = run.pass_rows(
        np.array(sorted(keys), np.int64), [n for g in groups for n in g.names]
    )
    by_source = {
        name: {row["key"]: row for row in reversed(table.to_pylist())}
        for name, table in found.items()
    }
    for key in keys:
        row: dict = {}
        for group in groups:
            chosen = next(
                (
                    candidate
                    for name in group.sources
                    if (candidate := by_source.get(name, {}).get(key)) is not None
                    and any(candidate.get(n) is not None for n in group.names)
                ),
                {},
            )
            row |= {n: chosen.get(n) for n in group.names if n in COLUMNS}
        if any(value is not None for value in row.values()):
            rows[key] = row
    for pair in reversed(CLAIMS):
        for name, source in run.sources.items():
            if (source.catalogue, source.release) != pair:
                continue
            for key, candidate in by_source.get(name, {}).items():
                claims[key] = (*pair, candidate["catalogue_id"])
    return rows, claims


def _checks(target: Target, row: dict) -> tuple[tuple[str, ...], list[str]]:
    """The checks that agree and those that disagree."""
    agreed, failed = [], []
    parallax = _parallax(target, row)
    if parallax is not None:
        (agreed if parallax else failed).append("parallax")
    magnitudes = _magnitudes(target, row)
    if any(magnitudes.values()):
        agreed.append(next(band for band, ok in magnitudes.items() if ok))
    elif magnitudes:
        failed.append("/".join(magnitudes))
    return tuple(agreed), failed


def _parallax(target: Target, row: dict) -> bool | None:
    twin, twin_error = row["parallax"], row["parallax_error"] or 0.0
    if twin is None:
        return None
    if target.parallax is not None:
        error = target.parallax_error or 0.1 * abs(target.parallax)
        return abs(target.parallax - twin) <= PARALLAX_SIGMA * math.hypot(
            error, twin_error
        )
    if target.distance:
        expected = 1000 / target.distance
        return abs(expected - twin) <= max(
            PARALLAX_SIGMA * twin_error, DISTANCE_TOLERANCE * expected
        )
    return None


def _magnitudes(target: Target, row: dict) -> dict[str, bool]:
    """Each band the catalogue gives that compares with the twin: agrees?"""
    g = row["phot_g_mean_mag"]
    bp, rp = row["phot_bp_mean_mag"], row["phot_rp_mean_mag"]
    colour = None if bp is None or rp is None else bp - rp
    found = {}
    if g is not None and target.g_mag is not None:
        found["G"] = abs(target.g_mag - g) <= MAG_TOLERANCE
    for band, value, relation in (
        ("V", target.v_mag, G_MINUS_V),
        ("K", target.k_mag, G_MINUS_K),
    ):
        expected = _g_from(value, colour, relation)
        if g is not None and expected is not None:
            found[band] = abs(expected - g) <= MAG_TOLERANCE
    # A Hipparcos star without Gaia photometry has its own V.
    if g is None and row["v_mag"] is not None and target.v_mag is not None:
        found["V"] = abs(target.v_mag - row["v_mag"]) <= MAG_TOLERANCE
    return found


def _g_from(
    value: float | None,
    colour: float | None,
    relation: tuple[tuple[float, ...], tuple[float, float]],
) -> float | None:
    coefficients, (low, high) = relation
    if value is None or colour is None or not low < colour < high:
        return None
    return value + sum(c * colour**n for n, c in enumerate(coefficients))
