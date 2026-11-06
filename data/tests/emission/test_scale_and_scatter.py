"""Tests for the H-alpha scale, the sky maps, the codes and the scattered light."""

import contextlib
import itertools
import json
import logging

import numpy as np
import pytest

from space_map_data.dust.sources import file_digest
from space_map_data.emission import build, encode, gates, local, scatter, sky, sources
from space_map_data.galaxy import volumes


class TestSky:
    def test_degrade_takes_the_mean_of_the_children(self):
        values = np.arange(12 * 4**2, dtype=float)
        coarse = sky.degrade(values, 2)
        assert coarse[0] == values[:4].mean()
        assert coarse.mean() == pytest.approx(values.mean())

    def test_a_constant_map_stays_constant_when_smoothed(self):
        assert np.allclose(sky.smooth(np.full(12 * 8**2, 3.0), 10.0), 3.0)

    def test_a_pixel_holds_its_own_direction(self):
        d = sky.directions(16)
        assert np.array_equal(sky.pixel_of(d, 16), np.arange(len(d)))


class TestScale:
    def test_the_factor_keeps_to_its_limit_and_is_one_where_the_cube_is_dark(self):
        n = 12 * local.FACTOR_NSIDE**2
        projection = np.ones(n)
        projection[:10] = 0
        wanted = np.full(n, 100.0)
        factor = local.factor_map(np.repeat(projection, 4), np.repeat(wanted, 4), 0.0)
        assert factor[:10].tolist() == [1.0] * 10
        assert factor[10:].max() == local.FACTOR_LIMIT

    def test_a_factor_of_one_leaves_the_cube(self):
        cube = np.random.default_rng(0).random((8, 8, 8)).astype(np.float32)
        factor = np.ones(12 * local.FACTOR_NSIDE**2)
        assert np.allclose(local.apply_factor(cube, factor), cube)

    def test_each_voxel_takes_the_factor_toward_it(self):
        cube = np.ones((32, 32, 32), np.float32)
        factor = np.where(sky.directions(local.FACTOR_NSIDE)[:, 2] > 0, 2.0, 0.5)
        scaled = local.apply_factor(cube, factor)
        # Voxels well above and below the plane, away from the edge of the factor.
        assert np.allclose(scaled[:, :, 28:], 2.0)
        assert np.allclose(scaled[:, :, :4], 0.5)

    def test_the_target_takes_out_the_scattered_share_and_the_far_regions(self):
        assert local.target(np.array([100.0]), np.array([10.0]))[0] == pytest.approx(
            100 * (1 - local.SCATTERED_SHARE) - 10
        )


class TestCodes:
    def test_the_gain_sets_the_mean_read_to_the_cube(self):
        rng = np.random.default_rng(1)
        cube = np.where(
            rng.random((16, 16, 16)) > 0.6, rng.lognormal(-12, 2, (16, 16, 16)), 0
        )
        codes, encoding = encode.halpha_codes(cube, float(cube.max()))
        at = rng.random((200_000, 3))
        from space_map_data.dust.march import linear_fetch

        read = encode.linear_read(codes, encoding, at).mean()
        assert read == pytest.approx(linear_fetch(cube, at).mean(), rel=0.01)


class _Uniform:
    """Light j inside a sphere of radius R about the origin, no dust."""

    def __init__(self, j: float, radius: float):
        self.j, self.radius = j, radius

    def light(self, points):
        inside = np.linalg.norm(points, axis=1) <= self.radius
        return np.where(inside[:, None], self.j, 0.0) * np.ones((1, 3))

    def dust(self, points):
        return np.zeros(len(points))


class TestScatter:
    def test_the_directions_weigh_the_sphere(self):
        d, w = scatter.direction_set(32, 24)
        assert w.sum() == pytest.approx(1.0)
        assert (w * d[:, 2]).sum() == pytest.approx(0.0, abs=1e-12)
        # Nodes sit at the middle of each band in t, not in sin b: 2% off at the poles.
        assert (w * d[:, 2] ** 2).sum() == pytest.approx(1 / 3, rel=0.03)

    def test_j_at_the_centre_of_a_uniform_ball_is_j_times_its_radius(self):
        d, w = scatter.direction_set(8, 8)
        edges = scatter.step_edges(400, 2000.0)
        got = scatter.mean_intensity(
            _Uniform(2.0, 1000.0), np.zeros((1, 3)), d, w, edges
        )
        assert got[0] == pytest.approx(2000.0, rel=0.01)

    def test_henyey_greenstein_sums_to_one(self):
        d, w = scatter.direction_set(64, 64)
        g = np.array((0.0, 0.5, 0.57))
        total = (w[:, None] * 4 * np.pi * scatter.henyey_greenstein(d[:, 2], g)).sum(0)
        assert total == pytest.approx(1.0, rel=0.02)

    def test_three_channels_read_back(self):
        box = volumes.Box(scatter.J_BOX.half, (8, 8, 4), scatter.J_BOX.z_scale)
        j = np.random.default_rng(2).random((8, 8, 4, 3)).astype(np.float32)
        form = scatter.store_j(j, 3)
        values = encode.half_bits(j * form.scale).view(np.float16).astype(np.float32)
        stored = scatter.StoredJ(form, values, box)
        centres = scatter.voxel_centres(box, box.size)
        got = stored.read(centres.reshape(-1, 3)).reshape(j.shape)
        assert np.allclose(got, j, rtol=2e-3)


def test_leinert_covers_the_sky():
    edges = sorted(gates.LEINERT)
    assert edges[0][0] == 0 and edges[-1][1] == 90
    assert all(a[1] == b[0] for a, b in itertools.pairwise(edges))


def test_the_power_law_index_of_a_known_sample():
    rng = np.random.default_rng(4)
    rate = 1e47 * (1 - rng.random(20_000)) ** (-1 / 0.75)
    alpha, error, n = gates.power_law_index(rate, 1e47)
    assert alpha == pytest.approx(-1.75, abs=3 * error)
    assert n == 20_000


@pytest.fixture
def source_files(tmp_path, monkeypatch):
    """The WISE catalogue and Finkbeiner's map as small files."""
    for name, attribute in (
        ("wise.csv", "WISE_FILE"),
        ("fink.fits", "FINKBEINER_FILE"),
    ):
        (tmp_path / name).write_text(name)
        monkeypatch.setattr(sources, attribute, tmp_path / name)
    return {
        "wise": file_digest(sources.WISE_FILE),
        "finkbeiner": file_digest(sources.FINKBEINER_FILE),
    }


class TestRefusals:
    """The export refuses an emission build made on another nest, glow or model, or
    from a changed source."""

    @pytest.fixture
    def built(self, tmp_path, monkeypatch, source_files):
        (tmp_path / "halpha.high.npy").write_bytes(b"codes")
        raw = {
            "nest": "nest-a",
            "light": {"glow": "g", "model": "m"},
            "sources": source_files,
            "digests": {"halpha.high.npy": file_digest(tmp_path / "halpha.high.npy")},
        }
        (tmp_path / build.ENCODING_FILE).write_text(json.dumps(raw))
        monkeypatch.setattr(build, "nest_token", lambda root=None: "nest-a")
        monkeypatch.setattr(
            build, "light_inputs", lambda *args: {"glow": "g", "model": "m"}
        )
        return tmp_path

    def test_a_current_build_is_read(self, built):
        assert build.read_encoding(built)["nest"] == "nest-a"

    def test_another_nest_is_refused(self, built, monkeypatch):
        monkeypatch.setattr(build, "nest_token", lambda root=None: "nest-b")
        with pytest.raises(build.StaleEmission, match="another nest"):
            build.read_encoding(built)

    def test_another_glow_or_model_is_refused(self, built, monkeypatch):
        monkeypatch.setattr(build, "light_inputs", lambda *args: {"glow": "x"})
        with pytest.raises(build.StaleEmission, match="glow or model"):
            build.read_encoding(built)

    def test_a_changed_file_is_refused(self, built):
        (built / "halpha.high.npy").write_bytes(b"other")
        with pytest.raises(build.StaleEmission, match="not the file"):
            build.read_encoding(built)

    @pytest.mark.parametrize("name", ["wise", "finkbeiner"])
    def test_a_changed_source_is_refused(self, built, name):
        path = sources.WISE_FILE if name == "wise" else sources.FINKBEINER_FILE
        path.write_text("a newer release")
        with pytest.raises(build.StaleEmission, match=name):
            build.read_encoding(built)

    def test_the_glow_export_leaves_out_an_emission_without_a_model(
        self, built, caplog
    ):
        from space_map_data.export import glow as glow_export

        with caplog.at_level(logging.WARNING):
            assert glow_export.read_emission(built, built, built, built, None) is None
        assert "no model" in caplog.text


class TestStepRefusals:
    """A step refuses the step files and sources another run read."""

    @pytest.fixture
    def stepped(self, tmp_path, monkeypatch, source_files):
        monkeypatch.setattr(build, "nest_token", lambda root=None: "nest-a")
        np.savez(tmp_path / build.REGIONS_DATA, rate=np.ones(3))
        regions = file_digest(tmp_path / build.REGIONS_DATA)
        (tmp_path / build.REGIONS_FILE).write_text(
            json.dumps(
                {"nest": "nest-a", "wise": source_files["wise"], "data": regions}
            )
        )
        for tier in build.TIERS:
            np.save(tmp_path / build.scaled_name(tier), np.zeros((2, 2, 2)))
        record = {
            "sun": {"nest": "nest-a"},
            "regions": regions,
            "finkbeiner": source_files["finkbeiner"],
            "digests": {
                t: file_digest(tmp_path / build.scaled_name(t)) for t in build.TIERS
            },
        }
        (tmp_path / build.SCALE_FILE).write_text(json.dumps(record))
        return tmp_path

    def test_current_steps_are_read(self, stepped):
        assert build.read_regions(stepped)["rate"].tolist() == [1.0, 1.0, 1.0]
        assert build._read_scale(stepped)["regions"]

    def test_regions_of_a_changed_catalogue_are_refused(self, stepped):
        sources.WISE_FILE.write_text("V3.1")
        with pytest.raises(build.StaleEmission, match="wise"):
            build.read_regions(stepped)

    def test_a_scale_of_other_regions_is_refused(self, stepped):
        record = json.loads((stepped / build.REGIONS_FILE).read_text())
        np.savez(stepped / build.REGIONS_DATA, rate=np.full(3, 2.0))
        record["data"] = file_digest(stepped / build.REGIONS_DATA)
        (stepped / build.REGIONS_FILE).write_text(json.dumps(record))
        with pytest.raises(build.StaleEmission, match="regions"):
            build._read_scale(stepped)

    def test_a_scale_of_a_changed_map_is_refused(self, stepped):
        sources.FINKBEINER_FILE.write_text("another map")
        with pytest.raises(build.StaleEmission, match="finkbeiner"):
            build._read_scale(stepped)

    def test_the_dimming_gate_refuses_a_sky_of_another_encoding(self, stepped):
        (stepped / build.ENCODING_FILE).write_text("{}")
        (stepped / gates.SHIPPED_RECORD).write_text(json.dumps({"encoding": "old"}))
        with pytest.raises(build.StaleEmission, match="gate-halpha"):
            gates.dimming_gate(stepped, 1)


class TestServed:
    def test_the_nest_and_far_dust_are_read_with_the_export_held(self, monkeypatch):
        events: list[str] = []

        @contextlib.contextmanager
        def held(_root):
            events.append("held")
            try:
                yield
            finally:
                events.append("let go")

        monkeypatch.setattr(build, "served", held)
        monkeypatch.setattr(
            build.sky_map, "load_nest", lambda *_args: events.append("nest")
        )
        monkeypatch.setattr(
            build.StoredFar, "load", lambda *_args: events.append("far")
        )
        build._served()
        assert events == ["held", "nest", "far", "let go"]
