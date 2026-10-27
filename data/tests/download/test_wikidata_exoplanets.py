"""Tests for the Wikidata exoplanet item list."""

import gzip
import json

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.exoplanets import wikidata

HEADER = "\t".join(wikidata.COLUMNS)
ROWS = [
    '<http://www.wikidata.org/entity/Q1>\t"51 Peg b"\t"51_peg_b--5"\t12',
    '<http://www.wikidata.org/entity/Q2>\t"HD 160691 d|mu Ara d"\t\t9',
    '<http://www.wikidata.org/entity/Q3>\t\t"11_umi_b--575"\t1',
]
ITEMS = "\n".join([HEADER, *ROWS]) + "\n"


def _downloader(tmp_path, monkeypatch, count: int, items: str = ITEMS):
    monkeypatch.setattr(wikidata, "OUT_DIR", tmp_path)
    monkeypatch.setattr(wikidata, "ITEMS_FILE", tmp_path / "items.tsv.gz")

    def answer(request: httpx.Request) -> httpx.Response:
        if b"tsv_export" in request.content:
            return httpx.Response(200, text=items)
        return httpx.Response(200, text=f"?items\n{count}\n")

    return wikidata.WikidataExoplanetsDownloader(
        httpx.Client(transport=httpx.MockTransport(answer))
    )


class TestReadItems:
    """Each item with all its archive names and exoplanet.eu pages."""

    def test_reads_every_value(self, tmp_path):
        path = tmp_path / "items.tsv.gz"
        path.write_bytes(gzip.compress(ITEMS.encode()))
        assert wikidata.read_items(path) == [
            wikidata.ExoplanetItem("Q1", ("51 Peg b",), ("51_peg_b--5",), 12),
            wikidata.ExoplanetItem("Q2", ("HD 160691 d", "mu Ara d"), (), 9),
            wikidata.ExoplanetItem("Q3", (), ("11_umi_b--575",), 1),
        ]
        assert wikidata.exoplanet_qids(path) == {"Q1", "Q2", "Q3"}

    def test_no_list_before_the_first_download(self, tmp_path):
        assert wikidata.exoplanet_qids(tmp_path / "items.tsv.gz") == set()

    def test_rejects_other_columns(self, tmp_path):
        path = tmp_path / "items.tsv.gz"
        path.write_bytes(gzip.compress(b"?item\t?archive_id\t?articles\n"))
        with pytest.raises(ValueError, match="columns"):
            wikidata.read_items(path)


class TestQuery:
    """The list and its count leave out the same list items."""

    def test_leaves_out_lists(self):
        assert "wd:Q13406463" in wikidata.ITEMS_QUERY
        assert "wd:Q13406463" in wikidata.COUNT_QUERY


class TestDownloader:
    """The count check."""

    def test_writes_a_complete_list(self, tmp_path, monkeypatch):
        _downloader(tmp_path, monkeypatch, 3).download()
        assert len(wikidata.read_items(tmp_path / "items.tsv.gz")) == 3
        metadata = json.loads((tmp_path / "metadata.json").read_text())
        assert metadata["record_count"] == 3

    def test_rejects_a_short_answer(self, tmp_path, monkeypatch):
        with pytest.raises(DownloadError, match="returned 3 items and counts 4"):
            _downloader(tmp_path, monkeypatch, 4).download()
