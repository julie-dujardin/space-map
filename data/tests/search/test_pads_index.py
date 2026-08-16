"""Tests for the launch-pad search documents."""

import gzip
import json
from pathlib import Path

from space_map_data.search.indices.base import pad_pk
from space_map_data.search.indices.pads import build_pad_documents

CANAVERAL = {
    "site-cape-canaveral": {
        "type": "launch_site",
        "applies_to": "earth_satellite",
        "member_count": 900,
        "gcat_sites": [
            {
                "code": "CC",
                "name": "Cape Canaveral Air Station, Florida",
                "launches": 700,
                "pads": [
                    {
                        "code": "LC40",
                        "name": "Space Launch Complex 40, Cape Canaveral",
                        "label": "Space Launch Complex 40",
                        "lat": 28.5619,
                        "lon": -80.5772,
                        "launches": 381,
                    }
                ],
            },
            # A place with no pads GCAT could position at all.
            {"code": "CCA", "name": "Space Florida", "launches": 3},
        ],
    },
    # Everything that is not a launch range is nobody's pad.
    "lv-falcon-9": {"type": "launch_vehicle", "applies_to": "earth_satellite"},
}


def _write_bundles(tmp_path: Path, groups: dict, localized: dict | None = None) -> Path:
    groups_dir = tmp_path / "v1" / "groups"
    (groups_dir / "__global__").mkdir(parents=True)
    (groups_dir / "__global__" / "0.json.gz").write_bytes(
        gzip.compress(json.dumps(groups).encode())
    )
    for lang, entries in (localized or {}).items():
        (groups_dir / lang).mkdir(parents=True)
        (groups_dir / lang / "0.json.gz").write_bytes(
            gzip.compress(json.dumps(entries).encode())
        )
    return tmp_path


class TestBuildPadDocuments:
    """`build_pad_documents` turns a site bundle's pads into search documents."""

    def test_one_document_per_placed_pad(self, tmp_path):
        docs = list(build_pad_documents(_write_bundles(tmp_path, CANAVERAL)))
        assert len(docs) == 1
        doc = docs[0]
        assert doc["id"] == pad_pk("site-cape-canaveral", "LC40")
        assert doc["kind"] == "pad"
        assert doc["pad"] == {
            "code": "LC40",
            "site_slug": "site-cape-canaveral",
            "site_name": "Cape Canaveral Air Station, Florida",
            "lat": 28.5619,
            "lon": -80.5772,
            "launches": 381,
        }

    def test_prefers_the_label_over_the_raw_name(self, tmp_path):
        docs = list(build_pad_documents(_write_bundles(tmp_path, CANAVERAL)))
        assert docs[0]["name"] == "Space Launch Complex 40"

    def test_falls_back_to_the_raw_name(self, tmp_path):
        groups = json.loads(json.dumps(CANAVERAL))
        del groups["site-cape-canaveral"]["gcat_sites"][0]["pads"][0]["label"]
        docs = list(build_pad_documents(_write_bundles(tmp_path, groups)))
        assert docs[0]["name"] == "Space Launch Complex 40, Cape Canaveral"

    def test_carries_the_range_name_per_locale(self, tmp_path):
        localized = {"fr": {"site-cape-canaveral": {"name": "base de Cap Canaveral"}}}
        docs = list(build_pad_documents(_write_bundles(tmp_path, CANAVERAL, localized)))
        # A pad's own name is GCAT's English; the range is what a reader may
        # look for it by in their own language.
        assert docs[0]["description_fr"] == "base de Cap Canaveral"
        assert "description_ja" not in docs[0]

    def test_carries_no_prominence(self, tmp_path):
        # Sorting below everything that has a sitelink count is the point.
        docs = list(build_pad_documents(_write_bundles(tmp_path, CANAVERAL)))
        assert "sitelinks_count" not in docs[0]

    def test_no_bundles_at_all(self, tmp_path):
        assert list(build_pad_documents(tmp_path)) == []


class TestPadPk:
    """`pad_pk` keys a pad under the collection holding it."""

    def test_mirrors_the_group_key(self):
        assert pad_pk("site-cape-canaveral", "LC39A") == "g-site-cape-canaveral-p-LC39A"

    def test_replaces_what_meili_will_not_take_in_a_key(self):
        assert pad_pk("site-baikonur", "LC200/39") == "g-site-baikonur-p-LC200-39"
