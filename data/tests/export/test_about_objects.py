"""Checks for the objects table of `/about/data`: the kinds, the split of each
file's bytes, the text counts and the sources, with the served extrasolar
census."""

import gzip
import struct

import orjson
import pytest

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.about_objects import (
    catalogue_kind,
    entry_sources,
    has_own_text,
    kind_of,
    object_rows,
    position_file_bytes,
)
from space_map_data.export.objects.writer import write_object_bundles
from space_map_data.export.position.elements.writer import write_elements
from space_map_data.export.position.format import (
    ID_TYPE_ORDINAL,
    OBJECT_TYPE_ORDINAL,
    align8,
    pack_body_header,
    pack_chebyshev_header,
    pack_elements_header,
    pack_probes_header,
)
from space_map_data.extrasolar import ids
from space_map_data.models.object import ObjectType, OrbitalSource
from tests.conftest import make_object


def _gzip(path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(data))


def _satcat_elements(types: list[ObjectType]) -> bytes:
    """The header, id and type columns of an elements file of NORAD rows."""
    n = len(types)
    return (
        pack_elements_header(n, id_type_ordinal=ID_TYPE_ORDINAL[ID_TYPES.NORAD_SATCAT])
        + bytes(align8(4 * n))
        + bytes(OBJECT_TYPE_ORDINAL[t] for t in types)
    )


def _chebyshev(bodies: list[tuple[ObjectType, int]]) -> bytes:
    """A chebyshev file of NAIF bodies, given as (type, segment count), with
    two coefficients per axis."""
    buf = pack_chebyshev_header(0.0, 1.0, len(bodies))
    for object_type, segments in bodies:
        buf += pack_body_header(
            naif_id=1,
            parent_id=0,
            obj_id_value=1,
            radius_km=1.0,
            coeffs_per_axis=2,
            id_type_ordinal=ID_TYPE_ORDINAL[ID_TYPES.NAIF],
            has_localized=False,
            object_type_ordinal=OBJECT_TYPE_ORDINAL[object_type],
            segment_count=segments,
        )
        buf += (struct.pack("<dd", 0.0, 1.0) + bytes(3 * 2 * 4)) * segments
    return buf


class TestKindOf:
    @pytest.mark.parametrize(
        "object_type",
        ["asteroid", "asteroid_inner", "asteroid_main_belt", "asteroid_tno"],
    )
    def test_asteroid_zones_share_one_row(self, object_type):
        assert kind_of(object_type, False) == "asteroid"

    def test_spacecraft_split_by_id(self):
        assert kind_of("spacecraft", True) == "satellite"
        assert kind_of("spacecraft", False) == "probe"

    def test_other_types_keep_their_name(self):
        assert kind_of("moon", False) == "moon"
        assert kind_of("debris", True) == "debris"


# A star, a resolved star system and a planet of the star.
STAR_ID = ids.encode(0, 1, 5)
SYSTEM_ID = ids.encode(0, 3, 5)
PLANET_ID = f"x-{STAR_ID}-b-1"


class TestCatalogueKind:
    def test_by_home_table(self):
        assert catalogue_kind(f"x-{STAR_ID}") == "star"
        assert catalogue_kind(f"x-{SYSTEM_ID}") == "star_system"
        assert catalogue_kind(PLANET_ID) == "planet"

    def test_solar_system(self):
        assert catalogue_kind("naif-10") is None


class TestHasOwnText:
    def test_description_or_article(self):
        assert has_own_text({"description": "asteroïde"})
        assert has_own_text({"wikipedia": {"url": "https://fr.wikipedia.org/"}})

    def test_names_and_linked_items_do_not_count(self):
        assert not has_own_text({"name": "Cérès", "instance_of": [{"name": "x"}]})


class TestEntrySources:
    def test_asteroid(self):
        works: set[str] = set()
        keys = entry_sources(
            {
                "ephemeris_source": "sbdb",
                "cross_refs": {"wikidata_qid": "Q1", "mpc_designation": "1"},
                "sbdb": {"color": {"r": 1}},
                "orientation": {"source": "lightcurve"},
                "radii": {"a": 1},
                "radii_source": "occultation",
                "radii_reference": {"title": "Paper", "url": "https://doi.org/x"},
                "interior": {"taxonomy_sources": ["mahlke"]},
                "radiation": {"sources": [{"title": "SIDC", "url": "https://sidc"}]},
            },
            works,
        )
        assert keys == {
            "sbdb",
            "wikidata",
            "mpc",
            "truecolortools",
            "damit",
            "taxonomy:mahlke",
        }
        assert works == {"https://doi.org/x", "https://sidc"}

    def test_satellite(self):
        keys = entry_sources(
            {"ephemeris_source": "spacetrack", "celestrak": {}, "images": [{}]}, set()
        )
        assert keys == {"spacetrack", "celestrak", "jonathan", "commons"}

    def test_pole_and_radii_from_the_kernels(self):
        keys = entry_sources({"orientation": {"source": "pck"}, "radii": {}}, set())
        assert keys == {"pck"}


class TestPositionFileBytes:
    def test_elements_split_by_rows(self, tmp_path):
        path = tmp_path / "0.bin.gz"
        objects = [
            make_object(id="naif-599", naif_id=599, object_type=ObjectType.planet),
            *(
                make_object(
                    id=f"naif-50{n}", naif_id=500 + n, object_type=ObjectType.moon
                )
                for n in range(1, 4)
            ),
        ]
        write_elements(objects, path, OrbitalSource.spice, has_localized={})
        size = path.stat().st_size
        split = position_file_bytes(path)
        assert split["planet"] == pytest.approx(size / 4)
        assert split["moon"] == pytest.approx(3 * size / 4)

    def test_norad_rows(self, tmp_path):
        path = tmp_path / "0.bin.gz"
        types = [ObjectType.spacecraft, ObjectType.debris, ObjectType.debris]
        _gzip(path, _satcat_elements(types))
        split = position_file_bytes(path)
        assert set(split) == {"satellite", "debris"}
        assert split["debris"] == pytest.approx(2 * split["satellite"])

    def test_chebyshev_split_by_body_bytes(self, tmp_path):
        path = tmp_path / "0.bin.gz"
        _gzip(path, _chebyshev([(ObjectType.planet, 1), (ObjectType.moon, 3)]))
        size = path.stat().st_size
        split = position_file_bytes(path)
        segment = 16 + 3 * 2 * 4
        planet, moon = 32 + segment, 32 + 3 * segment
        assert split["planet"] == pytest.approx(size * planet / (planet + moon))
        assert split["moon"] == pytest.approx(size * moon / (planet + moon))

    def test_probes_file_is_all_probe(self, tmp_path):
        path = tmp_path / "0.bin.gz"
        _gzip(path, pack_probes_header(0.0, 1.0, 1, 1.0) + bytes(100))
        assert position_file_bytes(path) == {"probe": path.stat().st_size}


CENSUS: dict[str, dict] = {
    "star": {"count": 3, "size_bytes": 300, "sources": {"gaia-dr3": 3}},
    "star_system": {"count": 1, "size_bytes": 30, "sources": {"star-systems": 1}},
    "planet": {
        "count": 2,
        "size_bytes": 20,
        "sources": {"nasa-exoplanet-archive": 2},
    },
}


def _serve(extrasolar_dir) -> int:
    """A served `v1/x/` with the census. Its bytes."""
    served = extrasolar_dir / "v1" / "x"
    served.mkdir(parents=True)
    (served / "metadata.json").write_bytes(orjson.dumps({"objects": CENSUS}))
    return sum(entry["size_bytes"] for entry in CENSUS.values())


def _sources(row: dict) -> dict[str, int]:
    return {source["key"]: source["objects"] for source in row["sources"]}


def _export(out) -> None:
    """A small export tree with entries of the solar system and of the
    extrasolar catalogue."""
    saturn = {
        "id": "naif-699",
        "type": "planet",
        "ephemeris_source": "naif",
        "cross_refs": {"wikidata_qid": "Q193"},
        "has_rings": True,
        "ring_features": {
            "a-ring": {"name": "A Ring", "wikidata_qid": "Q1"},
            "b-ring": {"name": "B Ring"},
        },
        "ring_sources": [{"title": "PDS", "url": "https://pds-rings"}],
    }
    vega, pair = f"x-{STAR_ID}", f"x-{SYSTEM_ID}"
    global_data = {
        "naif-699": saturn,
        "spkid-1": {"id": "spkid-1", "type": "asteroid_main_belt"},
        "spkid-2": {"id": "spkid-2", "type": "asteroid_tno"},
        "norad_satcat-1": {"id": "norad_satcat-1", "type": "spacecraft"},
        "probe-1": {"id": "probe-1", "type": "spacecraft"},
        "naif-10": {"id": "naif-10", "type": "star"},
        vega: {
            "id": vega,
            "type": "star",
            "cross_refs": {"wikidata_qid": "Q9"},
            "images": [{}],
        },
        # Its class makes its entry a binary star, its home table a system.
        pair: {"id": pair, "type": "binary_star", "cross_refs": {"wikidata_qid": "Q7"}},
        PLANET_ID: {
            "id": PLANET_ID,
            "type": "exoplanet",
            "cross_refs": {"wikidata_qid": "Q8"},
        },
    }
    localized = {
        "en": {
            "spkid-1": {"name": "x", "description": "asteroid"},
            vega: {"wikipedia": {"url": "https://en.wikipedia.org/wiki/Vega"}},
        },
        "fr": {
            "spkid-2": {"name": "y", "instance_of": [{"name": "TNO"}]},
            "naif-699": {
                "wikipedia": {"url": "https://fr.wikipedia.org/wiki/Saturne"},
                "ring_features": {
                    "a-ring": {"name": "anneau A", "extract": "…"},
                    "b-ring": {"name": "anneau B"},
                },
            },
        },
    }
    write_object_bundles(out, global_data, localized)
    _gzip(
        out / "position" / "earth" / "0.bin.gz",
        _satcat_elements([ObjectType.spacecraft]),
    )
    nomenclature = out / "nomenclature"
    _gzip(nomenclature / "labels" / "en" / "naif-499.txt.gz", b"Olympus Mons\nGale")
    _gzip(nomenclature / "positions" / "naif-499.bin.gz", bytes(40))
    _gzip(
        nomenclature / "details" / "__global__" / "0.json.gz",
        orjson.dumps({"naif-499:1": {"wikidata_qid": "Q2", "images": [{}]}}),
    )
    _gzip(
        nomenclature / "details" / "de" / "0.json.gz",
        orjson.dumps({"naif-499:1": {"description": "Vulkan"}}),
    )


class TestObjectRows:
    """A small export tree and the census of the extrasolar export, read back
    row by row."""

    @pytest.fixture
    def rows(self, tmp_path) -> dict[str, dict]:
        out = tmp_path / "v1"
        _export(out)
        served = _serve(tmp_path / "space-map-extrasolar")
        self.total = served + sum(
            p.stat().st_size for p in out.rglob("*") if p.is_file()
        )
        return {
            row["id"]: row
            for row in object_rows(out, tmp_path / "space-map-extrasolar")
        }

    def test_rows_in_page_order(self, rows):
        assert list(rows) == [
            "star",
            "star_system",
            "planet",
            "asteroid",
            "ring_system",
            "surface_feature",
            "satellite",
            "probe",
        ]

    def test_counts(self, rows):
        assert rows["asteroid"]["count"] == 2
        # The Sun and the census; an entry is one of the census.
        assert rows["star"]["count"] == 4
        assert rows["star_system"]["count"] == 1
        assert rows["planet"]["count"] == 3
        assert rows["ring_system"]["count"] == 2
        assert rows["ring_system"]["systems"] == 1
        assert rows["surface_feature"]["count"] == 2

    def test_bytes_add_up_to_the_files(self, rows):
        assert sum(row["size_bytes"] for row in rows.values()) == pytest.approx(
            self.total, abs=len(rows)
        )
        assert rows["satellite"]["position_bytes"] > 0
        assert rows["ring_system"]["size_bytes"] > 0
        assert rows["star_system"]["size_bytes"] > 30

    def test_text_in_each_language(self, rows):
        asteroid = rows["asteroid"]["localized"]
        assert (asteroid["en"], asteroid["fr"], asteroid["any"]) == (1, 0, 1)
        assert rows["planet"]["localized"]["fr"] == 1
        assert rows["star"]["localized"]["en"] == 1
        assert rows["ring_system"]["localized"]["fr"] == 1
        assert rows["surface_feature"]["localized"]["de"] == 1

    def test_sources(self, rows):
        assert _sources(rows["star"]) == {
            "gaia-dr3": 3,
            "wikidata": 1,
            "commons": 1,
            "wikipedia": 1,
        }
        assert _sources(rows["star_system"]) == {"star-systems": 1, "wikidata": 1}
        assert _sources(rows["planet"]) == {
            "nasa-exoplanet-archive": 2,
            "naif": 1,
            "wikidata": 2,
            "wikipedia": 1,
        }
        rings = _sources(rows["ring_system"])
        assert rings == {"wikidata": 1, "wikipedia": 1}
        assert rows["ring_system"]["works"] == 1
        features = _sources(rows["surface_feature"])
        assert features == {"iau-naming": 2, "wikidata": 1, "commons": 1}


class TestNoCensus:
    def test_the_entries_stand_for_their_kinds(self, tmp_path, caplog):
        out = tmp_path / "v1"
        _export(out)
        rows = {
            row["id"]: row
            for row in object_rows(out, tmp_path / "space-map-extrasolar")
        }
        counts = {
            kind: rows[kind]["count"] for kind in ("star", "star_system", "planet")
        }
        assert counts == {"star": 2, "star_system": 1, "planet": 2}
        assert "nothing served" in caplog.text

    def test_an_export_without_a_census_refuses(self, tmp_path):
        served = tmp_path / "space-map-extrasolar" / "v1" / "x"
        served.mkdir(parents=True)
        (served / "metadata.json").write_bytes(orjson.dumps({"format": 1}))
        with pytest.raises(ValueError, match="no census"):
            object_rows(tmp_path / "v1", tmp_path / "space-map-extrasolar")
