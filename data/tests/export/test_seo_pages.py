"""Tests for the SEO page records.

A record must hold every field ``frontend/src/lib/seo/meta.ts`` reads of the
page's bundle entries: the Worker builds the page's meta from the record alone.
"""

import gzip
from pathlib import Path
from unittest.mock import MagicMock

import orjson

from space_map_data.export.objects.writer import hash_bucket
from space_map_data.export.seo_pages import (
    Spec,
    _card_images,
    _project,
    write_seo_pages,
)
from space_map_data.export.sitemap import SitemapPages
from space_map_data.models.feature import Feature


def _write_bundles(bundle_dir: Path, n_buckets: int, entries: dict[str, dict]) -> None:
    """Write *entries* as the export does: one file per bucket that has one."""
    buckets: dict[int, dict[str, dict]] = {}
    for key, entry in entries.items():
        buckets.setdefault(hash_bucket(key, n_buckets), {})[key] = entry
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for bucket, bucket_entries in buckets.items():
        (bundle_dir / f"{bucket}.json.gz").write_bytes(
            gzip.compress(orjson.dumps(bucket_entries))
        )


def _image(file: str, kind: str = "photo", attr: str = "free") -> dict:
    return {
        "file": file,
        "source_url": f"https://commons.wikimedia.org/wiki/File:{file}",
        "kind": kind,
        "attr": attr,
        "variants": {"s": "webp", "m": "webp"},
        "width": 100,
        "height": 100,
    }


class TestProject:
    """The fields of an entry that a record keeps."""

    def test_keeps_the_listed_fields_and_sub_fields(self):
        entry = {
            "name": "Ceres",
            "orbit": {"a": 2.77},
            "sbdb": {"class": "MBA", "H": 3.3, "albedo": 0.09},
            "discoverers": [{"name": "Piazzi", "wikipedia": "x"}],
        }
        spec: Spec = {"name": None, "sbdb": ("class", "H"), "discoverers": ("name",)}

        assert _project(entry, spec) == {
            "name": "Ceres",
            "sbdb": {"class": "MBA", "H": 3.3},
            "discoverers": [{"name": "Piazzi"}],
        }

    def test_leaves_out_a_sub_object_with_none_of_the_fields(self):
        assert (
            _project({"wikidata": {"qid": "Q1"}}, {"wikidata": ("launch_date",)}) == {}
        )


class TestCardImages:
    """The images a record keeps for the page's card."""

    def test_keeps_the_first_of_each_kind_and_tier_in_order(self):
        images = [
            _image("a", attr="credit"),
            _image("b"),
            _image("c"),
            _image("d", kind="logo"),
            _image("e", kind="radar"),
            _image("f", attr="other"),
        ]

        assert [image["file"] for image in _card_images(images)] == ["a", "b", "d"]

    def test_keeps_what_the_card_reads_of_an_image(self):
        assert _card_images([_image("a")]) == [
            {
                "file": "a",
                "kind": "photo",
                "attr": "free",
                "variants": {"s": "webp", "m": "webp"},
            }
        ]


class TestWriteSeoPages:
    """Records of the pages of the sitemap, from the bundles in the export."""

    def _export(self, out: Path) -> None:
        _write_bundles(
            out / "objects" / "__global__",
            2,
            {
                "naif-499": {
                    "name": "Mars",
                    "type": "planet",
                    "orbit": {"a": 1.52},
                    "images": [_image("Mars.png", attr="credit"), _image("Mars.jpg")],
                },
                "x-5-b-2": {"name": "Dimidium", "type": "exoplanet"},
            },
        )
        _write_bundles(
            out / "objects" / "en",
            1,
            {"naif-499": {"name": "Mars", "description": "planet", "wikipedia": {}}},
        )
        _write_bundles(out / "objects" / "fr", 1, {"naif-499": {"name": "Mars"}})
        _write_bundles(
            out / "groups" / "__global__",
            1,
            {
                "cat-planets": {
                    "galleries": [{"key": "m", "images": [_image("All.jpg")]}]
                }
            },
        )
        _write_bundles(out / "groups" / "en", 1, {"cat-planets": {"name": "Planets"}})
        _write_bundles(
            out / "nomenclature" / "details" / "__global__",
            1,
            {"naif-301:7": {"origin": "Tycho Brahe", "diameter_km": 85}},
        )
        credit = out / "images" / "Mars.png"
        credit.mkdir(parents=True)
        (credit / "metadata.json.gz").write_bytes(
            gzip.compress(
                orjson.dumps(
                    {
                        "license": {"name": "CC BY 4.0", "url": "https://x"},
                        "artist": "Kevin M. Gill",
                        "description": "Mars",
                    }
                )
            )
        )

    def _write(self, out: Path) -> dict:
        self._export(out)
        tycho = Feature(feature_id=7, object_id="naif-301", name="Tycho")
        write_seo_pages(
            out,
            SitemapPages(
                objects={"naif-499": "/b/499/Mars"},
                groups={"cat-planets": "/g/cat-planets/Planets"},
                features=[(tycho, "/b/301/f/7/Tycho")],
                planets=("x-5-b-2",),
            ),
            MagicMock(),
            {"global": 2, "en": 1, "fr": 1},
            {"global": 1},
            {"global": 1, "en": 1},
        )
        return orjson.loads(
            gzip.decompress((out / "seo" / "pages.json.gz").read_bytes())
        )

    def test_keys_each_record_by_its_asset_path(self, tmp_path: Path):
        assert sorted(self._write(tmp_path)) == [
            "f/naif-301/7",
            "g/cat-planets",
            "o/naif-499",
            "o/x-5-b-2",
        ]

    def test_holds_an_object_in_every_language_with_its_card_credits(
        self, tmp_path: Path
    ):
        assert self._write(tmp_path)["o/naif-499"] == {
            "global": {
                "name": "Mars",
                "type": "planet",
                "images": [
                    {
                        "file": "Mars.png",
                        "kind": "photo",
                        "attr": "credit",
                        "variants": {"s": "webp", "m": "webp"},
                    },
                    {
                        "file": "Mars.jpg",
                        "kind": "photo",
                        "attr": "free",
                        "variants": {"s": "webp", "m": "webp"},
                    },
                ],
            },
            "localized": {
                "en": {"name": "Mars", "description": "planet"},
                "fr": {"name": "Mars"},
            },
            "credits": {
                "Mars.png": {
                    "license": {"name": "CC BY 4.0"},
                    "artist": "Kevin M. Gill",
                }
            },
        }

    def test_gives_a_group_the_lead_image_of_its_first_gallery(self, tmp_path: Path):
        record = self._write(tmp_path)["g/cat-planets"]

        assert [image["file"] for image in record["global"]["images"]] == ["All.jpg"]
        assert record["localized"] == {"en": {"name": "Planets"}}

    def test_names_a_feature_in_every_language(self, tmp_path: Path):
        record = self._write(tmp_path)["f/naif-301/7"]

        assert record["global"] == {"origin": "Tycho Brahe"}
        assert record["names"] == {"en": "Tycho", "fr": "Tycho"}
