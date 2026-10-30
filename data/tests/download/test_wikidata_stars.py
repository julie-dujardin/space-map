"""Tests for the download of the Wikidata star items."""

import gzip
import json

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import wikidata_stars
from space_map_data.download.providers.stars.wikidata_stars import (
    COUNT_QUERY,
    ITEMS_QUERY,
    NOT_STAR_QIDS,
    STAR_QIDS,
    STAR_ROOT_QIDS,
    SYSTEM_ROOT_QIDS,
    StarItem,
    WikidataStarsDownloader,
    parse_term,
    read_items,
)

HEADER = "\t".join(wikidata_stars.COLUMNS)
ENTITY = "http://www.wikidata.org/entity/"
# The star and system classes of Proxima and of Algol, as QLever gives them.
ROWS = [
    (
        '<http://www.wikidata.org/entity/Q14266>\t"5853498713190525696"\t"HIP 70890"\t\t'
        '"Proxima Centauri"@en\t"Proxima Centauri"@mul\t12'
        f'\t"{ENTITY}Q285400|{ENTITY}Q5893"\t'
    ),
    (
        '<http://www.wikidata.org/entity/Q1146698>\t"4375233191015944192|4375236218971926400"'
        '\t"HIP 85295"\t"HD 157881"\t"Gliese 673"@en\t\t7\t\t'
    ),
    (
        '<http://www.wikidata.org/entity/Q13080>\t\t"HIP 14576"\t"HD 19356"\t"Algol"@en\t\t12'
        f'\t"{ENTITY}Q24452"'
        f'\t"{ENTITY}Q1993624|{ENTITY}Q24452|{ENTITY}Q13890"'
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
                star_classes=("Q285400", "Q5893"),
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
            StarItem(
                qid="Q13080",
                gaia_dr3=(),
                hip=("14576",),
                hd=("19356",),
                label_en="Algol",
                label_mul=None,
                articles=12,
                star_classes=("Q24452",),
                system_classes=("Q1993624", "Q24452", "Q13890"),
            ),
        ]
        assert wikidata_stars.star_qids(path) == {"Q14266", "Q1146698", "Q13080"}

    @pytest.mark.parametrize(
        ("hd", "expected"),
        [
            ('"HD 48915A"', ("48915",)),
            ('"HD 48915 A"', ("48915",)),
            ('"HD 48915A|HD 48915"', ("48915",)),
            ('"HD 48915B"', ()),
            ('"HD 189733 b"', ()),
            ('"HD 126614Ab"', ()),
            ('"HD 1|HD 2"', ("1", "2")),
        ],
    )
    def test_the_component_a_of_an_hd_number(self, tmp_path, hd, expected):
        path = tmp_path / "items.tsv.gz"
        row = f'<http://www.wikidata.org/entity/Q3409>\t\t"HIP 7A"\t{hd}\t\t\t12\t\t'
        path.write_bytes(gzip.compress(f"{HEADER}\n{row}\n".encode()))
        (found,) = read_items(path)
        assert (found.hd, found.hip) == (expected, ())

    def test_a_gaia_id_off_the_sky_is_skipped(self, tmp_path, caplog):
        # 12 * 4**12 << 35 is the first id past the last level-12 pixel.
        path = tmp_path / "items.tsv.gz"
        row = (
            "<http://www.wikidata.org/entity/Q14266>"
            '\t"6917529027641081856|5853498713190525696"\t\t\t\t\t12\t\t'
        )
        path.write_bytes(gzip.compress(f"{HEADER}\n{row}\n".encode()))
        (found,) = read_items(path)
        assert found.gaia_dr3 == ("5853498713190525696",)
        assert "Q14266: skipped the Gaia DR3 ids out of range" in caplog.text

    @pytest.mark.parametrize(
        "header",
        [
            ("?item", "?n"),
            # The list of 2026-10-30, with the WDS designations and all classes.
            (
                "?item",
                "?gaia_dr3",
                "?hip",
                "?hd",
                "?label_en",
                "?label_mul",
                "?articles",
                "?wds",
                "?classes",
                "?star_classes",
                "?system_classes",
            ),
        ],
    )
    def test_other_columns_fail(self, tmp_path, header):
        path = tmp_path / "items.tsv.gz"
        path.write_bytes(gzip.compress(("\t".join(header) + "\n").encode()))
        with pytest.raises(ValueError, match="columns"):
            read_items(path)

    def test_no_list_yet(self, tmp_path):
        assert wikidata_stars.star_qids(tmp_path / "items.tsv.gz") == set()


class TestQuery:
    """The list and its count leave out the same objects that are not stars.
    The list gives the classes that are a kind of star or of star system."""

    def test_both_queries_filter_by_type(self):
        for query in (ITEMS_QUERY, COUNT_QUERY):
            assert query.count("MINUS") == 2
            for qid in (*NOT_STAR_QIDS, *STAR_QIDS):
                assert f"wd:{qid} " in query

    def test_the_list_gives_the_classes_of_a_star_or_a_system(self):
        assert "?wds" not in ITEMS_QUERY
        assert "?item wdt:P31 ?class ." not in ITEMS_QUERY
        for qid in (*STAR_ROOT_QIDS, *SYSTEM_ROOT_QIDS):
            assert f"wd:{qid} " in ITEMS_QUERY
        assert "?star_class wdt:P279* ?star_root" in ITEMS_QUERY
        assert "?system_class wdt:P279* ?system_root" in ITEMS_QUERY
        assert "wdt:P31 ?class" not in COUNT_QUERY


class TestDownloader:
    """The count check and the floor from the previous download."""

    def test_writes_the_items(self, tmp_path, monkeypatch):
        _downloader(tmp_path, monkeypatch, 3).download()
        assert len(read_items(tmp_path / "items.tsv.gz")) == 3
        metadata = json.loads((tmp_path / "metadata.json").read_text())
        assert metadata["record_count"] == 3

    def test_a_short_answer_fails(self, tmp_path, monkeypatch):
        with pytest.raises(DownloadError, match="returned 3 items and counts 4"):
            _downloader(tmp_path, monkeypatch, 4).download()
        assert not (tmp_path / "items.tsv.gz").exists()

    def test_a_bad_answer_fails_and_leaves_no_part(self, tmp_path, monkeypatch):
        items = ITEMS.replace('"Gliese 673"@en', '"Gliese 673')
        with pytest.raises(DownloadError, match="unterminated"):
            _downloader(tmp_path, monkeypatch, 3, items).download()
        assert list(tmp_path.glob("items.tsv.gz*")) == []

    def test_a_large_loss_fails(self, tmp_path, monkeypatch):
        (tmp_path / "metadata.json").write_text(json.dumps({"record_count": 100}))
        with pytest.raises(DownloadError, match="at least 95"):
            _downloader(tmp_path, monkeypatch, 3).download()
