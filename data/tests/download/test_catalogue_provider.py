"""Tests for the manifest-driven catalogue downloader."""

import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from space_map_data.constants.manifests.catalogues import (
    Catalogue,
    CdsFiles,
    RemoteFile,
    ZenodoFiles,
)
from space_map_data.download.cds import CDS_URL
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.catalogues import fetch, provider
from space_map_data.download.providers.catalogues.fetch import post_lines_gz
from space_map_data.download.providers.catalogues.provider import (
    ZENODO_URL,
    CatalogueDownloader,
)
from space_map_data.download.providers.three_d import resumable

README = """J/A+A/1/A1          A test catalogue                    (Author+, 2024)
================================================================================
File Summary:
--------------------------------------------------------------------------------
 FileName      Lrecl  Records   Explanations
--------------------------------------------------------------------------------
ReadMe            80        .   This file
main.dat         100        3   Main catalogue
notes.dat         80        2   Notes
--------------------------------------------------------------------------------

See also:
 J/A+A/2/A2 : Another catalogue
"""

ARCHIVE = b"zip bytes"
PAGE = b"<html><table></table></html>"
EXPORT = b"a,b\n1,2\n"
MAIN = f"{CDS_URL}/J/A+A/1/A1/main.dat.gz"
LIST = "https://example.test/list.html"
HTML = {"content-type": "text/html; charset=UTF-8"}


def catalogue(
    key: str,
    cds: CdsFiles | None = None,
    zenodo: ZenodoFiles | None = None,
    urls: tuple[RemoteFile, ...] = (),
    refresh_days: int | None = None,
) -> Catalogue:
    return Catalogue(
        key=key,
        title="Test",
        reference="Author 2024",
        license="None stated.",
        terms_url="https://example.test/terms",
        distribution="undecided",
        cds=cds,
        zenodo=zenodo,
        urls=urls,
        refresh_days=refresh_days,
    )


CDS = catalogue("cds-one", cds=CdsFiles("J/A+A/1/A1", ("main.dat.gz", "notes.dat")))
ZENODO = catalogue("zenodo-one", zenodo=ZenodoFiles(42))
ONE_PAGE = catalogue("plain-one", urls=(RemoteFile(LIST, "list.html"),))
PLAIN = catalogue(
    "plain-one",
    urls=(
        RemoteFile(LIST, "list.html"),
        RemoteFile("https://example.test/table.csv", "table.csv"),
    ),
)
# The form answer makes the export, as a session would.
FORM = catalogue(
    "form-one",
    urls=(
        RemoteFile("https://example.test/form", "form.html", "POST", (("all", "1"),)),
        RemoteFile("https://example.test/export", "export.csv"),
    ),
)


class Server:
    """A fake of CDS, Zenodo and one plain site. It records each request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.files: dict[str, bytes] = {
            f"{CDS_URL}/J/A+A/1/A1/ReadMe": README.encode(),
            MAIN: gzip.compress(b"a\nb\nc\n"),
            f"{CDS_URL}/J/A+A/1/A1/notes.dat": b"x\ny\n",
            "https://zenodo.test/42/archive.zip": ARCHIVE,
            LIST: PAGE,
            "https://example.test/table.csv": EXPORT,
            "https://example.test/form": PAGE,
        }
        self.md5 = hashlib.md5(ARCHIVE).hexdigest()
        self.record: object = None
        self.posted = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(ZENODO_URL):
            number = url.rsplit("/", 1)[-1]
            entry = {
                "key": "archive.zip",
                "checksum": f"md5:{self.md5}",
                "links": {"self": f"https://zenodo.test/{number}/archive.zip"},
            }
            return httpx.Response(200, json=self.record or {"files": [entry]})
        if url == "https://example.test/export":
            body = EXPORT if self.posted else b"\n"
            self.posted = False
            return httpx.Response(200, content=body)
        if url == "https://example.test/form":
            self.posted = True
        if url not in self.files:
            return httpx.Response(404)
        headers = HTML if url.endswith((".html", "/form")) else {}
        return httpx.Response(200, content=self.files[url], headers=headers)

    def fetched(self, suffix: str) -> int:
        return sum(str(r.url).endswith(suffix) for r in self.requests)


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(resumable, "RETRY_WAIT_SECONDS", 0)
    monkeypatch.setattr(fetch, "RETRY_WAIT_SECONDS", 0)


@pytest.fixture
def server() -> Server:
    server = Server()
    server.files["https://zenodo.test/43/archive.zip"] = ARCHIVE
    return server


@pytest.fixture
def make(tmp_path, monkeypatch, server):
    """Build a downloader over the given catalogues."""

    class Provider(CatalogueDownloader):
        name = "test_catalogues"
        group = "test"

    client = httpx.Client(
        transport=httpx.MockTransport(server),
        headers={"User-Agent": "space-map-bot/0.1 (a@b.test)"},
    )
    monkeypatch.setattr(provider, "SOURCES_CATALOGUES_DIR", tmp_path)

    def build(*catalogues: Catalogue) -> CatalogueDownloader:
        monkeypatch.setattr(provider, "load_catalogues", lambda group: list(catalogues))
        return Provider(client)

    return build


def metadata(tmp_path) -> dict:
    return json.loads((tmp_path / "test/metadata.json").read_text())


class TestDownload:
    """One run over the three kinds of source."""

    def test_writes_each_file_as_published(self, make, tmp_path):
        make(CDS, ZENODO, PLAIN).download()
        out = tmp_path / "test"
        assert (
            gzip.decompress((out / "cds-one/main.dat.gz").read_bytes()) == b"a\nb\nc\n"
        )
        assert (out / "cds-one/ReadMe").read_text() == README
        assert (out / "zenodo-one/archive.zip").read_bytes() == ARCHIVE
        assert json.loads((out / "zenodo-one/record.json").read_text())["files"]
        assert (out / "plain-one/list.html").read_bytes() == PAGE
        assert (out / "plain-one/table.csv").read_bytes() == EXPORT

    def test_records_the_url_and_size_of_each_file(self, make, tmp_path):
        make(ZENODO, PLAIN).download()
        meta = metadata(tmp_path)
        assert meta["complete"] is True
        assert meta["record_count"] == 2
        assert meta["catalogues"]["plain-one"]["files"] == {
            "list.html": {"url": LIST, "bytes": len(PAGE)},
            "table.csv": {
                "url": "https://example.test/table.csv",
                "bytes": len(EXPORT),
            },
        }
        assert meta["catalogues"]["zenodo-one"]["zenodo"] == 42

    def test_cds_requests_carry_no_bot_token(self, make, server):
        make(CDS, PLAIN).download()
        agents = {r.url.host: r.headers["User-Agent"] for r in server.requests}
        assert "bot" not in agents["cdsarc.cds.unistra.fr"]
        assert "a@b.test" in agents["cdsarc.cds.unistra.fr"]
        assert agents["example.test"] == "space-map-bot/0.1 (a@b.test)"

    def test_a_forced_run_fetches_no_file_again(self, make, server):
        downloader = make(CDS, ZENODO, PLAIN)
        downloader.download()
        downloader.download()
        assert server.fetched("main.dat.gz") == 1
        assert server.fetched("archive.zip") == 1
        assert server.fetched("list.html") == 1

    def test_a_forced_run_restores_a_missing_file(self, make, server, tmp_path):
        downloader = make(PLAIN)
        downloader.download()
        (tmp_path / "test/plain-one/table.csv").unlink()
        downloader.download()
        assert (tmp_path / "test/plain-one/table.csv").read_bytes() == EXPORT
        assert server.fetched("list.html") == 1


class TestChecks:
    """A file that fails its check never takes its name."""

    def test_wrong_record_count_fails_the_catalogue(self, make, server, tmp_path):
        server.files[MAIN] = gzip.compress(b"a\n")
        with pytest.raises(DownloadError, match="1 of 2 catalogues failed: cds-one"):
            make(CDS, PLAIN).download()
        assert not (tmp_path / "test/cds-one/main.dat.gz").exists()

    def test_a_headline_is_not_a_record(self, make, server, tmp_path):
        server.files[MAIN] = gzip.compress(b"# name\na\nb\nc\n")
        make(CDS).download()
        assert (tmp_path / "test/cds-one/main.dat.gz").exists()

    def test_the_other_catalogues_still_land(self, make, server, tmp_path):
        server.files[MAIN] = b"not gzip"
        with pytest.raises(DownloadError, match="cds-one"):
            make(CDS, PLAIN).download()
        meta = metadata(tmp_path)
        assert meta["complete"] is False
        assert list(meta["catalogues"]) == ["plain-one"]
        assert (tmp_path / "test/plain-one/list.html").exists()
        assert not (tmp_path / "test/cds-one/main.dat.gz").exists()

    def test_wrong_md5_fails_the_catalogue(self, make, server, tmp_path):
        server.md5 = "0" * 32
        with pytest.raises(DownloadError, match="zenodo-one"):
            make(ZENODO).download()
        assert not (tmp_path / "test/zenodo-one/archive.zip").exists()

    def test_an_unexpected_zenodo_record_fails_the_catalogue(
        self, make, server, tmp_path
    ):
        server.record = {"files": [{"key": "archive.zip"}]}
        with pytest.raises(DownloadError, match="1 of 2 catalogues failed"):
            make(ZENODO, PLAIN).download()
        assert list(metadata(tmp_path)["catalogues"]) == ["plain-one"]

    def test_missing_file_fails_the_catalogue(self, make, server):
        del server.files[LIST]
        with pytest.raises(DownloadError, match="plain-one"):
            make(PLAIN).download()

    def test_an_empty_file_fails_the_catalogue(self, make, server, tmp_path):
        server.files["https://example.test/table.csv"] = b""
        with pytest.raises(DownloadError, match="plain-one"):
            make(PLAIN).download()
        assert not (tmp_path / "test/plain-one/table.csv").exists()

    def test_a_failed_refresh_keeps_the_last_good_file(self, make, server, tmp_path):
        living = catalogue("cds-one", cds=CDS.cds, refresh_days=7)
        downloader = make(living)
        downloader.download()
        age(tmp_path, "cds-one", days=8)
        server.files[MAIN] = gzip.compress(b"a\n")
        with pytest.raises(DownloadError):
            downloader.download()
        kept = (tmp_path / "test/cds-one/main.dat.gz").read_bytes()
        assert gzip.decompress(kept) == b"a\nb\nc\n"
        assert "cds-one" in metadata(tmp_path)["catalogues"]


def age(tmp_path, key: str, days: int) -> None:
    """Move the fetch date of one catalogue into the past."""
    path = tmp_path / "test/metadata.json"
    meta = json.loads(path.read_text())
    old = datetime.now(timezone.utc) - timedelta(days=days)
    meta["catalogues"][key]["fetched_at"] = old.isoformat()
    path.write_text(json.dumps(meta))


class TestCompleteness:
    """When a finished provider runs again, and what it then fetches."""

    def test_complete_after_a_clean_run(self, make):
        downloader = make(CDS, PLAIN)
        downloader.download()
        assert downloader.is_complete(None)

    def test_a_new_entry_is_the_only_one_requested(self, make, server):
        make(CDS).download()
        before = len(server.requests)
        downloader = make(CDS, ZENODO)
        assert not downloader.is_complete(None)
        downloader.download()
        hosts = {r.url.host for r in server.requests[before:]}
        assert hosts == {"zenodo.org", "zenodo.test"}

    def test_a_new_file_of_a_catalogue_is_the_only_one_fetched(self, make, server):
        make(ONE_PAGE).download()
        downloader = make(PLAIN)
        assert not downloader.is_complete(None)
        downloader.download()
        assert server.fetched("list.html") == 1
        assert server.fetched("table.csv") == 1

    def test_a_changed_url_fetches_the_file_again(self, make, server, tmp_path):
        make(ONE_PAGE).download()
        server.files["https://example.test/v2/list.html"] = b"<html>v2</html>"
        moved = catalogue(
            "plain-one",
            urls=(RemoteFile("https://example.test/v2/list.html", "list.html"),),
        )
        downloader = make(moved)
        assert not downloader.is_complete(None)
        downloader.download()
        assert (
            tmp_path / "test/plain-one/list.html"
        ).read_bytes() == b"<html>v2</html>"

    def test_a_changed_zenodo_record_fetches_the_file_again(self, make, server):
        make(ZENODO).download()
        downloader = make(catalogue("zenodo-one", zenodo=ZenodoFiles(43)))
        assert not downloader.is_complete(None)
        downloader.download()
        assert server.fetched("43/archive.zip") == 1

    def test_a_file_the_manifest_drops_is_deleted(self, make, tmp_path):
        make(PLAIN).download()
        make(ONE_PAGE).download()
        assert not (tmp_path / "test/plain-one/table.csv").exists()
        assert (tmp_path / "test/plain-one/list.html").exists()
        assert list(metadata(tmp_path)["catalogues"]["plain-one"]["files"]) == [
            "list.html"
        ]

    def test_a_lapsed_refresh_fetches_again(self, make, server, tmp_path):
        living = catalogue("plain-one", urls=ONE_PAGE.urls, refresh_days=7)
        downloader = make(living)
        downloader.download()
        assert downloader.is_complete(None)
        age(tmp_path, "plain-one", days=8)
        assert not downloader.is_complete(None)
        downloader.download()
        assert server.fetched("list.html") == 2
        assert downloader.is_complete(None)


class TestForm:
    """A catalogue whose file exists only after a form is posted."""

    def test_posts_the_form_fields_before_the_file(self, make, server, tmp_path):
        make(FORM).download()
        post = next(r for r in server.requests if r.method == "POST")
        assert post.content == b"all=1"
        assert (tmp_path / "test/form-one/export.csv").read_bytes() == EXPORT

    def test_a_missing_file_posts_the_form_again(self, make, server, tmp_path):
        downloader = make(FORM)
        downloader.download()
        (tmp_path / "test/form-one/export.csv").unlink()
        downloader.download()
        assert sum(r.method == "POST" for r in server.requests) == 2
        assert (tmp_path / "test/form-one/export.csv").read_bytes() == EXPORT


class TestQueryAnswer:
    """The gzip writer of a query answer."""

    def run(self, tmp_path, answers, check=lambda part, lines: None):
        client = httpx.Client(transport=httpx.MockTransport(lambda r: answers.pop(0)))
        dest = tmp_path / "rows.csv.gz"
        return dest, lambda: post_lines_gz(
            client, "https://example.test/tap", dest, data={"q": "x"}, check=check
        )

    def test_counts_the_lines(self, tmp_path):
        dest, post = self.run(tmp_path, [httpx.Response(200, content=b"h\n1\n2\n")])
        assert post() == 3
        assert gzip.decompress(dest.read_bytes()) == b"h\n1\n2\n"

    def test_a_server_error_is_tried_again(self, tmp_path):
        answers = [httpx.Response(503), httpx.Response(200, content=b"h\n")]
        dest, post = self.run(tmp_path, answers)
        assert post() == 1

    def test_a_refused_query_is_not_tried_again(self, tmp_path):
        dest, post = self.run(tmp_path, [httpx.Response(400)])
        with pytest.raises(DownloadError, match="HTTP 400"):
            post()

    def test_a_failed_check_keeps_the_last_answer(self, tmp_path):
        def refuse(part, lines):
            raise DownloadError("short")

        dest, post = self.run(
            tmp_path, [httpx.Response(200, content=b"h\n")], check=refuse
        )
        dest.write_bytes(b"last good")
        with pytest.raises(DownloadError, match="short"):
            post()
        assert dest.read_bytes() == b"last good"
        assert not (tmp_path / "rows.csv.gz.part").exists()
