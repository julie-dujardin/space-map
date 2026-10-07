"""Tests for the IAU star-name downloader."""

import json

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import iau_names
from space_map_data.download.providers.stars.iau_names import (
    IAUStarNamesDownloader,
    parse_names,
)

PAGE = """<html><body>
<table><thead><tr><th>Mo</th><th>Tu</th></tr></thead><tbody><tr><td>18</td><td>19</td></tr></tbody></table>
<table>
  <thead><tr><th>proper names</th><th>Designation</th><th>HIP</th><th>Bayer ID</th></tr></thead>
  <tbody>
    <tr><td> Acamar </td><td>HR 897</td><td>13847</td><td>θ1 Eri</td></tr>
    <tr><td>Absolutno</td><td>see <a href="#">XO-5</a> page</td><td></td><td></td></tr>
    <tr><td colspan="4">footer</td></tr>
  </tbody>
  <tfoot><tr><td>proper names</td><td></td><td></td><td></td></tr></tfoot>
</table>
</body></html>"""


def _downloader(tmp_path, monkeypatch, page: str) -> IAUStarNamesDownloader:
    monkeypatch.setattr(iau_names, "OUT_DIR", tmp_path)
    monkeypatch.setattr(iau_names, "MIN_NAMES", 2)
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=page))
    )
    return IAUStarNamesDownloader(client)


class TestParseNames:
    """Finding the name table among the other tables of the page."""

    def test_rows_are_keyed_by_column_title(self):
        assert parse_names(PAGE) == [
            {
                "proper names": "Acamar",
                "Designation": "HR 897",
                "HIP": "13847",
                "Bayer ID": "θ1 Eri",
            },
            {
                "proper names": "Absolutno",
                "Designation": "see XO-5 page",
                "HIP": "",
                "Bayer ID": "",
            },
        ]

    def test_page_without_the_table_fails(self):
        with pytest.raises(DownloadError, match="No table"):
            parse_names("<table><tr><td>18</td></tr></table>")


class TestDownload:
    """What a run writes, and when it refuses."""

    def test_writes_the_page_and_the_rows(self, tmp_path, monkeypatch):
        dl = _downloader(tmp_path, monkeypatch, PAGE)
        dl.download()
        names = json.loads((tmp_path / "names.json").read_text())
        assert [row["proper names"] for row in names] == ["Acamar", "Absolutno"]
        assert (tmp_path / "names.html").read_text() == PAGE
        assert json.loads(dl.metadata_file.read_text())["record_count"] == 2

    def test_list_much_shorter_than_the_last_one_fails(self, tmp_path, monkeypatch):
        dl = _downloader(tmp_path, monkeypatch, PAGE)
        dl.metadata_file.write_text(json.dumps({"record_count": 40}))
        with pytest.raises(DownloadError, match="at least 38 are expected"):
            dl.download()

    def test_short_list_fails_and_writes_nothing(self, tmp_path, monkeypatch):
        dl = _downloader(tmp_path, monkeypatch, PAGE)
        monkeypatch.setattr(iau_names, "MIN_NAMES", 3)
        with pytest.raises(DownloadError, match="2 rows"):
            dl.download()
        assert not list(tmp_path.iterdir())
