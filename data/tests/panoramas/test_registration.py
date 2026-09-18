import math

import numpy as np

from space_map_data.panoramas import registration
from space_map_data.panoramas.registration import Lens

LENS = Lens(512, 512, 600.0, 255.5, 255.5)
HEIGHT_M = 1.6
ARM_M = 0.2
# The lens stands to the right of the view, a third of the way to the front.
ARM = math.radians(60)


def pointing(azimuth_deg: float, pitch_deg: float) -> np.ndarray:
    """A level camera: columns are its right, down and forward, east-north-up."""
    azimuth, pitch = math.radians(azimuth_deg), math.radians(pitch_deg)
    forward = np.array(
        [
            math.cos(pitch) * math.sin(azimuth),
            math.cos(pitch) * math.cos(azimuth),
            math.sin(pitch),
        ]
    )
    right = np.array([math.cos(azimuth), -math.sin(azimuth), 0.0])
    return np.column_stack([right, np.cross(forward, right), forward])


def arm(azimuth_deg: float) -> np.ndarray:
    """Where the lens stands from the axis, east-north-up."""
    angle = math.radians(azimuth_deg) + ARM
    return ARM_M * np.array([math.sin(angle), math.cos(angle), 0.0])


def scene(seed=4):
    """Rough ground on a level plane under a blank sky, as a lens would see them.

    Grain at two scales, so that ground near the mast and ground near the
    horizon both hold texture the overlaps can lock on to.
    """
    fine = np.random.default_rng(seed).random((400, 400)).astype(np.float32)
    coarse = np.random.default_rng(seed + 1).random((40, 40)).astype(np.float32)

    def look(origin, rays):
        with np.errstate(divide="ignore", invalid="ignore"):
            reach = (HEIGHT_M + origin[2]) / -rays[..., 2]
        hit = origin[:2] + rays[..., :2] * reach[..., None]
        # Twenty fine texels to the metre, two coarse ones, tiled to the horizon.
        texel = np.nan_to_num(hit * 20) % 399
        seen = registration.sample(fine, 1, texel[..., 0], texel[..., 1]) * 0.5
        seen += registration.sample(coarse, 1, texel[..., 0] / 10, texel[..., 1] / 10)
        return np.where(rays[..., 2] < 0, seen / 1.5, 0.9) * 255

    return look


def sweep(azimuths, pitch_deg=-20.0):
    look = scene()
    columns, rows = np.meshgrid(np.arange(512.0), np.arange(512.0))
    rotations = [pointing(a, pitch_deg) for a in azimuths]
    rasters = [
        look(arm(a), LENS.rays(columns, rows) @ r.T)
        for a, r in zip(azimuths, rotations)
    ]
    return rotations, rasters


def between_views(first, second, view, camera) -> float:
    """Degrees by which two relative rotations disagree along one view.

    The view is a sky direction; `camera` turns the first frame onto the sky.
    """
    ray = camera.T @ view
    moved = first @ second.T @ ray
    return math.degrees(math.acos(np.clip(moved @ ray, -1, 1)))


def test_a_lens_ray_and_the_view_it_came_from_undo_each_other():
    views = np.array([[0.3, 0.5, -0.8], [0.1, -0.9, -0.2], [0.6, 0.0, 0.8]])
    views /= np.linalg.norm(views, axis=1, keepdims=True)
    offset = np.array([0.15, -0.1, 0.0])
    rays = registration.lens_rays(views, offset, 1.5)
    rays /= np.linalg.norm(rays, axis=1, keepdims=True)
    assert np.allclose(registration.view_directions(rays, offset, 1.5), views)
    # Sky has no distance, so a lens off the axis sees it where the axis does.
    assert np.allclose(rays[2], views[2])


def test_a_reduced_raster_is_sampled_at_full_scale_coordinates():
    ramp = np.tile(np.arange(90.0), (90, 1))
    reduced = registration.reduce(ramp, 3)
    assert reduced.shape == (30, 30)
    found = registration.sample(
        reduced, 3, np.array([10.0, 40.5]), np.array([7.0, 50.0])
    )
    assert np.allclose(found, [10.0, 40.5])


def test_lens_positions_are_believed_only_when_they_turn_with_the_view():
    azimuths = [0, 30, 60, 90]
    rotations = [pointing(a, -30.0) for a in azimuths]
    # The label states the lens from some point of the craft, not the axis.
    centres = [arm(a) + [0.7, -0.2, HEIGHT_M] for a in azimuths]

    found = registration.lens_offsets(centres, rotations)

    assert np.allclose(found, [arm(a) for a in azimuths], atol=1e-6)
    mirrored = [[c[1], c[0], c[2]] for c in centres]
    assert registration.lens_offsets(mirrored, rotations) is None
    assert registration.lens_offsets(centres[:2], rotations[:2]) is None


def test_overlaps_recover_pointing_the_label_states_loosely():
    azimuths = [0, 30, 60, 90]
    truth, rasters = sweep(azimuths)
    loose = [
        registration.turn(np.deg2rad(error)) @ r
        for error, r in zip(
            ([0.8, 0.0, 0.3], [-0.6, 0.4, 0.0], [0.0, -0.7, -0.4], [0.5, 0.5, 0.2]),
            truth,
        )
    ]
    found = registration.register(
        [LENS] * 4, rasters, loose, [arm(a) + [0, 0, HEIGHT_M] for a in azimuths]
    )
    assert found.report["status"] == "registered on overlaps"
    assert found.report["residual_deg"] < 0.15 < found.report["stated_residual_deg"]
    # Overlaps see how frames stand to each other, never the sweep as a whole;
    # and what they are solved for is the far field, so the horizon is judged
    # where two frames meet.
    for k in range(3):
        seam = pointing(azimuths[k] + 15, 0.0)[:, 2]
        stated = between_views(
            loose[k].T @ loose[k + 1], truth[k].T @ truth[k + 1], seam, loose[k]
        )
        solved = between_views(
            found.rotations[k].T @ found.rotations[k + 1],
            truth[k].T @ truth[k + 1],
            seam,
            found.rotations[k],
        )
        assert solved < 0.1 < stated
    assert not found.report["lens_on_axis"]


def test_a_sweep_without_texture_keeps_its_stated_pointing():
    rotations = [pointing(a, -30.0) for a in (0, 30, 60)]
    blank = [np.full((512, 512), 80.0)] * 3
    found = registration.register([LENS] * 3, blank, rotations)
    assert found.report == {"status": "stated pointing kept"}
    assert all(np.array_equal(a, b) for a, b in zip(found.rotations, rotations))
    assert not np.any(found.offsets)
