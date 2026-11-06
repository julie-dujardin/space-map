"""Calibrate the model light: shapes from the papers, the scale from the catalogue.

The face-on profile is Lian et al. 2024's, so its half-light radius is theirs. One
factor scales everything that profile holds to the catalogue's own dereddened column
at the Sun, where the tree is complete for the stars that carry the light. The halo
and the Clouds keep their published light. Colours: the disc at the Sun takes the
catalogue column's colour; young light and the thick disc take the colour of their
stars in the catalogue; the radial colour of the disc and the bulge's colour follow
Lian's r - H; the halo takes the colour of metal-poor globular clusters (Harris 1996,
2010 edition); the Clouds that of Bothun & Thompson 1988.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from space_map_data.galaxy import model, photometry, sources
from space_map_data.galaxy.geometry import R0, Z0
from space_map_data.galaxy.model import BAR_MASSES, NSC_MASS, NSD_MASS, Model
from space_map_data.glow import colour, light

logger = logging.getLogger(__name__)

CALIBRATION = "calibration.json"
COLUMN = "column.json"
PROFILE_STEP_PC = 50.0
PROFILE_REACH_PC = 30_000.0
# Lian's rings that hold the bulge; the disc runs flat under them.
BULGE_RINGS = 3
# The share of a ring's light the disc keeps where the bars lie.
DISC_FLOOR_SHARE = 0.5
# The catalogue's column: a cylinder about the Sun, to 2 kpc each side.
COLUMN_RADIUS_PC = 300.0
COLUMN_HEIGHT_PC = 2000.0
# The share of young light comes from a wider cylinder, for its few stars.
SHARE_RADIUS_PC = 1000.0
# Young: blue main-sequence stars brighter than M0 = 1.5, and supergiants.
YOUNG_BLUEST_BP_RP = 0.0
YOUNG_FAINTEST_M0 = 1.5
YOUNG_SUPERGIANT_M0 = -3.5
# Thick disc: stars 1 to 2.5 kpc from the plane near the Sun.
THICK_RADIUS_PC = 1500.0
THICK_HEIGHTS_PC = (1000.0, 2500.0)
# Halo colour: metal-poor clusters with little reddening.
HALO_FEH_BELOW = -1.0
HALO_REDDENING_BELOW = 0.2
# Bothun & Thompson 1988: B - V corrected for foreground reddening.
CLOUD_B_V = {"lmc": 0.56, "smc": 0.47}
SAMPLE_CHUNK = 2_000_000


@dataclass
class Selection:
    flux_g: float = 0.0
    rgb: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def add(self, flux_g: np.ndarray, rgb: np.ndarray, weight: np.ndarray) -> None:
        self.flux_g += float((flux_g * weight).sum())
        self.rgb = self.rgb + (rgb * weight[:, None]).sum(axis=0)


def catalogue_column(sample_path: Path) -> dict:
    """Sums of the dereddened light of the glow build's sample near the Sun."""
    sample = np.load(sample_path, mmap_mode="r")
    picks = {
        "column": Selection(),
        "share_all": Selection(),
        "share_young": Selection(),
        "thick": Selection(),
    }
    for start in range(0, len(sample), SAMPLE_CHUNK):
        rows = np.asarray(sample[start : start + SAMPLE_CHUNK], np.float64)
        x, y, z, mag, bp_rp, column, weight = rows.T
        cyl = np.hypot(x, y)
        taken = light.taken_out(column, bp_rp, mag)
        m0 = light.dust_free_magnitude(mag, taken)
        flux_g = 10.0 ** (-0.4 * m0)
        rgb = light.star_flux(mag, colour.star_colours(bp_rp), taken)
        bp_rp0 = bp_rp - light.REDDENING * taken
        low = np.abs(z) < COLUMN_HEIGHT_PC
        selections = {
            "column": low & (cyl < COLUMN_RADIUS_PC),
            "share_all": low & (cyl < SHARE_RADIUS_PC),
            "share_young": low
            & (cyl < SHARE_RADIUS_PC)
            & (
                ((bp_rp0 < YOUNG_BLUEST_BP_RP) & (m0 < YOUNG_FAINTEST_M0))
                | (m0 < YOUNG_SUPERGIANT_M0)
            ),
            "thick": (cyl < THICK_RADIUS_PC)
            & (np.abs(z) > THICK_HEIGHTS_PC[0])
            & (np.abs(z) < THICK_HEIGHTS_PC[1]),
        }
        for name, chosen in selections.items():
            picks[name].add(flux_g[chosen], rgb[chosen], weight[chosen])
    area = np.pi * COLUMN_RADIUS_PC**2
    rgb_column = picks["column"].rgb
    return {
        "column_g_per_pc2": picks["column"].flux_g / area,
        "column_rgb_per_pc2": (rgb_column / area).tolist(),
        "column_bp_rp": float(photometry.bp_rp_of_display(rgb_column)),
        "young_share_g": picks["share_young"].flux_g / picks["share_all"].flux_g,
        "young_bp_rp": float(photometry.bp_rp_of_display(picks["share_young"].rgb)),
        "thick_bp_rp": float(photometry.bp_rp_of_display(picks["thick"].rgb)),
        "selections": {
            "column_radius_pc": COLUMN_RADIUS_PC,
            "column_height_pc": COLUMN_HEIGHT_PC,
            "share_radius_pc": SHARE_RADIUS_PC,
            "young": f"(BP-RP)0 < {YOUNG_BLUEST_BP_RP} and M0 < {YOUNG_FAINTEST_M0}, or M0 < {YOUNG_SUPERGIANT_M0}",
            "thick": f"cylinder {THICK_RADIUS_PC} pc, |z| {THICK_HEIGHTS_PC} pc",
        },
    }


def face_on_rings(shape, edges: np.ndarray, step: float = 20.0) -> np.ndarray:
    """The mean face-on surface density of `shape(x, y)` (already integrated over z)
    in each ring about the centre."""
    reach = edges[-1]
    axis = np.arange(-reach, reach, step) + step / 2
    X, Y = np.meshgrid(axis, axis, indexing="ij")
    R = np.hypot(X, Y).ravel()
    values = shape(X.ravel() + R0, Y.ravel())
    ring = np.searchsorted(edges, R, side="right") - 1
    inside = (ring >= 0) & (ring < len(edges) - 1)
    sums = np.bincount(ring[inside], values[inside], len(edges) - 1)
    counts = np.bincount(ring[inside], minlength=len(edges) - 1)
    return sums / np.maximum(counts, 1)


def _bulge_face_on(x, y) -> np.ndarray:
    heights = np.linspace(-3000.0, 3000.0, 601)
    total = np.zeros(len(x))
    for z in heights:
        total += model.bulge_shape(x, y, np.full(len(x), z - Z0))
    return total * (heights[1] - heights[0])


def bulge_bar_rings(edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Face-on ring means of the box/peanut bulge and of both long bars, each per
    unit of its light."""
    bulge = face_on_rings(_bulge_face_on, edges, 40.0)
    bars = face_on_rings(
        lambda x, y: model.bar_planform(x, y) / model.bar_planform_integral(), edges
    )
    return bulge, bars


def split_centre(
    lian_r: np.ndarray, areas: np.ndarray, bulge: np.ndarray, bars: np.ndarray
) -> tuple[float, float, float, np.ndarray]:
    """The light of the bulge and of the bars, the bars' light by mass ratio, and the
    disc's ring profile, all in r.

    The bulge's projected shape is flatter in its middle than Lian's inner rings, so
    the rings inside 3 kpc keep their summed light, not each its own: the bulge takes
    what rises above a disc that runs flat under it. The bars take Wegg et al. 2015's
    mass ratio to the bulge at the bulge's mass-to-light ratio, but no more than
    leaves the disc `DISC_FLOOR_SHARE` of a ring: at that ratio the bars would
    outshine Lian's rings at 2 to 4 kpc. Rings from 3 kpc keep their light.
    """
    inner = np.arange(len(lian_r)) < BULGE_RINGS
    ratio = (BAR_MASSES["bar"] + BAR_MASSES["superthin"]) / BAR_MASSES["bulge"]
    has_bar = (bars > 0.05 * bars.max()) & ~inner
    level = float(lian_r[BULGE_RINGS])
    light_bulge = light_bars = 0.0
    for _ in range(50):
        excess = ((lian_r - level - light_bars * bars) * areas)[inner].sum()
        light_bulge = max(float(excess / (bulge * areas)[inner].sum()), 0.0)
        room = (1 - DISC_FLOOR_SHARE) * (lian_r - light_bulge * bulge)
        cap = max(float(np.min(room[has_bar] / bars[has_bar])), 0.0)
        light_bars = min(ratio * light_bulge, cap)
        disc = lian_r - light_bulge * bulge - light_bars * bars
        level = max(float(disc[BULGE_RINGS]), 0.0)
    return light_bulge, light_bars, ratio * light_bulge, np.where(inner, level, disc)


def _log_interp(at: np.ndarray, points: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Interpolation in log, carried on at the last slope past the last point."""
    logs = np.log(np.maximum(values, 1e-12))
    out = np.interp(at, points, logs)
    slope = (logs[-1] - logs[-2]) / (points[-1] - points[-2])
    past = at > points[-1]
    out[past] = logs[-1] + slope * (at[past] - points[-1])
    return np.exp(out)


def _flux_of_r(light_r, bp_rp):
    """G flux of light given in L_sun of SDSS r."""
    return light_r * 10.0 ** (
        -0.4 * (photometry.SUN_SDSS_R + photometry.gaia_minus_r(bp_rp))
    )


def _flux_of_v(light_v, bp_rp):
    return light_v * 10.0 ** (
        -0.4 * (photometry.SUN_V + photometry.gaia_minus_v(bp_rp))
    )


def halo_bp_rp() -> tuple[float, float, int]:
    clusters = sources.harris_clusters()
    chosen = (
        (clusters.metallicity < HALO_FEH_BELOW)
        & (clusters.reddening < HALO_REDDENING_BELOW)
        & np.isfinite(clusters.b_v)
        & np.isfinite(clusters.absolute_v)
    )
    weight = 10.0 ** (-0.4 * clusters.absolute_v[chosen])
    b_v = clusters.b_v[chosen] - clusters.reddening[chosen]
    mean = float((weight * b_v).sum() / weight.sum())
    return float(photometry.bp_rp_of_b_v(mean)), mean, int(chosen.sum())


def calibrate(column: dict, out: Path) -> dict:
    """Write the calibration from Lian's profile and the catalogue column."""
    lian = sources.lian_profiles()
    edges, rings = lian.edges, lian.radius
    bulge_rings, bar_rings = bulge_bar_rings(edges)
    areas = np.pi * np.diff(edges**2)
    light_bulge, light_bars, bars_by_mass, disc_rings = split_centre(
        lian.r, areas, bulge_rings, bar_rings
    )
    radius = np.arange(0.0, PROFILE_REACH_PC + PROFILE_STEP_PC, PROFILE_STEP_PC)
    disc_r = _log_interp(radius, rings, disc_rings)
    disc_r[radius > PROFILE_REACH_PC - PROFILE_STEP_PC] = 0.0

    ages = lian.ages
    # Old stars of the bulge fill the inner rings' oldest bin, so the thick disc takes
    # the share of the first ring past the bars.
    first_disc = 4
    thick_share = ages[:, 5] / ages.sum(axis=1)
    thick_share[:first_disc] = thick_share[first_disc]
    thick_share = np.interp(radius, rings, thick_share)
    envelope = np.interp(radius, rings, ages[:, 0], left=0.0, right=0.0)
    at_sun = float(np.interp(R0, rings, ages[:, 0]))

    # Colours. r - H of Lian's rings gives the disc's change with radius and the
    # bulge's offset; the catalogue gives the disc at the Sun.
    r_h = (photometry.SUN_SDSS_R - photometry.SUN_H) + 2.5 * np.log10(lian.h / lian.r)
    bp_of_ring = photometry.bp_rp_of_r_h(r_h)
    bp_at_sun_rh = float(np.interp(R0, rings, bp_of_ring))
    bulge_rh = (photometry.SUN_SDSS_R - photometry.SUN_H) + 2.5 * np.log10(
        lian.h[:2].sum() / lian.r[:2].sum()
    )
    bulge_offset = float(photometry.bp_rp_of_r_h(bulge_rh)) - bp_at_sun_rh
    disc_offset = np.interp(radius, rings, bp_of_ring) - bp_at_sun_rh
    young_bp = column["young_bp_rp"]
    thick_bp = column["thick_bp_rp"]
    halo_bp, halo_b_v, halo_clusters = halo_bp_rp()
    cloud_bp = {
        name: float(photometry.bp_rp_of_b_v(b_v)) for name, b_v in CLOUD_B_V.items()
    }

    young_share = column["young_share_g"]
    target_rgb = np.array(column["column_rgb_per_pc2"])
    thin_bp = column["column_bp_rp"]
    for _ in range(4):
        thin_bp_profile = thin_bp + disc_offset
        bulge_bp = thin_bp + bulge_offset
        young_r = young_share * float(np.interp(R0, radius, disc_r))
        young = np.minimum(young_r * envelope / at_sun, 0.9 * disc_r)
        thick = thick_share * disc_r
        thin = disc_r - thick - young
        profiles = {
            "thin": _flux_of_r(thin, thin_bp_profile),
            "thick": _flux_of_r(thick, thick_bp),
            "young": _flux_of_r(young, young_bp),
        }
        bar_share = BAR_MASSES["bar"] / (BAR_MASSES["bar"] + BAR_MASSES["superthin"])
        light = {
            "bulge": light_bulge,
            "bar": light_bars * bar_share,
            "superthin": light_bars * (1 - bar_share),
            # The bulge's mass-to-light ratio, as Lian et al. tried for the nuclear disc.
            "nsd": light_bulge * NSD_MASS / BAR_MASSES["bulge"],
            "nsc": light_bulge * NSC_MASS / BAR_MASSES["bulge"],
        }
        flux = {
            name: float(_flux_of_r(value, bulge_bp)) for name, value in light.items()
        }
        flux["halo"] = float(_flux_of_v(model.HALO_LIGHT_V, halo_bp))
        for name in ("lmc", "smc"):
            m_v = sources.lvdb_cloud(name).absolute_v
            flux[name] = float(
                10.0 ** (-0.4 * (m_v + photometry.gaia_minus_v(cloud_bp[name])))
            )
        bp = {
            "thick": thick_bp,
            "young": young_bp,
            **{name: bulge_bp for name in model.CENTRE},
            "halo": halo_bp,
            **cloud_bp,
        }
        unscaled = Model(
            radius,
            profiles["thin"],
            thin_bp_profile,
            profiles["thick"],
            profiles["young"],
            flux,
            bp,
        )
        parts = model_column(unscaled, (*model.DISC, *model.CENTRE, "halo"))
        fixed = parts.pop("halo")
        scaled_g = sum(part["g"] for part in parts.values())
        scaled_rgb = sum(part["rgb"] for part in parts.values())
        scale = (column["column_g_per_pc2"] - fixed["g"]) / scaled_g
        model_rgb = scale * scaled_rgb + fixed["rgb"]
        # The thin disc's colour is the free one: it gives the model's column at the
        # Sun the catalogue's colour.
        miss = float(photometry.bp_rp_of_display(model_rgb)) - float(
            photometry.bp_rp_of_display(target_rgb)
        )
        thin_bp -= miss
    result = {
        "profiles": {
            "radius_pc": radius.tolist(),
            "thin": (scale * profiles["thin"]).tolist(),
            "thin_bp_rp": thin_bp_profile.tolist(),
            "thick": (scale * profiles["thick"]).tolist(),
            "young": (scale * profiles["young"]).tolist(),
        },
        "flux": {k: (v * scale if k in model.CENTRE else v) for k, v in flux.items()},
        "bp_rp": bp,
        "fit": {
            "lian_scale": scale,
            "bulge_light_r": light_bulge * scale,
            "bars_light_r": light_bars * scale,
            "bars_light_r_by_mass_ratio": bars_by_mass * scale,
            "disc_under_bulge_r_per_pc2": float(disc_rings[0]) * scale,
            "young_share_at_sun": young_share,
            "thin_bp_rp_at_sun": thin_bp,
            "bulge_bp_rp_offset": bulge_offset,
            "halo_b_v": halo_b_v,
            "halo_clusters": halo_clusters,
            "cloud_b_v": CLOUD_B_V,
            "column_colour_miss_bp_rp": miss,
        },
        "column": column,
    }
    (out / CALIBRATION).write_text(json.dumps(result, indent=1))
    logger.info("calibration: Lian scale %.3f, thin BP-RP %.3f", scale, thin_bp)
    return result


COLUMN_STEPS_Z = 4001
COLUMN_RINGS = 6
COLUMN_AZIMUTHS = 12


def column_points() -> tuple[np.ndarray, np.ndarray, float]:
    """Points that sample the Sun's cylinder, and the area times height of each."""
    z = np.linspace(-COLUMN_HEIGHT_PC, COLUMN_HEIGHT_PC, COLUMN_STEPS_Z)
    ring = (np.arange(COLUMN_RINGS) + 0.5) / COLUMN_RINGS
    radius = COLUMN_RADIUS_PC * np.sqrt(ring)
    angle = (np.arange(COLUMN_AZIMUTHS) + 0.5) / COLUMN_AZIMUTHS * 2 * np.pi
    r, a = np.meshgrid(radius, angle, indexing="ij")
    xy = np.stack((r.ravel() * np.cos(a.ravel()), r.ravel() * np.sin(a.ravel())), 1)
    points = np.concatenate([np.column_stack((xy, np.full(len(xy), h))) for h in z])
    return points, z, float(z[1] - z[0])


def model_column(m: Model, names=model.COMPONENTS) -> dict[str, dict]:
    """Each component's mean column in the Sun's cylinder: G flux per pc^2 and RGB."""
    points, _, dz = column_points()
    per = COLUMN_RINGS * COLUMN_AZIMUTHS
    out = {}
    x, y, z = points.T
    for name, density in m.densities(x, y, z, names).items():
        rgb = density[:, None] * m.colours(name, x, y, z)
        out[name] = {"g": float(density.sum() * dz / per), "rgb": rgb.sum(0) * dz / per}
    return out
