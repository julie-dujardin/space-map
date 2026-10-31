"""Tests for the group documents of the search index."""

import gzip
import json
from pathlib import Path

from space_map_data.search.indices.groups import build_group_documents


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(data).encode()))


def test_a_constellation_needs_a_blurb_and_another_group_does_not(tmp_path: Path):
    groups = tmp_path / "v1" / "groups"
    base = {"applies_to": "star", "member_count": 0}
    _write(
        groups / "__global__" / "0.json.gz",
        {
            "sky-orion": {"slug": "sky-orion", "type": "sky_constellation", **base},
            "sky-mensa": {"slug": "sky-mensa", "type": "sky_constellation", **base},
            "star-giant": {"slug": "star-giant", "type": "star_family", **base},
        },
    )
    _write(
        groups / "en" / "0.json.gz",
        {
            "sky-orion": {"name": "Orion", "wikipedia": {"extract": "A hunter."}},
            "sky-mensa": {"name": "Mensa", "wikipedia": {"title": "Mensa"}},
            "star-giant": {"name": "Giant star"},
        },
    )
    slugs = [doc["group"]["slug"] for doc in build_group_documents(tmp_path)]
    assert slugs == ["sky-orion", "star-giant"]


def test_a_culture_needs_no_blurb(tmp_path: Path):
    groups = tmp_path / "v1" / "groups"
    base = {"applies_to": "star", "member_count": 1, "type": "sky_culture"}
    _write(
        groups / "__global__" / "0.json.gz",
        {
            "culture-maya": {"slug": "culture-maya", **base},
            "culture-aztec": {"slug": "culture-aztec", **base},
        },
    )
    _write(
        groups / "en" / "0.json.gz",
        {
            "culture-maya": {"name": "Maya", "wikipedia": {"extract": "Maya sky."}},
            "culture-aztec": {"name": "Aztec"},
        },
    )
    slugs = [doc["group"]["slug"] for doc in build_group_documents(tmp_path)]
    assert slugs == ["culture-maya", "culture-aztec"]
