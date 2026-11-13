"""Tests for the Wikidata ID resolver."""

from pathlib import Path
from typing import cast

import httpx
import pytest
from sqlalchemy.orm import Session

from space_map_data.constants.providers import ID_TYPES
from space_map_data.download.providers.wikidata.id_resolver import (
    WikidataIdResolver,
    _our_forms,
)


class _Session:
    """Holds the Object SPK-IDs the resolver matches P716 against."""

    def __init__(self, spkids: list[int]) -> None:
        self.spkids = spkids

    def scalars(self, stmt):
        return iter(self.spkids)


def _row(qid: str, value: str) -> dict:
    return {
        "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "id": {"value": value},
    }


@pytest.fixture
def client():
    with httpx.Client() as c:
        yield c


@pytest.fixture
def make_resolver(tmp_path, monkeypatch, client):
    def make(spkids, rows) -> WikidataIdResolver:
        resolver = WikidataIdResolver(client, cast(Session, _Session(spkids)), tmp_path)
        query = rows if callable(rows) else (lambda query: rows)
        monkeypatch.setattr(resolver, "_sparql_query", query)
        return resolver

    return make


class TestOurForms:
    """How a Wikidata value maps onto the IDs we hold."""

    def test_norad_is_zero_padded(self):
        assert _our_forms(ID_TYPES.NORAD_SATCAT, "5") == ("00005",)

    def test_horizons_numbered_spkid(self):
        assert _our_forms(ID_TYPES.SPKID, "2046373") == ("2046373", "20046373")

    def test_old_unnumbered_spkid(self):
        assert _our_forms(ID_TYPES.SPKID, "3781359") == ("3781359", "50781382")

    def test_others_as_given(self):
        assert _our_forms(ID_TYPES.COSPAR, "1998-067A") == ("1998-067A",)


class TestResolve:
    """Every value of a property against the IDs we hold, by SPK-ID."""

    def test_keeps_only_our_ids(self, tmp_path, make_resolver):
        resolver = make_resolver(
            [54667839, 1000019],
            [
                _row("Q141895716", "54667839"),
                _row("Q2554066", "1000019"),
                _row("Q1", "99999999"),
                _row("Q2", "not-a-number"),
            ],
        )
        assert resolver.resolve([ID_TYPES.SPKID]) == {"Q141895716", "Q2554066"}
        assert resolver._read_ids_csv("P716") == {
            "1000019": ["Q2554066"],
            "54667839": ["Q141895716"],
        }

    def test_horizons_numbered_form(self, tmp_path, make_resolver):
        resolver = make_resolver([20046373], [_row("Q62825462", "2046373")])
        resolver.resolve([ID_TYPES.SPKID])
        assert resolver._read_ids_csv("P716") == {"20046373": ["Q62825462"]}

    def test_a_value_we_hold_is_not_shifted(self, tmp_path, make_resolver):
        resolver = make_resolver([2046373], [_row("Q9", "2046373")])
        resolver.resolve([ID_TYPES.SPKID])
        assert resolver._read_ids_csv("P716") == {"2046373": ["Q9"]}

    def test_several_items_per_id(self, tmp_path, make_resolver):
        resolver = make_resolver(
            [20612891],
            [_row("Q25421068", "2612891"), _row("Q118970886", "20612891")],
        )
        resolver.resolve([ID_TYPES.SPKID])
        assert resolver._read_ids_csv("P716") == {
            "20612891": ["Q118970886", "Q25421068"]
        }

    def test_rewrites_the_match_file(self, tmp_path, make_resolver):
        resolver = make_resolver([54667839], [_row("Q141895716", "54667839")])
        (tmp_path / "matches").mkdir()
        resolver._write_ids_csv("P716", {"3788040": ["Q5"], "54667839": ["Q6"]})
        resolver.resolve([ID_TYPES.SPKID])
        assert resolver._read_ids_csv("P716") == {"54667839": ["Q141895716"]}

    def test_no_match_keeps_the_file(self, tmp_path, make_resolver):
        resolver = make_resolver([], [_row("Q141895716", "54667839")])
        (tmp_path / "matches").mkdir()
        resolver._write_ids_csv("P716", {"54667839": ["Q141895716"]})
        assert resolver.resolve([ID_TYPES.SPKID]) == {"Q141895716"}
        assert resolver._read_ids_csv("P716") == {"54667839": ["Q141895716"]}

    def test_an_empty_answer_keeps_the_file(self, tmp_path, make_resolver):
        resolver = make_resolver([54667839], [])
        (tmp_path / "matches").mkdir()
        resolver._write_ids_csv("P716", {"54667839": ["Q141895716"]})
        resolver.resolve([ID_TYPES.SPKID])
        assert resolver._read_ids_csv("P716") == {"54667839": ["Q141895716"]}

    def test_a_large_drop_keeps_the_file(self, tmp_path, make_resolver):
        resolver = make_resolver([1], [_row("Q1", "1")])
        (tmp_path / "matches").mkdir()
        old = {str(n): [f"Q{n}"] for n in range(1, 202)}
        resolver._write_ids_csv("P716", old)
        resolver.resolve([ID_TYPES.SPKID])
        assert resolver._read_ids_csv("P716") == old

    def test_a_held_drop_still_adds_new_rows(self, tmp_path, make_resolver):
        resolver = make_resolver([999], [_row("Q999", "999")])
        (tmp_path / "matches").mkdir()
        old = {str(n): [f"Q{n}"] for n in range(1, 202)}
        resolver._write_ids_csv("P716", old)
        resolver.resolve([ID_TYPES.SPKID])
        assert resolver._read_ids_csv("P716") == {**old, "999": ["Q999"]}

    def test_a_failed_query_keeps_the_file(self, tmp_path, make_resolver):
        def fail(query):
            raise RuntimeError("SPARQL failed after retries")

        resolver = make_resolver([54667839], fail)
        (tmp_path / "matches").mkdir()
        resolver._write_ids_csv("P716", {"54667839": ["Q141895716"]})
        assert resolver.resolve([ID_TYPES.SPKID]) == {"Q141895716"}
        assert resolver._read_ids_csv("P716") == {"54667839": ["Q141895716"]}


class TestSparqlQuery:
    """A cut-off answer is asked again."""

    def test_retries_a_truncated_answer(self, monkeypatch):
        from space_map_data.download.providers.wikidata import id_resolver

        bodies = [b'{"results": {"bindings": [{"x"', b'{"results": {"bindings": []}}']
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, content=bodies.pop(0))
        )
        monkeypatch.setattr(id_resolver.time, "sleep", lambda s: None)
        with httpx.Client(transport=transport) as client:
            resolver = WikidataIdResolver(
                client, cast(Session, _Session([])), Path(".")
            )
            assert resolver._sparql_query("SELECT") == []

    def test_retries_a_server_error(self, monkeypatch):
        from space_map_data.download.providers.wikidata import id_resolver

        responses = [
            httpx.Response(500),
            httpx.Response(200, json={"results": {"bindings": []}}),
        ]
        transport = httpx.MockTransport(lambda request: responses.pop(0))
        monkeypatch.setattr(id_resolver.time, "sleep", lambda s: None)
        with httpx.Client(transport=transport) as client:
            resolver = WikidataIdResolver(
                client, cast(Session, _Session([])), Path(".")
            )
            assert resolver._sparql_query("SELECT") == []
