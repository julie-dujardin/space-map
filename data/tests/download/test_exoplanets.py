"""Unit tests for the exoplanet downloaders."""

import csv
import gzip
import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote_plus

import httpx
import pytest

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.exoplanets import (
    exoplanet_eu,
    gaia,
    names,
    nasa_archive,
    simbad,
    tap,
)
from space_map_data.download.providers.exoplanets.exoplanet_eu import (
    export_form,
    status_counts,
)
from space_map_data.download.providers.exoplanets.gaia import (
    ExoplanetGaiaDownloader,
    gaia_ids,
)
from space_map_data.download.providers.exoplanets.names import (
    CSV_SOURCES,
    NO_COMPONENT,
    CsvSource,
    Name,
    component_variants,
    csv_names,
    oec_names,
    without_component,
)
from space_map_data.download.providers.exoplanets.nasa_archive import (
    TABLES,
    ArchiveTable,
    ExoplanetArchiveDownloader,
    check_table,
)
from space_map_data.download.providers.exoplanets.open_catalogue import count_objects
from space_map_data.download.providers.exoplanets.simbad import (
    ExoplanetSimbadDownloader,
    drop_large_parents,
    log_coverage,
)
from space_map_data.download.providers.exoplanets.tap import (
    tap_join,
    tap_sync,
    tap_to_file,
    votable,
)

_URL = "https://tap.test/sync"
_VOTABLE_NS = {"v": "http://www.ivoa.net/xml/VOTable/v1.3"}
_TAP_ERROR = (
    '<?xml version="1.0"?><VOTABLE><RESOURCE type="results">'
    '<INFO name="QUERY_STATUS" value="ERROR">\nTable nope is not available.\n</INFO>'
    "</RESOURCE></VOTABLE>"
)
_OEC = b"""<systems><system><name>Kepler-16</name>
<binary><name>Kepler-16 (AB)</name>
  <star><name>Kepler-16 A</name><name>KIC 12644769 A</name></star>
  <star><name>Kepler-16 B</name></star>
  <planet><name>Kepler-16 (AB) b</name><name>Kepler-16 b</name></planet>
</binary></system>
<system><name>Sun</name><binary><star><name>Sun</name></star></binary></system>
</systems>"""


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _answer(status: int, body: str) -> httpx.Client:
    return _client(lambda request: httpx.Response(status, text=body))


def _sent(request: httpx.Request) -> tuple[str, list[str]]:
    """The query text of a TAP request and the values it uploads."""
    body = unquote_plus(request.content.decode())
    return body, re.findall(r"<TD>(.*?)</TD>", body)


def _read(path: Path) -> list[list[str]]:
    with path.open(newline="") as fh:
        return list(csv.reader(fh))


@pytest.fixture(autouse=True)
def no_retry_pause(monkeypatch):
    monkeypatch.setattr(tap, "RETRY_PAUSE_SECONDS", 0)


class TestVotable:
    """The uploaded table is valid XML with one typed column."""

    def test_char_column_escapes_markup(self):
        root = ET.fromstring(votable("name", "char", ["R&D <1>", "HD 1"]))
        field = root.find(".//v:FIELD", _VOTABLE_NS)
        assert field is not None
        assert field.attrib == {"name": "name", "datatype": "char", "arraysize": "*"}
        cells = [cell.text for cell in root.iterfind(".//v:TD", _VOTABLE_NS)]
        assert cells == ["R&D <1>", "HD 1"]

    def test_long_column_has_no_arraysize(self):
        root = ET.fromstring(votable("oid", "long", [3262054]))
        field = root.find(".//v:FIELD", _VOTABLE_NS)
        assert field is not None
        assert field.attrib == {"name": "oid", "datatype": "long"}


class TestTapSync:
    """A TAP error arrives as a VOTable and must not pass as data."""

    def test_returns_the_csv_body(self):
        with _answer(200, "count\n3\n") as client:
            assert tap_sync(client, _URL, "q") == "count\n3\n"

    @pytest.mark.parametrize("status", [200, 400, 500])
    def test_error_votable_raises_with_the_reason(self, status):
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(status, text=_TAP_ERROR)

        with _client(handler) as client:
            with pytest.raises(DownloadError, match="Table nope is not available"):
                tap_sync(client, _URL, "q")
        assert calls == 1

    def test_empty_answer_raises(self):
        with _answer(200, "") as client:
            with pytest.raises(DownloadError, match="empty answer"):
                tap_sync(client, _URL, "q")

    def test_upload_goes_as_the_table_named_sent(self):
        seen: list[bytes] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.content)
            return httpx.Response(200, text="name\n")

        with _client(handler) as client:
            tap_sync(client, _URL, "q", upload=b"<VOTABLE/>")
        assert b"sent,param:sent" in seen[0]
        assert b'name="sent"; filename="sent.xml"' in seen[0]

    @pytest.mark.parametrize("failure", ["timeout", 429, 503])
    def test_unanswered_query_is_sent_again(self, failure):
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls > 1:
                return httpx.Response(200, text="count\n3\n")
            if failure == "timeout":
                raise httpx.ReadTimeout("no answer", request=request)
            return httpx.Response(failure, text="busy")

        with _client(handler) as client:
            assert tap_sync(client, _URL, "q") == "count\n3\n"
        assert calls == 2

    def test_silent_service_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("no answer", request=request)

        with _client(handler) as client:
            with pytest.raises(DownloadError, match="did not answer: no answer"):
                tap_sync(client, _URL, "q")


class TestTapToFile:
    """A large table goes to disk without a copy in memory."""

    def test_writes_the_body(self, tmp_path):
        with _answer(200, "a,b\n1,2\n") as client:
            tap_to_file(client, _URL, "q", tmp_path / "t.csv")
        assert (tmp_path / "t.csv").read_text() == "a,b\n1,2\n"

    @pytest.mark.parametrize("status", [200, 400])
    def test_error_votable_raises(self, tmp_path, status):
        with _answer(status, _TAP_ERROR) as client:
            with pytest.raises(DownloadError, match="Table nope is not available"):
                tap_to_file(client, _URL, "q", tmp_path / "t.csv")


class TestTapJoin:
    """Values go up in chunks and the rows come back as one table."""

    def test_merges_the_chunks(self):
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, text=f"name,oid\nHD {calls},{calls}\n")

        with _client(handler) as client:
            header, rows = tap_join(client, _URL, "q", "name", "char", list("abcde"), 2)
        assert calls == 3
        assert header == ["name", "oid"]
        assert rows == [["HD 1", "1"], ["HD 2", "2"], ["HD 3", "3"]]

    def test_nothing_to_send_raises(self):
        with _answer(200, "name\n") as client:
            with pytest.raises(DownloadError, match="No id to send"):
                tap_join(client, _URL, "q", "id", "long", [], 2)


class TestCheckTable:
    """An Exoplanet Archive table must be whole and keep its key columns."""

    table = ArchiveTable("pscomppars", ("pl_name", "hostname"), "planets")

    def _check(self, tmp_path: Path, body: str, rows: int) -> None:
        path = tmp_path / "t.csv"
        path.write_text(body)
        check_table(self.table, path, rows)

    def test_accepts_a_whole_table(self, tmp_path):
        self._check(tmp_path, "pl_name,hostname\nA b,A\nC b,C\n", 2)

    def test_quoted_line_break_is_one_row(self, tmp_path):
        self._check(tmp_path, 'pl_name,hostname\nA b,"A\nB"\n', 1)

    def test_missing_column_raises(self, tmp_path):
        with pytest.raises(DownloadError, match="no column hostname"):
            self._check(tmp_path, "pl_name,host\nA b,A\n", 1)

    def test_empty_file_raises(self, tmp_path):
        with pytest.raises(DownloadError, match="no column pl_name, hostname"):
            self._check(tmp_path, "", 0)

    def test_short_table_raises(self, tmp_path):
        with pytest.raises(DownloadError, match="1 rows, the archive counts 2"):
            self._check(tmp_path, "pl_name,hostname\nA b,A\n", 2)


class TestArchiveDownload:
    """The tables on disk are always one generation."""

    tables = (
        ArchiveTable("pscomppars", ("a",), "first"),
        ArchiveTable("two", ("a",), "second"),
    )

    def _downloader(self, monkeypatch, tmp_path, bodies: dict[str, str]):
        def handler(request: httpx.Request) -> httpx.Response:
            query, _ = _sent(request)
            table = query.rsplit(" ", 1)[-1]
            if "count(*)" in query:
                return httpx.Response(200, text="count(*)\n2\n")
            return httpx.Response(200, text=bodies[table])

        monkeypatch.setattr(nasa_archive, "OUT_DIR", tmp_path)
        monkeypatch.setattr(nasa_archive, "TABLES", self.tables)
        return ExoplanetArchiveDownloader(_client(handler))

    def test_writes_every_table(self, monkeypatch, tmp_path):
        bodies = {"pscomppars": "a\n1\n2\n", "two": "a\n3\n4\n"}
        self._downloader(monkeypatch, tmp_path, bodies).download()
        assert (tmp_path / "pscomppars.csv").read_text() == "a\n1\n2\n"
        assert (tmp_path / "two.csv").read_text() == "a\n3\n4\n"
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "metadata.json",
            "pscomppars.csv",
            "two.csv",
        ]

    def test_failed_table_leaves_the_old_files(self, monkeypatch, tmp_path):
        (tmp_path / "pscomppars.csv").write_text("old")
        bodies = {"pscomppars": "a\n1\n2\n", "two": "a\n3\n"}
        with pytest.raises(DownloadError, match="two has 1 rows"):
            self._downloader(monkeypatch, tmp_path, bodies).download()
        assert [p.name for p in tmp_path.iterdir()] == ["pscomppars.csv"]
        assert (tmp_path / "pscomppars.csv").read_text() == "old"


class TestExoplanetEuExport:
    """The export posts the site's own form with every status ticked."""

    page = (
        '<input type="hidden" name="csrfmiddlewaretoken" value="tok3n">'
        '<input id="status_1" name="status_1" checked>'
        '<input id="status_2" name="status_2"><input id="status_4" name="status_4">'
    )
    header = "name,alternate_names,star_name,star_alternate_names,planet_status"

    def test_form_ticks_every_status_box(self):
        assert export_form(self.page) == {
            "csrfmiddlewaretoken": "tok3n",
            "query_f": "",
            "status_1": "on",
            "status_2": "on",
            "status_4": "on",
        }

    def test_page_without_the_form_raises(self):
        with pytest.raises(DownloadError, match="no filter form"):
            export_form("<html>maintenance</html>")

    def test_counts_rows_per_status(self):
        body = f"{self.header}\na,,,,Confirmed\nb,,,,Candidate\nc,,,,Confirmed\n"
        assert status_counts(body) == {"Confirmed": 2, "Candidate": 1}

    def test_missing_column_raises(self):
        with pytest.raises(DownloadError, match="no column star_name, star_alt"):
            status_counts("name,alternate_names,planet_status\na,,Confirmed\n")

    def test_non_catalogue_body_raises(self):
        with pytest.raises(DownloadError, match="exoplanet.eu export has no column"):
            status_counts("<!DOCTYPE html><html>403</html>")


class TestOpenCatalogueCounts:
    """The OEC file must unpack to a `systems` document."""

    def test_counts_each_element_kind(self):
        assert count_objects(gzip.compress(_OEC)) == {
            "system": 2,
            "binary": 2,
            "star": 3,
            "planet": 1,
        }

    def test_other_root_element_raises(self):
        with pytest.raises(DownloadError, match="<html>"):
            count_objects(gzip.compress(b"<html/>"))


class TestWithoutComponent:
    """Only a component letter or a microlensing lens suffix is dropped."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("HD 109271 A", "HD 109271"),
            ("HD 106906 (AB)", "HD 106906"),
            ("b Cen (AB)", "b Cen"),
            ("GJ 667 ABC", "GJ 667"),
            ("OGLE-2005-BLG-390L", "OGLE-2005-BLG-390"),
            ("KMT-2019-BLG-1806L", "KMT-2019-BLG-1806"),
            ("PSR J1824-2452L", None),
            ("HD 2039", None),
            ("WASP-12", None),
            ("V830 Tau", None),
            ("A", None),
        ],
    )
    def test_cases(self, name, expected):
        assert without_component(name) == expected


class TestCatalogueNames:
    """Every name and alias of an object is collected under the object's key."""

    def _source(self, tmp_path: Path, **kwargs) -> CsvSource:
        path = tmp_path / "catalog.csv"
        path.write_text(
            "star_name,alts,tid,kepoi_name\n"
            'HD 1 A,"HIP 5, GJ 9",42,K00752.01\n'
            ",orphan,7,K00001.01\n"
            "HD 2\n"
        )
        return CsvSource(PROVIDERS.EXOPLANET_EU, path, "star", "star_name", **kwargs)

    def test_reads_plain_list_and_rewritten_columns(self, tmp_path):
        source = self._source(
            tmp_path,
            columns=("star_name",),
            lists=("alts",),
            formatted=(("tid", "TIC {}".format), ("kepoi_name", names._koi)),
        )
        found = csv_names(source)
        assert {n.name for n in found if n.object == "HD 1 A"} == {
            "HD 1 A",
            "HIP 5",
            "GJ 9",
            "TIC 42",
            "KOI-752.01",
        }
        assert {n.table for n in found} == {"catalog"}

    def test_row_without_a_key_gives_no_name(self, tmp_path):
        found = csv_names(self._source(tmp_path, lists=("alts",)))
        assert {n.object for n in found} == {"HD 1 A"}

    def test_short_row_reads_as_empty_cells(self, tmp_path):
        found = csv_names(self._source(tmp_path, columns=("star_name",)))
        assert Name("exoplanet_eu", "catalog", "star", "HD 2", "HD 2") in found

    def test_missing_column_raises_with_the_file_name(self, tmp_path):
        source = self._source(tmp_path, columns=("star_name", "toipfx"))
        with pytest.raises(DownloadError, match="catalog.csv has no column toipfx"):
            csv_names(source)

    def test_variant_is_added_for_stars_only(self):
        star = Name("exoplanet_eu", "catalog", "star", "HD 1 A", "HD 1 A")
        planet = Name("exoplanet_eu", "catalog", "planet", "HD 1 B", "HD 1 B")
        assert component_variants({star, planet}) == {
            Name("exoplanet_eu", "catalog", "star", "HD 1 A", "HD 1", NO_COMPONENT)
        }

    def test_variant_never_repeats_a_printed_name(self):
        printed = {
            Name("exoplanet_eu", "catalog", "star", "HD 1 A", "HD 1 A"),
            Name("exoplanet_eu", "catalog", "star", "HD 1 A", "HD 1"),
        }
        assert component_variants(printed) == set()

    def test_oec_names_key_on_the_first_name(self, tmp_path):
        path = tmp_path / "systems.xml.gz"
        path.write_bytes(gzip.compress(_OEC))
        oec = PROVIDERS.OPEN_EXOPLANET_CATALOGUE
        assert oec_names(path) == {
            Name(oec, "systems", "binary", "Kepler-16 (AB)", "Kepler-16 (AB)"),
            Name(oec, "systems", "star", "Kepler-16 A", "Kepler-16 A"),
            Name(oec, "systems", "star", "Kepler-16 A", "KIC 12644769 A"),
            Name(oec, "systems", "star", "Kepler-16 B", "Kepler-16 B"),
            Name(oec, "systems", "star", "Sun", "Sun"),
            Name(oec, "systems", "planet", "Kepler-16 (AB) b", "Kepler-16 (AB) b"),
            Name(oec, "systems", "planet", "Kepler-16 (AB) b", "Kepler-16 b"),
        }


class TestReadColumnsAreChecked:
    """A column that the name collection reads is one its download checks."""

    @pytest.mark.parametrize("source", CSV_SOURCES, ids=lambda s: f"{s.table}-{s.kind}")
    def test_source_columns_are_download_columns(self, source):
        if source.catalogue == PROVIDERS.EXOPLANET_EU:
            checked = set(exoplanet_eu.COLUMNS)
        else:
            checked = {c for t in TABLES if t.name == source.table for c in t.columns}
        assert set(source.read_columns) <= checked


class TestInputReader:
    """A provider that reads other providers' files follows those files."""

    def _downloader(self, monkeypatch, tmp_path: Path) -> ExoplanetGaiaDownloader:
        out = tmp_path / "gaia"
        monkeypatch.setattr(gaia, "OUT_DIR", out)
        monkeypatch.setattr(ExoplanetGaiaDownloader, "inputs", (tmp_path / "ids.csv",))
        downloader = ExoplanetGaiaDownloader(_answer(200, ""))
        (tmp_path / "ids.csv").write_text("Gaia DR3 5")
        downloader._save_metadata(_URL, 1, complete=True)
        return downloader

    def test_complete_while_the_input_is_older(self, monkeypatch, tmp_path):
        downloader = self._downloader(monkeypatch, tmp_path)
        os.utime(tmp_path / "ids.csv", (0, 0))
        assert downloader.is_complete(None)

    def test_newer_input_forces_a_run(self, monkeypatch, tmp_path):
        downloader = self._downloader(monkeypatch, tmp_path)
        later = downloader.metadata_file.stat().st_mtime + 60
        os.utime(tmp_path / "ids.csv", (later, later))
        assert not downloader.is_complete(None)

    def test_missing_input_forces_a_run_that_names_it(self, monkeypatch, tmp_path):
        downloader = self._downloader(monkeypatch, tmp_path)
        (tmp_path / "ids.csv").unlink()
        assert not downloader.is_complete(None)
        with pytest.raises(DownloadError, match="ids.csv is missing"):
            downloader.download()


class TestSimbadHelpers:
    """Coverage is logged honestly and cluster members stay out."""

    def test_variant_only_match_is_counted_apart(self, caplog):
        found = [
            Name("exoplanet_eu", "catalog", "star", "HD 1 A", "HD 1 A"),
            Name("exoplanet_eu", "catalog", "star", "HD 1 A", "HD 1", NO_COMPONENT),
            Name("exoplanet_eu", "catalog", "star", "HD 2", "HD 2"),
            Name("exoplanet_eu", "catalog", "star", "HD 3", "HD 3"),
        ]
        with caplog.at_level(logging.INFO):
            log_coverage(found, {"HD 1": "1", "HD 2": "2"})
        assert "exoplanet_eu star: 1 of 3 in SIMBAD, 1 more" in caplog.text

    def test_parent_with_many_children_loses_its_links(self, monkeypatch):
        monkeypatch.setattr(simbad, "MAX_CHILDREN", 2)
        header = ["child", "link_bibcode", "membership", "parent"]
        links = [[str(n), "", "", "9"] for n in range(3)] + [["7", "", "", "8"]]
        assert drop_large_parents(header, links) == [["7", "", "", "8"]]


class TestSimbadDownload:
    """The four files agree on the objects they hold."""

    oid_of = {"HD 1": "1", "HIP 5": "1", "HD 1 A b": "2"}
    # 3 is a planet that no catalogue names. 4 is its host. 7 is the parent of 1.
    links = [("2", "", "", "1"), ("3", "", "", "4"), ("1", "", "", "7")]

    def _handler(self, request: httpx.Request) -> httpx.Response:
        query, sent = _sent(request)
        if "otype in" in query:
            rows = [("oid",), ("2",), ("3",)]
        elif "join ident" in query:
            matched = [(n, self.oid_of[n]) for n in sent if n in self.oid_of]
            rows = [("name", "oidref"), *matched]
        elif "h.child = s.oid" in query:
            rows = [("child", "link_bibcode", "membership", "parent")]
            rows += [link for link in self.links if link[0] in sent]
        elif "h.parent = s.oid" in query:
            rows = [("child", "link_bibcode", "membership", "parent")]
            rows += [link for link in self.links if link[3] in sent]
        elif "join basic" in query:
            rows = [("oid", "main_id"), *((oid, f"obj {oid}") for oid in sent)]
        else:
            rows = [("oidref", "ids"), *((oid, f"Gaia DR3 {oid}") for oid in sent)]
        return httpx.Response(200, text="".join(",".join(r) + "\n" for r in rows))

    def test_download(self, monkeypatch, tmp_path):
        catalog = tmp_path / "catalog.csv"
        catalog.write_text(
            "name,star_name,star_alternate_names\nHD 1 A b,HD 1 A,HIP 5\n"
        )
        oec = tmp_path / "systems.xml.gz"
        oec.write_bytes(
            gzip.compress(b"<systems><star><name>HD 404</name></star></systems>")
        )
        eu = PROVIDERS.EXOPLANET_EU
        sources = (
            CsvSource(
                eu,
                catalog,
                "star",
                "star_name",
                ("star_name",),
                ("star_alternate_names",),
            ),
            CsvSource(eu, catalog, "planet", "name", ("name",)),
        )
        monkeypatch.setattr(names, "CSV_SOURCES", sources)
        monkeypatch.setattr(names, "OEC_FILE", oec)
        monkeypatch.setattr(simbad, "OUT_DIR", tmp_path / "simbad")
        monkeypatch.setattr(ExoplanetSimbadDownloader, "inputs", (catalog, oec))

        ExoplanetSimbadDownloader(_client(self._handler)).download()

        out = tmp_path / "simbad"
        header, *rows = _read(out / "names.csv")
        assert header == [
            "catalogue",
            "table",
            "kind",
            "object",
            "name",
            "variant",
            "oid",
        ]
        assert rows == [
            [
                "exoplanet_eu",
                "catalog",
                "planet",
                "HD 1 A b",
                "HD 1 A b",
                "printed",
                "2",
            ],
            ["exoplanet_eu", "catalog", "star", "HD 1 A", "HD 1", "no_component", "1"],
            ["exoplanet_eu", "catalog", "star", "HD 1 A", "HD 1 A", "printed", ""],
            ["exoplanet_eu", "catalog", "star", "HD 1 A", "HIP 5", "printed", "1"],
            [
                "open_exoplanet_catalogue",
                "systems",
                "star",
                "HD 404",
                "HD 404",
                "printed",
                "",
            ],
        ]
        assert sorted(_read(out / "h_link.csv")[1:]) == sorted(map(list, self.links))
        linked = [["1"], ["2"], ["3"], ["4"], ["7"]]
        assert [row[:1] for row in _read(out / "basic.csv")[1:]] == linked
        assert [row[:1] for row in _read(out / "ids.csv")[1:]] == linked

    def test_failed_query_writes_no_file(self, monkeypatch, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            if "join ids" in _sent(request)[0]:
                return httpx.Response(200, text="oidref,ids\n")
            return self._handler(request)

        catalog = tmp_path / "catalog.csv"
        catalog.write_text("name\nHD 1 A b\n")
        oec = tmp_path / "systems.xml.gz"
        oec.write_bytes(gzip.compress(b"<systems/>"))
        source = CsvSource(PROVIDERS.EXOPLANET_EU, catalog, "planet", "name", ("name",))
        monkeypatch.setattr(names, "CSV_SOURCES", (source,))
        monkeypatch.setattr(names, "OEC_FILE", oec)
        monkeypatch.setattr(simbad, "OUT_DIR", tmp_path / "simbad")
        monkeypatch.setattr(ExoplanetSimbadDownloader, "inputs", (catalog, oec))

        with pytest.raises(DownloadError, match="SIMBAD ids has 0 rows for 4 objects"):
            ExoplanetSimbadDownloader(_client(handler)).download()
        assert list((tmp_path / "simbad").iterdir()) == []


class TestGaiaIds:
    """Gaia ids are read by release, since a DR2 id is not a DR3 id."""

    def test_splits_the_releases(self):
        dr2, dr3 = gaia_ids(
            [
                "HD 1|Gaia DR3 20|Gaia DR2 10|TIC 3",
                'x,"Gaia DR3 5","Gaia DR2 10"\ny,"Gaia DR3 20",',
            ]
        )
        assert dr2 == [10]
        assert dr3 == [5, 20]


class TestGaiaDownload:
    """The orbit table holds each solution once, under the table's header."""

    @staticmethod
    def _handler(request: httpx.Request) -> httpx.Response:
        query, sent = _sent(request)
        orbits = "source_id,nss_solution_type\n"
        if "dr2_neighbourhood" in query:
            body = "dr2_source_id,dr3_source_id\n" + "".join(f"{i},5\n" for i in sent)
        elif "nss_two_body_orbit as o" in query:
            body = orbits + "5,OrbitalTargetedSearch\n5,SB1\n"
        elif "nss_solution_type like" in query:
            body = (
                orbits + "5,OrbitalTargetedSearch\n6,OrbitalTargetedSearchValidated\n"
            )
        else:
            body = "source_id\n8\n"
        return httpx.Response(200, text=body)

    def test_download(self, monkeypatch, tmp_path):
        ids = tmp_path / "ids.csv"
        ids.write_text("1,HD 1|Gaia DR3 5|Gaia DR2 10\n")
        monkeypatch.setattr(gaia, "OUT_DIR", tmp_path / "gaia")
        monkeypatch.setattr(ExoplanetGaiaDownloader, "inputs", (ids,))

        ExoplanetGaiaDownloader(_client(self._handler)).download()

        out = tmp_path / "gaia"
        assert _read(out / "dr2_neighbourhood.csv") == [
            ["dr2_source_id", "dr3_source_id"],
            ["10", "5"],
        ]
        assert _read(out / "nss_two_body_orbit.csv") == [
            ["source_id", "nss_solution_type"],
            ["5", "OrbitalTargetedSearch"],
            ["5", "SB1"],
            ["6", "OrbitalTargetedSearchValidated"],
        ]
        assert _read(out / "vari_planetary_transit.csv") == [["source_id"], ["8"]]

    def test_input_without_a_gaia_id_raises(self, monkeypatch, tmp_path):
        ids = tmp_path / "ids.csv"
        ids.write_text("1,HD 1|TIC 3\n")
        monkeypatch.setattr(gaia, "OUT_DIR", tmp_path / "gaia")
        monkeypatch.setattr(ExoplanetGaiaDownloader, "inputs", (ids,))
        with pytest.raises(DownloadError, match="No id to send"):
            ExoplanetGaiaDownloader(_client(self._handler)).download()
