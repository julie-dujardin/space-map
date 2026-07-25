"""Tests for the feature-type (``ft-``) group tier."""

import datetime
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.constants.categories import CATEGORY_BY_SLUG, SURFACE_FEATURES_SLUG
from space_map_data.constants.nomenclature.families import FEATURE_FAMILY_CODES
from space_map_data.constants.nomenclature.feature_types import (
    FEATURE_TYPE_CODE_BY_SLUG,
    FEATURE_TYPE_SLUG_PREFIX,
    FEATURE_TYPE_SLUGS,
    FEATURE_TYPES,
)
from space_map_data.export.groups.feature_type import (
    TOP_BODIES,
    build_feature_type_groups,
)
from space_map_data.export.groups.registry import (
    GROUP_BY_SLUG,
    GroupCategory,
    GroupType,
)
from space_map_data.export import notable
from space_map_data.export.notable import feature_member_key, notable_entries
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.base import Base


@pytest.fixture
def session() -> Iterator[Session]:
    """Fresh in-memory SQLite with the full schema, scoped to one test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def _entities(sitelinks: dict[str, int] | None = None) -> MagicMock:
    """Cache stub returning a sitelink count per feature QID."""
    counts = sitelinks or {}

    def get_feature_entity(qid: str | None):
        if qid is None or qid not in counts:
            return None
        return {"sitelinks": {f"w{i}": "" for i in range(counts[qid])}}

    cache = MagicMock()
    cache.get_feature_entity.side_effect = get_feature_entity
    return cache


def _body(session: Session, object_id: str, name: str, qid: str | None = None) -> None:
    session.add(
        Object(
            id=object_id,
            name=name,
            object_type=ObjectType.moon,
            wikidata_qid=qid,
        )
    )


def _feature(session: Session, feature_id: int, **kwargs) -> None:
    defaults = {
        "feature_id": feature_id,
        "object_id": "naif-301",
        "name": f"Feature {feature_id}",
        "target": "moon",
        "center_lat": 0.0,
        "center_lon": 0.0,
        "diameter": 10.0,
        "feature_type_code": "AA",
        "approval_date": datetime.date(1970, 1, 1),
    }
    defaults.update(kwargs)
    session.add(Feature(**defaults))


class TestSlugs:
    """The ft- slug table backing the group registry."""

    def test_every_type_has_a_unique_prefixed_slug(self):
        assert len(FEATURE_TYPE_SLUGS) == len(FEATURE_TYPES)
        assert len(set(FEATURE_TYPE_SLUGS.values())) == len(FEATURE_TYPES)
        assert all(
            slug.startswith(FEATURE_TYPE_SLUG_PREFIX)
            for slug in FEATURE_TYPE_SLUGS.values()
        )

    def test_slugs_are_url_safe_and_readable(self):
        assert FEATURE_TYPE_SLUGS["AA"] == "ft-crater"
        assert FEATURE_TYPE_SLUGS["AL"] == "ft-albedo-feature"
        assert FEATURE_TYPE_CODE_BY_SLUG["ft-vallis"] == "VA"

    def test_meta_category_exists_for_the_ft_pages(self):
        """The browse node ft- pages breadcrumb up to."""
        spec = CATEGORY_BY_SLUG[SURFACE_FEATURES_SLUG]
        assert spec.wikidata_qid == "Q1463003"  # planetary nomenclature
        assert GROUP_BY_SLUG[SURFACE_FEATURES_SLUG].type is GroupType.CATEGORY

    def test_registry_carries_one_group_per_type(self):
        for code, slug in FEATURE_TYPE_SLUGS.items():
            group = GROUP_BY_SLUG[slug]
            assert group.type is GroupType.FEATURE_TYPE
            assert group.applies_to is GroupCategory.SURFACE_FEATURE
            assert group.wikidata_qid == FEATURE_TYPES[code].qid


class TestBuildFeatureTypeGroups:
    """Per-type roll-ups from the features table."""

    def test_counts_bodies_and_approval_range(self, session: Session):
        _body(session, "naif-301", "Moon", "Q405")
        _body(session, "naif-499", "Mars", "Q111")
        _feature(session, 1, approval_date=datetime.date(1935, 1, 1))
        _feature(session, 2, approval_date=datetime.date(1976, 5, 3))
        _feature(session, 3, object_id="naif-499", approval_date=None)
        session.flush()

        out = build_feature_type_groups(session, _entities())
        stats = out.stats["ft-crater"]
        assert stats.feature_count == 3
        assert out.member_counts["ft-crater"] == 3
        assert stats.body_count == 2
        assert stats.bodies == [
            {
                "name": "Moon",
                "primary_type": "object",
                "primary_id": "naif-301",
                "n": 2,
            },
            {
                "name": "Mars",
                "primary_type": "object",
                "primary_id": "naif-499",
                "n": 1,
            },
        ]
        assert stats.first_approval == "1935-01-01"
        assert stats.last_approval == "1976-05-03"
        assert stats.approval_histogram == {1935: 1, 1976: 1}
        assert stats.body_qids == {"naif-301": "Q405", "naif-499": "Q111"}

    def test_unused_type_still_gets_an_empty_page(self, session: Session):
        _body(session, "naif-301", "Moon")
        _feature(session, 1)
        session.flush()

        out = build_feature_type_groups(session, _entities())
        assert out.stats["ft-vallis"].feature_count == 0
        assert out.member_counts["ft-vallis"] == 0
        assert "ft-vallis" not in out.notable_members

    def test_unexportable_features_are_excluded(self, session: Session):
        """Members must match what the map + search index actually carry."""
        _body(session, "naif-301", "Moon")
        _feature(session, 1)
        _feature(session, 2, center_lat=None)  # no position → not exported
        _feature(session, 3, object_id=None)  # unmatched body → not exported
        session.flush()

        out = build_feature_type_groups(session, _entities())
        assert out.stats["ft-crater"].feature_count == 1

    def test_largest_is_the_biggest_named_example(self, session: Session):
        _body(session, "naif-301", "Moon")
        _feature(session, 1, diameter=10.0)
        _feature(session, 2, diameter=93.0, name="Copernicus")
        _feature(session, 3, diameter=None)
        session.flush()

        out = build_feature_type_groups(session, _entities())
        assert out.stats["ft-crater"].largest == {
            "name": "Copernicus",
            "primary_type": "naif",
            "primary_id": "301",
            "secondary_type": "feature",
            "secondary_id": "2",
            "diameter_km": 93.0,
        }

    def test_chart_rows_capped_with_the_tail_kept_in_body_count(self, session: Session):
        for i in range(TOP_BODIES + 3):
            _body(session, f"naif-{i}", f"Body {i}")
            for j in range(i + 1):
                _feature(session, i * 100 + j, object_id=f"naif-{i}")
        session.flush()

        stats = build_feature_type_groups(session, _entities()).stats["ft-crater"]
        assert len(stats.bodies) == TOP_BODIES
        assert stats.body_count == TOP_BODIES + 3
        # Most features first.
        assert [b["n"] for b in stats.bodies] == sorted(
            (b["n"] for b in stats.bodies), reverse=True
        )

    def test_notable_ranks_by_prominence_then_size(self, session: Session):
        _body(session, "naif-301", "Moon")
        _feature(session, 1, name="Big anonymous", diameter=500.0)
        _feature(session, 2, name="Tycho", diameter=85.0, wikidata_qid="Q1")
        _feature(session, 3, name="Small anonymous", diameter=5.0)
        session.flush()

        out = build_feature_type_groups(session, _entities({"Q1": 42}))
        members = out.notable_members["ft-crater"]
        assert [m.fallback_name for m in members] == [
            "Tycho",
            "Big anonymous",
            "Small anonymous",
        ]
        assert members[0].feature_id == 2
        assert members[0].object_id == "naif-301"
        assert members[0].sitelinks_count == 42


class TestMetaCategoryStats:
    """The Surface Features browse node's own stat cards."""

    def test_totals_span_every_type(self, session: Session):
        _body(session, "naif-301", "Moon")
        _body(session, "naif-499", "Mars")
        _feature(session, 1)
        _feature(session, 2, object_id="naif-499")
        _feature(session, 3, object_id="naif-499", feature_type_code="VA")
        session.flush()

        stats = build_feature_type_groups(session, _entities()).stats[
            SURFACE_FEATURES_SLUG
        ]
        assert stats.feature_count == 3
        assert stats.body_count == 2
        # Types with no features get a page but no chip, so they don't count.
        assert stats.type_count == 2

    def test_meta_node_is_absent_from_member_counts(self, session: Session):
        """The category tier sums that map — an entry here would double it."""
        _body(session, "naif-301", "Moon")
        _feature(session, 1)
        session.flush()

        out = build_feature_type_groups(session, _entities())
        assert SURFACE_FEATURES_SLUG not in out.member_counts
        assert sum(out.member_counts.values()) == 1

    def test_families_cover_every_type_exactly_once(self, session: Session):
        """The curated grouping is a partition of the 57 descriptor codes."""
        _body(session, "naif-301", "Moon")
        for i, code in enumerate(FEATURE_TYPES):
            _feature(session, i, feature_type_code=code)
        session.flush()

        families = (
            build_feature_type_groups(session, _entities())
            .stats[SURFACE_FEATURES_SLUG]
            .families
        )
        slugs = [slug for fam in families for slug in fam["types"]]
        assert sorted(slugs) == sorted(FEATURE_TYPE_SLUGS.values())
        assert len(slugs) == len(set(slugs))
        # Narrative order, not by size — impact leads even before any counting.
        assert [f["key"] for f in families] == list(FEATURE_FAMILY_CODES)

    def test_family_counts_and_type_order(self, session: Session):
        _body(session, "naif-301", "Moon")
        _feature(session, 1)  # AA — impact
        _feature(session, 2, feature_type_code="SF")  # impact
        _feature(session, 3, feature_type_code="SF")
        _feature(session, 4, feature_type_code="VA")  # fluvial
        session.flush()

        families = {
            f["key"]: f
            for f in build_feature_type_groups(session, _entities())
            .stats[SURFACE_FEATURES_SLUG]
            .families
        }
        assert families["impact"]["n"] == 3
        # Most-populated type first within the family.
        assert families["impact"]["types"][:2] == ["ft-satellite-feature", "ft-crater"]
        assert families["fluvial"]["n"] == 1

    def test_unused_types_and_families_drop_out(self, session: Session):
        """A type with no chip can't be rendered, so it can't be listed."""
        _body(session, "naif-301", "Moon")
        _feature(session, 1)  # AA — impact, the only populated family
        session.flush()

        families = (
            build_feature_type_groups(session, _entities())
            .stats[SURFACE_FEATURES_SLUG]
            .families
        )
        assert families == [{"key": "impact", "n": 1, "types": ["ft-crater"]}]

    def test_naming_origins_ranked_and_capped(self, session: Session):
        _body(session, "naif-301", "Moon")
        _feature(session, 1, ethnicity="Greek")
        _feature(session, 2, ethnicity="Greek")
        _feature(session, 3, ethnicity="Latin")
        _feature(session, 4, ethnicity=None)  # unattributed → not charted
        session.flush()

        origins = (
            build_feature_type_groups(session, _entities())
            .stats[SURFACE_FEATURES_SLUG]
            .naming_origins
        )
        assert origins == [{"name": "Greek", "n": 2}, {"name": "Latin", "n": 1}]

    def test_per_type_stats_carry_no_type_count(self, session: Session):
        """Only the meta node emits ``feature_type_count`` in the bundle."""
        _body(session, "naif-301", "Moon")
        _feature(session, 1)
        session.flush()

        assert (
            build_feature_type_groups(session, _entities())
            .stats["ft-crater"]
            .type_count
            == 0
        )


class TestNotableFeatureEntries:
    """Bundle entries for feature members route to the body's feature URL."""

    def test_entry_carries_host_body_and_feature_id(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ):
        # Thumbnails come from the real ingest cache; pin it empty here.
        monkeypatch.setattr(notable, "collect_feature_images", lambda _fid: None)
        _body(session, "naif-301", "Moon")
        _feature(session, 7, name="Tycho", diameter=85.29)
        session.flush()

        members = build_feature_type_groups(session, _entities()).notable_members[
            "ft-crater"
        ]
        entries = notable_entries(members, _entities())
        assert entries == [
            {
                "name": "Tycho",
                "id": "naif-301",
                "feature_id": 7,
                "diameter_km": 85.29,
                "first_obs": "1970-01-01",
            }
        ]

    def test_member_key_is_body_and_feature(self):
        assert feature_member_key("naif-301", 7) == "naif-301:7"
