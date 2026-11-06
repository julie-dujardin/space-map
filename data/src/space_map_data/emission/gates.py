"""The gates of the emission build, on the shipped codes, each written to
`gates/<name>.json`.

    gate-halpha   the placed H-alpha against Finkbeiner by band and named region
    gate-wise     the far regions: sources, luminosity function, their sky
    gate-scatter  scattered over direct starlight from the Sun against Leinert, its
                  colour, its share from outside, and isotropy against
                  Henyey-Greenstein
    gate-sun      what the Sun view gains, at the band gate's exposure
    gate-tiers    `low` against `high`
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from space_map_data.dust.encode import Encoding
from space_map_data.dust.parallel import forked_map
from space_map_data.dust.sources import file_digest
from space_map_data.emission import (
    build,
    encode,
    lines,
    local,
    project,
    regions,
    scatter,
    sky,
    sources,
    views,
)
from space_map_data.extrasolar.store import write_json
from space_map_data.galaxy import volumes
from space_map_data.glow import build as glow_build
from space_map_data.glow import light

logger = logging.getLogger(__name__)

GATES_DIR = "gates"
BANDS = ((0, 2), (2, 5), (5, 10), (10, 20), (20, 40), (40, 60), (60, 90))
# Named regions (l, b, radius deg), and Barnard's Loop as an annulus about Orion's
# centre on its eastern side.
NAMED = {
    "Orion": (209.0, -19.4, 2.0),
    "Gum Nebula": (260.0, -3.0, 15.0),
    "Rosette": (206.3, -2.1, 1.0),
    "North America": (85.6, -0.7, 1.5),
    "Carina": (287.6, -0.6, 1.5),
    "Galactic centre": (0.0, 0.0, 2.0),
}
BARNARD = (207.0, -17.5, 6.0, 8.5)


def _write(out: Path, name: str, result: dict) -> None:
    write_json(out / GATES_DIR / f"{name}.json", result)
    logger.info("%s: %s", name, json.dumps(result)[:2000])


def masks(nside: int) -> dict[str, np.ndarray]:
    found = {f"abs(b) {lo}-{hi}": sky.band_mask(nside, lo, hi) for lo, hi in BANDS}
    for name, (l_deg, b_deg, r) in NAMED.items():
        found[name] = sky.disc_mask(nside, l_deg, b_deg, r)
    lo, hi = BARNARD[2], BARNARD[3]
    ring = sky.disc_mask(nside, BARNARD[0], BARNARD[1], hi) & ~sky.disc_mask(
        nside, BARNARD[0], BARNARD[1], lo
    )
    found["Barnard's Loop"] = ring & (sky.longitudes(nside) <= BARNARD[0])
    return found


def stored_halpha(out: Path, tier: str) -> project.Fetch:
    """The shipped H-alpha codes, LINEAR, then the decode."""
    raw = json.loads((out / build.ENCODING_FILE).read_text())
    encoding = Encoding(raw["halpha"][tier]["floor"], raw["halpha"][tier]["top"])
    codes = np.load(out / build.halpha_name(tier)).astype(np.float32)
    return project.cube_fetch(
        codes, local.HALF_PC, lambda grid, at: encode.linear_read(grid, encoding, at)
    )


SHIPPED = "gate.halpha.shipped.npy"
SHIPPED_RECORD = "gate.halpha.shipped.json"


def _encoding_digest(out: Path) -> str:
    return file_digest(out / build.ENCODING_FILE)


def _to_rayleigh() -> float:
    return float(lines.column_to_rayleigh(lines.display_to_emissivity(1.0)))


def halpha_gate(out: Path, workers: int) -> None:
    """Gate 1: everything placed, as seen from the Sun, against Finkbeiner."""
    nside = local.SKY_NSIDE
    nest, far = build._served()
    rays = sky.directions(nside)
    shipped, _, _ = project.from_sun(
        nest,
        far,
        stored_halpha(out, "high"),
        rays,
        local.END_PC,
        local.STEP_PC,
        workers,
    )
    shipped *= _to_rayleigh()
    found = build.read_regions(out)
    far_sky = found["sky"]
    bare = np.load(out / "sun.seen.npy")
    observed = local.finkbeiner(nside)
    wanted = local.target(observed, far_sky)
    np.save(out / SHIPPED, shipped)
    write_json(out / SHIPPED_RECORD, {"encoding": _encoding_digest(out)})
    rows = {}
    for name, m in masks(nside).items():
        f = observed[m].mean()
        placed = shipped[m] + far_sky[m]
        rows[name] = {
            "finkbeiner_R": round(float(f), 3),
            "placed_over_finkbeiner": round(float(placed.mean() / f), 3),
            "median_pixel_ratio": round(float(np.median(placed / observed[m])), 3),
            "mccallum_unscaled_over_finkbeiner": round(float(bare[m].mean() / f), 3),
            "far_regions_share": round(float(far_sky[m].mean() / f), 3),
            "scattered_share_removed": local.SCATTERED_SHARE,
            "unplaced_share": round(
                float(np.maximum(wanted[m] - shipped[m], 0).mean() / f), 3
            ),
            "over_target_share": round(
                float(np.maximum(shipped[m] - wanted[m], 0).mean() / f), 3
            ),
        }
    scale = json.loads((out / build.SCALE_FILE).read_text())
    whole = {
        "placed": float((shipped + far_sky).sum() / observed.sum()),
        "local": float(shipped.sum() / observed.sum()),
        "far": float(far_sky.sum() / observed.sum()),
        "scattered_removed": local.SCATTERED_SHARE,
        "unplaced": float(np.maximum(wanted - shipped, 0).sum() / observed.sum()),
        "mccallum_unscaled": float(bare.sum() / observed.sum()),
    }
    _write(
        out,
        "halpha",
        {
            "whole_sky": whole,
            "regions": rows,
            "factor_by_pixel": scale["factor_by_pixel"],
            "factor_by_light": scale["factor_by_light"],
            "at_limit_share": scale["at_limit_share"],
        },
    )


def power_law_index(rate: np.ndarray, lowest: float) -> tuple[float, float, int]:
    """The maximum-likelihood index of dN/dL ~ L^alpha above `lowest`, its error and
    the count."""
    above = rate[rate >= lowest]
    n = len(above)
    alpha = -(1.0 + n / np.log(above / lowest).sum())
    return float(alpha), float((-alpha - 1.0) / np.sqrt(n)), n


# Mascoop et al. 2021: single power law, 20 cm MAGPIS + VGPS, and their completeness
# in log N_ly (Fig. 2).
MASCOOP_ALPHA = (-1.75, 0.03)
MASCOOP_COMPLETE_LOG = 47.6


def wise_gate(out: Path, workers: int) -> None:
    """Gate 3: what was used, the luminosity function, the share inside the cube, and
    the far regions' sky against Finkbeiner in the plane."""
    summary = json.loads((out / build.REGIONS_FILE).read_text())
    found = build.read_regions(out)
    rate, source = found["rate"], found["source"]
    l_deg = (
        np.degrees(np.arctan2(found["position"][:, 1], found["position"][:, 0])) % 360
    )
    first = (source == 0) & (l_deg > 18) & (l_deg < 65)
    alpha, error, n = power_law_index(rate[first], 10.0**MASCOOP_COMPLETE_LOG)
    # This sample's own completeness: the peak of its counts in 0.25 dex.
    counts, edges = np.histogram(np.log10(rate[first]), np.arange(44, 51.01, 0.25))
    peak = float(edges[np.argmax(counts)])
    alpha_peak, error_peak, n_peak = power_law_index(rate[first], 10.0**peak)
    nside = local.SKY_NSIDE
    observed = local.finkbeiner(nside)
    far_sky = found["sky"]
    lon = sky.longitudes(nside)
    plane = {}
    for lo in range(0, 360, 30):
        m = sky.band_mask(nside, 0, 2) & (lon >= lo) & (lon < lo + 30)
        plane[f"l {lo}-{lo + 30}"] = round(
            float(far_sky[m].mean() / observed[m].mean()), 4
        )
    seen_share = found["seen_erg_s"].sum() / found["halpha_erg_s"].sum()
    _write(
        out,
        "wise",
        {
            "used": summary["used"],
            "by_source": summary["by_source"],
            "light_share_by_source": summary["light_share_by_source"],
            "dropped_inside_cube": summary["dropped_inside_cube"],
            "dropped_light_share": summary["dropped_light_share"],
            "size_fit": summary["size_fit"],
            "luminosity_function": {
                "alpha": round(alpha, 3),
                "error": round(error, 3),
                "regions": n,
                "complete_above_log_rate": MASCOOP_COMPLETE_LOG,
                "above_own_peak": {
                    "log_rate": peak,
                    "alpha": round(alpha_peak, 3),
                    "error": round(error_peak, 3),
                    "regions": n_peak,
                },
                "mascoop_2021": MASCOOP_ALPHA,
            },
            "total_rate": float(rate.sum()),
            "total_halpha_erg_s": float(found["halpha_erg_s"].sum()),
            "seen_from_sun_share": float(seen_share),
            "far_sky_over_finkbeiner_abs_b_under_2": plane,
            "column_median_mag": float(np.median(found["column"])),
        },
    )


@dataclass(frozen=True)
class Nebula:
    """A nebula's published foreground extinction (A_V in mag, V taken as A0 at 550
    nm), distance and ionising rate, the aperture of the comparison (deg) and the
    radius of the sphere that holds its gas in the cube (pc)."""

    l_deg: float
    b_deg: float
    distance_pc: float
    a_v: float
    a_v_source: str
    rate: float
    rate_source: str
    aperture_deg: float
    sphere_pc: float


NEBULAE = {
    "M42": Nebula(
        209.01, -19.38, 414.0, 1.5,
        "Da Rio et al. 2010, sect. 4.4: cluster median; 0.9 to 2.7 in the gas,"
        " Weilbacher et al. 2015 sect. 5.1",
        7.35e48, "O'Dell et al. 2017 sect. 1, theta1 Ori C", 1.0, 20.0,
    ),
    "M8": Nebula(
        5.97, -1.18, 1320.0, 1.35,
        "Prisinzano et al. 2019 sect. 6: E(B-V) 0.27 at R_V 5.0",
        1.1e49, "Binder & Povich 2018 Table 2, radio", 0.75, 20.0,
    ),
    "Rosette": Nebula(
        206.3, -2.1, 1500.0, 1.5,
        "Muzic et al. 2022 sect. 2.1; 1.27 to 1.86 for the O stars, Martins et al."
        " 2012 Table 1",
        6.0e49, "Martins et al. 2012 Table 4, sum of the seven O stars", 1.2, 25.0,
    ),
    "North America": Nebula(
        85.6, -0.7, 785.0, 9.6,
        "Kuhn & Hillenbrand 2020: the ionising star; the nebula's face off the dark"
        " cloud A_V < 0.78, Cambresy et al. 2002 sect. 3.2",
        5.1e49, "McCallum et al. 2025 sect. 3.2, from the spectral type", 1.5, 25.0,
    ),
}  # fmt: skip


def _sum_in_sphere(cube: np.ndarray, centre: np.ndarray, radius: float) -> float:
    """The light of a [x, y, z] cube of the level 2 box within a sphere, per pc^3
    times pc^3."""
    n = cube.shape[0]
    voxel = 2 * local.HALF_PC / n
    c = (np.arange(n) + 0.5) * voxel - local.HALF_PC
    lo = np.searchsorted(c, centre - radius - voxel)
    hi = np.searchsorted(c, centre + radius + voxel)
    sub = cube[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]]
    x, y, z = np.meshgrid(
        c[lo[0] : hi[0]], c[lo[1] : hi[1]], c[lo[2] : hi[2]], indexing="ij"
    )
    inside = (x - centre[0]) ** 2 + (y - centre[1]) ** 2 + (
        z - centre[2]
    ) ** 2 <= radius**2
    return float(sub[inside].sum() * voxel**3)


def dimming_gate(out: Path, workers: int) -> None:
    """Gate 2: the nest's column to four nebulae against the published one, their
    intrinsic against their observed H-alpha, and what the render shows from the
    Sun against what Finkbeiner sees. Run after gate-halpha, whose sky it reads."""
    record = json.loads((out / SHIPPED_RECORD).read_text())
    if record["encoding"] != _encoding_digest(out):
        raise build.StaleEmission(f"{SHIPPED} is of another encoding: run gate-halpha")
    nest, far = build._served()
    nside = 1024
    observed_sky = sources.finkbeiner_sky()
    pixel_sr = 4 * np.pi / len(observed_sky)
    cube = np.load(out / build.scaled_name("high"))
    found = build.read_regions(out)
    k = lines.K_LINE["halpha"]
    to_halpha = 1.0 / (lines.AT_TEN_PC * lines.TOTAL_PER_HALPHA)
    shipped = np.load(out / SHIPPED)
    observed_coarse = local.finkbeiner(local.SKY_NSIDE)
    rows = {}
    for name, entry in NEBULAE.items():
        l_deg, b_deg = entry.l_deg, entry.b_deg
        distance = entry.distance_pc
        axis = regions.galactic_vector(np.array([l_deg]), np.array([b_deg]))[0]
        disc = sky.disc_mask(nside, l_deg, b_deg, entry.aperture_deg)
        d = sky.directions(nside)[disc]
        columns = project.column_to(nest, far, d * distance)
        # Observed H-alpha in the aperture less the mean of an annulus at 1.5 to 2
        # radii, as a luminosity at the distance.
        ring = sky.disc_mask(
            nside, l_deg, b_deg, 2 * entry.aperture_deg
        ) & ~sky.disc_mask(nside, l_deg, b_deg, 1.5 * entry.aperture_deg)
        excess = observed_sky[disc].sum() - observed_sky[ring].mean() * disc.sum()
        photons = max(excess, 0.0) * pixel_sr * 1e6 / (4 * np.pi)
        flux = photons * lines.HALPHA_PHOTON_J * 1e7
        observed = flux * 4 * np.pi * (distance * lines.PC_CM) ** 2
        centre = axis * distance
        if (np.abs(centre) <= local.HALF_PC).all():
            intrinsic = _sum_in_sphere(cube, centre, entry.sphere_pc) * to_halpha
            held = "local cube"
        else:
            # Catalogue distances differ from the published ones, so match on the sky.
            toward = (
                found["position"] / np.linalg.norm(found["position"], axis=1)[:, None]
            )
            near = toward @ axis >= np.cos(np.radians(entry.aperture_deg))
            intrinsic = float(found["halpha_erg_s"][near].sum())
            at = np.linalg.norm(found["position"][near], axis=1)
            held = f"{int(near.sum())} WISE regions at {np.round(at).astype(int).tolist()} pc"
        implied = 2.5 * np.log10(max(intrinsic, 1e-30) / max(observed, 1e-30)) / k
        # What the render shows from the Sun in the aperture, against Finkbeiner.
        coarse = sky.disc_mask(local.SKY_NSIDE, l_deg, b_deg, entry.aperture_deg)
        placed = shipped[coarse].sum() + found["sky"][coarse].sum()
        rows[name] = {
            "placed_seen_over_observed": round(
                float(placed / observed_coarse[coarse].sum()), 3
            ),
            "held_by": held,
            "nest_a0_median": round(float(np.median(columns)), 3),
            "nest_a0_p10_p90": [
                round(float(q), 3) for q in np.percentile(columns, (10, 90))
            ],
            "published_a_v": entry.a_v,
            "published_source": entry.a_v_source,
            "observed_halpha_erg_s": float(observed),
            "intrinsic_halpha_erg_s": float(intrinsic),
            "intrinsic_rate": float(intrinsic / regions.HALPHA_PER_PHOTON_ERG),
            "published_rate": entry.rate,
            "rate_source": entry.rate_source,
            "a0_implied_by_intrinsic_over_observed": round(float(implied), 3),
        }
    _write(out, "dimming", {"k_halpha": k, "nebulae": rows})


# Leinert et al. 1998 Table 39 (Pioneer 10, about 440 nm): diffuse Galactic light
# over line-of-sight starlight, by abs(b).
LEINERT = {
    (0, 5): (0.21, 0.05),
    (5, 10): (0.34, 0.07),
    (10, 15): (0.31, 0.03),
    (15, 20): (0.19, 0.04),
    (20, 30): (0.25, 0.04),
    (30, 60): (0.17, None),
    (60, 90): (0.12, 0.02),
}
LUMA = np.array((0.2126, 0.7152, 0.0722))
SUN_NSIDE = 64
# The band gate's exposure: V = 0.0585 omega 10^(0.4 limit) I at 60 deg, 900 CSS px,
# limit 7.5 (glow_data.md).
BAND_EXPOSURE = 9.63e-5
OUTSIDE_PC = 30_000.0


def stored_j(out: Path, tier: str):
    raw = json.loads((out / build.ENCODING_FILE).read_text())["j"]
    table = raw["colour"]["rgb"] if raw["channels"] == 1 else []
    form = scatter.JForm(
        raw["channels"],
        raw["texture_scale"],
        tuple(tuple(tuple(cell) for cell in row) for row in table),
        tuple(raw["shield"]["factor"]),
    )
    bits = np.load(out / build.j_bits_name(tier))
    values = np.ascontiguousarray(bits, np.uint16).view(np.float16).astype(np.float32)
    return scatter.StoredJ(form, values, build.j_box(tier))


def scene(out: Path, tier: str = "high"):
    return views.Scene(
        build.light_field(), stored_j(out, tier), stored_halpha(out, tier)
    )


def sun_parts(out: Path, tier: str, workers: int, nside: int = SUN_NSIDE) -> dict:
    """The Sun's sky by part, with the far regions, cached in the build with the
    digest of the encoding it was made from."""
    path = out / f"gate.sun_sky.{tier}.{nside}.npz"
    encoding = _encoding_digest(out)
    if path.exists():
        with np.load(path) as cached:
            if str(cached["encoding"]) == encoding:
                return {k: cached[k] for k in cached.files if k != "encoding"}
    parts = views.sun_sky(scene(out, tier), nside, workers)
    found = build.read_regions(out)
    parts["regions"] = views.regions_from(found, np.zeros(3), found["column"], nside)
    np.savez(path, encoding=np.array(encoding), **parts)
    return parts


def _band_rows(parts: dict, nside: int, bands) -> dict:
    rows = {}
    b = np.abs(sky.latitudes(nside))
    for lo, hi in bands:
        m = (b >= lo) & (b < hi)
        d, s = parts["direct"][m].mean(0), parts["scattered"][m].mean(0)
        rows[f"abs(b) {lo}-{hi}"] = {
            "scattered_over_direct_rgb": np.round(s / d, 4).tolist(),
            "scattered_over_direct_luma": round(float(s @ LUMA / (d @ LUMA)), 4),
            "colour_scattered_over_direct_b_over_r": round(
                float((s[2] / s[0]) / (d[2] / d[0])), 4
            ),
        }
    return rows


def _outside(scene_, origin: np.ndarray, target_axes, workers: int, n: int = 96):
    """Rays from `origin` to an n x n grid over the Galaxy, even steps in the box."""
    centre = np.array(volumes.CENTRE)
    u, v = target_axes
    q = (np.arange(n) + 0.5) / n * 2 - 1
    a, b = np.meshgrid(q * 25_000.0, q * 25_000.0, indexing="ij")
    targets = centre + a.reshape(-1, 1) * u + b.reshape(-1, 1) * v
    rays = targets - origin
    distance = np.linalg.norm(rays, axis=1)
    rays /= distance[:, None]
    mids, lengths = views.box_rays(origin, rays, volumes.INNER_HIGH, 1536)
    got = views.march_all(scene_, origin, rays, mids, lengths, workers, size=256)
    # The solid angle of each ray's cell of the grid, so the parts sum to fluxes.
    normal = np.cross(u, v)
    cell = (2 * 25_000.0 / n) ** 2
    got["solid_angle"] = cell * np.abs(rays @ normal) / distance**2
    return got


def scatter_gate(out: Path, workers: int) -> None:
    """Gate 4: from the Sun, scattered over direct starlight by band against Leinert,
    and its colour; from 30 kpc face-on and edge-on, the scattered share."""
    parts = sun_parts(out, "high", workers)
    leinert = {}
    rows = _band_rows(parts, SUN_NSIDE, LEINERT)
    for (lo, hi), (value, error) in LEINERT.items():
        row = rows[f"abs(b) {lo}-{hi}"]
        leinert[f"abs(b) {lo}-{hi}"] = {
            "blue_464nm": row["scattered_over_direct_rgb"][2],
            "luma": row["scattered_over_direct_luma"],
            "leinert_440nm": value,
            "leinert_error": error,
            "colour_b_over_r_vs_direct": row["colour_scattered_over_direct_b_over_r"],
        }
    sc = scene(out, "high")
    found = build.read_regions(out)
    centre = np.array(volumes.CENTRE)
    shares = {}
    for name, offset, axes in (
        ("face-on", (0, 0, OUTSIDE_PC), (np.array([1, 0, 0]), np.array([0, 1, 0]))),
        ("edge-on", (0, -OUTSIDE_PC, 0), (np.array([1, 0, 0]), np.array([0, 0, 1]))),
    ):
        origin = centre + np.array(offset, float)
        got = _outside(sc, origin, axes, workers)
        np.savez(out / f"gate.outside.{name}.npz", **got)
        omega = got["solid_angle"][:, None]
        flux = {part: (got[part] * omega).sum(0) for part in views.PARTS}
        column = views.column_between(sc.field, origin, found["position"])
        flux["regions"] = views.regions_flux(found, origin, column).sum(0)
        total = sum(flux.values())
        shares[name] = {
            "scattered_share_rgb": np.round(flux["scattered"] / total, 4).tolist(),
            "scattered_share_luma": round(
                float(flux["scattered"] @ LUMA / (total @ LUMA)), 4
            ),
            "halpha_local_share_luma": round(
                float(flux["halpha"] @ LUMA / (total @ LUMA)), 6
            ),
            "halpha_regions_share_luma": round(
                float(flux["regions"] @ LUMA / (total @ LUMA)), 6
            ),
        }
    whole = {
        "scattered_over_direct_rgb": np.round(
            parts["scattered"].mean(0) / parts["direct"].mean(0), 4
        ).tolist()
    }
    _write(
        out, "scatter", {"sun_whole_sky": whole, "leinert": leinert, "outside": shares}
    )


_hg_job: tuple | None = None


def _hg_ray(index: int) -> tuple[np.ndarray, np.ndarray]:
    """The scattered light toward the camera along one ray: isotropic and
    Henyey-Greenstein with Draine's g, per channel."""
    assert _hg_job is not None
    field, origin, rays, mids, lengths, d, w, edges = _hg_job
    ray = rays[index]
    column = 0.0
    iso = np.zeros(3)
    hg = np.zeros(3)
    # Photons that reach the camera leave each point along -ray; light that comes
    # from direction d travels along -d, so the angle between them has cos d . ray.
    phase = 4 * np.pi * scatter.henyey_greenstein(d @ ray, scatter.ASYMMETRY)
    for s, ds in zip(mids[index], lengths[index], strict=True):
        p = origin + ray * s
        rho = float(field.dust(p[None])[0])
        column += rho * ds / 2
        if rho > 1e-6 and ds > 0:
            radiance = scatter.radiance(field, p[None], d, edges)[0]
            kappa = light.K_RGB * rho * scatter.TAU_PER_MAG
            seen = 10.0 ** (-0.4 * light.K_RGB * column)
            iso += scatter.ALBEDO * kappa * (w @ radiance) * seen * ds
            hg += (
                scatter.ALBEDO
                * kappa
                * ((w[:, None] * phase) * radiance).sum(0)
                * seen
                * ds
            )
        column += rho * ds / 2
    return iso, hg


def isotropy_gate(out: Path, workers: int) -> None:
    """What isotropic scattering costs against Henyey-Greenstein, on a few rays."""
    global _hg_job
    field = build.light_field()
    d, w = scatter.direction_set(build.J_LONGITUDES, build.J_LATITUDES)
    edges = scatter.step_edges(build.J_STEPS)
    centre = np.array(volumes.CENTRE)
    cases = {}
    toward = regions.galactic_vector(
        np.array([358.0, 2.0, 358.0, 2.0, 0.0, 0.0]),
        np.array([-1.5, -1.5, 1.5, 1.5, -3.0, 3.0]),
    )
    cases["Sun toward the centre"] = (
        np.zeros(3),
        toward,
        *views.log_steps(160, 1.0, 30_000.0),
    )
    high = regions.galactic_vector(
        np.array([0.0, 90.0, 180.0, 270.0]), np.full(4, 45.0)
    )
    cases["Sun at abs(b) 45"] = (
        np.zeros(3),
        high,
        *views.log_steps(160, 1.0, 30_000.0),
    )
    for name, offset in (
        ("face-on 30 kpc", (0, 0, OUTSIDE_PC)),
        ("edge-on 30 kpc", (0, -OUTSIDE_PC, 0)),
    ):
        origin = centre + np.array(offset, float)
        targets = centre + np.array(
            [[x, 0.0, 0.0] for x in (-12000, -6000, -2000, 3000, 8000, 12000)]
        )
        if name.startswith("face"):
            targets += np.array(
                [[0.0, y, 0.0] for y in (2000, -5000, 7000, 1000, -3000, 4000)]
            )
        rays = targets - origin
        rays /= np.linalg.norm(rays, axis=1)[:, None]
        mids, lengths = views.box_rays(origin, rays, volumes.INNER_HIGH, 192)
        cases[name] = (origin, rays, mids, lengths)
    result = {}
    for name, (origin, rays, mids, lengths) in cases.items():
        mids = np.broadcast_to(mids, (len(rays), mids.shape[-1]))
        lengths = np.broadcast_to(lengths, (len(rays), lengths.shape[-1]))
        _hg_job = (field, origin, rays, mids, lengths, d, w, edges)
        try:
            got = forked_map(_hg_ray, range(len(rays)), workers)
        finally:
            _hg_job = None
        iso = np.array([g[0] for g in got])
        hg = np.array([g[1] for g in got])
        ratio = hg.sum(0) / iso.sum(0)
        result[name] = {
            "hg_over_isotropic_rgb": np.round(ratio, 3).tolist(),
            "per_ray_luma": np.round((hg @ LUMA) / (iso @ LUMA), 3).tolist(),
        }
    _write(
        out, "isotropy", {"asymmetry_rgb": scatter.ASYMMETRY.tolist(), "views": result}
    )


def _cube_luma() -> tuple[np.ndarray, np.ndarray]:
    """The sky cube's linear luminance per Nside 64 pixel, and the drawn stars and
    glow at the band gate, from the glow's band run."""
    with np.load(glow_build.BUILD_DIR / "band.npz") as band:
        return band["cube"], band["drawn"] + band["glow_soft"]


def sun_gate(out: Path, workers: int) -> None:
    """Gate 5: what the Sun's view gains, at the band gate's exposure, by band: the
    H-alpha and scattered light that the render draws inside 2,000 AU on the cube,
    and outside it on the drawn stars and the glow."""
    parts = sun_parts(out, "high", workers)
    cube, drawn_glow = _cube_luma()
    halpha = (parts["halpha"] + parts["regions"]) @ LUMA * BAND_EXPOSURE
    scattered = parts["scattered"] @ LUMA * BAND_EXPOSURE
    b = np.abs(sky.latitudes(SUN_NSIDE))
    lon = sky.longitudes(SUN_NSIDE)
    bands = {f"abs(b) {lo}-{hi}": (b >= lo) & (b < hi) for lo, hi in BANDS}
    bands["abs(b) < 5"] = b < 5
    bands["centre, abs(b) < 5, l +-15"] = (b < 5) & ((lon < 15) | (lon > 345))
    bands["anticentre, abs(b) < 5"] = (b < 5) & (np.abs(lon - 180) < 15)
    for name, (l_deg, b_deg, r) in NAMED.items():
        bands[name] = sky.disc_mask(SUN_NSIDE, l_deg, b_deg, max(r, 2.0))
    bands["whole sky"] = np.ones(len(b), bool)
    rows = {}
    for name, m in bands.items():
        rows[name] = {
            "cube_mean": round(float(cube[m].mean()), 6),
            "halpha_mean": round(float(halpha[m].mean()), 7),
            "scattered_mean": round(float(scattered[m].mean()), 6),
            "gain_on_cube": round(
                float((halpha[m] + scattered[m]).mean() / cube[m].mean()), 4
            ),
            "halpha_on_cube": round(float(halpha[m].mean() / cube[m].mean()), 4),
            "scattered_on_cube": round(float(scattered[m].mean() / cube[m].mean()), 4),
            "gain_on_drawn_and_glow": round(
                float((halpha[m] + scattered[m]).mean() / drawn_glow[m].mean()), 4
            ),
            "median_pixel_gain_on_cube": round(
                float(np.median((halpha[m] + scattered[m]) / cube[m])), 4
            ),
        }
    _write(out, "sun", {"exposure": BAND_EXPOSURE, "bands": rows})


def tier_gate(out: Path, workers: int) -> None:
    """Gate 7: `low` against `high`, per sky band from the Sun."""
    high = sun_parts(out, "high", workers)
    low = sun_parts(out, "low", workers)
    rows = {}
    b = np.abs(sky.latitudes(SUN_NSIDE))
    for lo, hi in BANDS:
        m = (b >= lo) & (b < hi)
        rows[f"abs(b) {lo}-{hi}"] = {
            part: round(
                float(low[part][m].sum(0) @ LUMA / (high[part][m].sum(0) @ LUMA)), 4
            )
            for part in ("scattered", "halpha")
        }
    whole = {
        part: round(float(low[part].sum(0) @ LUMA / (high[part].sum(0) @ LUMA)), 4)
        for part in ("scattered", "halpha", "direct")
    }
    _write(out, "tiers", {"whole_sky": whole, "bands": rows})
