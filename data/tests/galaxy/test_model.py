import json
from types import SimpleNamespace

import numpy as np
import pytest

from space_map_data.export.extrasolar import container
from space_map_data.export.glow import model_payload
from space_map_data.galaxy import (
    build,
    calibrate,
    clouds,
    geometry,
    model,
    photometry,
    residual,
    sources,
    volumes,
)
from space_map_data.galaxy.geometry import R0, Z0
from space_map_data.galaxy.volumes import Box, block_mean


class TestGeometry:
    """The frame, the warp, the arms and the dust shape."""

    def test_the_sun_is_at_r0_and_azimuth_zero(self):
        R, beta, Z = geometry.galactocentric(np.zeros(1), np.zeros(1), np.zeros(1))
        assert R[0] == pytest.approx(R0)
        assert beta[0] == pytest.approx(0.0)
        assert Z[0] == pytest.approx(Z0)

    def test_azimuth_grows_toward_rotation(self):
        _, beta, _ = geometry.galactocentric(
            np.array([R0]), np.array([1000.0]), np.zeros(1)
        )
        assert beta[0] == pytest.approx(np.pi / 2)

    def test_warp_starts_at_its_radius_and_rises_north_toward_l_90(self):
        inside = geometry.warp_height(np.array([9000.0]), np.array([1.5]))
        north = geometry.warp_height(np.array([15000.0]), np.radians([107.4]))
        south = geometry.warp_height(np.array([15000.0]), np.radians([-72.6]))
        assert inside[0] == 0.0
        assert north[0] > 0 > south[0]

    def test_arm_field_is_one_on_a_ridge_and_never_more(self):
        arm = next(a for a in geometry.ARMS if a.name == "Perseus" and not a.drimmel)
        ridge = np.exp(arm.lnr(np.array([60.0])))
        field = geometry.arm_field(ridge, np.radians([60.0]))
        assert field[0] == pytest.approx(1.0, abs=1e-3)
        R = np.linspace(1000, 20000, 400)
        beta = np.linspace(-np.pi, np.pi, 400)
        assert geometry.arm_field(R, beta).max() <= 1.0 + 1e-9

    def test_drimmel_holds_the_third_and_fourth_quadrants(self):
        zone = geometry.d25_zone(np.radians([-45.0, 60.0, 180.0]))
        assert zone[0] == pytest.approx(1.0)
        assert zone[1] == pytest.approx(0.0)
        assert zone[2] == pytest.approx(0.0)

    def test_far_side_contrast_keeps_the_mean(self):
        R = np.full(2000, 6000.0)
        beta = np.linspace(-np.pi, np.pi, 2000, endpoint=False)
        X = -R * np.cos(beta)
        far = X > 2000
        x = X + R0
        flat, mean = geometry.contrasted_arms(x, R, beta, far_side=0.0)
        drawn, _ = geometry.contrasted_arms(x, R, beta, far_side=1.0)
        assert np.allclose(flat[far], mean[far])
        assert drawn[far].std() > flat[far].std()

    def test_dust_shape_falls_with_height_and_has_a_hole(self):
        z = np.array([-Z0, 500.0 - Z0])
        at = geometry.dust_shape(np.array([0.0, 0.0]), np.zeros(2), z)
        assert at[1] < at[0]
        hole = geometry.dust_shape(
            np.array([R0, R0 - 4000.0]), np.zeros(2), -np.full(2, Z0)
        )
        assert hole[0] < hole[1]


class TestPhotometry:
    def test_colour_relations_invert(self):
        bp_rp = np.array([0.5, 0.8, 1.2, 1.6])
        assert np.allclose(
            photometry.bp_rp_of_b_v(photometry.b_minus_v(bp_rp)), bp_rp, atol=2e-3
        )
        assert np.allclose(
            photometry.bp_rp_of_r_h(photometry.r_minus_h(bp_rp)), bp_rp, atol=2e-3
        )

    def test_display_colour_inverts(self):
        bp_rp = np.array([0.0, 0.8, 1.5])
        back = photometry.bp_rp_of_display(photometry.display(bp_rp))
        assert np.allclose(back, bp_rp, atol=0.02)


def _grid_integral(shape, half, step):
    axis = np.arange(-half, half, step) + step / 2
    x, y, z = np.meshgrid(axis + R0, axis, axis - Z0, indexing="ij")
    return shape(x.ravel(), y.ravel(), z.ravel()).sum() * step**3


class TestShapes:
    """Each shape holds unit light, so its flux is its total."""

    def test_bulge_integrates_to_one(self):
        assert _grid_integral(model.bulge_shape, 6000.0, 60.0) == pytest.approx(
            1.0, rel=0.01
        )

    def test_nuclear_disc_integrates_to_one(self):
        step, axis = 10.0, np.arange(-1500.0, 1500.0, 10.0) + 5.0
        x, y = np.meshgrid(axis + R0, axis, indexing="ij")
        z = np.arange(-400.0, 400.0, 1.0) + 0.5 - Z0
        face = sum(
            model.nsd_shape(x.ravel(), y.ravel(), np.full(x.size, h)).sum() for h in z
        )
        assert face * step * step == pytest.approx(1.0, rel=0.01)

    def test_bar_planform_is_normalised(self):
        step, axis = 20.0, np.arange(-7000.0, 7000.0, 20.0) + 10.0
        x, y = np.meshgrid(axis + R0, axis, indexing="ij")
        total = model.bar_planform(x.ravel(), y.ravel()).sum() * step * step
        assert total == pytest.approx(model.bar_planform_integral(), rel=0.01)

    @pytest.fixture
    def lmc(self, monkeypatch):
        # The integral holds wherever the cloud sits, so the LVDB file is not needed.
        row = sources.CloudRow(80.89, -69.76, 49_590.0, -18.1, 2700.0, "test")
        monkeypatch.setattr(sources, "lvdb_cloud", lambda _key: row)
        clouds.lmc_frame.cache_clear()
        yield
        clouds.lmc_frame.cache_clear()

    def test_lmc_integrates_to_one(self, lmc):
        centre = clouds.lmc_frame()[0]
        step = 200.0
        axis = np.arange(-15000.0, 15000.0, step) + step / 2
        x, y, z = np.meshgrid(*(axis + c for c in centre), indexing="ij")
        total = clouds.lmc_shape(x.ravel(), y.ravel(), z.ravel()).sum() * step**3
        assert total == pytest.approx(1.0, rel=0.05)


class TestCalibration:
    def test_split_keeps_the_light_of_lian_rings(self):
        edges = np.arange(18) * 1000.0
        areas = np.pi * np.diff(edges**2)
        lian = 100.0 * np.exp(-np.arange(17) / 3.0) + 50.0 * np.exp(
            -np.arange(17) * 2.0
        )
        bulge = np.exp(-np.arange(17) * 1.5)
        bulge /= (bulge * areas).sum()
        bars = np.zeros(17)
        bars[2:5] = 1.0
        bars /= (bars * areas).sum()
        lb, lbar, _, disc = calibrate.split_centre(lian, areas, bulge, bars)
        total = disc + lb * bulge + lbar * bars
        outer = np.arange(17) >= calibrate.BULGE_RINGS
        assert np.allclose(total[outer], lian[outer])
        inner = ~outer
        assert (total * areas)[inner].sum() == pytest.approx(
            (lian * areas)[inner].sum()
        )
        assert (disc >= 0).all()


class TestVolumes:
    def test_texture_coordinates_of_voxel_centres(self):
        box = Box((1000.0, 1000.0, 3000.0), (4, 4, 8), 150.0)
        edges = box.edges(2)
        middle = 0.5 * (edges[1:] + edges[:-1])
        w = box.texture_of_height(middle)
        assert np.all((w > np.arange(8) / 8) & (w < (np.arange(8) + 1) / 8))
        assert box.texture_of_height(np.array([3000.0]))[0] == pytest.approx(1.0)

    def test_block_mean_keeps_the_light(self):
        box = Box((1000.0, 1000.0, 3000.0), (4, 4, 8), 150.0)
        rng = np.random.default_rng(1)
        volume = rng.random((4, 4, 8, 3)).astype(np.float32)
        low = block_mean(volume, box)
        high_light = (volume * box.heights[None, None, :, None]).sum()
        low_light = (low * box.halved().heights[None, None, :, None]).sum() * 4
        assert low_light == pytest.approx(high_light, rel=1e-5)


class TestColourTable:
    def test_weights_sum_to_one_and_rows_too(self):
        rng = np.random.default_rng(2)
        points = rng.uniform(-60000, 60000, (5000, 3)) + np.array([R0, 0, 0])
        index, weight = residual.table_weights(points)
        assert np.allclose(weight.sum(axis=1), 1.0)
        assert index.max() < residual.TABLE_SIZE
        rgb = rng.random((5000, 3))
        table = residual.colour_table(points, rgb, rgb)
        assert np.allclose(table.sum(axis=1), 1.0)


class TestModelFile:
    def test_order_is_x_fastest(self):
        bits = np.zeros((4, 2, 2), np.uint16)
        bits[1, 0, 0] = 1
        bits[0, 1, 0] = 2
        bits[0, 0, 1] = 3
        decoded = container.decode(model_payload(bits, 2, "low"))
        texels = decoded.numpy("texels")
        assert texels[1] == 1 and texels[4] == 2 and texels[8] == 3


class TestRounding:
    def test_rounding_keeps_values_within_its_step(self):
        from space_map_data.galaxy.build import rounded_bits
        from space_map_data.glow import encode

        values = np.geomspace(1e-4, 3e4, 1000)
        bits = rounded_bits(encode.half_bits(values), 7)
        back = encode.bits_to_values(bits)
        assert np.all(np.abs(back / values - 1) <= 2.0**-8 + 2.0**-11)
        assert np.all(np.isfinite(back))


def _flat_light(points: np.ndarray) -> np.ndarray:
    """Model RGB of 1 and each tier's catalogue RGB of 0.25 at every point."""
    out = np.full((len(points), 3 + 3 * len(build.CAT_TIERS)), 0.25)
    out[:, :3] = 1.0
    return out


class TestBuildRecords:
    """Each step of the model build refuses what another run wrote."""

    @pytest.fixture
    def run(self, tmp_path, monkeypatch):
        glow, out = tmp_path / "glow", tmp_path / "model"
        glow.mkdir()
        out.mkdir()
        inner = Box((1000.0, 1000.0, 300.0), (4, 4, 4), 50.0)
        outer = Box((4000.0, 4000.0, 4000.0), (4, 4, 4))
        monkeypatch.setattr(
            volumes,
            "TIERS",
            {
                "high": {"inner": inner, "outer": outer},
                "low": {"inner": inner.halved(), "outer": outer.halved()},
            },
        )
        monkeypatch.setattr(build, "Model", SimpleNamespace(load=lambda *_: None))
        monkeypatch.setattr(
            residual, "CatalogueGrid", SimpleNamespace(load=lambda *_: None)
        )
        monkeypatch.setattr(residual, "sampler", lambda *_: _flat_light)
        (out / calibrate.CALIBRATION).write_text(json.dumps({"fit": 1}))
        self.grid(glow, "first")
        return out, glow

    @staticmethod
    def grid(glow, token: str) -> None:
        """A glow build's encoding, as `glow_inputs` reads it."""
        (glow / "encoding.json").write_text(
            json.dumps({"tree": token, "nest": "nest", "digests": {}})
        )

    @staticmethod
    def steps(out, glow, *names: str) -> None:
        for name in names:
            if name == "bake":
                build.build_bake(out, glow, 1.0, 1)
            else:
                getattr(build, f"build_{name}")(out, glow, 1.0)

    def test_a_whole_run_reads_back_with_its_shapes_and_boxes(self, run):
        out, glow = run
        self.steps(out, glow, "bake", "residual", "encoded")
        raw = build.read_encoding(out, glow)
        assert raw["shapes"]["bits.inner.low.npy"] == [2, 2, 2]
        assert raw["boxes"]["inner"] == {
            "half_extent_pc": [1000.0, 1000.0, 300.0],
            "z_scale_pc": 50.0,
        }

    def test_a_new_grid_and_bake_refuse_the_old_residual(self, run):
        out, glow = run
        self.steps(out, glow, "bake", "residual", "encoded")
        self.grid(glow, "second")
        self.steps(out, glow, "bake")
        with pytest.raises(build.StaleModel, match="another bake"):
            self.steps(out, glow, "encoded")

    def test_a_bake_on_another_calibration_is_not_encoded(self, run):
        out, glow = run
        self.steps(out, glow, "bake", "residual")
        (out / calibrate.CALIBRATION).write_text(json.dumps({"fit": 2}))
        with pytest.raises(build.StaleModel, match="calibration"):
            self.steps(out, glow, "encoded")

    def test_the_read_refuses_a_calibration_changed_since(self, run):
        out, glow = run
        self.steps(out, glow, "bake", "residual", "encoded")
        (out / calibrate.CALIBRATION).write_text(json.dumps({"fit": 2}))
        with pytest.raises(build.StaleModel, match="calibration"):
            build.read_encoding(out, glow)

    def test_the_residual_refuses_a_bake_not_of_its_record(self, run):
        out, glow = run
        self.steps(out, glow, "bake")
        np.save(out / build.bake_name("inner"), np.zeros((4, 4, 4, 9), np.float32))
        with pytest.raises(build.StaleModel, match="bake"):
            self.steps(out, glow, "residual")
