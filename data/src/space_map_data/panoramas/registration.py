"""Frames of one mast sweep, registered against each other.

A mast camera turns about the mast, not about its own lens, so the lens moves
between frames and nearby ground shifts by degrees from one frame to the next.
The stated pointing of a frame can also be a degree off. Both faults show where
frames overlap: the first as blur, the second as edges that do not meet.

The overlaps measure the pointing. The lens positions come from the label, in
the same east-north-up frame as its pointing vectors, and the ground is taken
as a level plane below the mast, so a lens that moved still puts each piece of
ground at one place on the sphere.
"""

from dataclasses import dataclass
import logging
import math

import numpy as np

logger = logging.getLogger(__name__)

# Overlaps are compared with frames about this many samples wide. Phase
# correlation splits a sample tenfold, which is finer than the sphere.
MEASURE_WIDTH = 512
# Block sizes in samples, coarse then fine. The coarse pass must hold the
# whole fault of the stated model, the fine pass only what is left of it.
BLOCKS = (128, 64)
STRIDE = 32
# Correlation peaks below this are texture-free sky or sand.
MINIMUM_PEAK = 0.1
# Samples around a peak left out when judging whether it stands alone, and
# the share of the peak its row or column may reach before it is a ridge.
RIDGE = 3
MAXIMUM_RIDGE = 0.5
MINIMUM_MATCHES = 12
# A correction larger than this means the matches are wrong, not the label.
MAXIMUM_CORRECTION_DEG = 6
# The stated lens positions must turn with the view to this tolerance before
# the circle they lie on is believed; a short arc of a few frames fits any.
ARM_TOLERANCE_DEG = 3
# Metres the lens can plausibly stand above the ground.
HEIGHT_RANGE_M = (0.5, 4)
# Radians below which a match is trusted in full.
TRUST_FLOOR = math.radians(0.05)
# Radians beyond which a match counts as simply wrong.
OUTLIER = math.radians(1.5)
# Elevations, in degrees, between which a match loses its say in the solve.
# The far field is the ground plane and the sky, and only a rotation moves
# it; the steep near field holds the craft's own deck and wheels, which no
# plane models, and a fit that chases them puts a step in the horizon. The
# horizon itself is what the eye follows across a seam, so a match that
# straddles it counts three times.
FAR_FIELD_DEG, NEAR_FIELD_DEG, HORIZON_DEG = -8.0, -25.0, -4.0
NEAR_FIELD_SAY, HORIZON_SAY = 0.05, 3.0


@dataclass(frozen=True)
class Lens:
    """A pinhole: raster size, focal length and principal point in pixels."""

    width: int
    height: int
    scale: float
    centre_x: float
    centre_y: float

    def rays(self, x, y):
        found = np.stack(
            [
                (x - self.centre_x) / self.scale,
                (y - self.centre_y) / self.scale,
                np.ones(np.shape(x)),
            ],
            axis=-1,
        )
        return found / np.linalg.norm(found, axis=-1, keepdims=True)

    def pixels(self, rays):
        """Pixel coordinates of camera-frame rays, and which of them land."""
        with np.errstate(divide="ignore", invalid="ignore"):
            x = self.centre_x + rays[..., 0] / rays[..., 2] * self.scale
            y = self.centre_y + rays[..., 1] / rays[..., 2] * self.scale
        inside = (
            (rays[..., 2] > 0)
            & (x >= 0)
            & (x <= self.width - 1)
            & (y >= 0)
            & (y <= self.height - 1)
        )
        return np.nan_to_num(x), np.nan_to_num(y), inside


@dataclass
class Sweep:
    """Where every lens of a sweep stood and looked."""

    rotations: list[np.ndarray]
    # Lens positions from the mast axis, in metres, in the frame of the sphere.
    offsets: np.ndarray
    height_m: float
    report: dict


def lens_rays(views, offset, height_m: float):
    """Directions from a lens to what the sphere shows along `views`."""
    drop = np.maximum(0, -views[..., 2:3]) / height_m
    return views - offset * drop


def view_directions(rays, offset, height_m: float):
    """The inverse of `lens_rays`, for rays from a lens level with the axis."""
    drop = np.maximum(0, -rays[..., 2:3]) / height_m
    found = rays + offset * drop
    return found / np.linalg.norm(found, axis=-1, keepdims=True)


def reduce(raster, factor: int):
    """Box-average a raster; pixel `i` of the result centres on `i * factor + (factor - 1) / 2`."""
    if factor == 1:
        return raster.astype(np.float32)
    rows = raster.shape[0] // factor * factor
    columns = raster.shape[1] // factor * factor
    shaped = raster[:rows, :columns].reshape(
        rows // factor, factor, columns // factor, factor, *raster.shape[2:]
    )
    return shaped.mean(axis=(1, 3), dtype=np.float32)


def sample(reduced, factor: int, x, y):
    """Bilinear samples of a reduced raster at full-scale pixel coordinates."""
    rows, columns = reduced.shape[:2]
    x = np.clip((x - (factor - 1) / 2) / factor, 0, columns - 1)
    y = np.clip((y - (factor - 1) / 2) / factor, 0, rows - 1)
    left = np.minimum(x.astype(np.int32), columns - 2)
    top = np.minimum(y.astype(np.int32), rows - 2)
    right_share = (x - left).astype(np.float32)
    bottom_share = (y - top).astype(np.float32)
    if reduced.ndim == 3:
        right_share = right_share[..., None]
        bottom_share = bottom_share[..., None]
    upper = (
        reduced[top, left] * (1 - right_share) + reduced[top, left + 1] * right_share
    )
    lower = (
        reduced[top + 1, left] * (1 - right_share)
        + reduced[top + 1, left + 1] * right_share
    )
    return upper * (1 - bottom_share) + lower * bottom_share


def skew(vector):
    x, y, z = vector
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])


def turn(vector):
    """The rotation a rotation vector names."""
    angle = np.linalg.norm(vector)
    if angle < 1e-12:
        return np.eye(3)
    axis = skew(vector / angle)
    return np.eye(3) + math.sin(angle) * axis + (1 - math.cos(angle)) * axis @ axis


def lens_offsets(centres, rotations):
    """Where each lens stood from the mast axis, or None if the label cannot say.

    The positions lie on a circle about the axis. Its centre is fitted, and
    the fit is believed only if the lens turns with the view: the mirrored
    reading of the frame fails that check, and so does a short arc.
    """
    points = np.asarray(centres, float)
    if len(points) < 3:
        return None
    flat = points[:, :2]
    design = np.column_stack([2 * flat, np.ones(len(flat))])
    solved, *_ = np.linalg.lstsq(design, (flat**2).sum(axis=1), rcond=None)
    offsets = np.column_stack([flat - solved[:2], np.zeros(len(flat))])
    if not np.all(np.linalg.norm(offsets, axis=1) > 0):
        return None
    axes = np.array([r[:, 2] for r in rotations])
    # Bearing of the arm less bearing of the view, as one angle per frame.
    turned = np.exp(
        1j
        * (
            np.arctan2(offsets[:, 0], offsets[:, 1])
            - np.arctan2(axes[:, 0], axes[:, 1])
        )
    )
    spread = np.degrees(np.abs(np.angle(turned / turned.mean())).max())
    return offsets if spread < ARM_TOLERANCE_DEG else None


def phase_shift(first, second):
    """How far `second` must move to lie on `first`, and how sure that is."""
    size = first.shape[0]
    window = np.hanning(size)[:, None] * np.hanning(size)[None, :]
    one = np.fft.rfft2((first - first.mean()) * window)
    other = np.fft.rfft2((second - second.mean()) * window)
    cross = one * np.conj(other)
    surface = np.fft.irfft2(cross / (np.abs(cross) + 1e-6), s=first.shape)
    peak = np.unravel_index(np.argmax(surface), surface.shape)
    shift = []
    for axis, position in enumerate(peak):
        index = list(peak)
        values = []
        for step in (-1, 0, 1):
            index[axis] = (position + step) % size
            values.append(surface[tuple(index)])
        curve = values[0] - 2 * values[1] + values[2]
        exact = position + (0 if curve == 0 else 0.5 * (values[0] - values[2]) / curve)
        shift.append(exact - size if exact > size / 2 else exact)
    # A block that holds one straight edge, such as a bare horizon, matches
    # anywhere along that edge: its peak is a ridge, and the shift along the
    # ridge means nothing. The peak's height over the rest of its own row and
    # column says whether it is a point at all.
    row, column = surface[peak[0]].copy(), surface[:, peak[1]].copy()
    for line, position in ((row, peak[1]), (column, peak[0])):
        line[[(position + step) % size for step in range(-RIDGE, RIDGE + 1)]] = 0
    ridge = max(row.max(), column.max()) / (surface[peak] + 1e-9)
    return shift[1], shift[0], float(surface[peak]), float(ridge)


class Registration:
    def __init__(self, lenses, rasters, rotations, offsets, height_m):
        self.lenses = lenses
        self.reduction = max(1, min(lens.width for lens in lenses) // MEASURE_WIDTH)
        self.grays = [
            reduce(r.mean(axis=-1) if r.ndim == 3 else r, self.reduction)
            for r in rasters
        ]
        self.stated = [np.asarray(r, float) for r in rotations]
        self.offsets = offsets
        self.height_m = height_m
        self.pairs = self.overlapping(np.array([r[:, 2] for r in self.stated]))

    def overlapping(self, axes):
        found = []
        for i in range(len(axes)):
            for j in range(i + 1, len(axes)):
                reach = math.atan(
                    self.lenses[i].width / 2 / self.lenses[i].scale
                ) + math.atan(self.lenses[j].width / 2 / self.lenses[j].scale)
                if math.acos(np.clip(axes[i] @ axes[j], -1, 1)) < 0.9 * reach:
                    found.append((i, j))
        return found

    def measure(self, rotations, offsets, block):
        """Points that two frames both show, as a ray of each."""
        found = ([], [])
        for i, j in self.pairs:
            scale = min(self.lenses[i].scale, self.lenses[j].scale) / self.reduction
            centre = rotations[i][:, 2] + rotations[j][:, 2]
            centre /= np.linalg.norm(centre)
            right = np.cross(centre, [0, 0, 1.0])
            if np.linalg.norm(right) < 1e-6:
                right = np.array([1.0, 0, 0])
            right /= np.linalg.norm(right)
            upward = np.cross(right, centre)
            half = math.tan(
                math.atan(self.lenses[i].width / 2 / self.lenses[i].scale) * 1.1
            )
            steps = (np.arange(-half * scale, half * scale) + 0.5) / scale
            across, down = np.meshgrid(steps, steps)
            views = centre + across[..., None] * right - down[..., None] * upward
            views /= np.linalg.norm(views, axis=-1, keepdims=True)
            shown = []
            for k in (i, j):
                rays = lens_rays(views, offsets[k], self.height_m) @ rotations[k]
                x, y, inside = self.lenses[k].pixels(rays)
                shown.append(
                    (sample(self.grays[k], self.reduction, x, y), x, y, inside)
                )
            both = shown[0][3] & shown[1][3]
            for row in range(0, both.shape[0] - block + 1, STRIDE):
                for column in range(0, both.shape[1] - block + 1, STRIDE):
                    cut = np.s_[row : row + block, column : column + block]
                    if not both[cut].all():
                        continue
                    dx, dy, peak, ridge = phase_shift(
                        shown[0][0][cut], shown[1][0][cut]
                    )
                    if (
                        peak < MINIMUM_PEAK
                        or ridge > MAXIMUM_RIDGE
                        or max(abs(dx), abs(dy)) > block / 3
                    ):
                        continue
                    # What the first frame shows here, the second shows there.
                    here = (row + block // 2, column + block // 2)
                    there = np.array(
                        centre
                        + (steps[here[1]] - dx / scale) * right
                        - (steps[here[0]] - dy / scale) * upward
                    )
                    rays = lens_rays(there, offsets[j], self.height_m) @ rotations[j]
                    x, y, inside = self.lenses[j].pixels(rays)
                    if not inside:
                        continue
                    found[0].append((i, shown[0][1][here], shown[0][2][here]))
                    found[1].append((j, float(x), float(y)))
        return [self.camera_rays(side) for side in found]

    def camera_rays(self, sightings):
        """Frame indices and camera-frame rays of one side of every match."""
        frames = np.array([s[0] for s in sightings], dtype=np.int64)
        rays = np.array(
            [self.lenses[k].rays(np.float64(x), np.float64(y)) for k, x, y in sightings]
        ).reshape(-1, 3)
        return frames, rays

    def rotations(self, parameters):
        return [
            turn(parameters[3 * k : 3 * k + 3]) @ stated
            for k, stated in enumerate(self.stated)
        ]

    def residuals(self, matches, parameters, offsets):
        """How far apart the sphere puts the two sightings of every match."""
        rotations = np.array(self.rotations(parameters))
        seen = [
            view_directions(
                np.einsum("nij,nj->ni", rotations[frames], rays),
                offsets[frames],
                self.height_m,
            )
            for frames, rays in matches
        ]
        return (seen[0] - seen[1]).ravel()

    def far_field(self, matches):
        """How much of a say each match gets, by how far below the horizon it looks."""
        frames, rays = matches[0]
        stated = np.array(self.stated)
        elevation = np.degrees(
            np.arcsin(np.einsum("nij,nj->ni", stated[frames], rays)[:, 2])
        )
        share = np.clip(
            (elevation - NEAR_FIELD_DEG) / (FAR_FIELD_DEG - NEAR_FIELD_DEG),
            NEAR_FIELD_SAY,
            1,
        ) * np.where(elevation > HORIZON_DEG, HORIZON_SAY, 1)
        # Only the say of one match against another's; a sweep that looks
        # steeply down everywhere is not held to the label any harder.
        return share / share.mean()

    def solve(self, matches, offsets):
        """Gauss-Newton on every rotation, from the stated pointing."""
        count = len(self.stated)
        parameters = np.zeros(3 * count)
        say = self.far_field(matches)
        # One match's worth of pull towards the label: it fixes the turn of the
        # whole sweep, which no overlap can see, and nothing else.
        prior = np.eye(3 * count)
        for _ in range(20):
            residual = self.residuals(matches, parameters, offsets)
            size = np.linalg.norm(residual.reshape(-1, 3), axis=1)
            trust = np.repeat(say * self.trust(matches, size), 3)
            jacobian = np.empty((len(residual), 3 * count))
            for column in range(3 * count):
                moved = parameters.copy()
                moved[column] += 1e-6
                jacobian[:, column] = (
                    self.residuals(matches, moved, offsets) - residual
                ) / 1e-6
            step, *_ = np.linalg.lstsq(
                np.vstack([jacobian * trust[:, None], prior]),
                np.concatenate([-residual * trust, -parameters]),
                rcond=None,
            )
            parameters += step
            if np.abs(step).max() < 1e-6:
                break
        return parameters, self.cost(matches, parameters, offsets)

    def trust(self, matches, size):
        """How far each match is believed, judged against its own pair.

        A match that disagrees with the rest of its pair is a wrong match. A
        whole pair that disagrees with the rest of the sweep is a label error,
        which is what the solve is for: a sweep whose first and last frames
        miss each other by a degree must still close.
        """
        pair = matches[0][0] * len(self.stated) + matches[1][0]
        limit = np.empty_like(size)
        for key in np.unique(pair):
            members = pair == key
            # The scale comes from the better matches of the pair: a wrong
            # match with a loud say can otherwise hold the median up to its
            # own miss. Frames repeated at one pointing match exactly, and a
            # scale of zero would leave every other match untrusted.
            limit[members] = max(2 * np.percentile(size[members], 20), TRUST_FLOOR)
        return np.where(size < limit, 1, limit / size)

    def cost(self, matches, parameters, offsets) -> float:
        """Mean miss in degrees, with no match allowed to count for more than an outlier."""
        size = np.linalg.norm(
            self.residuals(matches, parameters, offsets).reshape(-1, 3), axis=1
        )
        return float(np.degrees(np.minimum(size, OUTLIER).mean()))

    def run(self) -> Sweep:
        count = len(self.stated)
        still = np.zeros((count, 3))
        stated = Sweep(
            self.stated, still, self.height_m, {"status": "stated pointing kept"}
        )
        # A lens that stayed on the axis is tried too: a label can be wrong
        # about where the lens stood, and the overlaps then say so.
        candidates = [still] if self.offsets is None else [self.offsets, still]
        offsets, parameters = candidates[0], np.zeros(3 * count)
        for block in BLOCKS:
            matches = self.measure(self.rotations(parameters), offsets, block)
            if len(matches[0][0]) < MINIMUM_MATCHES:
                logger.info("Too few overlap matches to register")
                return stated
            parameters, cost, offsets = min(
                ((*self.solve(matches, tried), tried) for tried in candidates),
                key=lambda found: found[1],
            )
        report = {
            "matches": len(matches[0][0]),
            "residual_deg": round(cost, 3),
            "stated_residual_deg": round(
                self.cost(matches, np.zeros(3 * count), still), 3
            ),
        }
        turned = np.degrees(np.linalg.norm(parameters.reshape(-1, 3), axis=1))
        if (
            turned.max() > MAXIMUM_CORRECTION_DEG
            or report["residual_deg"] >= report["stated_residual_deg"]
        ):
            logger.info("Registration refused: %s, turned %.1f°", report, turned.max())
            return stated
        report["status"] = "registered on overlaps"
        report["largest_correction_deg"] = round(float(turned.max()), 3)
        report["lens_on_axis"] = offsets is still
        if offsets is not still:
            report["lens_arm_m"] = round(
                float(np.linalg.norm(offsets, axis=1).mean()), 4
            )
            report["lens_height_m"] = round(self.height_m, 3)
        return Sweep(self.rotations(parameters), offsets, self.height_m, report)


def register(lenses, rasters, rotations, centres=None) -> Sweep:
    """Register the frames of one sweep; the stated pointing stands if that fails.

    `centres` are the lens positions a label states, east-north-up in metres,
    with the ground at zero.
    """
    offsets, height = None, HEIGHT_RANGE_M[0]
    if centres is not None:
        offsets = lens_offsets(centres, rotations)
        height = float(np.mean(np.asarray(centres, float)[:, 2]))
        if not HEIGHT_RANGE_M[0] < height < HEIGHT_RANGE_M[1]:
            offsets = None
    return Registration(lenses, rasters, rotations, offsets, height).run()
