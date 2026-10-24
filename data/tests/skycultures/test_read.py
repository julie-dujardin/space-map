"""Tests for reading the downloaded sky-culture datasets."""

import json
from pathlib import Path

import pytest

from space_map_data.skycultures import read
from space_map_data.skycultures.licences import NO_LICENCE, NON_COMMERCIAL

DESCRIPTION = """# Test Sky

## Introduction

Text.

## Authors

Someone.

## References

 - [#1]: A book.
 - [#2]: [A page](https://example.org)
   continued here.

## License

CC BY-SA 4.0
"""


def stellarium_tree(root: Path) -> Path:
    cultures = root / "skycultures"
    for key in ("test", "hidden"):
        (cultures / key).mkdir(parents=True)
        (cultures / key / "index.json").write_text(json.dumps({"id": key}))
    (cultures / "test" / "description.md").write_text(DESCRIPTION)
    (cultures / "test" / "territory.geojson").write_text(
        '{"type": "FeatureCollection"}'
    )
    (cultures / "CMakeLists.txt").write_text(
        "ADD_SUBDIRECTORY( test )\n# Exclude\n# ADD_SUBDIRECTORY( hidden )\n"
    )
    (cultures / "common_star_names.fab").write_text(
        '# comment\n 13847|_("Acamar") 2\n 13847|_("Other") 2,5\nbroken line\n'
    )
    return root


def bucur_tree(root: Path) -> Path:
    (root / "json").mkdir(parents=True)
    culture = {
        "id": "Ava Guarani",
        "name": "Ava Guaraní",
        "region": "Americas",
        "licence": "CC BY-SA",
        "source": ["a2020", "missing"],
    }
    (root / "json" / "Ava Guarani.json").write_text(json.dumps(culture))
    (root / "sources.bib").write_text(
        "@book{a2020,\n  title={A},\n  year={2020}\n}\n\n@article{b2021,\n  title={B}\n}\n"
    )
    return root


class TestStellarium:
    """A culture's metadata comes from its description and the build file."""

    @pytest.fixture
    def cultures(self, tmp_path):
        return {c.key: c for c in read.read_stellarium(stellarium_tree(tmp_path))}

    def test_name_licence_sources_and_territory(self, cultures):
        culture = cultures["test"]
        assert culture.name == "Test Sky"
        assert culture.authors == "Someone."
        assert culture.licence.parts[0].licence == "CC BY-SA 4.0"
        assert culture.sources == [
            {"number": 1, "text": "A book."},
            {"number": 2, "text": "[A page](https://example.org) continued here."},
        ]
        assert culture.territory == {"type": "FeatureCollection"}
        assert culture.path == "skycultures/test"
        assert culture.packaged

    def test_culture_without_description_has_no_licence(self, cultures):
        culture = cultures["hidden"]
        assert culture.licence.data == NON_COMMERCIAL
        assert culture.licence.flags == (NO_LICENCE,)
        assert not culture.packaged

    def test_common_star_names_by_hip_number(self, tmp_path):
        names = read.read_common_names(stellarium_tree(tmp_path))
        assert names == {
            "common_names": {
                "HIP 13847": [
                    {"english": "Acamar", "references": [2]},
                    {"english": "Other", "references": [2, 5]},
                ]
            }
        }


class TestBucur:
    """A culture's sources are its BibTeX entries."""

    def test_sources_licence_and_key(self, tmp_path):
        (culture,) = read.read_bucur(bucur_tree(tmp_path))
        assert culture.key == "ava_guarani"
        assert culture.name == "Ava Guaraní"
        assert culture.path == "json/Ava Guarani.json"
        assert culture.licence.parts[0].licence == "CC BY-SA"
        assert culture.sources[0]["bibtex"].startswith("@book{a2020,")
        assert culture.sources[0]["bibtex"].endswith("}")
        assert culture.sources[1] == {"key": "missing", "bibtex": None}

    def test_bib_entries_split_at_each_entry(self):
        entries = read.bib_entries("@book{x,\n t={1}\n}\n@misc{y,\n t={2}\n}\n")
        assert list(entries) == ["x", "y"]
        assert entries["y"] == "@misc{y,\n t={2}\n}"
