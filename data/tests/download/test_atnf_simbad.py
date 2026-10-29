"""Tests for the SIMBAD query of the ATNF pulsar names."""

import csv
import json

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import atnf_simbad
from space_map_data.download.providers.stars.atnf_simbad import AtnfSimbadDownloader
from tests.extrasolar.test_class_sources import write_psrcat

# What the fake SIMBAD knows: identifier → oid, main identifier, object type.
KNOWN = {
    "PSR J0146+6145": ["10", "PSR J0146+6145", "Psr"],
    "PSR B0531+21": ["20", "PSR B0531+21", "Psr"],
    "PSR J1808-2024": ["30", "PSR J1808-2024", "gam"],
}


@pytest.fixture
def sent() -> list[str]:
    return []


@pytest.fixture
def downloader(tmp_path, monkeypatch, sent):
    remnants = tmp_path / "catalogues" / "stellar-remnants"
    remnants.mkdir(parents=True)
    (remnants / "metadata.json").write_text("{}")
    monkeypatch.setattr(atnf_simbad, "SOURCES_CATALOGUES_DIR", tmp_path / "catalogues")
    monkeypatch.setattr(
        atnf_simbad, "ATNF_FILE", write_psrcat(tmp_path / "psrcat_pkg.tar.gz")
    )
    monkeypatch.setattr(atnf_simbad, "SIMBAD_FILE", tmp_path / "out" / "names.csv")

    def fake_join(client, url, query, column, datatype, values, chunk):
        assert "join ident" in query
        sent.extend(values)
        rows = [[value, *KNOWN[value]] for value in values if value in KNOWN]
        return ["name", "oid", "main_id", "otype"], rows

    monkeypatch.setattr(atnf_simbad, "tap_join", fake_join)
    return AtnfSimbadDownloader(httpx.Client())


def _rows(path):
    with path.open(newline="") as handle:
        return list(csv.reader(handle))


class TestDownload:
    """names.csv holds every J and B name, with its object where SIMBAD has
    one."""

    def test_sends_the_j_and_b_names(self, downloader, sent):
        downloader.download()
        assert "PSR J0534+2200" in sent
        assert "PSR B0531+21" in sent
        assert "PSR J0104+6029_P" in sent
        assert len(sent) == len(set(sent)) == 11

    def test_writes_names_with_empty_oid_for_unknown(self, downloader):
        downloader.download()
        rows = _rows(atnf_simbad.SIMBAD_FILE)
        assert rows[0] == ["name", "oid", "main_id", "otype"]
        assert rows[1:4] == [
            ["B0531+21", "20", "PSR B0531+21", "Psr"],
            ["B1310+18", "", "", ""],
            ["J0104+6029_P", "", "", ""],
        ]
        assert ["J0146+6145", "10", "PSR J0146+6145", "Psr"] in rows
        assert len(rows) == 12
        meta = json.loads(
            (atnf_simbad.SIMBAD_FILE.parent / "metadata.json").read_text()
        )
        assert meta["names_sent"] == 11
        assert meta["names_resolved"] == 2
        assert meta["complete"] is True

    def test_missing_input_fails(self, downloader):
        (
            atnf_simbad.SOURCES_CATALOGUES_DIR / "stellar-remnants" / "metadata.json"
        ).unlink()
        with pytest.raises(DownloadError, match="run its provider first"):
            downloader.download()

    def test_no_match_fails(self, downloader, monkeypatch):
        monkeypatch.setattr(
            atnf_simbad,
            "tap_join",
            lambda *a: (["name", "oid", "main_id", "otype"], []),
        )
        with pytest.raises(DownloadError, match="matched none"):
            downloader.download()

    def test_a_name_on_two_objects_fails(self, downloader, monkeypatch):
        rows = [
            ["PSR J0146+6145", "10", "PSR J0146+6145", "Psr"],
            ["PSR J0146+6145", "11", "4U 0142+61", "X"],
        ]
        monkeypatch.setattr(
            atnf_simbad,
            "tap_join",
            lambda *a: (["name", "oid", "main_id", "otype"], rows),
        )
        with pytest.raises(DownloadError, match="two objects"):
            downloader.download()
