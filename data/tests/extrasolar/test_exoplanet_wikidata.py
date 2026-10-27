"""Tests for the links of the Wikidata exoplanet items to the planets."""

import logging

import pyarrow as pa

from space_map_data.download.providers.exoplanets.wikidata import ExoplanetItem
from space_map_data.extrasolar.exoplanets.catalogues import ARCHIVE, EU
from space_map_data.extrasolar.exoplanets.wikidata import (
    eu_slug,
    link_items,
    planet_qid,
    with_items,
)
from space_map_data.extrasolar.tables import CROSS_ID


def _planets(*rows: tuple[int, int, str | None, list[tuple[str, str]]]) -> pa.Table:
    """Planets table rows: (host, number, designation, [(catalogue, id)])."""
    return pa.Table.from_pylist(
        [
            {
                "host": host,
                "number": number,
                "designation": designation,
                "cross_ids": [
                    {"catalogue": c, "release": "r", "catalogue_id": i} for c, i in ids
                ],
            }
            for host, number, designation, ids in rows
        ],
        pa.schema(
            [
                ("host", pa.int64()),
                ("number", pa.uint16()),
                ("designation", pa.string()),
                ("cross_ids", pa.list_(CROSS_ID)),
            ]
        ),
    )


def _item(qid: str, archive=(), eu=(), articles: int = 1) -> ExoplanetItem:
    return ExoplanetItem(qid, tuple(archive), tuple(eu), articles)


# μ Ara: the archive's d is exoplanet.eu's c.
MU_ARA = _planets(
    (7, 2, "HD 160691 c", [(ARCHIVE, "3.1"), (EU, "mu Ara b")]),
    (7, 3, "HD 160691 d", [(ARCHIVE, "3.2"), (EU, "mu Ara c")]),
    (7, 4, "HD 160691 e", [(ARCHIVE, "3.3"), (EU, "mu Ara d")]),
)


class TestEuSlug:
    """exoplanet.eu names and page ids in one form."""

    def test_a_name_and_its_page(self):
        assert eu_slug("11 UMi b") == eu_slug("11_umi_b--575") == "11_umi_b"

    def test_punctuation_runs(self):
        assert eu_slug("WASP-9 b") == "wasp_9_b"
        assert eu_slug("2MASS J0249-0557 (AB) c") == "2mass_j0249_0557_ab_c"

    def test_an_old_page_id(self):
        assert eu_slug("kepler_22_b") == "kepler_22_b"


class TestLinkItems:
    """An item links to the one planet its ids reach."""

    def test_by_archive_name(self):
        planets = _planets((5, 1, "51 Peg b", [(ARCHIVE, "3.9")]))
        items = [_item("Q1", archive=["51 Peg b"])]
        assert link_items(planets, items).qid == {(5, 1): "Q1"}

    def test_by_exoplanet_eu_page(self):
        planets = _planets((5, 1, "Kepler-22 b", [(EU, "Kepler-22 b")]))
        items = [_item("Q1", eu=["kepler_22_b--12"])]
        assert link_items(planets, items).qid == {(5, 1): "Q1"}

    def test_archive_name_as_the_designation_of_another_catalogue(self):
        # The archive lists Kepler-1658 b, but only OEC's row joined.
        planets = _planets((5, 1, "Kepler-1658 b", [("open-exoplanet-catalogue", "x")]))
        items = [_item("Q1", archive=["Kepler-1658 b"])]
        assert link_items(planets, items).qid == {(5, 1): "Q1"}

    def test_both_ids_on_one_planet(self):
        planets = _planets((5, 1, "51 Peg b", [(ARCHIVE, "3.9"), (EU, "51 Peg b")]))
        item = _item("Q1", archive=["51 Peg b"], eu=["51_peg_b--5"])
        assert link_items(planets, [item]).qid == {(5, 1): "Q1"}

    def test_ids_on_two_planets_link_to_neither(self):
        items = [
            _item("Q931620", archive=["HD 160691 c"], eu=["mu_ara_c--116"]),
            _item("Q1072379", archive=["HD 160691 d"], eu=["mu_ara_d--253"]),
            _item("Q2", archive=["HD 160691 e"], eu=["mu_ara_d--253"]),
        ]
        links = link_items(MU_ARA, items)
        assert links.qid == {(7, 4): "Q2"}
        assert links.several == ["Q931620", "Q1072379"]

    def test_the_item_with_most_articles_keeps_a_planet(self):
        planets = _planets((5, 1, "51 Peg b", [(ARCHIVE, "3.9")]))
        items = [
            _item("Q1", archive=["51 Peg b"], articles=3),
            _item("Q2", archive=["51 Peg b"], articles=9),
            _item("Q3", archive=["51 Peg b"], articles=9),
        ]
        assert link_items(planets, items).qid == {(5, 1): "Q2"}

    def test_a_star_item_reaches_no_planet(self, caplog):
        planets = _planets((5, 1, "51 Peg b", [(ARCHIVE, "3.9")]))
        with caplog.at_level(logging.INFO):
            links = link_items(planets, [_item("Q1", archive=["51 Peg"])])
        assert (links.qid, links.unlinked) == ({}, 1)
        assert "1 items reach no planet" in caplog.text


class TestWithItems:
    """The planets table keeps each link as a cross id."""

    def test_the_qid_joins_the_cross_ids(self):
        links = link_items(MU_ARA, [_item("Q2", archive=["HD 160691 e"])])
        rows = with_items(MU_ARA, links).to_pylist()
        assert [planet_qid(row["cross_ids"]) for row in rows] == [None, None, "Q2"]
        assert rows[2]["cross_ids"][:2] == MU_ARA.to_pylist()[2]["cross_ids"]
