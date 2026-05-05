"""Tests for space_map_data.export.labels.write_global_labels."""

import gzip

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.labels import write_global_labels
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.models.object import ObjectType


def _parse(path):
    """Parse a gzipped labels file → {id: name}."""
    text = gzip.decompress(path.read_bytes()).decode()
    if not text:
        return {}
    out = {}
    for line in text.split("\n"):
        sep = line.index("\x1f")
        out[line[:sep]] = line[sep + 1 :]
    return out


class TestWriteGlobalLabels:
    """Promoted-set selection, name fallback, file layout."""

    def test_only_promoted_types_and_extras_are_emitted(self, tmp_path):
        all_objs = ChunkObjectData()
        # Promoted by type
        all_objs.global_data["naif-399"] = {"type": ObjectType.planet, "name": "Earth"}
        all_objs.global_data["naif-301"] = {"type": ObjectType.moon, "name": "Moon"}
        # Promoted via curated extras list
        all_objs.global_data["naif--31"] = {
            "type": ObjectType.spacecraft,
            "name": "Voyager 1",
        }
        # Random non-promoted asteroid — should not appear
        all_objs.global_data["spkid-20012345"] = {
            "type": ObjectType.asteroid,
            "name": "Random",
        }

        write_global_labels(tmp_path, all_objs)

        names = _parse(tmp_path / "labels" / "en.gz")
        assert set(names) == {"naif-399", "naif-301", "naif--31"}

    def test_emits_one_file_per_language(self, tmp_path):
        all_objs = ChunkObjectData()
        all_objs.global_data["naif-399"] = {"type": ObjectType.planet, "name": "Earth"}

        write_global_labels(tmp_path, all_objs)

        for lang in LANGUAGES:
            assert (tmp_path / "labels" / f"{lang}.gz").exists()

    def test_localized_name_takes_precedence_over_global(self, tmp_path):
        all_objs = ChunkObjectData()
        all_objs.global_data["naif-399"] = {"type": ObjectType.planet, "name": "Earth"}
        all_objs.localized_data["fr"]["naif-399"] = {"name": "Terre"}

        write_global_labels(tmp_path, all_objs)

        assert _parse(tmp_path / "labels" / "fr.gz")["naif-399"] == "Terre"
        # No localized override for English → fall through to global obj.name
        assert _parse(tmp_path / "labels" / "en.gz")["naif-399"] == "Earth"

    def test_empty_name_when_neither_localized_nor_global_has_one(self, tmp_path):
        all_objs = ChunkObjectData()
        # Curated extra with no Wikidata and no DB name (e.g. a probe with only
        # a NAIF id). The empty-name line still ships because the id needs to
        # appear in the keys for the frontend's auto-promote set; downstream
        # name coalescing turns the empty value into a null and the drawer
        # walks its fallback chain (loading → id) from there.
        all_objs.global_data["naif--31"] = {"type": ObjectType.spacecraft}

        write_global_labels(tmp_path, all_objs)

        assert _parse(tmp_path / "labels" / "en.gz") == {"naif--31": ""}
