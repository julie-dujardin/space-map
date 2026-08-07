"""Unit tests for the Wikipedia summary downloader."""

import json
from pathlib import Path

import httpx

from space_map_data.download.providers.wikipedia import (
    Task,
    WikipediaDownloader,
    _is_redirect_stub,
)


class _Resp:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _Client:
    """httpx.Client stand-in replying with one canned page set, recording params."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.params: list[dict] = []

    def get(self, url: str, **kwargs: object) -> _Resp:
        self.params.append(dict(kwargs.get("params") or {}))  # type: ignore[arg-type]
        return _Resp(self.payload)


def _page(title: str, extract: str = "", **extra: object) -> dict:
    return {"title": title, "extract": extract, **extra}


def _downloader(payload: dict, out_dir: Path) -> tuple[WikipediaDownloader, _Client]:
    client = _Client(payload)
    downloader = WikipediaDownloader(client)  # type: ignore[arg-type]
    downloader.out_dir = out_dir
    return downloader, client


class TestRedirectResolution:
    """Whose article a stored summary comes from when the sitelink redirects."""

    def test_a_renamed_article_is_stored_under_the_asking_qid(
        self, tmp_path: Path
    ) -> None:
        payload = {
            "query": {
                "redirects": [{"from": "Planetary ring", "to": "Ring system"}],
                "pages": [_page("Ring system", "A ring system is a disc...")],
            }
        }
        downloader, _ = _downloader(payload, tmp_path)

        downloader._fetch_batch(
            "en",
            [Task("Q179792", "Planetary ring", True)],
            tmp_path,
            follow_redirects=True,
        )

        stored = json.loads((tmp_path / "Q179792.json").read_text())
        assert stored["title"] == "Ring system"
        assert stored["extract"].startswith("A ring system")

    def test_a_redirect_into_a_section_stores_nothing(self, tmp_path: Path) -> None:
        """The lead of the parent article is not about the subject asked for."""
        payload = {
            "query": {
                "redirects": [
                    {
                        "from": "Cassini Division",
                        "to": "Rings of Saturn",
                        "tofragment": "Cassini Division",
                    }
                ],
                "pages": [_page("Rings of Saturn", "Saturn has the most extensive...")],
            }
        }
        downloader, _ = _downloader(payload, tmp_path)

        downloader._fetch_batch(
            "en",
            [Task("Q508315", "Cassini Division", True)],
            tmp_path,
            follow_redirects=True,
        )

        assert not (tmp_path / "Q508315.json").exists()

    def test_normalization_before_a_redirect_still_resolves(
        self, tmp_path: Path
    ) -> None:
        payload = {
            "query": {
                "normalized": [{"from": "venera", "to": "Venera"}],
                "redirects": [{"from": "Venera", "to": "Venera program"}],
                "pages": [_page("Venera program", "The Venera program...")],
            }
        }
        downloader, _ = _downloader(payload, tmp_path)

        downloader._fetch_batch(
            "en", [Task("Q192144", "venera", True)], tmp_path, follow_redirects=True
        )

        assert json.loads((tmp_path / "Q192144.json").read_text())["title"] == (
            "Venera program"
        )

    def test_two_qids_redirecting_to_one_page_both_get_it(self, tmp_path: Path) -> None:
        """The API answers with one page; the reply is indexed by title, so a
        title-to-QID map would have dropped one of them."""
        payload = {
            "query": {
                "redirects": [
                    {"from": "Ring", "to": "Ring system"},
                    {"from": "Planetary ring", "to": "Ring system"},
                ],
                "pages": [_page("Ring system", "A ring system is a disc...")],
            }
        }
        downloader, _ = _downloader(payload, tmp_path)

        downloader._fetch_batch(
            "en",
            [Task("Q1", "Ring", True), Task("Q2", "Planetary ring", True)],
            tmp_path,
            follow_redirects=True,
        )

        assert (tmp_path / "Q1.json").exists()
        assert (tmp_path / "Q2.json").exists()

    def test_objects_do_not_ask_the_api_to_follow_redirects(
        self, tmp_path: Path
    ) -> None:
        """An asteroid's sitelink redirects into a list of minor planets, whose
        lead is about the list. The parameter is omitted, not sent false: the
        API reads any value as true."""
        payload = {"query": {"pages": [_page("7509 Gamzatov")]}}
        downloader, client = _downloader(payload, tmp_path)

        downloader._fetch_batch(
            "en",
            [Task("Q1031378", "7509 Gamzatov", False)],
            tmp_path,
            follow_redirects=False,
        )

        assert "redirects" not in client.params[0]


class TestRefetchingStubs:
    """Which stored pages a later run replaces."""

    def test_a_stub_left_by_an_unresolved_redirect_is_refetched(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "Q179792.json"
        path.write_text(
            json.dumps({"title": "Planetary ring", "extract": "", "redirect": True})
        )
        assert _is_redirect_stub(path)

    def test_an_article_with_no_intro_is_left_alone(self, tmp_path: Path) -> None:
        """Nothing to redo — refetching would return the same empty extract."""
        path = tmp_path / "Q1.json"
        path.write_text(json.dumps({"title": "Some list", "extract": ""}))
        assert not _is_redirect_stub(path)

    def test_a_stored_summary_is_not_a_stub(self, tmp_path: Path) -> None:
        path = tmp_path / "Q2.json"
        path.write_text(json.dumps({"title": "Ring system", "extract": "A ring..."}))
        assert not _is_redirect_stub(path)


def test_downloader_uses_the_shared_metadata_dir() -> None:
    """Guards the constructor against a stray out_dir when tests rebind it."""
    downloader = WikipediaDownloader(httpx.Client())
    assert downloader.out_dir.name == "wikipedia"
