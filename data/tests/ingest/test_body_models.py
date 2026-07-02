"""Natural-body shape-model ingest: mesh parsing, GLB writing, DAMIT orientation."""

import math

import numpy as np

from space_map_data.ingest.providers.models import metadata
from space_map_data.ingest.providers.models.bodies import glb_writer, mesh_formats
from space_map_data.ingest.providers.models.bodies.damit import (
    DamitModel,
    DamitProcessor,
    _parse_shape,
)
from space_map_data.ingest.providers.models.bodies.orientation import damit_to_iau

_OBLIQUITY_DEG = 23.4392911
_J2000_JD = 2451545.0


def _rotate(v: np.ndarray, axis: np.ndarray, deg: float) -> np.ndarray:
    """Rodrigues rotation of ``v`` about unit ``axis`` — the frontend's spin."""
    r = math.radians(deg)
    return (
        v * math.cos(r)
        + np.cross(axis, v) * math.sin(r)
        + axis * float(np.dot(axis, v)) * (1 - math.cos(r))
    )


def _frontend_prime_meridian(alpha: float, delta: float, w: float) -> np.ndarray:
    """Reconstruct the body +X axis exactly as bodyQuaternion would (equatorial)."""
    ra, dec = math.radians(alpha), math.radians(delta)
    pole = np.array(
        [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
    )
    node = np.array([-math.sin(ra), math.cos(ra), 0.0])
    return _rotate(node, pole, w)


class TestMeshFormats:
    def test_vf_table(self, tmp_path):
        src = tmp_path / "s.tab"
        src.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        out = tmp_path / "o.obj"
        nv, nf = mesh_formats.table_to_obj(src, out)
        assert (nv, nf) == (3, 1)
        assert "f 1 2 3" in out.read_text()

    def test_counts_table_zero_based(self, tmp_path):
        # Header "nv nf", then verts, then 0-based faces → normalised to 1-based.
        src = tmp_path / "s.tab"
        src.write_text("3 1\n0 0 0\n1 0 0\n0 1 0\n0 1 2\n")
        out = tmp_path / "o.obj"
        nv, nf = mesh_formats.table_to_obj(src, out)
        assert (nv, nf) == (3, 1)
        assert "f 1 2 3" in out.read_text()

    def test_wrl_indexed_face_set(self, tmp_path):
        src = tmp_path / "s.wrl"
        src.write_text("point [ 0 0 0, 1 0 0, 0 1 0 ] coordIndex [ 0, 1, 2, -1 ]")
        out = tmp_path / "o.obj"
        nv, nf = mesh_formats.table_to_obj(src, out)
        assert (nv, nf) == (3, 1)

    def test_icq_cube(self, tmp_path):
        # q=1 → 6 faces × 4 verts, 2 tris per quad → 12 tris.
        src = tmp_path / "s.txt"
        verts = " ".join("0 0 0" for _ in range(6 * 4))
        src.write_text(f"1\n{verts}\n")
        out = tmp_path / "o.obj"
        mesh_formats.icq_to_obj(src, out)
        text = out.read_text()
        assert text.count("\nf ") + text.startswith("f ") >= 12


class TestGlbWriter:
    def test_tetrahedron_roundtrip(self, tmp_path):
        verts = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 2]], dtype=np.float64)
        faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.int64)
        dst = tmp_path / "t.glb"
        glb_writer.write_glb(verts, faces, dst)
        bounds = metadata.gltf_bounds(dst)
        assert bounds is not None
        assert bounds["max_extent"] == 2.0
        assert bounds["min"] == [0.0, 0.0, 0.0]
        stats = metadata.gltf_stats(dst)
        assert stats["triangles"] == 4


class TestDamitOrientation:
    def test_pole_ecliptic_north(self):
        # Ecliptic north pole → equatorial (RA 270°, Dec 90−ε).
        iau = damit_to_iau(0.0, 90.0, 5.0, 0.0, _J2000_JD)
        assert math.isclose(iau["pole_ra_0"], 270.0, abs_tol=1e-6)
        assert math.isclose(iau["pole_dec_0"], 90.0 - _OBLIQUITY_DEG, abs_tol=1e-6)

    def test_w_rate(self):
        iau = damit_to_iau(120.0, 30.0, 6.0, 45.0, _J2000_JD + 100.0)
        assert math.isclose(iau["w1"], 360.0 * 24.0 / 6.0, rel_tol=1e-12)

    def test_frontend_reconstructs_prime_meridian(self):
        # The derived (α,δ,w0,w1), fed through the frontend's body-X formula at
        # JD0, must reproduce the DAMIT model's prime meridian (independently
        # built here from the Kaasalainen matrices).
        for lam, beta, period, phi0, jd0 in [
            (35.0, -60.0, 7.3, 210.0, _J2000_JD + 1234.0),
            (200.0, 20.0, 12.0, 15.0, _J2000_JD - 800.0),
            (0.0, 0.0, 4.0, 0.0, _J2000_JD),
        ]:
            iau = damit_to_iau(lam, beta, period, phi0, jd0)
            w_at_jd0 = iau["w0"] + iau["w1"] * (jd0 - _J2000_JD)
            recon = _frontend_prime_meridian(
                iau["pole_ra_0"], iau["pole_dec_0"], w_at_jd0
            )
            truth = _damit_prime_meridian_equatorial(lam, beta, phi0)
            assert float(np.dot(recon, truth)) > 1 - 1e-9

    def test_pole_perpendicular_to_prime_meridian(self):
        iau = damit_to_iau(35.0, -60.0, 7.3, 210.0, _J2000_JD + 1234.0)
        ra, dec = math.radians(iau["pole_ra_0"]), math.radians(iau["pole_dec_0"])
        pole = np.array(
            [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]
        )
        w = iau["w0"]
        prime = _frontend_prime_meridian(iau["pole_ra_0"], iau["pole_dec_0"], w)
        assert abs(float(np.dot(pole, prime))) < 1e-9


class TestDamitParsers:
    def test_parse_shape(self, tmp_path):
        src = tmp_path / "shape.txt"
        src.write_text("3 1\n0 0 0\n1 0 0\n0 1 0\n1 2 3\n")
        verts, faces = _parse_shape(src)
        assert verts.shape == (3, 3)
        assert faces.tolist() == [[0, 1, 2]]  # 1-based → 0-based

    def _model(self, tmp_path, monkeypatch, iauspin: str | None) -> DamitModel:
        from space_map_data.ingest.providers.models import config

        monkeypatch.setattr(config, "DAMIT_DIR", tmp_path)
        m = DamitModel(2, 1, 35.0, -60.0, 7.3, 2451800.5, 210.0, None)
        if iauspin is not None:
            m.dir.mkdir(parents=True)
            (m.dir / "IAUspin").write_text(iauspin)
        return m

    def test_iauspin_preferred_and_normalized_to_j2000(self, tmp_path, monkeypatch):
        # W₀ given at a non-J2000 epoch must be shifted back by rate·Δdays.
        m = self._model(tmp_path, monkeypatch, "68.0 73.0 1200.0\n2451546.0 100.0\n")
        row = DamitProcessor._iau_orientation(m)
        assert row["pole_ra_0"] == 68.0
        assert row["pole_dec_0"] == 73.0
        assert row["w1"] == 1200.0
        assert math.isclose(row["w0"], (100.0 - 1200.0) % 360.0)

    def test_iauspin_absent_falls_back_to_conversion(self, tmp_path, monkeypatch):
        m = self._model(tmp_path, monkeypatch, None)
        row = DamitProcessor._iau_orientation(m)
        assert row == damit_to_iau(35.0, -60.0, 7.3, 210.0, 2451800.5)


def _damit_prime_meridian_equatorial(
    lam: float, beta: float, phi0: float
) -> np.ndarray:
    """Ground-truth body +X in equatorial coords from the Kaasalainen matrices."""

    def rz(g):
        c, s = math.cos(math.radians(g)), math.sin(math.radians(g))
        return np.array([[c, s, 0], [-s, c, 0], [0, 0, 1.0]])

    def ry(g):
        c, s = math.cos(math.radians(g)), math.sin(math.radians(g))
        return np.array([[c, 0, -s], [0, 1.0, 0], [s, 0, c]])

    def rx(g):
        c, s = math.cos(math.radians(g)), math.sin(math.radians(g))
        return np.array([[1.0, 0, 0], [0, c, -s], [0, s, c]])

    a = rz(phi0) @ ry(90 - beta) @ rz(lam)
    prime_ecl = a.T @ np.array([1.0, 0, 0])
    prime_eq = rx(_OBLIQUITY_DEG) @ prime_ecl
    return prime_eq / np.linalg.norm(prime_eq)
