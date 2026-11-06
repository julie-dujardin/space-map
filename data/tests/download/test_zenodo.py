"""Tests for the record of a Zenodo deposit."""

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.zenodo import ZENODO_URL, ZenodoFile, fetch_record


def entry(name: str, **fields: object) -> dict:
    """A file entry in the form of a recorded Zenodo answer."""
    return {
        "id": "4aa9f1d4-b079-497d-b621-df90b967a87b",
        "key": name,
        "checksum": "md5:34d44081ac70e8abfb8f8581408a1ae0",
        "links": {"self": f"https://zenodo.test/1/{name}"},
        **fields,
    }


def record(body: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{ZENODO_URL}/1"
        return httpx.Response(200, json=body)

    return fetch_record(httpx.Client(transport=httpx.MockTransport(handler)), 1)


FULL = {
    "metadata": {"license": {"id": "cc-by-4.0"}},
    "files": [entry("a.fits", size=3616), entry("b.py", size=12)],
}


class TestFile:
    """A caller that takes files only reads their URL and MD5."""

    def test_a_file_has_its_url_and_md5(self):
        assert record(FULL).file("a.fits") == ZenodoFile(
            "a.fits",
            "https://zenodo.test/1/a.fits",
            "34d44081ac70e8abfb8f8581408a1ae0",
        )

    @pytest.mark.parametrize(
        "metadata", [{}, {"license": "cc-by-4.0"}, {"license": {"title": "CC BY"}}]
    )
    def test_no_size_and_any_licence_form_are_accepted(self, metadata):
        body = {"metadata": metadata, "files": [entry("a.fits")]}
        assert record(body).file("a.fits").url == "https://zenodo.test/1/a.fits"

    def test_an_other_entry_without_a_checksum_is_not_read(self):
        other = {"key": "b.py", "links": {"self": "https://zenodo.test/1/b.py"}}
        body = {"files": [entry("a.fits"), other]}
        assert record(body).file("a.fits").name == "a.fits"

    def test_a_missing_file_fails(self):
        with pytest.raises(DownloadError, match="no file c.txt"):
            record(FULL).file("c.txt")

    def test_a_file_without_a_checksum_fails(self):
        body = {"files": [{"key": "a.fits", "links": {"self": "u"}}]}
        with pytest.raises(DownloadError, match="unexpected a.fits"):
            record(body).file("a.fits")

    @pytest.mark.parametrize("body", [{}, {"files": [{"size": 1}]}, []])
    def test_a_record_without_file_names_fails(self, body):
        with pytest.raises(DownloadError, match="unexpected record"):
            record(body)


class TestSizesAndLicence:
    """A caller that checks sizes or the licence asks for them, and a record without
    them is refused."""

    def test_the_sizes_and_the_licence(self):
        full = record(FULL)
        assert full.sizes() == {"a.fits": 3616, "b.py": 12}
        assert full.license() == "cc-by-4.0"

    def test_a_record_that_states_no_licence_has_none(self):
        assert record({"files": [], "metadata": {}}).license() is None

    @pytest.mark.parametrize("size", [None, "many"])
    def test_a_file_without_a_size_is_refused(self, size):
        fields = {} if size is None else {"size": size}
        body = {"files": [entry("a.fits", size=1), entry("b.py", **fields)]}
        with pytest.raises(DownloadError, match="unexpected sizes"):
            record(body).sizes()

    @pytest.mark.parametrize(
        "metadata", [{"license": {}}, {"license": "cc-by-4.0"}, "cc-by-4.0"]
    )
    def test_a_licence_in_another_form_is_refused(self, metadata):
        body = {"metadata": metadata, "files": []}
        with pytest.raises(DownloadError, match="unexpected licence"):
            record(body).license()
