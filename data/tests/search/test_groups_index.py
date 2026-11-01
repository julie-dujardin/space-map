"""Tests for the group documents of the search index."""

import gzip
import json
from pathlib import Path

from space_map_data.constants.categories import (
    MOONS_SLUG,
    PLANETARY_SYSTEMS_SLUG,
    PLANETS_SLUG,
    SOLAR_SYSTEM_SLUG,
)
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
            "sky-orion": {
                "slug": "sky-orion",
                "type": "sky_constellation",
                "home_figure": {
                    "culture": "modern_iau",
                    "figure": "Ori",
                    "name": "Orion",
                },
                **base,
            },
            "sky-mensa": {
                "slug": "sky-mensa",
                "type": "sky_constellation",
                "home_figure": {
                    "culture": "modern_iau",
                    "figure": "Men",
                    "name": "Mensa",
                },
                **base,
            },
            "sky-lost": {"slug": "sky-lost", "type": "sky_constellation", **base},
            "star-giant": {"slug": "star-giant", "type": "star_family", **base},
        },
    )
    _write(
        groups / "en" / "0.json.gz",
        {
            "sky-orion": {"name": "Orion", "wikipedia": {"extract": "A hunter."}},
            "sky-mensa": {"name": "Mensa", "wikipedia": {"title": "Mensa"}},
            "sky-lost": {"name": "Lost", "wikipedia": {"extract": "No figure."}},
            "star-giant": {"name": "Giant star"},
        },
    )
    docs = list(build_group_documents(tmp_path))
    assert [doc["group"]["slug"] for doc in docs] == ["sky-orion", "star-giant"]
    assert docs[0]["group"]["culture"] == "culture-modern_iau"
    assert docs[0]["group"]["figure"] == "Ori"


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


def test_a_constellation_is_a_fleet_or_a_breakup_cloud(tmp_path: Path):
    base = {"applies_to": "earth_sat", "member_count": 0, "type": "constellation"}
    _write(
        tmp_path / "v1" / "groups" / "__global__" / "0.json.gz",
        {
            "const-starlink": base | {"parent_category": "cat-satellites"},
            "const-fengyun-1c": base | {"parent_category": "cat-debris"},
            "star-giant": {
                "applies_to": "star",
                "member_count": 0,
                "type": "star_family",
                "parent_families": ["cat-stars"],
            },
        },
    )
    docs = {
        doc["group"]["slug"]: doc["group"] for doc in build_group_documents(tmp_path)
    }
    assert docs["const-starlink"]["types"] == ["constellation", "fleet"]
    assert docs["const-fengyun-1c"]["types"] == ["constellation", "breakup_cloud"]
    assert docs["star-giant"]["types"] == ["star_family"]
    assert docs["star-giant"]["parents"] == ["cat-stars"]
    assert "parents" not in docs["const-starlink"]


def test_the_solar_system_is_a_planetary_system(tmp_path: Path):
    base = {"applies_to": "object", "member_count": 0, "type": "category"}
    _write(
        tmp_path / "v1" / "groups" / "__global__" / "0.json.gz",
        {
            SOLAR_SYSTEM_SLUG: base,
            MOONS_SLUG: base,
            PLANETS_SLUG: base | {"solar_member_count": 8},
        },
    )
    docs = {doc["group"]["slug"]: doc for doc in build_group_documents(tmp_path)}
    assert docs[SOLAR_SYSTEM_SLUG]["classes"] == [PLANETARY_SYSTEMS_SLUG]
    assert docs[SOLAR_SYSTEM_SLUG]["planet_count"] == 8
    assert "classes" not in docs[MOONS_SLUG]
