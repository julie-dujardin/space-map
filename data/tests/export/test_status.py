"""Checks for the `/status` freshness report.

The catalog has to stay in step with the download registry — a provider added
without a catalog row would silently vanish from the page — and a row has to
survive metadata that is missing or half-written.
"""

from datetime import timedelta

import pytest

from space_map_data.download.common import SOURCES
from space_map_data.export.status import (
    CATEGORIES,
    SOURCE_CATALOG,
    SourceInfo,
    ordered_catalog,
    source_entry,
)

INFO = SourceInfo("Test source", "https://example.org/", "orbits")


class TestCatalog:
    """The catalog against the download registry it describes."""

    def test_covers_every_provider(self):
        assert set(SOURCE_CATALOG) == set(SOURCES)

    def test_categories_are_known(self):
        assert {i.category for i in SOURCE_CATALOG.values()} <= set(CATEGORIES)

    @pytest.mark.parametrize("name,info", sorted(SOURCE_CATALOG.items()))
    def test_row_is_presentable(self, name, info):
        assert info.label.strip() == info.label and info.label
        assert info.homepage.startswith("https://")


class TestSourceEntry:
    """Row shape, including providers that have never run."""

    def test_full_metadata(self):
        entry = source_entry(
            "demo",
            INFO,
            {
                "downloaded_at": "2026-09-11T20:09:06.422377+00:00",
                "record_count": 70656,
                "source_url": "https://example.org/data.csv",
            },
            timedelta(days=7),
        )
        assert entry == {
            "id": "demo",
            "label": "Test source",
            "homepage": "https://example.org/",
            "category": "orbits",
            "max_age_days": 7,
            "downloaded_at": "2026-09-11T20:09:06.422377+00:00",
            "record_count": 70656,
        }

    def test_no_metadata_keeps_the_row(self):
        entry = source_entry("demo", INFO, None, None)
        assert entry["id"] == "demo"
        assert "downloaded_at" not in entry
        assert "max_age_days" not in entry

    def test_checked_at_only_when_it_differs(self):
        same = source_entry(
            "demo", INFO, {"downloaded_at": "a", "checked_at": "a"}, None
        )
        assert "checked_at" not in same
        moved = source_entry(
            "demo", INFO, {"downloaded_at": "a", "checked_at": "b"}, None
        )
        assert moved["checked_at"] == "b"

    def test_ignores_malformed_fields(self):
        entry = source_entry(
            "demo", INFO, {"downloaded_at": None, "record_count": "lots"}, None
        )
        assert "downloaded_at" not in entry
        assert "record_count" not in entry

    def test_derived_is_flagged(self):
        info = SourceInfo("Derived", "https://example.org/", "orbits", derived=True)
        assert source_entry("demo", info, None, None)["derived"] is True


class TestOrder:
    """Page order — the frontend renders the list as it arrives."""

    def test_grouped_by_category(self):
        seen = [CATEGORIES.index(info.category) for _, info in ordered_catalog()]
        assert seen == sorted(seen)
        assert len(ordered_catalog()) == len(SOURCES)
