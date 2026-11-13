"""A model bundle ships GLBs only, each carrying the bundle's payload."""

import json
import os
import struct

import numpy as np

from space_map_data.ingest.providers.models import bundle, config, metadata
from space_map_data.ingest.providers.models.bodies import glb_writer
from space_map_data.ingest.providers.models.processor import ModelProcessor


def _glb(path, extras=None):
    verts = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 2]], dtype=np.float64)
    faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.int64)
    glb_writer.write_glb(verts, faces, path, extras)
    return path


def _bin_chunk(path):
    data = path.read_bytes()
    json_len = struct.unpack_from("<I", data, 12)[0]
    return data[20 + json_len :]


class TestEmbedPayload:
    """The payload lands in `asset.extras` and nothing else in the file moves."""

    def test_round_trip(self, tmp_path):
        src = _glb(tmp_path / "src.glb")
        out = tmp_path / "out"
        bundle.write_bundle(out, {"high": src}, {"slug": "eros", "tiers": ["high"]})
        dst = out / "high.glb"
        assert bundle.read_payload(dst) == {"slug": "eros", "tiers": ["high"]}
        assert _bin_chunk(dst) == _bin_chunk(src)
        assert metadata.gltf_stats(dst) == metadata.gltf_stats(src)

    def test_layout_stays_valid(self, tmp_path):
        data = bundle.embed_payload(_glb(tmp_path / "src.glb"), {"name": "Ďurech"})
        _magic, _version, length = struct.unpack_from("<4sII", data, 0)
        json_len = struct.unpack_from("<I", data, 12)[0]
        assert length == len(data)
        assert json_len % 4 == 0

    def test_other_asset_extras_survive(self, tmp_path):
        src = _glb(tmp_path / "src.glb", {"author": "someone"})
        data = bundle.embed_payload(src, {"slug": "x"})
        json_len = struct.unpack_from("<I", data, 12)[0]
        extras = json.loads(data[20 : 20 + json_len])["asset"]["extras"]
        assert extras == {"author": "someone", "spacemap": {"slug": "x"}}

    def test_a_hardlinked_destination_leaves_the_cache_alone(self, tmp_path):
        cached = _glb(tmp_path / "cached.glb")
        before = cached.read_bytes()
        out = tmp_path / "out"
        out.mkdir()
        os.link(cached, out / "high.glb")
        bundle.write_bundle(out, {"high": cached}, {"slug": "x"})
        assert cached.read_bytes() == before
        assert bundle.read_payload(out / "high.glb") == {"slug": "x"}


class TestReadPayload:
    def test_a_glb_without_one(self, tmp_path):
        assert bundle.read_payload(_glb(tmp_path / "a.glb")) is None

    def test_not_a_glb(self, tmp_path):
        (tmp_path / "a.glb").write_bytes(b"nope")
        assert bundle.read_payload(tmp_path / "a.glb") is None

    def test_missing(self, tmp_path):
        assert bundle.read_payload(tmp_path / "a.glb") is None

    def _with_json(self, path, body: bytes):
        body += b" " * (-len(body) % 4)
        path.write_bytes(
            struct.pack("<4sII", b"glTF", 2, 20 + len(body))
            + struct.pack("<II", len(body), 0x4E4F534A)
            + body
        )
        return path

    def test_json_that_is_not_utf8(self, tmp_path):
        glb = self._with_json(tmp_path / "a.glb", b'{"asset": "\xff"}')
        assert bundle.read_payload(glb) is None
        assert metadata.read_gltf_json(glb) is None

    def test_json_root_that_is_not_an_object(self, tmp_path):
        glb = self._with_json(tmp_path / "a.glb", b"[1, 2]")
        assert bundle.read_payload(glb) is None
        assert metadata.gltf_stats(glb) == {}


class TestWriteBundle:
    """The bundle directory holds exactly the tiers it ships."""

    def test_drops_a_dropped_tier_and_anything_else(self, tmp_path):
        src = _glb(tmp_path / "src.glb")
        out = tmp_path / "eros"
        out.mkdir()
        (out / "low.glb").write_bytes(b"old")
        (out / "metadata.json").write_text("{}")
        bundle.write_bundle(out, {"high": src}, {"tiers": ["high"]})
        assert sorted(p.name for p in out.iterdir()) == ["high.glb"]

    def test_every_tier_carries_the_payload(self, tmp_path):
        src = _glb(tmp_path / "src.glb")
        out = tmp_path / "eros"
        payload = {"tiers": ["high", "low"], "exports": {"high": {}, "low": {}}}
        bundle.write_bundle(out, {"high": src, "low": src}, payload)
        assert bundle.read_payload(out / "high.glb") == payload
        assert bundle.read_payload(out / "low.glb") == payload

    def test_an_unchanged_bundle_keeps_its_bytes(self, tmp_path):
        src = _glb(tmp_path / "src.glb")
        out = tmp_path / "eros"
        bundle.write_bundle(out, {"high": src}, {"slug": "eros", "processed_at": "1"})
        before = (out / "high.glb").read_bytes()
        os.utime(out / "high.glb", ns=(1, 1))
        bundle.write_bundle(out, {"high": src}, {"slug": "eros", "processed_at": "2"})
        assert (out / "high.glb").read_bytes() == before
        assert (out / "high.glb").stat().st_mtime_ns == 1

    def test_a_changed_payload_rewrites(self, tmp_path):
        src = _glb(tmp_path / "src.glb")
        out = tmp_path / "eros"
        bundle.write_bundle(out, {"high": src}, {"slug": "eros", "processed_at": "1"})
        bundle.write_bundle(out, {"high": src}, {"slug": "433", "processed_at": "2"})
        assert bundle.read_payload(out / "high.glb") == {
            "slug": "433",
            "processed_at": "2",
        }

    def test_a_changed_mesh_rewrites(self, tmp_path):
        out = tmp_path / "eros"
        payload = {"slug": "eros", "processed_at": "1"}
        bundle.write_bundle(out, {"high": _glb(tmp_path / "a.glb")}, payload)
        verts = np.array([[0, 0, 0], [3, 0, 0], [0, 3, 0], [0, 0, 3]], dtype=np.float64)
        faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.int64)
        glb_writer.write_glb(verts, faces, tmp_path / "b.glb")
        bundle.write_bundle(out, {"high": tmp_path / "b.glb"}, payload)
        assert _bin_chunk(out / "high.glb") == _bin_chunk(tmp_path / "b.glb")

    def test_one_stamp_across_tiers_and_a_new_one_for_a_changed_tier(self, tmp_path):
        out = tmp_path / "eros"
        a, b = _glb(tmp_path / "a.glb"), _glb(tmp_path / "b.glb")
        bundle.write_bundle(out, {"high": a, "low": a}, {"processed_at": "1"})
        bundle.write_bundle(out, {"high": a, "low": b}, {"processed_at": "2"})
        # b's mesh is a's, so nothing changed and the stamp holds.
        assert bundle.read_payload(out / "low.glb") == {"processed_at": "1"}
        verts = np.array([[0, 0, 0], [3, 0, 0], [0, 3, 0], [0, 0, 3]], dtype=np.float64)
        faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=np.int64)
        glb_writer.write_glb(verts, faces, b)
        bundle.write_bundle(out, {"high": a, "low": b}, {"processed_at": "3"})
        assert bundle.read_payload(out / "high.glb") == {"processed_at": "3"}
        assert bundle.read_payload(out / "low.glb") == {"processed_at": "3"}

    def test_read_bundle_leaves_out_a_tier_with_no_file(self, tmp_path):
        src = _glb(tmp_path / "src.glb")
        out = tmp_path / "eros"
        payload = {"tiers": ["high", "low"], "exports": {"high": {}, "low": {}}}
        bundle.write_bundle(out, {"high": src}, payload)
        meta = bundle.read_bundle(out)
        assert meta is not None
        assert list(meta["exports"]) == ["high"]
        assert meta["tiers"] == ["high"]

    def test_read_bundle_adds_each_tiers_size(self, tmp_path):
        src = _glb(tmp_path / "src.glb")
        out = tmp_path / "eros"
        payload = {"exports": {"high": {}, "low": {}}}
        bundle.write_bundle(out, {"high": src, "low": src}, payload)
        meta = bundle.read_bundle(out)
        assert meta is not None
        assert (
            meta["exports"]["high"]["size_bytes"] == (out / "high.glb").stat().st_size
        )
        assert meta["exports"]["low"]["size_bytes"] == (out / "low.glb").stat().st_size


class TestIsIntact:
    """A bundle is reused only as exactly its tier GLBs, each with a payload."""

    def _bundle(self, tmp_path):
        out = tmp_path / "mir"
        src = _glb(tmp_path / "src.glb")
        bundle.write_bundle(out, {"high": src, "low": src}, {"slug": "mir"})
        return out

    def test_intact(self, tmp_path):
        assert bundle.is_intact(self._bundle(tmp_path), ["high", "low"])

    def test_a_tier_it_should_not_ship(self, tmp_path):
        assert not bundle.is_intact(self._bundle(tmp_path), ["high"])

    def test_a_missing_tier(self, tmp_path):
        out = self._bundle(tmp_path)
        (out / "low.glb").unlink()
        assert not bundle.is_intact(out, ["high", "low"])

    def test_a_leftover_file(self, tmp_path):
        out = self._bundle(tmp_path)
        (out / "metadata.json").write_text("{}")
        assert not bundle.is_intact(out, ["high", "low"])

    def test_a_tier_without_payload(self, tmp_path):
        out = self._bundle(tmp_path)
        _glb(out / "low.glb")
        assert not bundle.is_intact(out, ["high", "low"])


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_args):
        return _Rows(self._rows)


class TestBundleIndex:
    """`tiers.json` lists what a client picks a tier by, for the bundles that
    ship more than an open `high`."""

    def _write(self, tmp_path, monkeypatch, bundles: dict[str, dict]):
        monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path)
        src = _glb(tmp_path / "src.glb")
        for slug, exports in bundles.items():
            payload = {"kind": "probe", "tiers": list(exports), "exports": exports}
            bundle.write_bundle(tmp_path / slug, dict.fromkeys(exports, src), payload)
        ModelProcessor.__new__(ModelProcessor)._write_bundle_index(
            _Session([("probe-1", "Mir", "spacecraft", "mir")])
        )
        return (
            json.loads((tmp_path / "index.json").read_text())["bundles"],
            json.loads((tmp_path / "tiers.json").read_text())["bundles"],
        )

    def test_tiers_name_each_shipped_tier(self, tmp_path, monkeypatch):
        index, tiers = self._write(
            tmp_path,
            monkeypatch,
            {
                "mir": {"high": {"distribution": "non-commercial"}, "low": {}},
                "eros": {"high": {}, "low": {}},
                "teapot": {"high": {"distribution": "non-commercial"}},
                "cassini": {"high": {}},
            },
        )

        def size(slug):
            return (tmp_path / slug / "high.glb").stat().st_size

        nc = "non-commercial"
        assert tiers == {
            "mir": {"high": {"distribution": nc, "size_bytes": size("mir")}, "low": {}},
            "eros": {"high": {"size_bytes": size("eros")}, "low": {}},
            "teapot": {"high": {"distribution": nc, "size_bytes": size("teapot")}},
        }
        assert set(index) == {"mir", "eros", "teapot", "cassini"}
        assert index["mir"]["objects"] == [
            {"id": "probe-1", "name": "Mir", "type": "spacecraft"}
        ]

    def test_a_bundle_without_payload_is_left_out(self, tmp_path, monkeypatch, caplog):
        (tmp_path / "bare").mkdir()
        _glb(tmp_path / "bare" / "high.glb")
        index, _ = self._write(tmp_path, monkeypatch, {"cassini": {"high": {}}})
        assert set(index) == {"cassini"}
        assert "bare: high.glb carries no payload" in caplog.text
