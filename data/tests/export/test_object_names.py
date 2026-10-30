"""Tests for the naming rules of export.names."""

from dataclasses import replace

from sqlalchemy.orm import Session

from space_map_data.constants.object_names import NAME_ENTITIES
from space_map_data.export.names import (
    CataloguePlanet,
    Names,
    ObjectNames,
    PlanetHost,
    by_language,
    feature_aliases,
    feature_names,
    mission_names,
    object_names,
    page_aliases,
    planet_names,
    repeated_letters,
    served_host,
    star_names,
    system_names,
)
from space_map_data.export.objects.stars import (
    PlanetObject,
    StarObject,
    planet_object,
)
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object, ObjectType, OrbitalSource, Satcat
from tests.conftest import EntityStub, labelled, make_object

_CURIOSITY = "probe-100265984"


def _probe(**overrides) -> Object:
    return make_object(
        id=_CURIOSITY,
        name="Curiosity (MSL)",
        object_type=ObjectType.spacecraft,
        orbital_source=OrbitalSource.spice_probe,
        probe_id=100265984,
        wikidata_qid="Q48496",
        **overrides,
    )


class TestNames:
    """The name in a language, and the names that differ from the global one."""

    def test_a_language_without_its_own_name_takes_the_global_one(self):
        names = Names("Mars", {"fr": "Mars", "ja": "火星"})
        assert names.get("de") == "Mars"
        assert names.get("ja") == "火星"
        assert names.overrides() == {"ja": "火星"}

    def test_by_language_keeps_only_what_differs(self):
        named = {"naif-499": Names("Mars", {"ja": "火星"}), "naif-1": Names("X")}
        assert by_language(named) == {"ja": {"naif-499": "火星"}}


class TestMissionNames:
    """A mission page takes the labels of its item, else its primary craft."""

    def test_the_item_names_the_mission(self):
        item = labelled({"en": "Cassini–Huygens", "ja": "カッシーニ・ホイヘンス"})
        names = mission_names(item, Names("Cassini Orbiter"))
        assert (names.name, names.get("ja")) == (
            "Cassini–Huygens",
            "カッシーニ・ホイヘンス",
        )

    def test_a_mission_with_no_item_takes_its_primary_craft(self):
        primary = Names("Pioneer Venus Orbiter", {"ja": "パイオニア・ヴィーナス"})
        assert mission_names(None, primary) == primary


class TestObjectNames:
    """Catalogue objects: the Wikidata label first, else the catalogue name."""

    def test_the_wikidata_label_comes_first(self):
        obj = make_object(id="naif-499", name="MARS", wikidata_qid="Q111")
        entities = EntityStub({"Q111": labelled({"en": "Mars", "ja": "火星"})})
        names = object_names(obj, entities)
        assert names.name == "Mars"
        assert names.get("ja") == "火星"

    def test_the_catalogue_name_stands_in_for_a_missing_item(self):
        obj = make_object(id="spkid-1", name="433 Eros", wikidata_qid=None)
        assert object_names(obj, EntityStub()) == Names("433 Eros")

    def test_a_probe_takes_the_item_of_the_craft(self):
        entities = EntityStub(
            {
                "Q48496": labelled({"en": "Mars Science Laboratory"}),
                NAME_ENTITIES[_CURIOSITY]: labelled(
                    {"en": "Curiosity", "ja": "キュリオシティ"}
                ),
            }
        )
        names = object_names(_probe(), entities)
        assert names.name == "Curiosity"
        assert names.get("ja") == "キュリオシティ"

    def test_a_missing_craft_item_leaves_the_registered_one(self):
        entities = EntityStub({"Q48496": labelled({"en": "Mars Science Laboratory"})})
        assert object_names(_probe(), entities).name == "Mars Science Laboratory"

    def test_a_satellite_takes_the_item_of_its_satcat_row(self):
        obj = make_object(
            id="norad_satcat-25544",
            name="ISS (ZARYA)",
            object_type=ObjectType.spacecraft,
            orbital_source=OrbitalSource.spacetrack,
            norad_cat_id=25544,
            wikidata_qid=None,
        )
        obj.satcat = Satcat(NORAD_CAT_ID=25544, wikidata_qid="Q25271")
        entities = EntityStub(
            {"Q25271": labelled({"en": "International Space Station"})}
        )
        assert object_names(obj, entities).name == "International Space Station"

    def test_an_unnamed_moon_has_its_designation_in_the_iau_form(self):
        obj = make_object(
            id="naif-65194",
            name=None,
            object_type=ObjectType.moon,
            provisional_designation="S2019_S37",
        )
        assert object_names(obj, EntityStub()).name == "S/2019 S 37"

    def test_a_moon_named_by_its_designation_has_the_iau_form(self):
        obj = make_object(
            id="naif-551",
            name="S2010_J1",
            object_type=ObjectType.moon,
            provisional_designation="S2010_J1",
        )
        assert object_names(obj, EntityStub()).name == "S/2010 J 1"

    def test_an_object_with_no_name_goes_by_its_id(self):
        obj = make_object(id="naif-55524", name=None, object_type=ObjectType.moon)
        assert object_names(obj, EntityStub()).name == "naif-55524"

    def test_an_unnamed_moon_has_its_designation_in_every_language(self):
        obj = make_object(
            id="naif-20939101",
            name="S/2006 (939) 1",
            object_type=ObjectType.moon,
            provisional_designation="S/2006 (939) 1",
            wikidata_qid="Q1",
        )
        labels = {"en": "S/2007 (939) 1", "ja": "(939) イシドラの衛星"}
        names = object_names(obj, EntityStub({"Q1": labelled(labels)}))
        assert names == Names("S/2006 (939) 1")

    def test_a_named_moon_drops_a_label_that_is_a_designation(self):
        obj = make_object(
            id="naif-2000317001",
            name="Olympias",
            object_type=ObjectType.moon,
            provisional_designation="S/2009 (317) 1",
            wikidata_qid="Q1",
        )
        labels = {"en": "S/2009 (317) 1", "de": "Olympias", "ja": "オリンピアス"}
        names = object_names(obj, EntityStub({"Q1": labelled(labels)}))
        assert names.name == "Olympias"
        assert (names.get("fr"), names.get("ja")) == ("Olympias", "オリンピアス")

    def test_a_label_loses_its_disambiguator(self):
        obj = make_object(id="spkid-20136199", name="136199 Eris", wikidata_qid="Q1")
        labels = {"en": "Eris", "ja": "エリス (準惑星)", "zh": "阋神星（矮行星）"}
        names = object_names(obj, EntityStub({"Q1": labelled(labels)}))
        assert (names.get("ja"), names.get("zh")) == ("エリス", "阋神星")

    def test_a_label_that_is_a_page_title_loses_its_underscore(self):
        obj = make_object(id="norad_satcat-4221", name="Azur", wikidata_qid="Q1")
        labels = {"en": "Azur", "ar": "أزور_(قمر_اصطناعي)"}
        names = object_names(obj, EntityStub({"Q1": labelled(labels)}))
        assert names.get("ar") == "أزور"

    def test_a_comet_keeps_its_parentheses(self):
        obj = make_object(
            id="spkid-1002449",
            name="C/2007 E2",
            object_type=ObjectType.comet,
            wikidata_qid="Q1",
        )
        labels = {"en": "C/2007 E2", "ja": "ラヴジョイ彗星 (C/2007 E2)"}
        names = object_names(obj, EntityStub({"Q1": labelled(labels)}))
        assert names.get("ja") == "ラヴジョイ彗星 (C/2007 E2)"

    def test_a_global_name_with_parentheses_keeps_them_in_every_language(self):
        obj = make_object(id="spkid-20099677", name="X", wikidata_qid="Q1")
        labels = {"en": "(99677) 2002 JC15", "ja": "99677 (2002 JC15)"}
        names = object_names(obj, EntityStub({"Q1": labelled(labels)}))
        assert names.get("ja") == "99677 (2002 JC15)"

    def test_an_item_in_hand_is_not_read_again(self):
        obj = make_object(id="naif-499", name="MARS", wikidata_qid="Q111")
        item = labelled({"en": "Mars", "ja": "火星"})
        assert object_names(obj, EntityStub(), item).get("ja") == "火星"


class TestSystemNames:
    """A planetary system barycenter takes the name of its planet."""

    def test_a_system_is_named_after_its_planet(self):
        names = system_names("naif-599", Names("Jupiter", {"fr": "Jupiter"}))
        assert names.name == "Jupiter system"
        assert names.get("fr") == "Système de Jupiter"

    def test_the_earth_moon_system_has_its_own_title(self):
        names = system_names("naif-399", Names("Earth", {"fr": "Terre"}))
        assert names.name == "Earth–Moon system"
        assert names.get("fr") == "Système Terre–Lune"

    def test_a_lookup_names_a_barycenter_after_its_planet(self, session: Session):
        session.add_all(
            [
                Object(id="naif-599", name="Jupiter", object_type=ObjectType.planet),
                Object(
                    id="naif-5",
                    name="Jupiter Barycenter",
                    object_type=ObjectType.barycenter,
                ),
            ]
        )
        session.commit()
        names = ObjectNames(EntityStub(), session)
        assert names.object("naif-5").name == "Jupiter system"


def _feature(**overrides) -> Feature:
    defaults = {
        "feature_id": 1,
        "name": "Asvaghosa",
        "unicode_name": "Aśvaghoṣa",
        "target": "Mercury",
        "wikidata_qid": "Q1",
    }
    return Feature(**(defaults | overrides))


class TestFeatureNames:
    """The IAU name in the Latin alphabet, a label in another script."""

    def test_the_iau_spelling_comes_first(self):
        entities = EntityStub({"Q1": labelled({"en": "Asvaghosa"})})
        assert feature_names(_feature(), entities).name == "Aśvaghoṣa"

    def test_the_iau_name_comes_first_in_every_latin_language(self):
        labels = {"de": "Tycho (Mondkrater)", "fr": "Tycho", "it": "Tycho B"}
        entities = EntityStub({"Q1": labelled(labels)})
        names = feature_names(_feature(name="Tycho", unicode_name=None), entities)
        assert [names.get(lang) for lang in ("de", "fr", "it")] == ["Tycho"] * 3

    def test_a_label_that_the_iau_name_replaces_is_an_alias(self):
        labels = {"de": "Tycho (Mondkrater)", "fr": "tycho", "it": "Tycho B (cratere)"}
        entities = EntityStub({"Q1": labelled(labels)})
        names = feature_names(_feature(name="Tycho", unicode_name=None), entities)
        # Without its disambiguator, or in another case, it is the IAU name.
        assert names.aliases == {"it": ("Tycho B",)}

    def test_a_label_in_the_script_of_the_language_comes_first(self):
        labels = {"ja": "ティコ", "ru": "Tycho", "zh": "第谷环形山"}
        entities = EntityStub({"Q1": labelled(labels)})
        names = feature_names(_feature(name="Tycho", unicode_name=None), entities)
        assert (names.get("ja"), names.get("zh")) == ("ティコ", "第谷环形山")
        # A Latin label in a language of another script is no name and no
        # alias.
        assert names.get("ru") == "Tycho"
        assert names.aliases == {}

    def test_a_label_in_another_script_loses_its_disambiguator(self):
        labels = {"ja": "エイトケン (クレーター)", "zh": "艾特肯环形山（月球）"}
        entities = EntityStub({"Q1": labelled(labels)})
        names = feature_names(_feature(name="Aitken", unicode_name=None), entities)
        assert (names.get("ja"), names.get("zh")) == ("エイトケン", "艾特肯环形山")

    def test_the_script_of_a_label_is_read_without_its_disambiguator(self):
        entities = EntityStub({"Q1": labelled({"ja": "ティコ (Tycho)"})})
        names = feature_names(_feature(name="Tycho", unicode_name=None), entities)
        assert names.get("ja") == "ティコ"

    def test_the_ascii_name_stands_in_for_a_missing_spelling(self):
        names = feature_names(_feature(unicode_name=None), EntityStub())
        assert names.name == "Asvaghosa"


class TestFeatureAliases:
    """The aliases of a feature: no disambiguator, and none that contains its
    name."""

    def test_an_alias_that_contains_the_name_as_whole_words_is_dropped(self):
        names = Names("Tycho", {"ja": "ティコ"})
        others = ["Cratère Tycho", "TYCHO CRATER", "Tycho's crater", "Tychonis"]
        assert feature_aliases(names, "fr", others) == ["Tychonis"]
        assert feature_aliases(names, "ja", ["ティコ・クレーター", "チコ"]) == ["チコ"]

    def test_a_name_of_several_words_matches_as_a_whole(self):
        names = Names("Mare Imbrium")
        others = ["Mare Imbrium basin", "Imbrium", "Mare Imbrii"]
        assert feature_aliases(names, "en", others) == ["Imbrium", "Mare Imbrii"]

    def test_an_alias_loses_its_disambiguator(self):
        names = Names("Tycho")
        others = ["Tyge (Mondkrater)", "Tyge", "第谷（环形山）"]
        assert feature_aliases(names, "de", others) == ["Tyge", "第谷"]

    def test_a_star_alias_that_contains_the_name_stays(self):
        # A star's "Sirius A" is a designation of its own.
        assert page_aliases(Names("Sirius"), "en", ["Sirius A"]) == ["Sirius A"]


class TestStarNames:
    """The Metadata name, then the labels that name the star in a language."""

    def test_a_label_that_repeats_the_english_one_adds_nothing(self):
        entity = labelled({"en": "Alpha Ceti", "de": "Alpha Ceti"})
        star = StarObject(1, "Alpha Ceti", "Q1")
        assert star_names(star, entity) == Names("Alpha Ceti")

    def test_a_catalogue_number_names_the_star_in_no_language(self):
        labels = {"en": "Gliese 105", "fr": "HR 753", "ru": "HD 93148 b"}
        star = StarObject(1, "Gliese 105", "Q1")
        assert star_names(star, labelled(labels)) == Names("Gliese 105")

    def test_a_label_loses_its_disambiguator(self):
        labels = {
            "en": "Capella",
            "de": "LB-1 (schwarzes Loch)",
            "ja": "カペラ (恒星)",
            "zh": "五諸侯增一 (井宿)",
        }
        star = StarObject(1, "Capella", "Q1")
        names = star_names(star, labelled(labels))
        assert [names.get(lang) for lang in ("de", "ja", "zh")] == [
            "LB-1",
            "カペラ",
            "五諸侯增一",
        ]

    def test_a_label_without_the_disambiguator_of_the_english_one(self):
        """The English label, and so the Metadata name, can have one too."""
        labels = {
            "en": "R Canis Majoris (Rommel)",
            "fr": "R Canis Majoris",
            "de": "R Canis Majoris (Stern)",
        }
        star = StarObject(1, "R Canis Majoris (Rommel)", "Q1")
        names = star_names(star, labelled(labels))
        assert names.overrides() == {"fr": "R Canis Majoris", "de": "R Canis Majoris"}

    def test_the_script_of_a_label_is_read_without_its_disambiguator(self):
        labels = {"en": "Capella", "ja": "カペラ (Capella)"}
        star = StarObject(1, "Capella", "Q1", iau_named=True)
        assert star_names(star, labelled(labels)).get("ja") == "カペラ"

    def test_a_label_in_its_script_can_hold_latin_letters(self):
        labels = {
            "en": "Mesting A",
            "ja": "メスティングA",
            "zh": "Liberalia 山",
            "ru": "C・ハーシェル",
        }
        star = StarObject(1, "Mesting A", "Q1", iau_named=True)
        names = star_names(star, labelled(labels))
        assert (names.get("ja"), names.get("zh")) == ("メスティングA", "Liberalia 山")
        # A label of a third script, or with no letter of the language's own.
        assert names.get("ru") == "Mesting A"

    def test_an_iau_name_beats_a_latin_label(self):
        entity = labelled({"en": "WASP-161", "fr": "WASP-161 b host", "ja": "トゥル"})
        star = StarObject(1, "Tislit", "Q1", iau_named=True)
        names = star_names(star, entity)
        assert names.get("fr") == "Tislit"
        assert names.get("ja") == "トゥル"

    def test_an_iau_name_beats_a_label_in_another_script_of_the_language(self):
        """A Greek Bayer letter puts the label in no script of the language."""
        labels = {"en": "Sigma Draconis", "de": "σ Draconis", "ja": "りゅう座σ星"}
        star = StarObject(1, "Alsafi", "Q1", iau_named=True)
        names = star_names(star, labelled(labels))
        assert (names.get("de"), names.get("ja")) == ("Alsafi", "Alsafi")

    def test_a_label_in_the_script_of_the_language_beats_an_iau_name(self):
        labels = {"en": "Sigma Draconis", "ja": "りゅう座シグマ星"}
        star = StarObject(1, "Alsafi", "Q1", iau_named=True)
        assert star_names(star, labelled(labels)).get("ja") == "りゅう座シグマ星"

    def test_a_label_that_the_iau_name_replaces_is_an_alias(self):
        labels = {
            "en": "Betelgeuse",
            "de": "Beteigeuze",
            "fr": "Bételgeuse (étoile)",
            "es": "betelgeuse",
            "ja": "ベテルギウス",
        }
        star = StarObject(1, "Betelgeuse", "Q1", iau_named=True)
        names = star_names(star, labelled(labels))
        assert names.get("de") == "Betelgeuse"
        # Without its disambiguator; one that differs only in case is no alias.
        assert names.aliases == {"de": ("Beteigeuze",), "fr": ("Bételgeuse",)}

    def test_a_star_without_an_iau_name_has_no_replaced_label(self):
        entity = labelled({"en": "Wolf 359", "de": "Wolf 359 (Stern)"})
        assert star_names(StarObject(1, "Wolf 359", "Q1"), entity).aliases == {}


def _planet(**overrides) -> PlanetObject:
    planet = PlanetObject(1, 1, "Proxima Cen b", "Q1", ("Proxima Cen b",), "b")
    return replace(planet, **overrides)


def _row(name: str, letter: str | None = "b", **overrides) -> dict:
    """A planets table row of host 1."""
    return {
        "host": 1,
        "name": name,
        "letter": letter,
        "name_source": "nasa-exoplanet-archive",
        "status": "confirmed",
    } | overrides


# The page of Proxima Centauri.
PROXIMA = PlanetHost(Names("Proxima Centauri", {"ja": "プロキシマ・ケンタウリ"}))
GJ_229 = PlanetHost(Names("Gliese 229", {"ja": "グリーゼ229"}))


class TestPlanetNames:
    """An IAU name, else the catalogue name of a controversial planet or of a
    repeated letter, else the name of the host's page and the letter."""

    def test_a_planet_takes_its_hosts_name_and_its_letter(self):
        names = planet_names(_planet(), PROXIMA)
        assert names.name == "Proxima Centauri b"
        assert names.get("ja") == "プロキシマ・ケンタウリ b"
        assert names.get("de") == "Proxima Centauri b"

    def test_its_catalogue_name_is_an_alias(self):
        aliases = planet_names(_planet(), PROXIMA).aliases
        assert aliases["en"] == aliases["ja"] == ("Proxima Cen b",)

    def test_a_designation_spelled_another_way_is_no_alias(self):
        host = PlanetHost(Names("Kepler-16 AB"))
        names = planet_names(_planet(name="Kepler-16 (AB) b"), host)
        assert names.name == "Kepler-16 AB b"
        assert names.aliases == {}

    def test_an_iau_name_is_kept_in_every_language(self):
        planet = _planet(name="Dimidium", iau_named=True)
        host = PlanetHost(Names("51 Pegasi", {"ja": "ペガスス座51番星"}))
        names = planet_names(planet, host)
        assert names == Names("Dimidium")
        assert names.get("ja") == "Dimidium"

    def test_no_letter_or_no_host_keeps_the_catalogue_name(self):
        assert planet_names(_planet(letter=None), PROXIMA) == Names("Proxima Cen b")
        assert planet_names(_planet(), None) == Names("Proxima Cen b")

    def test_a_host_with_an_iau_name_names_its_planets_too(self):
        """υ And e is "Titawin e" while Julie has not decided otherwise."""
        host = PlanetHost(Names("Titawin"), iau_named=True)
        assert planet_names(_planet(name="ups And e", letter="e"), host).name == (
            "Titawin e"
        )

    def test_a_planet_without_an_entry_is_named_from_its_row(self):
        """The system files name every planet by the same rule, from its
        planets table row and its host's Metadata row."""
        host = served_host({"name": "Gliese 1002", "name_source": "wikidata"})
        names = planet_names(CataloguePlanet.of(_row("GJ 1002 b"), ()), host)
        assert names.name == "Gliese 1002 b"
        assert names.aliases == {}

    def test_a_host_record_with_an_entry_takes_the_names_of_the_entry(self):
        record = {"name": "Proxima Cen", "name_source": "iau-wgsn"}
        host = served_host(record, PROXIMA.names)
        assert host == PlanetHost(PROXIMA.names, iau_named=True)
        assert served_host(record) == PlanetHost(Names("Proxima Cen"), iau_named=True)

    def test_a_host_record_with_no_name_names_no_planet(self):
        row = _row("GJ 1002 b", name_source="exoplanet-eu")
        host = served_host({"name": None, "name_source": None})
        assert host is None
        assert planet_names(CataloguePlanet.of(row, ()), host) == Names("GJ 1002 b")

    def test_a_controversial_planet_keeps_its_catalogue_name(self):
        """The name is the catalogue's claim, so no language composes another."""
        planet = _planet(controversial=True)
        names = planet_names(planet, PROXIMA)
        assert (names.name, names.langs) == ("Proxima Cen b", {})
        assert names.get("ja") == "Proxima Cen b"

    def test_a_controversial_planet_keeps_its_host_form_as_an_alias(self):
        """A search for the form after the host still finds it."""
        names = planet_names(_planet(controversial=True), PROXIMA)
        assert names.aliases["en"] == ("Proxima Centauri b",)
        assert names.aliases["ja"] == (f"{PROXIMA.names.get('ja')} b",)

    def test_a_controversial_planet_with_an_iau_name_keeps_it(self):
        """Dagon, Orbitar and Tondra stay."""
        planet = _planet(name="Dagon", iau_named=True, controversial=True)
        names = planet_names(planet, PROXIMA)
        assert names == Names("Dagon")
        assert names.get("ja") == "Dagon"

    def test_two_planets_with_one_letter_keep_their_catalogue_names(self):
        rows = [_row("Kapteyn c", "c"), _row("Kapteyn's Star c", "c")]
        repeated = repeated_letters(rows)
        names = [
            planet_names(CataloguePlanet.of(row, repeated), PROXIMA) for row in rows
        ]
        assert names == [Names("Kapteyn c"), Names("Kapteyn's Star c")]
        assert names[0].get("ja") == "Kapteyn c"

    def test_a_repeated_letter_beside_a_controversial_planet(self):
        """GJ 229 Bb shares its letter with a planet that keeps its name
        anyway, and the two pages still need two names."""
        rows = [
            _row("GJ 229 b", status="controversial"),
            _row("GJ 229 Bb", name_source="exoplanet-eu"),
        ]
        repeated = repeated_letters(rows)
        disputed, confirmed = (CataloguePlanet.of(row, repeated) for row in rows)
        assert (disputed.controversial, disputed.letter_repeated) == (True, True)
        assert (confirmed.controversial, confirmed.letter_repeated) == (False, True)
        assert planet_names(disputed, GJ_229) == Names("GJ 229 b")
        assert planet_names(confirmed, GJ_229) == Names("GJ 229 Bb")

    def test_an_iau_name_beside_a_repeated_letter_stays(self):
        rows = [
            _row("Sancho", "e", name_source="iau-nameexoworlds"),
            _row("mu Ara e", "e"),
        ]
        repeated = repeated_letters(rows)
        iau_named, catalogued = (
            planet_names(CataloguePlanet.of(row, repeated), PROXIMA) for row in rows
        )
        assert (iau_named, catalogued) == (Names("Sancho"), Names("mu Ara e"))

    def test_a_catalogue_name_is_no_alias_of_its_own_page(self):
        names = planet_names(_planet(controversial=True), PROXIMA)
        others = ["Proxima Cen b", "GJ 551 b"]
        assert "Proxima Cen b" not in page_aliases(names, "ja", others)

    def test_the_entry_and_the_system_file_give_one_name(self):
        """An object entry reads the same row as the system file."""
        item = {"catalogue": "wikidata", "release": "qid", "catalogue_id": "Q1"}
        rows = [
            _row("GJ 229 b", status="controversial"),
            _row("GJ 229 Bb"),
            _row("GJ 229 c", "c"),
        ]
        repeated = repeated_letters(rows)
        for number, row in enumerate(rows, 1):
            entry = planet_object(
                row
                | {
                    "number": number,
                    "designation": row["name"],
                    "aliases": None,
                    "cross_ids": [item],
                },
                repeated,
            )
            assert entry is not None
            assert planet_names(entry, GJ_229) == planet_names(
                CataloguePlanet.of(row, repeated), GJ_229
            )


class TestRepeatedLetters:
    """The letters that more than one planet of a host has."""

    def test_a_letter_counts_per_host(self):
        rows = [_row("A b"), _row("B b", host=2), _row("C b", host=2), _row("A c", "c")]
        assert repeated_letters(rows) == {(2, "b")}

    def test_a_planet_with_no_letter_repeats_nothing(self):
        assert repeated_letters([_row("KOI-1", None), _row("KOI-2", None)]) == set()

    def test_a_planet_that_keeps_another_name_counts(self):
        rows = [
            _row("Sancho", name_source="iau-nameexoworlds"),
            _row("X b", status="controversial"),
            _row("Y b"),
        ]
        assert repeated_letters(rows) == {(1, "b")}


class TestLookups:
    """Names by page id."""

    def test_an_id_with_no_object_is_none(self, object_names: ObjectNames):
        assert object_names.find("spkid-404") is None

    def test_many_objects_are_read_in_one_query(self, session: Session):
        session.add_all(
            [
                Object(id="spkid-1", name="433 Eros", object_type=ObjectType.asteroid),
                Object(id="naif-511", name="S2003_J2", object_type=ObjectType.moon),
            ]
        )
        session.commit()
        found = ObjectNames(EntityStub(), session).objects(
            ["spkid-1", "naif-511", "spkid-404"]
        )
        assert {key: names.name for key, names in found.items()} == {
            "spkid-1": "433 Eros",
            "naif-511": "S/2003 J 2",
        }

    def test_a_registry_probe_with_no_object_takes_its_registry_name(
        self, object_names: ObjectNames
    ):
        entry = {"probe_id": 7, "name": "Clementine ISA", "wikidata_qid": None}
        assert object_names.probe(entry).name == "Clementine ISA"

    def test_a_registry_probe_with_an_object_is_named_as_its_page(
        self, session: Session
    ):
        session.add(
            Object(
                id=_CURIOSITY,
                name="Curiosity (MSL)",
                object_type=ObjectType.spacecraft,
                probe_id=100265984,
                wikidata_qid="Q48496",
            )
        )
        session.commit()
        entities = EntityStub(
            {NAME_ENTITIES[_CURIOSITY]: labelled({"en": "Curiosity"})}
        )
        names = ObjectNames(entities, session)
        entry = {"probe_id": 100265984, "name": "MSL", "wikidata_qid": "Q48496"}
        assert names.probe(entry).name == "Curiosity"

    def test_a_star_and_a_planet_are_found_by_their_page_ids(self, session: Session):
        star = StarObject(16782998, "CD Ceti", "Q2")
        names = ObjectNames(
            EntityStub({"Q2": labelled({"en": "CD Ceti", "ja": "くじら座CD星"})}),
            session,
            [star],
            [_planet(host=16782998, name="CD Cet b")],
        )
        assert names.object("x-16782998").name == "CD Ceti"
        planet = names.object("x-16782998-b-1")
        assert (planet.name, planet.get("ja")) == ("CD Ceti b", "くじら座CD星 b")

    def test_a_host_with_no_entry_names_a_planet_by_its_metadata_name(
        self, session: Session
    ):
        planet = _planet(host=7, host_name="Proxima Centauri")
        names = ObjectNames(EntityStub(), session, [], [planet])
        assert names.object("x-7-b-1").name == "Proxima Centauri b"
