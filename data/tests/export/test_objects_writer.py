"""Tests for space_map_data.export.objects.writer."""

import gzip
import math
from typing import ClassVar
from unittest.mock import MagicMock

import orjson
import pytest

from space_map_data.export.names import Names
from space_map_data.export.objects import writer
from space_map_data.export.objects.body_mass import BodyMass, BodyMasses, Satellite
from space_map_data.export.objects.body_radius import (
    BodyRadii,
    BodyRadius,
    kernel_shapes,
)
from space_map_data.export.objects.compact import CompactMap
from space_map_data.export.objects.pick import pick_attrs
from space_map_data.export.objects.writer import (
    K_GLOBAL,
    K_LOCALIZED,
    _build_localized,
    _iso_currency_code,
    build_model_sources,
    hash_bucket,
    render_quality,
    write_object_bundles,
)
from space_map_data.ingest.providers.objects.sbdb import mass_kg_from_gm
from space_map_data.models.object import ModelProvenance, ObjectType
from tests.conftest import EntityStub, make_object
from tests.export.conftest import layers_of


def _entity_snak(qid: str) -> dict:
    return {
        "snaktype": "value",
        "datavalue": {
            "value": {"entity-type": "item", "numeric-id": int(qid[1:]), "id": qid},
            "type": "wikibase-entityid",
        },
    }


def _string_snak(val: str) -> dict:
    return {"snaktype": "value", "datavalue": {"value": val, "type": "string"}}


def _stmt(snak: dict, *, rank: str = "normal") -> dict:
    return {"mainsnak": snak, "type": "statement", "rank": rank}


def _currency_entity(iso_code: str) -> dict:
    """Build a minimal Wikidata entity that looks like a currency."""
    return {
        "labels": {"en": iso_code},
        "claims": {
            "P31": [_stmt(_entity_snak("Q8142"))],
            "P498": [_stmt(_string_snak(iso_code))],
        },
        "sitelinks": {},
    }


class TestIsoCurrencyCode:
    """Tests for _iso_currency_code helper."""

    def test_returns_iso_code_for_currency(self):
        cache = MagicMock()
        cache.get_referenced.return_value = _currency_entity("EUR")
        assert _iso_currency_code("Q4916", cache) == "EUR"

    def test_returns_none_for_non_currency(self):
        cache = MagicMock()
        cache.get_referenced.return_value = {
            "labels": {"en": "kilometre"},
            "claims": {
                "P31": [_stmt(_entity_snak("Q3647172"))],
            },
            "sitelinks": {},
        }
        assert _iso_currency_code("Q828224", cache) is None

    def test_returns_none_for_unknown_qid(self):
        cache = MagicMock()
        cache.get_referenced.return_value = None
        assert _iso_currency_code("Q999999", cache) is None


class TestPickAttrs:
    def test_extracts_present(self):
        obj = make_object(name="Earth", wikidata_qid="Q2", spkid=None)
        result = pick_attrs(obj, ("name", "wikidata_qid", "spkid"))
        assert result == {"name": "Earth", "wikidata_qid": "Q2"}

    def test_all_none(self):
        obj = make_object(
            wikidata_qid=None,
            spkid=None,
            norad_cat_id=None,
        )
        result = pick_attrs(obj, ("wikidata_qid", "spkid", "norad_cat_id"))
        assert result == {}

    def test_all_present(self):
        obj = make_object(name="Earth", wikidata_qid="Q2", naif_id=399)
        result = pick_attrs(obj, ("name", "wikidata_qid", "naif_id"))
        assert result == {
            "name": "Earth",
            "wikidata_qid": "Q2",
            "naif_id": 399,
        }

    def test_works_on_plain_object(self):
        """pick_attrs is generic — works on any object with attributes."""

        class Bag:
            x = 1
            y = None
            z = "hello"

        result = pick_attrs(Bag(), ("x", "y", "z"))
        assert result == {"x": 1, "z": "hello"}


class TestHashBucket:
    def test_is_deterministic(self):
        assert hash_bucket("spkid-54352560", 1000) == hash_bucket(
            "spkid-54352560", 1000
        )

    def test_stays_in_range(self):
        for i in range(200):
            assert 0 <= hash_bucket(f"spkid-{i}", 17) < 17

    def test_different_ids_distribute(self):
        # Cheap sanity check — 50 distinct ids across 10 buckets should hit >= 7 buckets.
        buckets = {hash_bucket(f"spkid-{i}", 10) for i in range(50)}
        assert len(buckets) >= 7


class TestWriteObjectBundles:
    """write_object_bundles hash-buckets ids, writes one gzipped JSON per bucket."""

    def test_global_bundle_count_is_ceil_total_over_k(self, tmp_path):
        # Use K_GLOBAL * 2 + 1 entries so the count exercises ceil rounding.
        n_items = K_GLOBAL * 2 + 1
        global_data = {f"spkid-{i}": {"id": f"spkid-{i}"} for i in range(n_items)}
        ns = write_object_bundles(tmp_path, global_data, {})
        assert ns["global"] == math.ceil(n_items / K_GLOBAL)
        out_dir = tmp_path / "objects" / "__global__"
        files = sorted(out_dir.iterdir())
        assert len(files) == ns["global"]
        # Each file decompresses to a dict keyed by object id; union covers all inputs.
        seen: set[str] = set()
        for f in files:
            entries = orjson.loads(gzip.decompress(f.read_bytes()))
            seen.update(entries)
            # Every entry must hash into its file's bucket.
            bucket = int(f.name.split(".", 1)[0])
            for obj_id in entries:
                assert hash_bucket(obj_id, ns["global"]) == bucket
        assert seen == set(global_data)

    def test_localized_n_is_per_language(self, tmp_path):
        # en has 2*K+1 entries → ceil = 3. fr has 50 → ceil = 1.
        n_en = K_LOCALIZED * 2 + 1
        localized = {
            "en": {f"spkid-{i}": {"name": f"n{i}"} for i in range(n_en)},
            "fr": {f"spkid-{i}": {"name": f"f{i}"} for i in range(50)},
        }
        ns = write_object_bundles(tmp_path, {}, localized)
        assert ns["en"] == math.ceil(n_en / K_LOCALIZED)
        assert ns["fr"] == 1
        assert (tmp_path / "objects" / "en").exists()
        assert (tmp_path / "objects" / "fr").exists()

    def test_bucket_file_is_its_entries_in_insertion_order(self, tmp_path):
        compact = CompactMap()
        for i in range(K_GLOBAL * 3):
            compact[f"spkid-{i}"] = {"id": f"spkid-{i}", "n": i}
        # A decoded entry goes out with its change.
        compact["spkid-7"]["coverage"] = {"windows": [[1.5, None]]}
        ns = write_object_bundles(tmp_path, compact, {})
        out_dir = tmp_path / "objects" / "__global__"
        assert sorted(f.name for f in out_dir.iterdir()) == sorted(
            f"{bucket}.json.gz" for bucket in range(ns["global"])
        )
        for bucket in range(ns["global"]):
            expected = {
                obj_id: entry
                for obj_id, entry in compact.items()
                if hash_bucket(obj_id, ns["global"]) == bucket
            }
            assert (out_dir / f"{bucket}.json.gz").read_bytes() == gzip.compress(
                orjson.dumps(expected)
            )

    def test_empty_language_yields_zero_and_no_directory(self, tmp_path):
        ns = write_object_bundles(tmp_path, {}, {"ja": {}, "ru": {}})
        assert ns["global"] == 0
        assert ns["ja"] == 0
        assert ns["ru"] == 0
        assert not (tmp_path / "objects" / "ja").exists()
        assert not (tmp_path / "objects" / "ru").exists()


class TestRenderQuality:
    """Tier resolution for the exported `render_quality` field."""

    def test_spacecraft_model_is_high(self):
        obj = make_object(
            id="probe-1",
            object_type=ObjectType.spacecraft,
            model_name="cassini",
            model_provenance=ModelProvenance.spacecraft,
        )
        assert render_quality(obj, None) == "high"

    def test_shape_model_is_high(self):
        obj = make_object(
            id="spkid-2000433",
            object_type=ObjectType.asteroid,
            model_name="eros-near",
            model_provenance=ModelProvenance.missions,
        )
        assert render_quality(obj, None) == "high"

    def test_texture_only_is_high(self):
        obj = make_object(map_texture_available=True)
        assert render_quality(obj, None) == "high"

    def test_lightcurve_model_is_medium_despite_diameter(self):
        obj = make_object(
            id="spkid-2000021",
            object_type=ObjectType.asteroid,
            spkid=2000021,
            model_name="damit-104",
            model_provenance=ModelProvenance.lightcurve,
        )
        size = BodyRadius(49.0, 49.0, 49.0, "sbdb")
        assert render_quality(obj, size) == "medium"

    def test_texture_outranks_lightcurve_model(self):
        obj = make_object(
            model_name="damit-104",
            model_provenance=ModelProvenance.lightcurve,
            map_texture_available=True,
        )
        assert render_quality(obj, None) == "high"

    def test_star_is_high_without_texture(self):
        obj = make_object(id="naif-10", object_type=ObjectType.star, naif_id=10)
        size = BodyRadius(695700.0, 695700.0, 695700.0, "pck")
        assert render_quality(obj, size) == "high"

    def test_pck_radii_only_is_low(self):
        obj = make_object(id="naif-901", object_type=ObjectType.moon, naif_id=901)
        size = BodyRadius(606.0, 606.0, 606.0, "pck")
        assert render_quality(obj, size) == "low"

    def test_sbdb_diameter_only_is_low(self):
        obj = make_object(
            id="spkid-2000433", object_type=ObjectType.asteroid, spkid=2000433
        )
        size = BodyRadius(8.4, 8.4, 8.4, "sbdb")
        assert render_quality(obj, size) == "low"

    def test_a_catalogue_size_is_low(self):
        """Weywot: only AsterSat sizes it."""
        obj = make_object(id="spkid-120050000", object_type=ObjectType.moon)
        size = BodyRadius(40.5, 40.5, 40.5, "astersat")
        assert render_quality(obj, size) == "low"

    def test_no_size_signal_is_none(self):
        obj = make_object(id="probe-2", object_type=ObjectType.spacecraft)
        assert render_quality(obj, None) is None


class TestBuildModelSources:
    """Compact per-slug provenance block behind the detail drawer's model line."""

    def test_damit_technique_rides_along(self):
        out = build_model_sources(
            {
                "damit-5915": {
                    "kind": "shape_model",
                    "provenance": "lightcurve",
                    "technique": "lightcurve_resolved",
                    "archive": "DAMIT",
                    "archive_url": "https://damit.cuni.cz/…/3414",
                }
            },
            {},
        )
        assert out["damit-5915"] == {
            "provenance": "lightcurve",
            "technique": "lightcurve_resolved",
            "archive": "DAMIT",
            "archive_url": "https://damit.cuni.cz/…/3414",
        }

    def test_author_rides_along_when_it_isnt_the_archive(self):
        out = build_model_sources(
            {
                "damit-5915": {
                    "kind": "shape_model",
                    "provenance": "lightcurve",
                    "archive": "DAMIT (Database of Asteroid Models from Inversion Techniques)",
                    "credit": {"name": "Vernazza et al. (2021)"},
                }
            },
            {},
        )
        assert out["damit-5915"]["author"] == "Vernazza et al. (2021)"

    def test_author_omitted_when_it_repeats_the_archive(self):
        out = build_model_sources(
            {
                "eros": {
                    "kind": "shape_model",
                    "provenance": "missions",
                    "archive": "PDS SBN (NEAR, Gaskell)",
                    "credit": {"name": "PDS SBN (NEAR, Gaskell)"},
                }
            },
            {},
        )
        assert "author" not in out["eros"]

    def test_technique_absent_on_mission_shapes(self):
        out = build_model_sources(
            {"eros": {"kind": "shape_model", "provenance": "missions"}}, {}
        )
        assert out["eros"] == {"provenance": "missions"}

    def test_spacecraft_bundles_are_excluded(self):
        out = build_model_sources({"cassini": {"provenance": "spacecraft"}}, {})
        assert out == {}

    def test_the_observing_craft_has_the_name_of_its_page(self):
        out = build_model_sources(
            {"eros": {"kind": "shape_model", "provenance": "missions", "probe_id": 7}},
            {7: Names("NEAR Shoemaker", {"ja": "ニア・シューメーカー"})},
        )
        assert out["eros"]["mission"] == {
            "name": "NEAR Shoemaker",
            "primary_type": "object",
            "primary_id": "probe-7",
        }


class TestLinkNames:
    """A page names its host and the pages it links to in each language."""

    def _localized(self, lang: str) -> dict:
        obj = make_object(
            id="naif-653", object_type=ObjectType.moon, parent_id="naif-6"
        )
        return _build_localized(
            obj,
            Names("Aegaeon"),
            Names("Saturn", {"ja": "土星"}),
            {
                "probe-1": Names("Cassini", {"ja": "カッシーニ"}),
                "naif-618": Names("Pan"),
            },
            lang,
            EntityStub(),
            None,
            {},
            None,
        )

    def test_a_language_with_its_own_names_gets_them(self):
        localized = self._localized("ja")
        assert localized["parent_name"] == "土星"
        assert localized["link_names"] == {"probe-1": "カッシーニ"}

    def test_a_language_with_none_gets_nothing(self):
        assert self._localized("fr") == {}


class TestBundleRadius:
    """The bundle sizes a body from `body_radius`, never from a Wikidata claim."""

    _WIKIDATA_RADIUS: ClassVar[dict] = {"radius": {"value": 100.0, "unit": "kilometre"}}

    @pytest.fixture(autouse=True)
    def _no_images(self, monkeypatch):
        monkeypatch.setattr(writer, "collect_object_images", lambda object_id: None)
        monkeypatch.setattr(writer, "panoramas_block", lambda object_id: None)

    @staticmethod
    def _weywot():
        return make_object(
            id="spkid-120050000",
            name="Weywot",
            naif_id=None,
            wikidata_qid="Q83894",
            object_type=ObjectType.moon,
        )

    def test_a_catalogue_size_beats_the_wikidata_radius(self):
        radii = BodyRadii(
            sizes={"spkid-120050000": BodyRadius(40.5, 40.5, 40.5, "astersat")},
            wikidata_km=lambda qid: 100.0,
        )
        data = TestPlanetFamilies._global(
            self._weywot(), {}, body_radii=radii, extracted=self._WIKIDATA_RADIUS
        )
        assert data["radii"] == {"a": 40.5, "b": 40.5, "c": 40.5}
        assert data["radii_source"] == "astersat"
        assert "radius" not in data.get("wikidata", {})

    def test_the_wikidata_radius_rides_in_radii(self):
        radii = BodyRadii(wikidata_km=lambda qid: 100.0)
        data = TestPlanetFamilies._global(
            self._weywot(), {}, body_radii=radii, extracted=self._WIKIDATA_RADIUS
        )
        assert data["radii"] == {"a": 100.0, "b": 100.0, "c": 100.0}
        assert data["radii_source"] == "wikidata"
        assert "radius" not in data.get("wikidata", {})

    def test_a_measured_shape_cites_the_work_that_fitted_it(self):
        # Bienor's pole is a 2017 paper, its ellipsoid a 2024 one: the size
        # rows credit the second.
        bienor = make_object(
            id="spkid-20054598", naif_id=2054598, object_type=ObjectType.asteroid
        )
        radii = BodyRadii(kernel_shapes({2054598: {"a": 1.0, "b": 1.0, "c": 1.0}}))
        data = TestPlanetFamilies._global(bienor, {}, body_radii=radii)
        assert data["radii_source"] == "occultation"
        assert data["radii_reference"]["url"].endswith("202450833")

    def test_a_body_with_no_size_has_no_radii(self):
        data = TestPlanetFamilies._global(self._weywot(), {})
        assert "radii" not in data


class TestBundleMass:
    """The bundle writes the `body_mass` pick and the density of it."""

    _WIKIDATA_MASS: ClassVar[dict] = {
        "mass": {"value": 3.0, "unit": "kilogram"},
        "density": {"value": 1.0, "unit": "gram per cubic centimetre"},
    }

    @pytest.fixture(autouse=True)
    def _no_images(self, monkeypatch):
        monkeypatch.setattr(writer, "collect_object_images", lambda object_id: None)
        monkeypatch.setattr(writer, "panoramas_block", lambda object_id: None)

    @staticmethod
    def _kerberos():
        return make_object(
            id="naif-904", name="Kerberos", naif_id=904, object_type=ObjectType.moon
        )

    @staticmethod
    def _global(obj, mass: BodyMass | None, size: BodyRadius | None) -> dict:
        radii = BodyRadii(shapes={904: size} if size else {})
        masses = BodyMasses(jpl={904: mass} if mass else {})
        return TestPlanetFamilies._global(
            obj,
            {},
            body_radii=radii,
            body_masses=masses,
            extracted=TestBundleMass._WIKIDATA_MASS,
        )

    def test_mass_and_density(self):
        # A 10 km sphere of 4.18879e18 g is 1 g/cm³.
        data = self._global(
            self._kerberos(),
            BodyMass(4.18879e15, "jpl_satellite_physical", False, "PLU060"),
            BodyRadius(10.0, 10.0, 10.0, "literature"),
        )
        assert data["mass_kg"] == 4.18879e15
        assert data["mass_source"] == "jpl_satellite_physical"
        assert data["mass_reference"] == "PLU060"
        assert "mass_nominal" not in data
        assert data["mean_density_g_cm3"] == 1.0
        assert "mean_density_nominal" not in data

    def test_a_nominal_mass_makes_the_density_nominal(self):
        data = self._global(
            self._kerberos(),
            BodyMass(4.18879e15, "jpl_satellite_physical", True, "PLU060"),
            BodyRadius(10.0, 10.0, 10.0, "literature"),
        )
        assert data["mass_nominal"] is True
        assert data["mean_density_nominal"] is True

    def test_a_body_keeps_the_wikidata_mass_and_density(self):
        """The deployed frontend reads them until it reads `mass_kg`."""
        data = self._global(self._kerberos(), None, None)
        assert {"mass", "density"} <= data["wikidata"].keys()
        assert "mass_kg" not in data
        assert "mean_density_g_cm3" not in data

    def test_a_system_mass_is_over_the_moons_too(self):
        """Two 10 km spheres share a 2 g/cm³ x one-sphere mass."""
        primary = make_object(
            id="spkid-20065803", naif_id=2065803, object_type=ObjectType.asteroid
        )
        sphere = BodyRadius(10.0, 10.0, 10.0, "pck")
        data = TestPlanetFamilies._global(
            primary,
            {},
            body_radii=BodyRadii(shapes={2065803: sphere, 120065803: sphere}),
            body_masses=BodyMasses(
                ephemeris={
                    2065803: BodyMass(
                        2 * 4.18879e15, "pck", False, "gm_de440.tpc", system=True
                    )
                },
                satellites={
                    "spkid-20065803": (
                        Satellite("spkid-120065803", 120065803, None, ObjectType.moon),
                    )
                },
            ),
        )
        assert data["mass_system"] is True
        assert data["mean_density_g_cm3"] == 1.0

    def test_a_craft_keeps_its_wikidata_mass(self):
        craft = make_object(
            id="probe-98", name="New Horizons", object_type=ObjectType.spacecraft
        )
        data = self._global(craft, None, None)
        assert "mass" in data["wikidata"]
        assert "mass_kg" not in data


class TestPlanetFamilies:
    """A Solar System planet's page carries its planet families."""

    @staticmethod
    def _global(
        obj,
        planet_families: dict[str, list[str]],
        body_radii: BodyRadii | None = None,
        extracted: dict | None = None,
        body_masses: BodyMasses | None = None,
    ) -> dict:
        entities = MagicMock()
        entities.get_entity.return_value = None
        entities.get_referenced.return_value = None
        names = (
            "nasa_science_urls",
            "orientation",
            "gms",
            "nut_prec",
            "model_sources",
            "probe_kernel_sources",
            "probe_ephemeris_accuracy",
            "probe_position_sources",
            "taxonomy",
            "ring_moons",
            "ring_metadata",
            "moon_sources",
        )
        empty: dict = {name: {} for name in names}
        return writer._build_global(
            obj,
            Names(obj.name),
            None,
            extracted or {},
            entities,
            MagicMock(),
            body_radii=body_radii or BodyRadii(),
            body_masses=body_masses or BodyMasses(),
            layers=layers_of(),
            nomenclature_body_ids=set(),
            planet_families=planet_families,
            **empty,
        )

    @pytest.fixture(autouse=True)
    def _no_images(self, monkeypatch):
        monkeypatch.setattr(writer, "collect_object_images", lambda object_id: None)
        monkeypatch.setattr(writer, "panoramas_block", lambda object_id: None)

    def test_a_planet(self):
        families = {"naif-399": ["terrestrial-planet", "goldilocks-planet"]}
        data = self._global(make_object(), families)
        assert data["planet_families"] == ["terrestrial-planet", "goldilocks-planet"]

    def test_another_body_has_none(self):
        moon = make_object(id="naif-301", name="Moon", object_type=ObjectType.moon)
        data = self._global(moon, {"naif-399": ["terrestrial-planet"]})
        assert "planet_families" not in data

    def test_a_moon_carries_whether_the_db_names_it(self):
        """The page name of a moon can be a Wikidata label, so search reads
        the DB's status here."""
        named = make_object(id="naif-301", name="Moon", object_type=ObjectType.moon)
        unnamed = make_object(
            id="naif-65194",
            name="S2019_S37",
            object_type=ObjectType.moon,
            provisional_designation="S2019_S37",
        )
        assert self._global(named, {})["iau_named"] is True
        assert self._global(unnamed, {})["iau_named"] is False
        assert "iau_named" not in self._global(make_object(), {})


class TestBundleDensity:
    """A body's density is its mass over the volume of its radii."""

    @pytest.fixture(autouse=True)
    def _no_images(self, monkeypatch):
        monkeypatch.setattr(writer, "collect_object_images", lambda object_id: None)
        monkeypatch.setattr(writer, "panoramas_block", lambda object_id: None)

    @staticmethod
    def _global(obj, gm: float, radii: tuple[float, float, float]) -> dict:
        return TestPlanetFamilies._global(
            obj,
            {},
            body_radii=BodyRadii(shapes={obj.naif_id: BodyRadius(*radii, "pck")}),
            body_masses=BodyMasses(
                ephemeris={
                    obj.naif_id: BodyMass(
                        mass_kg_from_gm(gm), "pck", False, "gm_de440.tpc"
                    )
                }
            ),
        )

    def test_earth(self):
        earth = make_object(id="naif-399", name="Earth", naif_id=399)
        data = self._global(earth, 398600.4355070226, (6378.1366, 6378.1366, 6356.7519))
        assert data["mean_density_g_cm3"] == 5.513

    def test_the_sun_keeps_its_density_and_luminosity(self):
        sun = make_object(
            id="naif-10", name="Sun", naif_id=10, object_type=ObjectType.star
        )
        data = self._global(sun, 132712440041.27939, (695_700.0, 695_700.0, 695_700.0))
        assert data["mean_density_g_cm3"] == 1.41
        assert data["luminosity_w"] == 3.828e26


def test_the_sun_luminosity_is_the_iau_nominal_value():
    assert writer.SUN_LUMINOSITY_W == 3.828e26
    assert writer.SUN_LUMINOSITY_REFERENCE["title"] == "IAU 2015 Resolution B3"
