"""Which cached panorama products reach the export, and in what shape."""

import gzip
import json
import os
from pathlib import Path

import orjson
import pytest
from PIL import Image

from space_map_data.export import panoramas
from space_map_data.export.objects.writer import hash_bucket

MARS = "naif-499"


def _product(**overrides) -> dict:
    base = {
        "id": "perseverance-sol2",
        "body_id": MARS,
        "mission": "perseverance",
        "instrument": "Navcam",
        "sol": 2,
        "start_time": "2021-02-20T21:48:15.029Z",
        "stop_time": "2021-02-20T22:06:31.743Z",
        "position": {"latitude": 18.44, "longitude": 77.45, "elevation_m": -2569.9},
        "image": "panorama.webp",
        "preview": "preview.webp",
        "north_azimuth_offset_deg": 0,
        "source_coverage": {"azimuth_start_deg": 67.2},
        "coverage": {"horizontal_degrees": 352.9, "sphere_percent": 15.7},
        "color": "rgb",
        "credit": "Courtesy NASA/JPL-Caltech",
        "reuse_policy_url": "https://www.jpl.nasa.gov/jpl-image-use-policy/",
        "sources": {"label_url": "https://example.test/label.xml"},
    }
    return {**base, **overrides}


def _write_cache(root: Path, collection: str, products: list[dict]) -> None:
    items = []
    for product in products:
        folder = root / collection / product["id"]
        folder.mkdir(parents=True)
        (folder / "metadata.json").write_text(json.dumps(product))
        (folder / "panorama.webp").write_bytes(b"webp" + product["id"].encode())
        Image.new("RGBA", (1536, 396)).save(folder / "preview.webp")
        items.append(
            {
                "id": product["id"],
                "metadata": f"{collection}/{product['id']}/metadata.json",
            }
        )
    (root / collection / "catalog.json").write_text(json.dumps({"panoramas": items}))


class TestSelection:
    """A product exports only when the viewer can place and orient it."""

    def test_complete_product_exports(self, tmp_path: Path):
        _write_cache(tmp_path, "perseverance", [_product()])
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry == {
            "id": "perseverance-sol2",
            "mission": "perseverance",
            "instrument": "Navcam",
            "sol": 2,
            "time": "2021-02-20T21:48:15Z",
            "time_end": "2021-02-20T22:06:31Z",
            "lat": 18.44,
            "lon": 77.45,
            "elevation_m": -2569.9,
            "north_offset_deg": 0,
            "azimuth_start_deg": 67.2,
            "hfov_deg": 352.9,
            "sphere_percent": 15.7,
            "color": "rgb",
            "credit": "Courtesy NASA/JPL-Caltech",
            "credit_url": "https://www.jpl.nasa.gov/jpl-image-use-policy/",
            "source_url": "https://example.test/label.xml",
        }
        folder = tmp_path / "perseverance" / "perseverance-sol2"
        assert product.image == folder / "panorama.webp"
        assert product.preview == folder / "preview.webp"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"body_id": None},
            {"position": None},
            {"image": None},
            {"grid_geometry_status": "estimated"},
            {"geometry_status": "estimated"},
            {"north_azimuth_offset_deg": None},
            {"start_time": "", "capture_time": None},
        ],
        ids=[
            "no body",
            "no position",
            "flat only",
            "grid fit",
            "strip fit",
            "no north",
            "undated",
        ],
    )
    def test_incomplete_product_stays_local(self, tmp_path: Path, overrides: dict):
        _write_cache(tmp_path, "perseverance", [_product(**overrides)])
        assert panoramas.load_panoramas(tmp_path) == {}

    def test_capture_time_stands_in_for_start_time(self, tmp_path: Path):
        _write_cache(
            tmp_path,
            "moon",
            [_product(start_time=None, stop_time=None, capture_time="1969-07-21")],
        )
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["time"] == "1969-07-21"
        assert "time_end" not in product.entry

    def test_missing_cache_exports_none(self, tmp_path: Path):
        assert panoramas.load_panoramas(tmp_path / "absent") == {}


class TestDedupe:
    """Two renditions of one mosaic share a URL key; only the first ships."""

    def test_same_time_and_place_kept_once(self, tmp_path: Path):
        _write_cache(tmp_path, "p", [_product(id="left"), _product(id="right")])
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["id"] == "left"


class TestOrder:
    """Entries are grouped by mission and follow the traverse in time."""

    def test_sorted_by_mission_then_time(self, tmp_path: Path):
        _write_cache(
            tmp_path,
            "mixed",
            [
                _product(id="p-late", start_time="2021-03-01T00:00:00Z"),
                _product(
                    id="c-any", mission="curiosity", start_time="2012-09-01T00:00:00Z"
                ),
                _product(id="p-early", start_time="2021-02-20T00:00:00Z"),
            ],
        )
        entries = panoramas.load_panoramas(tmp_path)[MARS]
        assert [p.entry["id"] for p in entries] == ["c-any", "p-early", "p-late"]

    def test_no_mission_sorts_first(self, tmp_path: Path):
        _write_cache(
            tmp_path,
            "loose",
            [
                _product(id="p"),
                _product(id="lone", mission=None, start_time="2021-03-01T00:00:00Z"),
            ],
        )
        entries = panoramas.load_panoramas(tmp_path)[MARS]
        assert [p.entry["id"] for p in entries] == ["lone", "p"]
        assert "mission" not in entries[0].entry


class TestAdditiveRun:
    """`--only panoramas` copies textures and patches the body's bundle in place."""

    def test_assets_and_bundle(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cache = tmp_path / "derived"
        _write_cache(cache, "perseverance", [_product()])
        monkeypatch.setattr(
            panoramas, "_cached", lambda: panoramas.load_panoramas(cache)
        )

        out_dir = tmp_path / "v1"
        bucket = hash_bucket(MARS, 3)
        bundle_path = out_dir / "objects" / "__global__" / f"{bucket}.json.gz"
        bundle_path.parent.mkdir(parents=True)
        bundle_path.write_bytes(
            gzip.compress(orjson.dumps({MARS: {"id": MARS, "name": "Mars"}}))
        )
        (out_dir / "metadata.json").write_bytes(
            orjson.dumps(
                {"object_bundles": {"global": 3}, "versions": {"objects": "0"}}
            )
        )

        (out_dir / "panoramas").mkdir()
        (out_dir / "panoramas" / "gone.webp").write_bytes(b"old")
        panoramas.write_panorama_assets(out_dir)
        panoramas._patch_global_bundles(out_dir)

        assert not (out_dir / "panoramas" / "gone.webp").exists()

        assert (
            out_dir / "panoramas" / "perseverance-sol2.webp"
        ).read_bytes() == b"webpperseverance-sol2"
        with Image.open(out_dir / "panoramas" / "perseverance-sol2-preview.webp") as im:
            assert im.size == (512, 132)
        bundle = orjson.loads(gzip.decompress(bundle_path.read_bytes()))
        assert bundle[MARS]["name"] == "Mars"
        assert [p["id"] for p in bundle[MARS]["panoramas"]] == ["perseverance-sol2"]

    def test_regenerated_preview_replaces_thumbnail(self, tmp_path: Path, monkeypatch):
        cache = tmp_path / "derived"
        _write_cache(cache, "perseverance", [_product()])
        monkeypatch.setattr(
            panoramas, "_cached", lambda: panoramas.load_panoramas(cache)
        )
        out_dir = tmp_path / "v1"
        panoramas.write_panorama_assets(out_dir)
        thumb = out_dir / "panoramas" / "perseverance-sol2-preview.webp"
        before = thumb.stat().st_mtime

        source = cache / "perseverance" / "perseverance-sol2" / "preview.webp"
        Image.new("RGBA", (1024, 396)).save(source)
        os.utime(source, (before + 60, before + 60))
        panoramas.write_panorama_assets(out_dir)
        with Image.open(thumb) as im:
            assert im.size == (512, 198)

    def test_body_that_lost_its_panoramas_is_cleared(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(panoramas, "_cached", dict)
        out_dir = tmp_path / "v1"
        bundle_path = out_dir / "objects" / "__global__" / "0.json.gz"
        bundle_path.parent.mkdir(parents=True)
        bundle_path.write_bytes(
            gzip.compress(
                orjson.dumps({MARS: {"id": MARS, "panoramas": [{"id": "x"}]}})
            )
        )
        panoramas._patch_global_bundles(out_dir)
        bundle = orjson.loads(gzip.decompress(bundle_path.read_bytes()))
        assert "panoramas" not in bundle[MARS]
