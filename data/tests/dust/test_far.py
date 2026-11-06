"""Tests for the far volume: the rest layer past level 0 of the dust nest."""

import json

import numpy as np
import pytest

from space_map_data.dust import far
from space_map_data.dust.encode import Encoding, compensate
from space_map_data.dust.nest import LEVELS
from space_map_data.dust.rest import scale_at
from space_map_data.export.dust import volume_payload
from space_map_data.export.extrasolar import container
from space_map_data.galaxy import geometry, volumes

SIGHTLINES = 12 * 4**7
# A base of 1e-3 everywhere, a near factor of 1, a window that fades out to 2 kpc.
FIELD = np.stack(
    (
        np.full(SIGHTLINES, 1e-3),
        np.ones(SIGHTLINES),
        np.zeros(SIGHTLINES),
        np.full(SIGHTLINES, 2000.0),
    )
).astype(np.float32)


class TestBox:
    def test_the_box_is_the_model_inner_box(self):
        high = far.FAR_TIERS["high"]
        assert high.half == volumes.INNER_HIGH.half
        assert high.z_scale == volumes.INNER_HIGH.z_scale
        assert high.size[2] == volumes.INNER_HIGH.size[2]

    def test_it_holds_level_0_past_the_galactic_centre(self):
        high = far.FAR_TIERS["high"]
        x_far = volumes.CENTRE[0] + high.half[0]
        assert x_far > LEVELS[0].half[0] + 10_000.0
        assert high.half[2] - abs(volumes.CENTRE[2]) > LEVELS[0].half[2]


class TestInterior:
    def test_texels_near_a_face_of_level_0_keep_the_field(self):
        low = far.FAR_TIERS["low"]
        inside = far.interior(low)
        x = 0.5 * (low.edges(0)[1:] + low.edges(0)[:-1]) + volumes.CENTRE[0]
        voxel = low.edges(0)[1] - low.edges(0)[0]
        held = np.asarray(inside.any(axis=(1, 2)))
        # Within one texel of the face at x = 20 kpc: never zeroed.
        assert not held[np.abs(x - LEVELS[0].half[0]) < 1.5 * voxel].any()
        # Deep in level 0: zeroed somewhere along y and z.
        assert held[np.abs(x - 5000.0) < voxel].all()
        # Outside level 0: never zeroed.
        assert not held[x > LEVELS[0].half[0]].any()

    def test_both_tiers_zero_the_same_region(self):
        rng = np.random.default_rng(3)
        density = rng.random(far.FAR_TIERS["high"].size).astype(np.float32) + 1.0
        zeroed = far.zero_interior(density, far.FAR_TIERS)
        low = far.low_tier(zeroed)
        assert ((low == 0) == far.interior(far.FAR_TIERS["low"])).all()


class TestField:
    def test_it_is_the_rest_scale_times_the_shape(self):
        points = np.array([[21000.0, 300.0, -20.0], [25000.0, -8000.0, 400.0]])
        x, y, z = points.T
        expected = 1e-3 * geometry.dust_shape(x, y, z)
        assert far.far_density(FIELD, points)[:, 0] == pytest.approx(expected, 1e-5)

    def test_the_near_factor_holds_only_in_its_window(self):
        field = FIELD.copy()
        field[1] = 3.0
        field[2] = 1000.0
        near = scale_at(field, *np.array([[500.0], [100.0], [5.0]]))
        farther = scale_at(field, *np.array([[21000.0], [4200.0], [210.0]]))
        assert near == pytest.approx(3e-3, rel=1e-5)
        assert farther == pytest.approx(1e-3, rel=1e-5)


class TestTextureCoordinates:
    def test_centre_faces_and_asinh_height(self):
        centre, half, z_scale = (8277.0, 0.0, -21.0), (24e3, 24e3, 3e3), 150.0
        points = np.array(
            [
                centre,
                (8277.0 + 24e3, -24e3, -21.0 + 3e3),
                (8277.0, 0.0, -21.0 + 150.0),
            ]
        )
        at = far.uvw(points, centre, half, z_scale)
        assert at[0] == pytest.approx([0.5, 0.5, 0.5])
        assert at[1] == pytest.approx([1.0, 0.0, 1.0])
        span = np.arcsinh(3e3 / 150.0)
        assert at[2, 2] == pytest.approx(0.5 + 0.5 * np.arcsinh(1.0) / span)


class TestStoredFar:
    def _export(self, root, codes, encoding):
        directory = root / "v1" / "dust"
        directory.mkdir(parents=True)
        payload = volume_payload(codes, far.FAR_INDEX, "high")
        written = container.write(directory, "high/far.bin.gz", payload)
        high = far.FAR_TIERS["high"]
        metadata = {
            "levels": [{"level": 0, "half_extent_pc": list(LEVELS[0].half)}],
            "far": {
                "centre_pc": list(volumes.CENTRE),
                "half_extent_pc": list(high.half),
                "z_scale_pc": high.z_scale,
                "floor": encoding.floor,
                "top": encoding.top,
                "high": {"path": written.path, "size": list(codes.shape)},
            },
        }
        (directory / "metadata.json").write_text(json.dumps(metadata))

    def test_a_read_is_zero_in_level_0_and_the_decode_outside(self, tmp_path):
        density = np.full(far.FAR_TIERS["high"].size, 2e-4, np.float32)
        encoding = Encoding(far.FLOOR, 2e-4)
        codes = compensate(density, encoding)
        self._export(tmp_path, codes, encoding)
        stored = far.StoredFar.load(tmp_path, "high")
        points = np.array([[19_000.0, 0.0, 0.0], [26_000.0, 0.0, 0.0]])
        read = stored.read(points)
        assert read[0] == 0.0
        assert read[1] == pytest.approx(2e-4, rel=0.01)

    def test_the_file_order_is_that_of_the_build(self, tmp_path):
        size = far.FAR_TIERS["high"].size
        codes = np.zeros(size, np.uint8)
        codes[size[0] - 1, size[1] // 2, size[2] // 2] = 255
        self._export(tmp_path, codes, Encoding(far.FLOOR, 1e-3))
        stored = far.StoredFar.load(tmp_path, "high")
        assert stored.codes.shape == size
        assert stored.codes[size[0] - 1, size[1] // 2, size[2] // 2] == 255
