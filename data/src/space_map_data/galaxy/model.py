"""The model light of the Galaxy: analytic components, in the units of the catalogue
grid. A density is G-band flux per pc^3, where M_G = 0 at 10 pc is 1, with no dust; a
component's display colour comes from its BP - RP through the client's star colour.

Components and their geometry (every length on R0 = 8,277 pc):
- thin disc: the radial profile of Lian et al. 2024 less the rest, exponential in
  height with 300 pc (Bland-Hawthorn & Gerhard 2016), the old m = 2 arms;
- thick disc: Lian's 10 to 12 Gyr share, 900 pc high (Bland-Hawthorn & Gerhard 2016);
- young arms: Lian's 0 to 2 Gyr profile on the arms of `geometry`, their flare;
- box/peanut bulge: Wegg & Gerhard 2013; thin and super-thin long bar: Wegg et al.
  2015; nuclear disc: Sormani et al. 2022; nuclear cluster: Bland-Hawthorn & Gerhard;
- stellar halo: Deason et al. 2019 for the light, Bland-Hawthorn & Gerhard for shape;
- Magellanic Clouds: `clouds`.
`calibrate` sets the amplitudes and colours, and this module reads them.
"""

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import numpy as np

from space_map_data.dust.nest import smoothstep
from space_map_data.galaxy import clouds, geometry, photometry
from space_map_data.galaxy.geometry import R0, Z0

THIN_HEIGHT_PC = 300.0
THICK_HEIGHT_PC = 900.0
# Wegg & Gerhard 2013: exponential scales along the bar's three axes, angle 27 deg.
BULGE_SCALES_PC = (700.0, 440.0, 180.0)
BULGE_ANGLE = np.radians(27.0)
# Wegg et al. 2015, Table 1, two-component fit: the thin bar.
BAR_ANGLE = np.radians(29.1)
BAR_SCALES_PC = (820.0, 230.0)
BAR_HEIGHT_PC = 200.0
BAR_EXPONENT = 3.98
BAR_OUT_PC = (4370.0, 110.0)
BAR_IN_PC = (3260.0, 560.0)
# The super-thin bar keeps the thin bar's planform at 45 pc high (Bland-Hawthorn &
# Gerhard 2016, from Wegg et al. 2015).
SUPERTHIN_HEIGHT_PC = 45.0
# Masses (1e9 M_sun) of Wegg et al. 2015, Table 2: N-body (box/peanut), thin, super-thin.
BAR_MASSES = {"bulge": 10.9, "bar": 4.0, "superthin": 3.3}
# Sormani et al. 2022: mass 1.05e9 M_sun, exponential scales.
NSD_MASS = 1.05
NSD_SCALES_PC = (88.6, 28.4)
# Bland-Hawthorn & Gerhard 2016: 1.8e7 M_sun, half-light radius 4.2 pc (Plummer).
NSC_MASS = 0.018
NSC_PLUMMER_PC = 4.2 / 1.305
# Deason et al. 2019: 7.9e8 L_sun (V) within 100 kpc, without Sagittarius. Shape of
# Bland-Hawthorn & Gerhard 2016: slopes -2.5 and the middle of -3.7 to -5.0, break
# 25 kpc, flattening 0.65 inside and 0.8 outside.
HALO_LIGHT_V = 7.9e8
HALO_REACH_PC = 100_000.0
HALO_BREAK_PC = 25_000.0
HALO_SLOPES = (2.5, 4.35)
HALO_FLATTENING = (0.65, 0.8)
HALO_FLATTENING_BAND_PC = (15_000.0, 35_000.0)
# A core keeps the inner power law finite; the bulge holds that light.
HALO_CORE_PC = 1000.0

DISC = ("thin", "thick", "young")
CENTRE = ("bulge", "bar", "superthin", "nsd", "nsc")
COMPONENTS = (*DISC, *CENTRE, "halo", "lmc", "smc")


def _cut(t: np.ndarray) -> np.ndarray:
    """Wegg et al. 2015, eq. 10, with the cut starting at its edge."""
    return np.where(t > 0, np.exp(-(np.minimum(t, 30.0) ** 2)), 1.0)


def bar_frame(x, y, angle: float):
    """Coordinates along the bar's major and minor axes (pc). The near end is at
    positive longitude."""
    X = x - R0
    return -X * np.cos(angle) + y * np.sin(angle), X * np.sin(angle) + y * np.cos(angle)


def bulge_shape(x, y, z) -> np.ndarray:
    """Box/peanut bulge, integral 1."""
    a, b, c = BULGE_SCALES_PC
    xb, yb = bar_frame(x, y, BULGE_ANGLE)
    r = np.sqrt((xb / a) ** 2 + (yb / b) ** 2 + ((z + Z0) / c) ** 2)
    return np.exp(-r) / (8 * np.pi * a * b * c)


def bar_planform(x, y) -> np.ndarray:
    """The long bar's face-on shape, not normalised."""
    a, b = BAR_SCALES_PC
    xb, yb = bar_frame(x, y, BAR_ANGLE)
    n = BAR_EXPONENT
    radius = np.hypot(x - R0, y)
    return (
        np.exp(-(((np.abs(xb) / a) ** n + (np.abs(yb) / b) ** n) ** (1 / n)))
        * _cut((radius - BAR_OUT_PC[0]) / BAR_OUT_PC[1])
        * _cut((BAR_IN_PC[0] - radius) / BAR_IN_PC[1])
    )


@cache
def bar_planform_integral() -> float:
    step = 10.0
    axis = np.arange(-7000.0, 7000.0, step) + step / 2
    x, y = np.meshgrid(axis + R0, axis, indexing="ij")
    return float(bar_planform(x.ravel(), y.ravel()).sum() * step * step)


def bar_shape(x, y, z, height: float) -> np.ndarray:
    """A long bar, integral 1."""
    vertical = np.exp(-np.abs(z + Z0) / height) / (2 * height)
    return bar_planform(x, y) / bar_planform_integral() * vertical


def nsd_shape(x, y, z) -> np.ndarray:
    radius = np.hypot(x - R0, y)
    a, h = NSD_SCALES_PC
    return np.exp(-radius / a - np.abs(z + Z0) / h) / (4 * np.pi * a * a * h)


def nsc_shape(x, y, z) -> np.ndarray:
    r2 = (x - R0) ** 2 + y * y + (z + Z0) ** 2
    a = NSC_PLUMMER_PC
    return 3.0 / (4 * np.pi * a**3) * (1 + r2 / (a * a)) ** -2.5


def halo_profile(x, y, z) -> np.ndarray:
    """The halo's density, not normalised."""
    X, Z = x - R0, z + Z0
    r = np.sqrt(X * X + y * y + Z * Z)
    low, high = HALO_FLATTENING
    band = HALO_FLATTENING_BAND_PC
    q = low + (high - low) * smoothstep((r - band[0]) / (band[1] - band[0]))
    rq = np.sqrt(X * X + y * y + (Z / q) ** 2 + HALO_CORE_PC**2) / HALO_BREAK_PC
    inner, outer = HALO_SLOPES
    return np.where(rq < 1, rq**-inner, rq**-outer)


@cache
def halo_integral() -> float:
    """The halo's integral to 100 kpc, on a grid in spherical shells."""
    radii = np.geomspace(10.0, HALO_REACH_PC, 600)
    mu = np.linspace(-1, 1, 201)[:-1] + 0.005
    r, m = np.meshgrid(radii, mu, indexing="ij")
    profile = halo_profile(R0 + r * np.sqrt(1 - m * m), 0.0 * r, r * m - Z0)
    shell = np.gradient(radii)[:, None] * 2 * np.pi * radii[:, None] ** 2 * 0.01
    return float((profile * shell).sum())


def halo_shape(x, y, z) -> np.ndarray:
    """The stellar halo, integral 1 within 100 kpc."""
    return halo_profile(x, y, z) / halo_integral()


@dataclass(frozen=True)
class Model:
    """The calibrated model. Profiles are surface densities in G flux per pc^2 on
    `radius`; totals are G flux. `far_side` is the far-side arm contrast."""

    radius: np.ndarray
    thin: np.ndarray
    thin_bp_rp: np.ndarray
    thick: np.ndarray
    young: np.ndarray
    flux: dict[str, float]
    bp_rp: dict[str, float]
    far_side: float = geometry.FAR_SIDE_ARMS
    raw: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path, far_side: float | None = None) -> Model:
        data = json.loads(path.read_text())
        profiles = data["profiles"]
        return cls(
            np.array(profiles["radius_pc"]),
            np.array(profiles["thin"]),
            np.array(profiles["thin_bp_rp"]),
            np.array(profiles["thick"]),
            np.array(profiles["young"]),
            data["flux"],
            data["bp_rp"],
            geometry.FAR_SIDE_ARMS if far_side is None else far_side,
            data,
        )

    def _profile(self, values: np.ndarray, R: np.ndarray) -> np.ndarray:
        return np.interp(R, self.radius, values, right=0.0)

    def densities(self, x, y, z, names=COMPONENTS) -> dict[str, np.ndarray]:
        """G flux per pc^3 of each named component at the points."""
        R, beta, Z = geometry.galactocentric(x, y, z)
        dz = Z - geometry.warp_height(R, beta)
        out: dict[str, np.ndarray] = {}
        if "thin" in names:
            vertical = np.exp(-np.abs(dz) / THIN_HEIGHT_PC) / (2 * THIN_HEIGHT_PC)
            out["thin"] = (
                self._profile(self.thin, R) * vertical * geometry.old_arms(R, beta)
            )
        if "thick" in names:
            vertical = np.exp(-np.abs(dz) / THICK_HEIGHT_PC) / (2 * THICK_HEIGHT_PC)
            out["thick"] = self._profile(self.thick, R) * vertical
        if "young" in names:
            out["young"] = self._young(x, R, beta, dz)
        if "bulge" in names:
            out["bulge"] = self.flux["bulge"] * bulge_shape(x, y, z)
        if "bar" in names:
            out["bar"] = self.flux["bar"] * bar_shape(x, y, z, BAR_HEIGHT_PC)
        if "superthin" in names:
            out["superthin"] = self.flux["superthin"] * bar_shape(
                x, y, z, SUPERTHIN_HEIGHT_PC
            )
        if "nsd" in names:
            out["nsd"] = self.flux["nsd"] * nsd_shape(x, y, z)
        if "nsc" in names:
            out["nsc"] = self.flux["nsc"] * nsc_shape(x, y, z)
        if "halo" in names:
            out["halo"] = self.flux["halo"] * halo_shape(x, y, z)
        for name in ("lmc", "smc"):
            if name in names:
                out[name] = self.flux[name] * clouds.shape(name, x, y, z)
        return out

    def _young(self, x, R, beta, dz) -> np.ndarray:
        surface = self._profile(self.young, R)
        sigma = geometry.young_sigma_z(R)
        out = np.zeros_like(surface)
        near = (surface > 0) & (np.abs(dz) < 8 * sigma)
        if near.any():
            field_, mean = geometry.contrasted_arms(
                x[near], R[near], beta[near], self.far_side
            )
            # Where no arm passes the young light would divide by nothing.
            ratio = np.where(mean > 1e-3, field_ / np.maximum(mean, 1e-3), 1.0)
            vertical = np.exp(-0.5 * (dz[near] / sigma[near]) ** 2) / (
                np.sqrt(2 * np.pi) * sigma[near]
            )
            out[near] = surface[near] * ratio * vertical
        return out

    def colours(self, name: str, x, y, z) -> np.ndarray:
        """The display colour of a component at the points, shape (n, 3)."""
        if name == "thin":
            R = np.hypot(np.asarray(x) - R0, y)
            return photometry.display(np.interp(R, self.radius, self.thin_bp_rp))
        return np.broadcast_to(photometry.display(self.bp_rp[name]), (len(x), 3))

    def rgb(self, x, y, z, names=COMPONENTS) -> np.ndarray:
        """Display flux per pc^3 and channel, shape (n, 3)."""
        out = np.zeros((len(x), 3))
        for name, density in self.densities(x, y, z, names).items():
            out += density[:, None] * self.colours(name, x, y, z)
        return out
