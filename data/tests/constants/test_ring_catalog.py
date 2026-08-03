"""Ring catalogue invariants, and a cross-check that the rows' explicit
render picks stay inside what the catalogue states."""

import re

import pytest

from space_map_data.constants.rings.catalog import (
    RING_CATALOGS,
    SATURN_MEASURED_THICKNESS,
    CatalogFeature,
    RenderedFeature,
    bundle_features,
    feature_mid,
    feature_span,
)
from space_map_data.constants.rings.wikidata import RING_FEATURE_PAGES

BODY_IDS = sorted(RING_CATALOGS)

# Kinds that are radially contained by their parent. Dust bands are named as
# extensions of the ring they sit beside, not inside it.
NESTED_KINDS = frozenset({"gap", "ringlet", "region", "arc"})

# The measured Saturn strip's zone edges come from the NSSDCA fact sheets,
# which disagree with PDS by a few hundred km on the main-ring edges.
BOUNDARY_TOLERANCE = 0.005


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _features(body: str) -> dict[str, CatalogFeature]:
    return {f.slug: f for f in RING_CATALOGS[body].features}


def _within(value: float, low: float, high: float) -> bool:
    """Inside [low, high], allowing the tolerance at either end."""
    return low * (1 - BOUNDARY_TOLERANCE) <= value <= high * (1 + BOUNDARY_TOLERANCE)


class TestCatalogue:
    """Structure of the per-body feature tables."""

    @pytest.mark.parametrize("body", BODY_IDS)
    def test_body_key_matches_row(self, body: str):
        assert RING_CATALOGS[body].body == body

    @pytest.mark.parametrize("body", BODY_IDS)
    def test_slugs_are_unique_and_normalised(self, body: str):
        slugs = [f.slug for f in RING_CATALOGS[body].features]
        assert len(slugs) == len(set(slugs))
        assert all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s) for s in slugs)

    @pytest.mark.parametrize("body", BODY_IDS)
    def test_parents_resolve_without_cycles(self, body: str):
        features = _features(body)
        for feature in features.values():
            seen = {feature.slug}
            parent = feature.parent
            while parent is not None:
                assert parent in features, f"{feature.slug} → missing {parent}"
                assert parent not in seen, f"cycle at {feature.slug}"
                seen.add(parent)
                parent = features[parent].parent

    @pytest.mark.parametrize("body", BODY_IDS)
    def test_every_feature_has_a_radius(self, body: str):
        for feature in RING_CATALOGS[body].features:
            assert feature_mid(feature) is not None, feature.slug

    @pytest.mark.parametrize("body", BODY_IDS)
    def test_nested_features_lie_inside_their_parent(self, body: str):
        features = _features(body)
        for feature in features.values():
            if feature.kind not in NESTED_KINDS or feature.parent is None:
                continue
            outer = feature_span(features[feature.parent])
            assert outer is not None, f"{feature.parent} has no span"
            mid = feature_mid(feature)
            assert mid is not None
            for radius in feature_span(feature) or (mid, mid):
                assert _within(radius, *outer), (
                    f"{feature.slug} outside {feature.parent}"
                )

    @pytest.mark.parametrize("body", BODY_IDS)
    def test_siblings_run_inward_to_outward(self, body: str):
        # Mid radius, the order the source tables use, except where an earlier
        # sibling encloses this one: Saturn's E ring spans the three co-orbital
        # rings, which are listed after it and sit well inside its mid radius.
        seen: dict[str | None, float] = {}
        spans: dict[str | None, list[tuple[float, float]]] = {}
        for feature in RING_CATALOGS[body].features:
            mid = feature_mid(feature)
            assert mid is not None
            previous = seen.get(feature.parent)
            enclosed = any(
                low <= mid <= high for low, high in spans.get(feature.parent, [])
            )
            assert previous is None or mid >= previous or enclosed, (
                f"{feature.slug} out of order"
            )
            seen[feature.parent] = max(previous or 0.0, mid)
            if span := feature_span(feature):
                spans.setdefault(feature.parent, []).append(span)

    @pytest.mark.parametrize("body", BODY_IDS)
    def test_optical_depth_ranges_are_ordered(self, body: str):
        for feature in RING_CATALOGS[body].features:
            tau = feature.optical_depth
            if tau is None or tau.high is None:
                continue
            assert tau.low <= tau.high, feature.slug

    def test_wikidata_keys_name_real_features(self):
        for key in RING_FEATURE_PAGES:
            body, _, slug = key.partition("/")
            assert body in RING_CATALOGS, key
            assert slug in _features(body), key


class TestRenderTablesAgree:
    """The rendered strips resolve their geometry from the catalogue rows, so
    only the explicit picks — τ, stand-in widths and spans, thickness figures
    from other sources — can disagree with it. Check those."""

    @staticmethod
    def _rendered(body: str) -> list[RenderedFeature]:
        catalog = RING_CATALOGS[body]
        return [
            feature
            for bundle in catalog.bundles
            for feature in bundle_features(catalog, bundle.name)
        ]

    def test_bundle_names_and_slugs_are_unique(self):
        slugs = [b.slug for c in RING_CATALOGS.values() for b in c.bundles]
        assert len(slugs) == len(set(slugs))
        for body in BODY_IDS:
            names = [b.name for b in RING_CATALOGS[body].bundles]
            assert len(names) == len(set(names)), body

    @pytest.mark.parametrize("body", BODY_IDS)
    def test_render_entries_name_real_bundles(self, body: str):
        # A typoed bundle name would silently drop the feature from every
        # strip rather than fail.
        bundles = {b.name for b in RING_CATALOGS[body].bundles}
        for feature in RING_CATALOGS[body].features:
            for render in feature.render:
                assert render.bundle in bundles, feature.slug

    @pytest.mark.parametrize("body", BODY_IDS)
    def test_rendered_spans_match_the_catalogue(self, body: str):
        features = _features(body)
        for feature in self._rendered(body):
            span = feature_span(features[feature.slug])
            if span is None:
                # Catalogue holds only a radius (the co-orbital rings and the
                # D-ring ringlets); the render span stands in for a width.
                mid = feature_mid(features[feature.slug])
                assert mid is not None
                assert feature.inner_km <= mid <= feature.outer_km, feature.slug
                continue
            assert _within(feature.inner_km, *span), feature.slug
            assert _within(feature.outer_km, *span), feature.slug

    @pytest.mark.parametrize("body", BODY_IDS)
    def test_rendered_optical_depths_match_the_catalogue(self, body: str):
        features = _features(body)
        for feature in self._rendered(body):
            tau = features[feature.slug].optical_depth
            if tau is None:
                continue
            low = tau.low if tau.high is not None else 0.0
            high = tau.high if tau.high is not None else tau.low
            assert low * 0.99 <= feature.optical_depth <= high * 1.01, feature.slug

    @pytest.mark.parametrize("body", BODY_IDS)
    def test_rendered_thickness_matches_the_catalogue(self, body: str):
        features = _features(body)
        for feature in self._rendered(body):
            row = features[feature.slug]
            if not feature.thickness_km or row.thickness_km is None:
                continue
            thickest = max(feature.thickness_km, feature.thickness_outer_km or 0)
            assert thickest <= row.thickness_km * (1 + BOUNDARY_TOLERANCE), feature.slug

    def test_measured_thickness_zones_match_the_catalogue(self):
        features = _features("naif-699")
        for zone in SATURN_MEASURED_THICKNESS:
            row = features[_slug(zone.name)]
            span = feature_span(row)
            assert span is not None
            assert _within(zone.inner_km, *span), zone.name
            assert _within(zone.outer_km, *span), zone.name
