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
        # Promoted by type, through its host
        all_objs.global_data["naif-301"] = {"type": ObjectType.moon, "name": "Moon"}
        # Promoted via curated extras list
        all_objs.global_data["probe-49065984"] = {
            "type": ObjectType.spacecraft,
            "name": "Voyager 1",
        }
        # Random non-promoted asteroid — should not appear
        all_objs.global_data["spkid-20012345"] = {
            "type": ObjectType.asteroid,
            "name": "Random",
        }

        write_global_labels(
            tmp_path,
            all_objs,
            set(),
            set(),
            set(all_objs.global_data.keys()),
            {"naif-301": "naif-399"},
        )

        names = _parse(tmp_path / "labels" / "en.gz")
        assert set(names) == {"naif-399", "naif-301", "probe-49065984"}

    def test_emits_one_file_per_language(self, tmp_path):
        all_objs = ChunkObjectData()
        all_objs.global_data["naif-399"] = {"type": ObjectType.planet, "name": "Earth"}

        write_global_labels(
            tmp_path, all_objs, set(), set(), set(all_objs.global_data.keys()), {}
        )

        for lang in LANGUAGES:
            assert (tmp_path / "labels" / f"{lang}.gz").exists()

    def test_localized_name_takes_precedence_over_global(self, tmp_path):
        all_objs = ChunkObjectData()
        all_objs.global_data["naif-399"] = {"type": ObjectType.planet, "name": "Earth"}
        all_objs.localized_data["fr"]["naif-399"] = {"name": "Terre"}

        write_global_labels(
            tmp_path, all_objs, set(), set(), set(all_objs.global_data.keys()), {}
        )

        assert _parse(tmp_path / "labels" / "fr.gz")["naif-399"] == "Terre"
        # No localized override for English → fall through to global obj.name
        assert _parse(tmp_path / "labels" / "en.gz")["naif-399"] == "Earth"

    def test_chebyshev_covered_bodies_are_auto_promoted(self, tmp_path):
        """DE441 perturber asteroids aren't in PROMOTED_EXTRA_IDS but render as
        individual meshes, so they need labels too."""
        all_objs = ChunkObjectData()
        all_objs.global_data["spkid-20000052"] = {
            "type": ObjectType.asteroid_main_belt,
            "name": "52 Europa",
        }

        write_global_labels(
            tmp_path,
            all_objs,
            {"spkid-20000052"},
            set(),
            set(all_objs.global_data.keys()),
            {},
        )

        assert _parse(tmp_path / "labels" / "en.gz") == {"spkid-20000052": "52 Europa"}

    def test_minor_flag_only_set_for_designation_only_moons(self, tmp_path):
        """Only moons with no IAU name get ``m``, in every language. The page
        of an unnamed moon has its designation as its name."""
        all_objs = ChunkObjectData()
        all_objs.global_data["naif-399"] = {"type": ObjectType.planet, "name": "Earth"}
        all_objs.global_data["naif-599"] = {
            "type": ObjectType.planet,
            "name": "Jupiter",
        }
        all_objs.global_data["naif-699"] = {"type": ObjectType.planet, "name": "Saturn"}
        # Moon with DB name → not minor, even though designation exists
        all_objs.global_data["naif-301"] = {
            "type": ObjectType.moon,
            "name": "Moon",
            "provisional_designation": "S0001",
        }
        # Moon named after its designation was given → not minor
        all_objs.global_data["naif-557"] = {
            "type": ObjectType.moon,
            "name": "Eirene",
            "provisional_designation": "S2003J5",
        }
        # Designation-only moon, its name in the IAU form → minor
        all_objs.global_data["naif-65289"] = {
            "type": ObjectType.moon,
            "name": "S/2020 S 48",
            "provisional_designation": "S2020 S48",
        }
        all_objs.localized_data["ja"]["naif-65289"] = {"name": "S/2020 S 48"}
        # Name filled from the designation by SPICE bodc2n — still designation-only, flag it too.
        all_objs.global_data["naif-55533"] = {
            "type": ObjectType.moon,
            "name": "S2010 J5",
            "provisional_designation": "S2010 J5",
        }

        write_global_labels(
            tmp_path,
            all_objs,
            set(),
            set(),
            set(all_objs.global_data.keys()),
            {
                "naif-301": "naif-399",
                "naif-557": "naif-599",
                "naif-65289": "naif-699",
                "naif-55533": "naif-599",
            },
        )

        moons = {"naif-301", "naif-557", "naif-65289", "naif-55533"}
        for lang in ("en", "ja"):
            flags = {
                obj_id: f
                for obj_id, (_, f) in _parse_with_flags(
                    tmp_path / "labels" / f"{lang}.gz"
                ).items()
                if obj_id in moons
            }
            assert flags == {
                "naif-301": "",
                "naif-557": "",
                "naif-65289": "m",
                "naif-55533": "m",
            }
        assert _parse(tmp_path / "labels" / "ja.gz")["naif-65289"] == "S/2020 S 48"

    def test_an_object_named_only_by_its_id_has_no_label(self, tmp_path):
        """A moon with no name and no designation is promoted with its host,
        but its id is no name to show."""
        all_objs = ChunkObjectData()
        all_objs.global_data["naif-599"] = {
            "type": ObjectType.planet,
            "name": "Jupiter",
        }
        all_objs.global_data["naif-55524"] = {
            "type": ObjectType.moon,
            "name": "naif-55524",
        }

        write_global_labels(
            tmp_path,
            all_objs,
            set(),
            set(),
            set(all_objs.global_data.keys()),
            {"naif-55524": "naif-599"},
        )

        for lang in ("en", "ja"):
            labels = _parse(tmp_path / "labels" / f"{lang}.gz")
            assert labels["naif-55524"] == ""

    def test_moon_is_promoted_only_where_its_host_is(self, tmp_path):
        """A small-body satellite sits at its host's heliocentric position, so
        one whose host is just a point in a cloud would read as a stray body in
        the belt. 87 Sylvia is a curated extra; 22 Kalliope is not."""
        all_objs = ChunkObjectData()
        all_objs.global_data["spkid-20000087"] = {
            "type": ObjectType.asteroid_main_belt,
            "name": "87 Sylvia",
        }
        all_objs.global_data["spkid-120000087"] = {
            "type": ObjectType.moon,
            "name": "Romulus",
        }
        all_objs.global_data["spkid-20000022"] = {
            "type": ObjectType.asteroid_main_belt,
            "name": "22 Kalliope",
        }
        all_objs.global_data["spkid-120000022"] = {
            "type": ObjectType.moon,
            "name": "Linus",
        }

        write_global_labels(
            tmp_path,
            all_objs,
            set(),
            set(),
            set(all_objs.global_data.keys()),
            {
                "spkid-120000087": "spkid-20000087",
                "spkid-120000022": "spkid-20000022",
            },
        )

        assert set(_parse(tmp_path / "labels" / "en.gz")) == {
            "spkid-20000087",
            "spkid-120000087",
        }

    def test_moon_of_a_dwarf_planet_is_promoted(self, tmp_path):
        """Dwarf planets are promoted by type, so their satellites ride along —
        Dysnomia belongs on the map even though it is a TNO moon."""
        all_objs = ChunkObjectData()
        all_objs.global_data["spkid-20136199"] = {
            "type": ObjectType.dwarf_planet,
            "name": "136199 Eris",
        }
        all_objs.global_data["spkid-120136199"] = {
            "type": ObjectType.moon,
            "name": "Dysnomia",
        }

        write_global_labels(
            tmp_path,
            all_objs,
            set(),
            set(),
            set(all_objs.global_data.keys()),
            {"spkid-120136199": "spkid-20136199"},
        )

        assert "spkid-120136199" in _parse(tmp_path / "labels" / "en.gz")

    def test_curated_moon_overrides_an_unpromoted_host(self, tmp_path):
        """PROMOTED_EXTRA_IDS is the escape hatch for a satellite worth showing
        without its host. Typed as a moon here to exercise that branch order —
        no curated entry is a moon today."""
        all_objs = ChunkObjectData()
        all_objs.global_data["spkid-20000617"] = {
            "type": ObjectType.moon,
            "name": "617 Patroclus",
        }

        write_global_labels(
            tmp_path,
            all_objs,
            set(),
            set(),
            set(all_objs.global_data.keys()),
            {"spkid-20000617": "spkid-99999999"},
        )

        assert "spkid-20000617" in _parse(tmp_path / "labels" / "en.gz")

    def test_all_probes_are_promoted_with_minor_flag_outside_extras(self, tmp_path):
        """Every probe ships in labels for the high-accuracy render system.
        Curated extras label normally; the rest get the ``m`` flag for
        collapsed-halo rendering."""
        all_objs = ChunkObjectData()
        # Curated extra — Voyager 1 is in PROMOTED_EXTRA_IDS
        all_objs.global_data["probe-49065984"] = {
            "type": ObjectType.spacecraft,
            "name": "VOYAGER 1 (-31)",
        }
        # Non-curated probe — still ships, marked minor for the collapsed-halo default
        all_objs.global_data["probe-99999999"] = {
            "type": ObjectType.spacecraft,
            "name": "GENERIC (-99)",
        }
        probe_ids = {"probe-49065984", "probe-99999999"}

        write_global_labels(
            tmp_path,
            all_objs,
            set(),
            probe_ids,
            set(all_objs.global_data.keys()),
            {},
        )

        assert _parse_with_flags(tmp_path / "labels" / "en.gz") == {
            "probe-49065984": ("VOYAGER 1 (-31)", ""),
            "probe-99999999": ("GENERIC (-99)", "m"),
        }

    def test_promoted_set_leaves_the_other_entries_compact(self, tmp_path):
        """The type check runs on all 1.6 M entries. A decoded dict kept for
        each of them would hold gigabytes."""
        all_objs = ChunkObjectData()
        all_objs.global_data["naif-399"] = {"type": ObjectType.planet, "name": "Earth"}
        all_objs.global_data["spkid-20012345"] = {
            "type": ObjectType.asteroid,
            "name": "Random",
        }

        write_global_labels(
            tmp_path,
            all_objs,
            set(),
            set(),
            set(all_objs.global_data.keys()),
            {},
        )

        assert isinstance(all_objs.global_data._data["spkid-20012345"], bytes)
