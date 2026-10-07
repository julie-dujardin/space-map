"""Tests for the options of the shared resumable file fetch."""

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.three_d import resumable
from space_map_data.download.providers.three_d.resumable import download_resumable

PAGE = b"<html><table></table></html>"
HTML = {"content-type": "text/html; charset=UTF-8"}


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(resumable, "RETRY_WAIT_SECONDS", 0)


class TestResumable:
    """The options of the shared file fetch that the provider uses."""

    def test_a_resume_names_the_file_it_started(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Range"] == "bytes=4-"
            assert request.headers["If-Range"] == '"v1"'
            return httpx.Response(206, content=b"5678")

        dest = tmp_path / "file.bin"
        (tmp_path / "file.bin.part").write_bytes(b"1234")
        (tmp_path / "file.bin.part.meta").write_text('"v1"')
        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert download_resumable(client, "https://example.test/file.bin", dest)
        assert dest.read_bytes() == b"12345678"

    def test_a_changed_upstream_file_starts_again(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"new file", headers={"etag": '"v2"'})

        dest = tmp_path / "file.bin"
        (tmp_path / "file.bin.part").write_bytes(b"old-")
        (tmp_path / "file.bin.part.meta").write_text('"v1"')
        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert download_resumable(client, "https://example.test/file.bin", dest)
        assert dest.read_bytes() == b"new file"

    def test_replace_fetches_over_a_file_on_disk(self, tmp_path):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"new"))
        )
        dest = tmp_path / "file.bin"
        dest.write_bytes(b"old")
        download_resumable(client, "https://example.test/file.bin", dest)
        assert dest.read_bytes() == b"old"
        download_resumable(client, "https://example.test/file.bin", dest, replace=True)
        assert dest.read_bytes() == b"new"

    def test_a_failed_check_keeps_the_file_on_disk(self, tmp_path):
        def refuse(path):
            raise DownloadError("bad")

        client = httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"new"))
        )
        dest = tmp_path / "file.bin"
        dest.write_bytes(b"old")
        with pytest.raises(DownloadError):
            download_resumable(
                client, "https://example.test/f", dest, replace=True, check=refuse
            )
        assert dest.read_bytes() == b"old"
        assert not (tmp_path / "file.bin.part").exists()

    def test_an_html_body_needs_the_html_option(self, tmp_path):
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=PAGE, headers=HTML)
            )
        )
        assert not download_resumable(client, "https://example.test/f", tmp_path / "a")
        assert download_resumable(
            client, "https://example.test/f", tmp_path / "b.html", html=True
        )

    def test_a_server_error_is_tried_again(self, tmp_path):
        answers = [httpx.Response(503), httpx.Response(200, content=b"ok")]
        client = httpx.Client(transport=httpx.MockTransport(lambda r: answers.pop(0)))
        assert download_resumable(client, "https://example.test/f", tmp_path / "f")
        assert (tmp_path / "f").read_bytes() == b"ok"
