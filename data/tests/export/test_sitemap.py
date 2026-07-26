"""Tests for sitemap URL construction.

The paths here must byte-match what ``frontend/src/lib/state/url.ts`` builds —
a mismatch makes every indexed URL a redirect or a 404.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.export.sitemap import (
    SITELINKS_THRESHOLD,
    _feature_paths,
    _object_path,
)
from space_map_data.models.feature import Feature
from space_map_data.models.object.base import Base


@pytest.fixture
def session() -> Iterator[Session]:
    """Fresh in-memory SQLite with the full schema, scoped to one test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def _entities(sitelinks: dict[str, int]) -> MagicMock:
    """Cache stub returning a sitelink count per feature QID."""

    def get_feature_entity(qid: str | None):
        if qid is None or qid not in sitelinks:
            return None
        return {"sitelinks": {f"w{i}": "" for i in range(sitelinks[qid])}}

    cache = MagicMock()
    cache.get_feature_entity.side_effect = get_feature_entity
    return cache


def _feature(session: Session, feature_id: int, **kwargs) -> None:
    defaults = {
        "feature_id": feature_id,
        "object_id": "naif-301",
        "name": f"Feature {feature_id}",
        "target": "moon",
        "wikidata_qid": f"Q{feature_id}",
    }
    defaults.update(kwargs)
    session.add(Feature(**defaults))


class TestObjectPath:
    """Id scheme → URL type segment."""

    def test_maps_each_known_prefix(self):
        assert _object_path("naif-499", "Mars") == "/b/499/Mars"
        assert _object_path("spkid-2000001", "Ceres") == "/s/2000001/Ceres"
        assert _object_path("norad_satcat-25544", "ISS") == "/e/25544/ISS"

    def test_encodes_the_name_segment(self):
        assert _object_path("naif-599", "Jupiter I") == "/b/599/Jupiter%20I"

    def test_rejects_an_unknown_scheme(self):
        assert _object_path("bogus-1", "X") is None
        assert _object_path("naif-", "X") is None


class TestFeaturePaths:
    """Feature URLs and the notability floor gating them."""

    def test_builds_the_route_shape_url_ts_resolves(self, session: Session):
        _feature(session, 7, name="Tycho")
        session.flush()

        paths = _feature_paths(session, _entities({"Q7": SITELINKS_THRESHOLD}))
        assert paths == ["/b/301/f/7/Tycho"]

    def test_drops_features_under_the_sitelink_floor(self, session: Session):
        _feature(session, 1, name="Famous")
        _feature(session, 2, name="Obscure")
        session.flush()

        paths = _feature_paths(
            session,
            _entities({"Q1": SITELINKS_THRESHOLD, "Q2": SITELINKS_THRESHOLD - 1}),
        )
        assert paths == ["/b/301/f/1/Famous"]

    def test_drops_features_with_no_wikidata_entity(self, session: Session):
        _feature(session, 1, name="Ghost")
        session.flush()

        assert _feature_paths(session, _entities({})) == []

    def test_prefers_the_unicode_name(self, session: Session):
        """The app routes on `unicode_name or name`, diacritics included."""
        _feature(session, 3, name="Bel'kovich", unicode_name="Belʹkovich")
        session.flush()

        paths = _feature_paths(session, _entities({"Q3": SITELINKS_THRESHOLD}))
        assert paths == ["/b/301/f/3/Bel%CA%B9kovich"]

    def test_skips_features_with_no_host_body(self, session: Session):
        _feature(session, 4, object_id=None)
        session.flush()

        assert _feature_paths(session, _entities({"Q4": SITELINKS_THRESHOLD})) == []
