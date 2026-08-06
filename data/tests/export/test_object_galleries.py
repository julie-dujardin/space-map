"""Tests for the pooled image shelves attached to an object's bundle."""

import pytest

from space_map_data.export.objects import galleries as galleries_mod
from space_map_data.export.objects.galleries import (
    MOON_GALLERY_LIMIT,
    attach_galleries,
)
from space_map_data.export.objects.writer import ChunkObjectData


def _image(file: str, kind: str = "photo") -> dict:
    return {"file": file, "kind": kind, "variants": {"s": "webp"}}


@pytest.fixture
def pools(monkeypatch) -> tuple[dict, dict]:
    """Stand-in image caches: ``{object_id: [...]}`` and ``{feature_id: [...]}``."""
    objects: dict[str, list[dict]] = {}
    features: dict[str, list[dict]] = {}
    monkeypatch.setattr(
        galleries_mod, "collect_object_images", lambda oid: objects.get(oid)
    )
    monkeypatch.setattr(
        galleries_mod,
        "collect_feature_images",
        lambda fid: features.get(str(fid)),
    )
    return objects, features


def _chunk(body_id: str, data: dict) -> ChunkObjectData:
    chunk = ChunkObjectData()
    chunk.global_data[body_id] = data
    return chunk


class TestAttachGalleries:
    """Pooling the notable moon and feature lists into image shelves."""

    def test_no_notable_lists_attaches_nothing(self, pools):
        chunk = _chunk("naif-599", {"images": [_image("a.jpg")]})
        attach_galleries(chunk)
        assert "galleries" not in chunk.global_data["naif-599"]

    def test_moons_shelf_follows_the_notable_order(self, pools):
        objects, _ = pools
        objects["naif-501"] = [_image("io.jpg")]
        objects["naif-502"] = [_image("europa.jpg")]
        chunk = _chunk(
            "naif-599",
            {"notable_moons": [{"id": "naif-501"}, {"id": "naif-502"}]},
        )
        attach_galleries(chunk)
        shelf = chunk.global_data["naif-599"]["galleries"][0]
        assert shelf["key"] == "moons"
        assert [entry["file"] for entry in shelf["images"]] == ["io.jpg", "europa.jpg"]

    def test_each_picture_carries_its_subject(self, pools):
        objects, _ = pools
        objects["naif-501"] = [_image("io.jpg")]
        chunk = _chunk("naif-599", {"notable_moons": [{"id": "naif-501"}]})
        attach_galleries(chunk)
        shelf = chunk.global_data["naif-599"]["galleries"][0]
        assert shelf["images"][0]["subject"] == "naif-501"

    def test_one_moon_cannot_fill_the_shelf(self, pools):
        objects, _ = pools
        objects["naif-501"] = [_image(f"io{i}.jpg") for i in range(6)]
        objects["naif-502"] = [_image("europa.jpg")]
        chunk = _chunk(
            "naif-599",
            {"notable_moons": [{"id": "naif-501"}, {"id": "naif-502"}]},
        )
        attach_galleries(chunk)
        files = [
            e["file"] for e in chunk.global_data["naif-599"]["galleries"][0]["images"]
        ]
        assert files.count("io0.jpg") == 1
        assert "europa.jpg" in files
        assert len([f for f in files if f.startswith("io")]) == 2

    def test_shelf_is_capped(self, pools):
        objects, _ = pools
        for i in range(20):
            objects[f"naif-{i}"] = [_image(f"m{i}a.jpg"), _image(f"m{i}b.jpg")]
        chunk = _chunk(
            "naif-599", {"notable_moons": [{"id": f"naif-{i}"} for i in range(20)]}
        )
        attach_galleries(chunk)
        shelf = chunk.global_data["naif-599"]["galleries"][0]
        assert len(shelf["images"]) == MOON_GALLERY_LIMIT

    def test_locator_maps_are_not_pictures_of_the_feature(self, pools):
        _, features = pools
        features["14940"] = [_image("map.svg", kind="locator")]
        chunk = _chunk("naif-301", {"notable_features": [{"feature_id": 14940}]})
        attach_galleries(chunk)
        assert "galleries" not in chunk.global_data["naif-301"]

    def test_a_picture_already_shown_is_not_pooled_again(self, pools):
        objects, _ = pools
        objects["naif-501"] = [_image("shared.jpg")]
        chunk = _chunk(
            "naif-599",
            {
                "images": [_image("shared.jpg")],
                "notable_moons": [{"id": "naif-501"}],
            },
        )
        attach_galleries(chunk)
        assert "galleries" not in chunk.global_data["naif-599"]

    def test_a_ring_picture_is_not_pooled_again_either(self, pools):
        objects, _ = pools
        objects["naif-601"] = [_image("rings.jpg"), _image("mimas.jpg")]
        chunk = _chunk(
            "naif-699",
            {
                "ring_images": [_image("rings.jpg")],
                "notable_moons": [{"id": "naif-601"}],
            },
        )
        attach_galleries(chunk)
        shelf = chunk.global_data["naif-699"]["galleries"][0]
        assert [entry["file"] for entry in shelf["images"]] == ["mimas.jpg"]

    def test_features_lead_the_moons(self, pools):
        objects, features = pools
        features["14940"] = [_image("tycho.jpg")]
        objects["naif-501"] = [_image("io.jpg")]
        chunk = _chunk(
            "naif-599",
            {
                "notable_features": [{"feature_id": 14940}],
                "notable_moons": [{"id": "naif-501"}],
            },
        )
        attach_galleries(chunk)
        keys = [g["key"] for g in chunk.global_data["naif-599"]["galleries"]]
        assert keys == ["features", "moons"]
