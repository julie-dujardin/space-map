"""Tests for the member image shelves attached to a collection's bundle."""

import pytest

from space_map_data.export.groups import bundles as bundles_mod
from space_map_data.export.groups.bundles import (
    MEMBER_GALLERY_COUNT,
    MEMBER_GALLERY_IMAGES,
    GallerySubject,
    _member_galleries,
)
from space_map_data.export.notable import NotableObject


def _image(file: str) -> dict:
    return {"file": file, "kind": "photo", "variants": {"s": "webp"}}


def _notable(object_id: str, **kwargs) -> NotableObject:
    return NotableObject(
        object_id=object_id,
        wikidata_qid=None,
        fallback_name=object_id,
        diameter_km=None,
        first_obs=None,
        **kwargs,
    )


def _shelves(members, own_images, member_ids, subjects=None) -> list[dict]:
    """``_member_galleries`` unwrapped — every test below expects shelves."""
    out = _member_galleries(members, own_images, member_ids, subjects)
    assert out is not None
    return out


@pytest.fixture
def pool(monkeypatch) -> dict[str, list[dict]]:
    """Stand-in object image cache, keyed by object id."""
    objects: dict[str, list[dict]] = {}
    monkeypatch.setattr(
        bundles_mod, "collect_object_images", lambda oid: objects.get(oid)
    )
    monkeypatch.setattr(
        bundles_mod, "object_image_count", lambda oid: len(objects.get(oid) or ())
    )
    return objects


class TestMemberGalleries:
    """One shelf per member, from the notable ranking and the whole collection."""

    def test_notable_members_lead_in_their_own_order(self, pool):
        pool.update({"a": [_image("A.jpg")], "b": [_image("B.jpg")]})
        out = _shelves([_notable("b"), _notable("a")], None, None)
        assert [g["key"] for g in out] == ["b", "a"]
        assert out[0]["subject"] == "b"

    def test_members_without_pictures_get_no_shelf(self, pool):
        pool["a"] = [_image("A.jpg")]
        out = _shelves([_notable("a"), _notable("empty")], None, None)
        assert [g["key"] for g in out] == ["a"]

    def test_group_and_feature_members_are_skipped(self, pool):
        pool.update({"a": [_image("A.jpg")], "host": [_image("H.jpg")]})
        members = [
            _notable("", group_slug="cat-moons"),
            _notable("host", feature_id=7),
            _notable("a"),
        ]
        assert [g["key"] for g in _shelves(members, None, None)] == ["a"]

    def test_the_group_own_pictures_are_not_repeated(self, pool):
        pool["a"] = [_image("Shared.jpg"), _image("Own.jpg")]
        out = _shelves([_notable("a")], [_image("Shared.jpg")], None)
        assert [e["file"] for e in out[0]["images"]] == ["Own.jpg"]

    def test_a_picture_is_never_on_two_shelves(self, pool):
        pool.update({"a": [_image("Same.jpg")], "b": [_image("Same.jpg")]})
        out = _shelves([_notable("a"), _notable("b")], None, None)
        assert [g["key"] for g in out] == ["a"]

    def test_shelves_come_from_membership_when_nothing_is_notable(self, pool):
        """The case the member-photo fallback used to cover."""
        pool.update({"m1": [_image("M1.jpg")], "m2": [_image("M2.jpg")]})
        out = _shelves(None, None, ["m1", "m2"])
        assert {g["key"] for g in out} == {"m1", "m2"}

    def test_membership_is_ranked_by_picture_count(self, pool):
        pool.update(
            {
                "few": [_image("F.jpg")],
                "many": [_image(f"M{i}.jpg") for i in range(3)],
            }
        )
        out = _shelves(None, None, ["few", "many"])
        assert [g["key"] for g in out] == ["many", "few"]

    def test_a_shelf_holds_at_most_MEMBER_GALLERY_IMAGES(self, pool):
        pool["a"] = [_image(f"{i}.jpg") for i in range(MEMBER_GALLERY_IMAGES + 4)]
        out = _shelves([_notable("a")], None, None)
        assert len(out[0]["images"]) == MEMBER_GALLERY_IMAGES

    def test_membership_adds_at_most_MEMBER_GALLERY_COUNT_shelves(self, pool):
        ids = [f"m{i}" for i in range(MEMBER_GALLERY_COUNT + 5)]
        pool.update({oid: [_image(f"{oid}.jpg")] for oid in ids})
        out = _shelves(None, None, ids)
        assert len(out) == MEMBER_GALLERY_COUNT

    def test_notable_and_membership_shelves_combine_without_duplicates(self, pool):
        pool.update({"a": [_image("A.jpg")], "m": [_image("M.jpg")]})
        out = _shelves([_notable("a")], None, ["a", "m"])
        assert [g["key"] for g in out] == ["a", "m"]

    def test_no_members_at_all_yields_nothing(self, pool):
        assert _member_galleries(None, None, None) is None
        assert _member_galleries([], [_image("Own.jpg")], []) is None

    def test_a_shelf_carries_its_subject_name(self, pool):
        pool["m"] = [_image("M.jpg")]
        subjects = {"m": GallerySubject("Meteosat-8", "Q42")}
        out = _member_galleries(None, None, ["m"], subjects)
        assert out is not None
        assert out[0]["name"] == "Meteosat-8"

    def test_an_unnamed_subject_leaves_the_shelf_nameless(self, pool):
        pool["m"] = [_image("M.jpg")]
        out = _shelves(None, None, ["m"], {})
        assert "name" not in out[0]
