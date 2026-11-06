"""The geometry that the model light and the dust's rest layer share: the Sun's
place, the warp, the young arms and their flare. Lanes sit on the arms only if dust
and young light read the same arms.

Positions are on nest axes in pc: the Sun at the origin, x to the Galactic centre, y
to l = 90 deg, z to the north Galactic pole. The azimuth `beta` is Galactocentric, 0
toward the Sun and growing in the sense of rotation (toward +y), as in Reid et al.
2019. Each published length is scaled from the R0 of its paper to R0 = 8,277 pc.
"""

from dataclasses import dataclass
from functools import cache

import numpy as np

from space_map_data.dust.nest import smoothstep

# GRAVITY Collaboration 2022.
R0 = 8277.0
# Bennett & Bovy 2019: 20.8 +- 0.3 pc above the plane.
Z0 = 21.0
REID_R0 = 8150.0
CHEN_R0 = 8000.0
DS01_R0 = 8000.0
REID_SCALE = R0 / REID_R0

# The contrast of the young arms past the Galactic centre, in light and in dust. No
# parallax places the arms there (Reid et al. 2019), so this is Julie's choice: 1
# draws the published geometry, 0 keeps only their mean over azimuth.
FAR_SIDE_ARMS = 1.0
# The contrast changes over this distance either side of the centre, along x.
FAR_SIDE_BAND_PC = 1000.0

# Chen et al. 2019, Table 1, the linear fit to all Cepheids.
WARP_RADIUS_PC = 9260.0 * R0 / CHEN_R0
WARP_SLOPE = 0.148
WARP_NODES = np.radians(17.4)

# Reid et al. 2019: the arms' vertical 1 sigma, 20 pc to 7 kpc and 36 pc/kpc past it.
YOUNG_SIGMA_Z_PC = 20.0
YOUNG_FLARE_START_PC = 7000.0
YOUNG_FLARE_SLOPE = 0.036
# Reid et al. 2014, as Reid 2019 adopts it: arm width grows 42 pc per kpc.
ARM_WIDTH_SLOPE = 0.042
ARM_WIDTH_FLOOR_PC = 100.0

# Old stars: an m = 2 pattern at +-10% (Eilers et al. 2020), pitch 12 deg, its crest
# on Reid's Perseus arm at beta = 0, faded in past the bar.
OLD_ARM_AMPLITUDE = 0.10
OLD_ARM_PITCH = np.radians(12.0)
OLD_ARM_RAMP_PC = (4000.0, 5000.0)

# Drimmel & Spergel 2001, Table 1 (their R0 = 8 kpc): the dust disc, and the dust arms'
# density and radial cut-off. The arms take the young geometry, width and height.
DS01_SCALE = R0 / DS01_R0
DUST_SCALE_LENGTH_PC = 2260.0 * DS01_SCALE
DUST_SCALE_HEIGHT_PC = 134.4 * DS01_SCALE
DUST_ARM_DENSITY = 162.0 / 1098.0
DUST_ARM_CUTOFF_PC = 6710.0 * DS01_SCALE
DUST_ARM_CUTOFF_LENGTH_PC = 2070.0 * DS01_SCALE
# Drimmel & Spergel's arm height, exp(-(z / 80 pc)^2), as a 1 sigma. The young light's
# flare adds to it. The masers' 20 pc layer inside 7 kpc is too thin for the dust: it
# leaves 5% of the Planck remainder at |b| < 2 deg unplaced.
DUST_ARM_SIGMA_PC = 80.0 / np.sqrt(2.0) * DS01_SCALE


def galactocentric(
    x: np.ndarray, y: np.ndarray, z: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Radius R (pc), azimuth beta (rad) and height above the plane Z (pc)."""
    X = x - R0
    return np.hypot(X, y), np.arctan2(y, -X), z + Z0


def warp_height(R: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """The height of the warped plane (pc), with the line of nodes of Chen 2019."""
    return WARP_SLOPE * np.maximum(R - WARP_RADIUS_PC, 0.0) * np.sin(beta - WARP_NODES)


def young_flare(R: np.ndarray) -> np.ndarray:
    """What the arms add to their vertical size past 7 kpc (pc)."""
    s = REID_SCALE
    return s * YOUNG_FLARE_SLOPE * np.maximum(R / s - YOUNG_FLARE_START_PC, 0.0)


def young_sigma_z(R: np.ndarray) -> np.ndarray:
    """The vertical 1 sigma of the young arms (pc)."""
    return REID_SCALE * YOUNG_SIGMA_Z_PC + young_flare(R)


# Reid et al. 2019, Table 2 (R0 = 8.15 kpc): beta_kink (deg), R_kink (kpc), pitch
# before and after the kink (deg), width (kpc, 1 sigma).
REID = {
    "3-kpc": (15.0, 3.52, -4.2, -4.2, 0.18),
    "Norma": (18.0, 4.46, -1.0, 19.5, 0.14),
    "Sct-Cen": (23.0, 4.91, 14.1, 12.1, 0.23),
    "Sgr-Car": (24.0, 6.04, 17.1, 1.0, 0.27),
    "Local": (9.0, 8.26, 11.4, 11.4, 0.31),
    "Perseus": (40.0, 8.87, 10.3, 8.7, 0.35),
    "Outer": (18.0, 12.24, 3.0, 9.4, 0.65),
}
# Drimmel et al. 2025, Table 2 (R0 = 8.277 kpc): pitch (deg) and ln R (kpc) at beta =
# 0, from Cepheids at beta -90 to 0 deg, the third and fourth quadrants.
D25 = {
    "Scutum": (10.4, 1.56),
    "Sgr-Car": (14.7, 2.0),
    "Orion": (15.8, 2.25),
    "Perseus": (21.5, 2.47),
}
# Drimmel's arms hold beta -90 to 0 deg, and Reid's the rest. The two sets cross-fade
# over this many degrees about each edge. Matching arm to arm would draw two arms
# where the papers disagree on which arm is which (Drimmel's Perseus lies on Reid's
# Outer arm at beta = 0).
D25_RANGE_DEG = (-90.0, 0.0)
D25_BLEND_DEG = 15.0
# Reid sets Sgr-Car's pitch to 10 deg past its masers (beta 2 to 97 deg): toward the
# fourth-quadrant tangent to match CO, and in to the bar by symmetry.
SGR_CAR_MASERS_DEG = (2.0, 97.0)
SGR_CAR_EXTENDED_PITCH = 10.0
# Norma joins Outer one turn in (Reid 2019): Outer's spiral runs in to here.
NORMA_JOIN_DEG = 365.0
TABLE_STEP_DEG = 0.1


def _reid_lnr(name: str, beta_deg: np.ndarray) -> np.ndarray:
    kink, radius, before, after = REID[name.removesuffix("-measured")][:4]
    pitch = np.where(beta_deg < kink, before, after)
    lnr = np.log(radius * 1000.0 * REID_SCALE) - np.radians(beta_deg - kink) * np.tan(
        np.radians(pitch)
    )
    if name == "Sgr-Car":
        for end in SGR_CAR_MASERS_DEG:
            at_end = _reid_lnr("Sgr-Car-measured", np.array(end))
            past = at_end - np.radians(beta_deg - end) * np.tan(
                np.radians(SGR_CAR_EXTENDED_PITCH)
            )
            beyond = beta_deg > end if end > kink else beta_deg < end
            lnr = np.where(beyond, past, lnr)
    return lnr


def d25_zone(beta: np.ndarray) -> np.ndarray:
    """The share of Drimmel's arms at each azimuth (rad); Reid's hold the rest."""
    degrees = (np.degrees(beta) + 180.0) % 360.0 - 180.0
    low, high = D25_RANGE_DEG
    b = D25_BLEND_DEG
    return smoothstep((degrees - low + b) / (2 * b)) * smoothstep(
        (high + b - degrees) / (2 * b)
    )


@dataclass(frozen=True)
class Arm:
    """One young arm over its range of azimuth, in degrees past a full turn where it
    winds on. Its ends fade over `fade` degrees. `drimmel` arms take their geometry
    from Drimmel et al. 2025 and their width from Reid's arm `reid`."""

    name: str
    low: float
    high: float
    fade: float
    drimmel: bool = False
    reid: str = ""

    def lnr(self, beta_deg: np.ndarray) -> np.ndarray:
        """ln R (pc) of the arm's ridge."""
        if self.drimmel:
            pitch, ln_r0 = D25[self.name]
            return (
                ln_r0
                + np.log(1000.0)
                - np.radians(beta_deg) * np.tan(np.radians(pitch))
            )
        if self.name == "Norma-Outer":
            outer = _reid_lnr("Outer", beta_deg)
            norma = _reid_lnr("Norma", beta_deg - 360.0)
            s = smoothstep((beta_deg - NORMA_JOIN_DEG + 5.0) / 10.0)
            return (1 - s) * outer + s * norma
        return _reid_lnr(self.name, beta_deg)

    def width(self, radius: np.ndarray) -> np.ndarray:
        """The 1 sigma width (pc) at the ridge radius."""
        name = self.reid or self.name
        if name == "Norma-Outer":
            inner, outer = REID["Norma"], REID["Outer"]
            slope = (outer[4] - inner[4]) / (outer[1] - inner[1])
            kink, w = inner[1], inner[4]
        else:
            kink, w, slope = REID[name][1], REID[name][4], ARM_WIDTH_SLOPE
        w_pc = REID_SCALE * 1000.0 * (w + slope * (radius / REID_SCALE / 1000.0 - kink))
        return np.maximum(w_pc, ARM_WIDTH_FLOOR_PC)

    def ends(self, beta_deg: np.ndarray) -> np.ndarray:
        return smoothstep((beta_deg - self.low) / self.fade) * smoothstep(
            (self.high - beta_deg) / self.fade
        )


# Reid's arms run from the bar to past the disc edge on their own pitches; the light's
# envelope and the dust's cut-off end them in radius. Sct-Cen so reaches the outer
# Scutum-Centaurus arm. The Local arm is a segment (Reid 2019), and the 3-kpc arm
# holds three masers. Drimmel's arms hold only the azimuths they measured.
ARMS = (
    Arm("Sct-Cen", -280.0, 140.0, 20.0),
    Arm("Sgr-Car", -180.0, 267.0, 20.0),
    Arm("Local", -60.0, 54.0, 20.0),
    Arm("Perseus", -180.0, 388.0, 20.0),
    Arm("Norma-Outer", -180.0, 414.0, 20.0),
    Arm("3-kpc", 0.0, 35.0, 10.0),
    Arm("Scutum", -110.0, 20.0, 10.0, True, "Sct-Cen"),
    Arm("Sgr-Car", -110.0, 20.0, 10.0, True, "Sgr-Car"),
    Arm("Orion", -110.0, 20.0, 10.0, True, "Local"),
    Arm("Perseus", -110.0, 20.0, 10.0, True, "Perseus"),
)


@dataclass(frozen=True)
class ArmTable:
    beta: np.ndarray
    lnr: np.ndarray
    # tan of the local pitch, -d ln R / d beta.
    tan_pitch: np.ndarray


@cache
def arm_table(arm: Arm) -> ArmTable:
    beta = np.arange(arm.low, arm.high + TABLE_STEP_DEG / 2, TABLE_STEP_DEG)
    lnr = arm.lnr(beta)
    return ArmTable(beta, lnr, -np.gradient(lnr, np.radians(beta)))


def arm_field(R: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """A Gaussian across each ridge, 1 on a ridge. Where arms overlap the nearest
    holds, as in Drimmel & Spergel 2001: Reid's pitches, carried past his masers,
    make some arms cross on the far side."""
    degrees = np.degrees(beta)
    zone = d25_zone(beta)
    fields = {False: np.zeros(np.shape(R)), True: np.zeros(np.shape(R))}
    for arm in ARMS:
        table = arm_table(arm)
        field = fields[arm.drimmel]
        first = int(np.floor((arm.low - 180.0) / 360.0))
        last = int(np.ceil((arm.high + 180.0) / 360.0))
        for turn in range(first, last + 1):
            b = degrees + 360.0 * turn
            inside = (b > arm.low) & (b < arm.high)
            if not inside.any():
                continue
            at = b[inside]
            ridge = np.exp(np.interp(at, table.beta, table.lnr))
            tan_pitch = np.interp(at, table.beta, table.tan_pitch)
            across = (R[inside] - ridge) / np.sqrt(1.0 + tan_pitch * tan_pitch)
            sigma = arm.width(ridge)
            here = np.exp(-0.5 * (across / sigma) ** 2) * arm.ends(at)
            field[inside] = np.maximum(field[inside], here)
    return (1.0 - zone) * fields[False] + zone * fields[True]


MEAN_STEP_PC = 25.0
MEAN_REACH_PC = 30000.0
MEAN_AZIMUTHS = 1800


@cache
def _mean_table() -> tuple[np.ndarray, np.ndarray]:
    radii = np.arange(0.0, MEAN_REACH_PC + MEAN_STEP_PC, MEAN_STEP_PC)
    beta = (np.arange(MEAN_AZIMUTHS) + 0.5) / MEAN_AZIMUTHS * 2 * np.pi - np.pi
    R, B = np.meshgrid(radii, beta, indexing="ij")
    return radii, arm_field(R.ravel(), B.ravel()).reshape(R.shape).mean(axis=1)


def arm_mean(R: np.ndarray) -> np.ndarray:
    """The mean of `arm_field` over azimuth at each radius."""
    radii, mean = _mean_table()
    return np.interp(R, radii, mean)


def far_side_contrast(x: np.ndarray, far_side: float = FAR_SIDE_ARMS) -> np.ndarray:
    return 1.0 + (far_side - 1.0) * smoothstep(
        (x - R0 + FAR_SIDE_BAND_PC) / (2 * FAR_SIDE_BAND_PC)
    )


def contrasted_arms(
    x: np.ndarray, R: np.ndarray, beta: np.ndarray, far_side: float = FAR_SIDE_ARMS
) -> tuple[np.ndarray, np.ndarray]:
    """The arm field with the far-side contrast, and its mean over azimuth. The
    contrast keeps the mean, so the far side holds the same light either way."""
    field = arm_field(R, beta)
    mean = arm_mean(R)
    return mean + far_side_contrast(x, far_side) * (field - mean), mean


def old_arms(R: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """The weak m = 2 pattern of old stars, a factor about 1."""
    crest_r = float(np.exp(_reid_lnr("Perseus", np.zeros(1)))[0])
    crest = -np.log(np.maximum(R, 1.0) / crest_r) / np.tan(OLD_ARM_PITCH)
    ramp = smoothstep(
        (R - OLD_ARM_RAMP_PC[0]) / (OLD_ARM_RAMP_PC[1] - OLD_ARM_RAMP_PC[0])
    )
    return 1.0 + OLD_ARM_AMPLITUDE * ramp * np.cos(2.0 * (beta - crest))


def dust_shape(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, far_side: float = FAR_SIDE_ARMS
) -> np.ndarray:
    """Dust density of the rest layer, 1 on the plane at the Sun's radius off the
    arms: Drimmel & Spergel's disc and arms, on the young arms, warp and flare."""
    R, beta, Z = galactocentric(x, y, z)
    dz = Z - warp_height(R, beta)
    inner = 0.5 * R0
    radial = np.exp(-(np.maximum(R, inner) - R0) / DUST_SCALE_LENGTH_PC)
    hole = np.exp(-((np.minimum(R - inner, 0.0) / (0.25 * R0)) ** 2))
    height = DUST_SCALE_HEIGHT_PC + young_flare(R)
    disc = radial * hole / np.cosh(dz / height) ** 2
    sigma = DUST_ARM_SIGMA_PC + young_flare(R)
    near = np.abs(dz) < 8.0 * sigma
    arms = np.zeros_like(disc)
    if near.any():
        Rn = R[near]
        cut = np.where(
            Rn > DUST_ARM_CUTOFF_PC,
            np.exp(-(((Rn - DUST_ARM_CUTOFF_PC) / DUST_ARM_CUTOFF_LENGTH_PC) ** 2)),
            1.0,
        )
        field, _ = contrasted_arms(x[near], Rn, beta[near], far_side)
        peak = DUST_ARM_DENSITY * np.exp(R0 / DUST_SCALE_LENGTH_PC)
        arms[near] = peak * cut * field * np.exp(-0.5 * (dz[near] / sigma[near]) ** 2)
    return disc + arms
