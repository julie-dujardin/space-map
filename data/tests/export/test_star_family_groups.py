"""Tests for the star family (``star-``) group pages."""

import json
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_map_data.constants.stars.families import (
    FAMILIES,
    FAMILY_SLUG_PREFIX,
    STAR_FAMILY_PAGES,
)
from space_map_data.export.extrasolar.build import export_extrasolar
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.groups import star_family
from space_map_data.export.groups.registry import (
    GROUP_BY_SLUG,
    GroupCategory,
    GroupType,
)
from space_map_data.export.notable import notable_entries
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
    return cache


class TestRegistry:
    """One page per family."""

    def test_every_family_has_a_page(self):
        for family, qids in STAR_FAMILY_PAGES.items():
            group = GROUP_BY_SLUG[f"{FAMILY_SLUG_PREFIX}{family}"]
            assert group.type is GroupType.STAR_FAMILY
            assert group.applies_to is GroupCategory.STAR
            assert group.wikidata_qid == qids[0]

    def test_parents(self):
        assert star_family.parent_slugs("star-g-type-main-sequence") == [
            "star-main-sequence"
        ]
        assert star_family.parent_slugs("star-rr-lyrae-variable") == [
            "star-horizontal-branch",
            "star-variable-star",
        ]
        assert star_family.parent_slugs("star-dwarf") == []


class TestBuild:
    """Counts and stars from the served extrasolar export."""

    @pytest.fixture
    def served(self, tmp_path):
        dwarf = {"evolstage_flame": 250, "mass_flame": 1.0, "flags_flame": "00"}
        built = write_registry(
            tmp_path / "reg",
            [
                star(10.0, 5.0, simbad=True),  # K0V
                star(11.0, 5.0, simbad=True) | {"simbad_sp_type": "K2V"},
                star(12.0, 5.0, simbad=True) | {"simbad_sp_type": "K5V"},
                star(13.0, 5.0) | dwarf,
            ],
        )
        out = tmp_path / "space-map-extrasolar"
        export_extrasolar(built.root, out, workers=1)
        return built.ids, out

    def test_counts_and_children(self, served):
        _, out = served
        groups = star_family.build_star_family_groups([], _entities({}), out)
        assert groups.member_counts["star-k-type-main-sequence"] == 3
        assert groups.member_counts["star-main-sequence"] == 4
        stats = groups.extra_stats["star-main-sequence"]
        assert (stats.published_star_count, stats.estimated_star_count) == (3, 1)
        assert set(groups.member_counts) == {f"star-{f}" for f in FAMILIES}
        assert groups.children["star-main-sequence"] == ["star-k-type-main-sequence"]
        assert groups.children["star-dwarf"] == ["star-main-sequence"]
        assert groups.notable_members == {}

    def test_stars_with_an_article_by_sitelinks(self, served):
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
        groups = star_family.build_star_family_groups(stars, entities, out)
        members = groups.notable_members["star-k-type-main-sequence"]
        assert [m.object_id for m in members] == [f"x-{ids[2]}", f"x-{ids[0]}"]
        assert all(m.star for m in members)
        assert groups.notable_members["star-dwarf"] == members
        assert "star-g-type-main-sequence" not in groups.notable_members

        entries = notable_entries(members, entities)
        assert [e["name"] for e in entries] == ["Label Q3", "Label Q1"]
        assert entries[0]["id"] == f"x-{ids[2]}"

    def test_no_served_export(self, tmp_path):
        groups = star_family.build_star_family_groups(
            [], _entities({}), tmp_path / "none"
        )
        assert groups.member_counts == {}
        assert groups.notable_members == {}
        assert groups.children == {}
        assert star_family.served_families_stamp(tmp_path / "none") is None

    def test_an_export_without_families_is_refused(self, tmp_path):
        root = tmp_path / "old" / "v1" / "x"
        root.mkdir(parents=True)
        (root / "metadata.json").write_text(json.dumps({"tables": {}}))
        with pytest.raises(KeyError):
            star_family.build_star_family_groups([], _entities({}), tmp_path / "old")

    def test_stamp_is_the_served_counts(self, served):
        _, out = served
        stamp = star_family.served_families_stamp(out)
        assert stamp is not None
        assert [entry["slug"] for entry in stamp] == list(FAMILIES)

    def test_rows_skip_an_empty_tile(self, served, monkeypatch):
        ids, out = served
        reader = ExportReader(out / "v1" / "x")
        reader.split("metadata")
        empty = MagicMock()
        empty.numpy.return_value = np.array([], np.int64)
        monkeypatch.setattr(reader, "read", lambda path, token: empty)
        assert reader.rows("metadata", ids, ["families"]) == {}
