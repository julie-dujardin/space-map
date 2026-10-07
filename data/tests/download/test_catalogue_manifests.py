"""Tests for the catalogue manifests and their loader."""

import pytest
import yaml

from space_map_data.constants.manifests import catalogues
from space_map_data.constants.manifests.catalogues import (
    MANIFESTS_DIR,
    CdsFiles,
    RemoteFile,
    ZenodoFiles,
    load_catalogues,
)

GROUPS = sorted(path.stem for path in MANIFESTS_DIR.glob("*.yaml"))

ENTRY = {
    "key": "a-catalogue",
    "title": "A catalogue",
    "reference": "Author 2024",
    "license": "CC BY 4.0",
    "terms_url": "https://example.test/terms",
    "distribution": "open",
    "urls": ["https://example.test/data/table.csv"],
}


@pytest.fixture
def load(tmp_path, monkeypatch):
    """Load a manifest made of the given entries."""
    monkeypatch.setattr(catalogues, "MANIFESTS_DIR", tmp_path)

    def run(*entries: dict):
        (tmp_path / "test.yaml").write_text(yaml.safe_dump({"catalogues": entries}))
        return load_catalogues("test")

    return run


class TestManifests:
    """The manifests in the repository."""

    def test_one_manifest_for_each_object_class(self):
        assert GROUPS == [
            "black-holes",
            "galaxies",
            "nebulae",
            "star-clusters",
            "stellar-remnants",
            "transients",
        ]

    @pytest.mark.parametrize("group", GROUPS)
    def test_every_entry_is_valid(self, group):
        assert load_catalogues(group)

    @pytest.mark.parametrize("group", GROUPS)
    def test_a_source_with_no_licence_is_undecided(self, group):
        cleared = [
            c.key
            for c in load_catalogues(group)
            if c.license.startswith("None stated") and c.distribution != "undecided"
        ]
        assert not cleared

    def test_no_key_is_used_by_two_manifests(self):
        keys = [c.key for group in GROUPS for c in load_catalogues(group)]
        assert len(keys) == len(set(keys))


class TestLoader:
    """What the loader reads from one entry."""

    def test_a_plain_url_keeps_its_file_name(self, load):
        (entry,) = load(ENTRY)
        assert entry.urls == (
            RemoteFile("https://example.test/data/table.csv", "table.csv"),
        )
        assert entry.refresh_days is None

    def test_a_url_mapping_can_name_and_post(self, load):
        url = {
            "url": "https://example.test/export",
            "name": "export.csv",
            "method": "POST",
            "data": {"all": "1"},
        }
        (entry,) = load(ENTRY | {"urls": [url]})
        assert entry.urls == (
            RemoteFile(
                "https://example.test/export", "export.csv", "POST", (("all", "1"),)
            ),
        )

    def test_cds_and_zenodo_sources(self, load):
        source = {
            "urls": None,
            "cds": {"catalogue": "J/A+A/1/A1", "files": ["main.dat.gz"]},
            "zenodo": {"record": 42},
            "refresh_days": 30,
        }
        (entry,) = load(ENTRY | source)
        assert entry.cds == CdsFiles("J/A+A/1/A1", ("main.dat.gz",))
        assert entry.zenodo == ZenodoFiles(42)
        assert entry.refresh_days == 30

    @pytest.mark.parametrize(
        "change,message",
        [
            ({"key": "Not A Slug"}, "lower-case slug"),
            ({"license": ""}, "`license` is missing"),
            ({"terms_url": None}, "`terms_url` is missing"),
            ({"distribution": "free"}, "unknown distribution"),
            ({"urls": []}, "no `cds`, `zenodo` or `urls`"),
            ({"refresh_day": 7}, "unknown fields"),
            ({"refresh_days": "30"}, "whole number of days"),
            ({"urls": [{"url": "https://example.test/a", "nmae": "a"}]}, "URL fields"),
            ({"urls": ["https://a.test/t.csv", "https://b.test/t.csv"]}, "repeated"),
            ({"urls": ["https://example.test/ReadMe"]}, "writes"),
        ],
    )
    def test_a_bad_entry_is_refused(self, load, change, message):
        with pytest.raises(ValueError, match=message):
            load(ENTRY | change)

    def test_a_repeated_key_is_refused(self, load):
        with pytest.raises(ValueError, match="repeated keys"):
            load(ENTRY, ENTRY)
