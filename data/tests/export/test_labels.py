"""Tests for space_map_data.export.labels.write_global_labels."""

import gzip

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.labels import write_global_labels
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.models.object import ObjectType


def _parse(path):
    """Parse a gzipped labels file → {id: name}, dropping the flags column."""
    return {obj_id: name for obj_id, (name, _) in _parse_with_flags(path).items()}


def _parse_with_flags(path):
    """Parse a gzipped labels file → {id: (name, flags)}."""
    text = gzip.decompress(path.read_bytes()).decode()
    if not text:
        return {}
    out = {}
    for line in text.split("\n"):
        parts = line.split("\x1f")
        assert len(parts) == 3, f"expected id<US>name<US>flags, got {parts!r}"
        out[parts[0]] = (parts[1], parts[2])
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

        write_global_labels(tmp_path, all_objs, set(), set(all_objs.global_data.keys()))

        names = _parse(tmp_path / "labels" / "en.gz")
        assert set(names) == {"naif-399", "naif-301", "naif--31"}

    def test_emits_one_file_per_language(self, tmp_path):
        all_objs = ChunkObjectData()
        all_objs.global_data["naif-399"] = {"type": ObjectType.planet, "name": "Earth"}

        write_global_labels(tmp_path, all_objs, set(), set(all_objs.global_data.keys()))

        for lang in LANGUAGES:
            assert (tmp_path / "labels" / f"{lang}.gz").exists()

    def test_localized_name_takes_precedence_over_global(self, tmp_path):
        all_objs = ChunkObjectData()
        all_objs.global_data["naif-399"] = {"type": ObjectType.planet, "name": "Earth"}
        all_objs.localized_data["fr"]["naif-399"] = {"name": "Terre"}

        write_global_labels(tmp_path, all_objs, set(), set(all_objs.global_data.keys()))

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

        write_global_labels(tmp_path, all_objs, set(), set(all_objs.global_data.keys()))

        assert _parse(tmp_path / "labels" / "en.gz") == {"naif--31": ""}

    def test_chebyshev_covered_bodies_are_auto_promoted(self, tmp_path):
        """DE441 perturber asteroids ride in chebyshev but aren't in
        PROMOTED_EXTRA_IDS; they're rendered as individual meshes anyway, so
        they belong in the labels set."""
        all_objs = ChunkObjectData()
        all_objs.global_data["spkid-20000052"] = {
            "type": ObjectType.asteroid_main_belt,
            "name": "52 Europa",
        }

        write_global_labels(
            tmp_path, all_objs, {"spkid-20000052"}, set(all_objs.global_data.keys())
        )

        assert _parse(tmp_path / "labels" / "en.gz") == {"spkid-20000052": "52 Europa"}

    def test_falls_back_to_provisional_designation(self, tmp_path):
        """SPICE-only minor moons (e.g. naif-551) have no Wikidata and no DB
        ``name``, but they do carry a provisional designation. Use that as the
        last fallback so the promoted entry shows something meaningful, and
        flag the line as minor so the frontend renders it as a collapsed halo."""
        all_objs = ChunkObjectData()
        all_objs.global_data["naif-551"] = {
            "type": ObjectType.moon,
            "provisional_designation": "2010J1",
        }

        write_global_labels(tmp_path, all_objs, set(), set(all_objs.global_data.keys()))

        assert _parse_with_flags(tmp_path / "labels" / "en.gz") == {
            "naif-551": ("2010J1", "m"),
        }

    def test_minor_flag_only_set_for_designation_only_moons(self, tmp_path):
        """Only moons whose label fell back to the designation get ``m``;
        named moons and moons with a Wikidata localized name stay unflagged."""
        all_objs = ChunkObjectData()
        # Moon with DB name → not minor, even though designation exists
        all_objs.global_data["naif-301"] = {
            "type": ObjectType.moon,
            "name": "Moon",
            "provisional_designation": "S0001",
        }
        # Moon with Wikidata localized name overriding the designation → not minor
        all_objs.global_data["naif-557"] = {
            "type": ObjectType.moon,
            "provisional_designation": "S2003J5",
        }
        all_objs.localized_data["en"]["naif-557"] = {"name": "Eirene"}
        # Designation-only moon → minor
        all_objs.global_data["naif-65289"] = {
            "type": ObjectType.moon,
            "provisional_designation": "S2020 S48",
        }
        # Moon whose DB name was filled from the designation by SPICE bodc2n →
        # still effectively designation-only, so it should also be flagged.
        all_objs.global_data["naif-55533"] = {
            "type": ObjectType.moon,
            "name": "S2010 J5",
            "provisional_designation": "S2010 J5",
        }

        write_global_labels(tmp_path, all_objs, set(), set(all_objs.global_data.keys()))

        flags = {
            obj_id: f
            for obj_id, (_, f) in _parse_with_flags(
                tmp_path / "labels" / "en.gz"
            ).items()
        }
        assert flags == {
            "naif-301": "",
            "naif-557": "",
            "naif-65289": "m",
            "naif-55533": "m",
        }
