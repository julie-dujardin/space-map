"""Tests for the download of the Wikidata star items."""

import gzip
import json

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import wikidata_stars
from space_map_data.download.providers.stars.wikidata_stars import (
    StarItem,
    WikidataStarsDownloader,
    parse_term,
    read_items,
)

HEADER = "\t".join(wikidata_stars.COLUMNS)
ROWS = [
    (
        '<http://www.wikidata.org/entity/Q14266>\t"5853498713190525696"\t"HIP 70890"\t\t'
        '"Proxima Centauri"@en\t"Proxima Centauri"@mul\t12'
    ),
    (
        '<http://www.wikidata.org/entity/Q1146698>\t"4375233191015944192|4375236218971926400"'
        '\t"HIP 85295"\t"HD 157881"\t"Gliese 673"@en\t\t7'
    ),
]
ITEMS = "\n".join([HEADER, *ROWS]) + "\n"


def _downloader(
    tmp_path, monkeypatch, count: int, items: str = ITEMS
) -> WikidataStarsDownloader:
    monkeypatch.setattr(wikidata_stars, "OUT_DIR", tmp_path)
    monkeypatch.setattr(wikidata_stars, "ITEMS_FILE", tmp_path / "items.tsv.gz")

    def answer(request: httpx.Request) -> httpx.Response:
        if b"tsv_export" in request.content:
            return httpx.Response(200, text=items)
        return httpx.Response(200, text=f"?items\n{count}\n")

    return WikidataStarsDownloader(httpx.Client(transport=httpx.MockTransport(answer)))


class TestParseTerm:
    """The values of SPARQL TSV terms."""

    @pytest.mark.parametrize(
        ("term", "expected"),
        [
            ("<http://www.wikidata.org/entity/Q14266>", "Q14266"),
            ('"Proxima Centauri"@en', "Proxima Centauri"),
            ('"12"^^<http://www.w3.org/2001/XMLSchema#int>', "12"),
            (r'"Teegarden\'s \"Star\""@en', 'Teegarden\'s "Star"'),
            (r'"a\bb\fc"@en', "a\bb\fc"),
            ("12", "12"),
            ("", None),
        ],
    )
    def test_terms(self, term, expected):
        assert parse_term(term) == expected

    @pytest.mark.parametrize(
        ("term", "error"),
        [(r'"a\qb"@en', "unknown escape"), ('"Proxima', "unterminated")],
    )
    def test_a_bad_literal_fails(self, term, error):
        with pytest.raises(ValueError, match=error):
            parse_term(term)


class TestReadItems:
    """Rows of the item list as StarItems."""

    def test_rows(self, tmp_path):
        path = tmp_path / "items.tsv.gz"
        path.write_bytes(gzip.compress(ITEMS.encode()))
        assert read_items(path) == [
            StarItem(
                qid="Q14266",
                gaia_dr3=("5853498713190525696",),
                hip=("70890",),
                hd=(),
                label_en="Proxima Centauri",
                label_mul="Proxima Centauri",
                articles=12,
            ),
            StarItem(
                qid="Q1146698",
                gaia_dr3=("4375233191015944192", "4375236218971926400"),
                hip=("85295",),
                hd=("157881",),
                label_en="Gliese 673",
                label_mul=None,
                articles=7,
            ),
        ]
        assert wikidata_stars.star_qids(path) == {"Q14266", "Q1146698"}

    def test_a_gaia_id_off_the_sky_is_skipped(self, tmp_path, caplog):
        # 12 * 4**12 << 35 is the first id past the last level-12 pixel.
        path = tmp_path / "items.tsv.gz"
        row = (
            "<http://www.wikidata.org/entity/Q14266>"
            '\t"6917529027641081856|5853498713190525696"\t\t\t\t\t12'
        )
        path.write_bytes(gzip.compress(f"{HEADER}\n{row}\n".encode()))
        (found,) = read_items(path)
        assert found.gaia_dr3 == ("5853498713190525696",)
        assert "Q14266: skipped the Gaia DR3 ids out of range" in caplog.text

    def test_other_columns_fail(self, tmp_path):
        path = tmp_path / "items.tsv.gz"
        path.write_bytes(gzip.compress(b"?item\t?n\n"))
        with pytest.raises(ValueError, match="columns"):
            read_items(path)

    def test_no_list_yet(self, tmp_path):
        assert wikidata_stars.star_qids(tmp_path / "items.tsv.gz") == set()


class TestDownloader:
    """The count check and the floor from the previous download."""

    def test_writes_the_items(self, tmp_path, monkeypatch):
        _downloader(tmp_path, monkeypatch, 2).download()
        assert len(read_items(tmp_path / "items.tsv.gz")) == 2
        metadata = json.loads((tmp_path / "metadata.json").read_text())
        assert metadata["record_count"] == 2

    def test_a_short_answer_fails(self, tmp_path, monkeypatch):
        with pytest.raises(DownloadError, match="returned 2 items and counts 3"):
            _downloader(tmp_path, monkeypatch, 3).download()
        assert not (tmp_path / "items.tsv.gz").exists()

    def test_a_bad_answer_fails_and_leaves_no_part(self, tmp_path, monkeypatch):
        items = ITEMS.replace('"Gliese 673"@en', '"Gliese 673')
        with pytest.raises(DownloadError, match="unterminated"):
            _downloader(tmp_path, monkeypatch, 2, items).download()
        assert list(tmp_path.glob("items.tsv.gz*")) == []

    def test_a_large_loss_fails(self, tmp_path, monkeypatch):
        (tmp_path / "metadata.json").write_text(json.dumps({"record_count": 100}))
        with pytest.raises(DownloadError, match="at least 95"):
            _downloader(tmp_path, monkeypatch, 2).download()
