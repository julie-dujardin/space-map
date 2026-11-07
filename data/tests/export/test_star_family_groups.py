"""Tests for the star family (``star-``) group pages."""

import json
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_map_data.constants.stars.families import (
    FAMILIES,
    FAMILY_SLUG_PREFIX,
    ROOT_FAMILY,
    STAR_FAMILY_PAGES,
)
from space_map_data.export.extrasolar.build import FAMILIES_FILE, export_extrasolar
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.groups import star_family
from space_map_data.export.groups.registry import (
    GROUP_BY_SLUG,
    GroupCategory,
    GroupType,
)
from space_map_data.export.names import Names, ObjectNames
from space_map_data.export.notable import NotableObject, notable_entries
from space_map_data.export.objects.stars import StarObject
from space_map_data.export.wikidata import StarEntity
from tests.extrasolar.export_registry import star, write_registry


def _entities(sitelinks: dict[str, tuple[int, list[str]]]) -> MagicMock:
    """A cache stub: each QID has a sitelink count and its Wikipedia languages."""

    def entity(qid: str | None):
        if qid not in sitelinks:
            return None
        return {
            "labels": {"en": f"Label {qid}"},
            "descriptions": {},
            "aliases": {},
            "claims": {},
            "sitelinks": {lang: qid for lang in sitelinks[qid][1]},
        }

    def get_star_entity(qid: str | None):
        found = entity(qid)
        return (
            None
            if found is None or qid is None
            else StarEntity(found, sitelinks[qid][0])
        )

    cache = MagicMock()
    cache.get_star_entity.side_effect = get_star_entity
    cache.get_listed_star.side_effect = entity
    cache.get_entity.side_effect = entity
    return cache


class TestRegistry:
    """One page per family."""

    def test_every_family_has_a_page(self):
        for family, qids in STAR_FAMILY_PAGES.items():
            if family == ROOT_FAMILY:
                assert f"{FAMILY_SLUG_PREFIX}{family}" not in GROUP_BY_SLUG
                continue
            group = GROUP_BY_SLUG[f"{FAMILY_SLUG_PREFIX}{family}"]
            assert group.type is GroupType.STAR_FAMILY
            assert group.applies_to is GroupCategory.STAR
            assert group.wikidata_qid == qids[0]

    def test_parents(self):
        assert star_family.PAGES.parent_slugs("star-g-type-main-sequence") == [
            "star-main-sequence"
        ]
        assert star_family.PAGES.parent_slugs("star-rr-lyrae-variable") == [
            "star-horizontal-branch",
            "star-variable-star",
        ]
        assert star_family.PAGES.parent_slugs("star-dwarf") == ["cat-stars"]


class TestBuild:
    """Counts and stars from the served extrasolar export."""

    @pytest.fixture
    def served(self, tmp_path):
        dwarf = {"evolstage_flame": 250, "mass_flame": 1.0, "flags_flame": "00"}
        built = write_registry(
            tmp_path / "reg",
            [
                star(10.0, 5.0, g=9.0, simbad=True),  # K0V
                star(11.0, 5.0, g=7.0, simbad=True) | {"simbad_sp_type": "K2V"},
                star(12.0, 5.0, g=8.0, simbad=True) | {"simbad_sp_type": "K5V"},
                star(13.0, 5.0) | dwarf,
            ],
        )
        out = tmp_path / "space-map-extrasolar"
        export_extrasolar(built.root, out, workers=1, cultures_dir=tmp_path / "none")
        return built.ids, out

    def test_counts_and_children(self, served, session):
        _, out = served
        groups = star_family.build_star_family_groups(
            [], ObjectNames(_entities({}), session), out
        )
        assert groups.member_counts["star-k-type-main-sequence"] == 3
        assert groups.member_counts["star-main-sequence"] == 4
        stats = groups.extra_stats["star-main-sequence"]
        assert (stats.published_star_count, stats.estimated_star_count) == (3, 1)
        assert set(groups.member_counts) == {
            "cat-stars",
            *(f"star-{f}" for f in FAMILIES if f != ROOT_FAMILY),
        }
        assert groups.children["star-main-sequence"] == ["star-k-type-main-sequence"]
        assert groups.children["star-dwarf"] == ["star-main-sequence"]
        assert groups.children["cat-stars"] == ["star-dwarf"]

    def test_the_stars_page_counts_every_star(self, served, session):
        _, out = served
        metadata = json.loads((out / "v1" / "x" / "metadata.json").read_text())
        metadata["objects"]["star"]["count"] = 6
        (out / "v1" / "x" / "metadata.json").write_text(json.dumps(metadata))
        groups = star_family.build_star_family_groups(
            [], ObjectNames(_entities({}), session), out
        )
        assert groups.member_counts["cat-stars"] == 6
        stats = groups.extra_stats["cat-stars"]
        assert (stats.published_star_count, stats.estimated_star_count) == (3, 1)

    @pytest.mark.parametrize(
        ("size", "error", "radius"),
        [
            ((2.0, "gaia-dr3-flame"), 0.1, 2.0),
            ((2.0, "gaia-dr3-flame"), 1.0, None),
            ((2.0, "gaia-dr3-flame-spec"), 0.1, 2.0),
            ((628.0, "literature"), None, 628.0),
            ((9.0, "jmdc"), None, 9.0),
            # GSP-Phot alone sized CM Vel at the edge of its grid.
            ((900.0, "gaia-dr3-gspphot"), 1.0, None),
            ((1.1, "nasa-exoplanet-archive"), 0.05, 1.1),
            ((1.1, "nasa-exoplanet-archive"), 0.2, None),
            ((1.1, "nasa-exoplanet-archive"), None, None),
        ],
    )
    def test_a_card_shows_a_measured_or_precise_radius(self, size, error, radius):
        found = {"radius": size[0], "radius_source": size[1]}
        assert star_family._card_radius(found, error) == radius

    def test_the_error_is_that_of_the_chosen_radius(self):
        """The bounds of its FLAME run for a FLAME radius, the catalogue's
        error for a catalogue's, on the Point source row or the held star's
        System row."""
        tables = {
            "point-source": {
                1: {"radius_flame_lower": 1.9, "radius_flame_upper": 2.2},
                2: {"radius_flame_lower": 1.9, "radius_flame_upper": 2.1}
                | {"host_radius_error": 0.3},
                5: {"radius_flame_spec_lower": 0.95, "radius_flame_spec_upper": 1.1},
            },
            "system": {3: {"star": [{"host_radius_error": 0.04}]}},
        }

        class Reader:
            def rows(self, slug, ids, columns):
                return {i: tables[slug][i] for i in ids if i in tables.get(slug, {})}

        sizes = {
            1: {"radius": 2.0, "radius_source": "gaia-dr3-flame"},
            2: {"radius": 1.0, "radius_source": "exoplanet-eu"},
            3: {"radius": 0.9, "radius_source": "open-exoplanet-catalogue"},
            4: {"radius": 9.0, "radius_source": "jmdc"},
            5: {"radius": 1.0, "radius_source": "gaia-dr3-flame-spec"},
        }
        errors = star_family._radius_errors(Reader(), sizes)  # ty: ignore[invalid-argument-type]
        assert errors == pytest.approx({1: 0.2, 2: 0.3, 3: 0.04, 5: 0.1})

    def test_the_largest_star_is_no_system(self, session):
        """A system has no Metadata radius, so the card never names one."""

        def rows(slug, ids, columns):
            if slug == "metadata":
                radius = {1: None, 2: 500.0}
                return {
                    id_: {"radius": radius[id_], "radius_source": "gaia-dr3-flame"}
                    for id_ in ids
                }
            return {
                id_: {"radius_flame_lower": 499.0, "radius_flame_upper": 501.0}
                for id_ in ids
            }

        reader = MagicMock(rows=MagicMock(side_effect=rows))
        stars = [
            StarObject(1, "A binary", object_type="binary_star"),
            StarObject(2, "A star"),
        ]
        names = ObjectNames(_entities({}), session)
        found = star_family._largest_star(reader, stars, names)
        assert found is not None
        card, page = found
        assert (card["primary_id"], page.name) == ("x-2", "A star")

    def test_the_plot_samples_the_stars(self, served, session):
        _, out = served
        plot = star_family.build_star_family_groups(
            [], ObjectNames(_entities({}), session), out
        ).plot
        assert plot is not None
        assert len(plot["bp_rp"]) == len(plot["abs_g"]) == len(plot["stage"])
        assert plot["named"][0]["id"] == "naif-10"
        assert plot["stages"][plot["stage"][0]] == "main-sequence"

    def test_stars_with_an_article_by_sitelinks(self, served, session):
        ids, out = served
        stars = [
            StarObject(ids[0], "Few links", "Q1"),
            StarObject(ids[1], "No article", "Q2"),
            StarObject(ids[2], "Many links", "Q3"),
            StarObject(ids[3], "Estimated only", "Q4"),
        ]
        entities = _entities(
            {"Q1": (5, ["de"]), "Q2": (90, []), "Q3": (40, ["en"]), "Q4": (99, ["en"])}
        )
        groups = star_family.build_star_family_groups(
            stars, ObjectNames(entities, session), out
        )
        members = groups.notable_members["star-k-type-main-sequence"]
        assert [m.object_id for m in members] == [
            f"x-{ids[2]}",
            f"x-{ids[0]}",
            f"x-{ids[1]}",
        ]
        assert [m.sitelinks_count for m in members] == [40, 5, None]
        assert all(m.extrasolar for m in members)
        assert groups.notable_members["star-dwarf"] == members
        # No brightest stars here: the list is the stars with an article.
        assert groups.notable_members["cat-stars"] == members[:2]
        assert "star-g-type-main-sequence" not in groups.notable_members

        entries = notable_entries(members)
        # A star is listed by the name of its page, its Metadata name.
        assert [e["name"] for e in entries] == ["Many links", "Few links", "No article"]
        assert entries[0]["id"] == f"x-{ids[2]}"

    def test_the_sun_is_in_the_families_of_its_type(self, served, session):
        ids, out = served
        sun = NotableObject("naif-10", "Q525", Names("Sun"), None, None)
        stars = [StarObject(ids[0], "Many links", "Q1")]
        languages = ["en", *(f"x{n}" for n in range(59))]
        entities = _entities({"Q1": (40, ["en"]), "Q525": (60, languages)})
        groups = star_family.build_star_family_groups(
            stars, ObjectNames(entities, session), out, sun
        )
        g_type = groups.notable_members["star-g-type-main-sequence"]
        assert [(m.object_id, m.sitelinks_count) for m in g_type] == [("naif-10", 60)]
        assert groups.notable_members["star-main-sequence"][:2] == [
            g_type[0],
            groups.notable_members["star-k-type-main-sequence"][0],
        ]
        assert "naif-10" not in {
            m.object_id for m in groups.notable_members["star-k-type-main-sequence"]
        }
        assert groups.notable_members["cat-stars"][0] == g_type[0]
        assert groups.member_counts["star-g-type-main-sequence"] == 1
        assert groups.extra_stats["star-g-type-main-sequence"].published_star_count == 1
        assert groups.member_counts["star-main-sequence"] == 5
        assert groups.member_counts["cat-stars"] == 5
        assert groups.extra_stats["cat-stars"].published_star_count == 4

    def test_the_brightest_stars_fill_the_list(self, served, session):
        ids, out = served
        groups = star_family.build_star_family_groups(
            [], ObjectNames(_entities({}), session), out
        )
        assert set(groups.notable_members) == {
            "star-k-type-main-sequence",
            "star-main-sequence",
            "star-dwarf",
        }
        members = groups.notable_members["star-k-type-main-sequence"]
        brightest = [ids[1], ids[2], ids[0]]
        assert [m.object_id for m in members] == [f"x-{id_}" for id_ in brightest]
        assert all(m.extrasolar and m.wikidata_qid is None for m in members)

        entries = notable_entries(members)
        assert [e["name"] for e in entries] == [f"Star {id_}" for id_ in brightest]
        assert not any("thumbnail" in e for e in entries)

    def test_a_listed_star_is_listed_once(self, served, session):
        ids, out = served
        stars = [StarObject(ids[0], "Faintest", "Q1")]
        groups = star_family.build_star_family_groups(
            stars, ObjectNames(_entities({"Q1": (5, ["de"])}), session), out
        )
        members = groups.notable_members["star-k-type-main-sequence"]
        assert [m.object_id for m in members] == [
            f"x-{ids[0]}",
            f"x-{ids[1]}",
            f"x-{ids[2]}",
        ]
        assert members[0].wikidata_qid == "Q1"

    def test_fill_stops_at_the_list_size(self, served, session, monkeypatch):
        ids, out = served
        monkeypatch.setattr(star_family, "LISTED_STARS", 2)
        stars = [StarObject(ids[2], "Few links", "Q1")]
        entities = _entities({"Q1": (5, ["de"])})
        groups = star_family.build_star_family_groups(
            stars, ObjectNames(entities, session), out
        )
        members = groups.notable_members["star-k-type-main-sequence"]
        assert [m.object_id for m in members] == [f"x-{ids[2]}", f"x-{ids[1]}"]

    def test_only_a_listed_star_is_named(self, served, session, monkeypatch):
        """Its names read its item into the shared cache."""
        ids, out = served
        monkeypatch.setattr(star_family, "LISTED_STARS", 1)
        stars = [
            StarObject(ids[0], "Few links", "Q1"),
            StarObject(ids[2], "Many links", "Q3"),
        ]
        names = ObjectNames(_entities({"Q1": (5, ["de"]), "Q3": (40, ["en"])}), session)
        named = []
        star = names.star
        monkeypatch.setattr(names, "star", lambda s: named.append(s.id) or star(s))
        star_family.build_star_family_groups(stars, names, out)
        assert named == [ids[2]]

    def test_no_served_export(self, tmp_path, session):
        groups = star_family.build_star_family_groups(
            [], ObjectNames(_entities({}), session), tmp_path / "none"
        )
        assert groups.member_counts == {}
        assert groups.notable_members == {}
        assert groups.children == {}
        assert star_family.served_families_stamp(tmp_path / "none") is None

    def test_an_export_without_families_is_refused(self, tmp_path, session):
        root = tmp_path / "old" / "v1" / "x"
        root.mkdir(parents=True)
        (root / "metadata.json").write_text(json.dumps({"tables": {}}))
        with pytest.raises(KeyError):
            star_family.build_star_family_groups(
                [], ObjectNames(_entities({}), session), tmp_path / "old"
            )

    def test_an_export_without_family_lists_is_refused(self, served, session):
        _, out = served
        (out / "v1" / "x" / FAMILIES_FILE).unlink()
        with pytest.raises(FileNotFoundError, match="--only extrasolar"):
            star_family.build_star_family_groups(
                [], ObjectNames(_entities({}), session), out
            )
        with pytest.raises(FileNotFoundError, match="--only extrasolar"):
            star_family.served_families_stamp(out)

    def test_stamp_follows_the_counts_lists_and_tiles(self, served, session):
        _, out = served
        stamp = star_family.served_families_stamp(out)
        assert stamp is not None
        reader = ExportReader(out / "v1" / "x")
        assert stamp["families"] == reader.metadata["families"]
        assert stamp["metadata"] == reader.metadata["tables"]["metadata"]["token"]
        assert stamp["system"] == reader.metadata["tables"]["system"]["token"]
        path = out / "v1" / "x" / FAMILIES_FILE
        lists = json.loads(path.read_text())
        lists["brightest"]["dwarf"].reverse()
        path.write_text(json.dumps(lists))
        changed = star_family.served_families_stamp(out)
        assert changed is not None
        assert changed["lists"] != stamp["lists"]
        assert changed["families"] == stamp["families"]

    def test_rows_skip_an_empty_tile(self, served, session, monkeypatch):
        ids, out = served
        reader = ExportReader(out / "v1" / "x")
        reader.split("metadata")
        empty = MagicMock()
        empty.numpy.return_value = np.array([], np.int64)
        monkeypatch.setattr(reader, "read", lambda path, token: empty)
        assert reader.rows("metadata", ids, ["families"]) == {}


class TestStarPages:
    def test_a_star_is_on_the_pages_of_every_family_above_its_own(self):
        assert set(star_family.star_pages(["red-dwarf"])) == {
            "cat-stars",
            "star-red-dwarf",
            "star-main-sequence",
            "star-dwarf",
        }

    def test_a_family_with_two_parents_climbs_both(self):
        assert {"star-horizontal-branch", "star-variable-star"} <= set(
            star_family.star_pages(["rr-lyrae-variable"])
        )

    def test_a_star_with_no_family_is_on_the_stars_page(self):
        assert star_family.star_pages(()) == ["cat-stars"]

    def test_the_root_family_has_no_page(self):
        assert star_family.star_pages(["classification"]) == ["cat-stars"]
