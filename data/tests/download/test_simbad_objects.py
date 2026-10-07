"""Tests for the SIMBAD export and the Wikidata identifier list."""

import gzip
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.catalogues import (
    fetch,
    simbad,
    wikidata_simbad,
)
from space_map_data.download.providers.catalogues.simbad import (
    SimbadObjectsDownloader,
    kept_types,
)
from space_map_data.download.providers.exoplanets import tap
from space_map_data.download.providers.catalogues.wikidata_simbad import (
    WikidataSimbadIdsDownloader,
)

OTYPEDEF = """otype,label,path
G,Galaxy,G
Sy2,Seyfert2,G > AGN > SyG > Sy2
PN,PlanetaryNeb,* > Ev* > PN
Psr,Pulsar,* > Ma* > N* > Psr
WD?,WhiteDwarf_Candidate,* > Ev* > WD*
RG*,RedGiant,* > Ev* > RG*
Rad,Radio,Rad
"""
FAMILIES = frozenset({"G", "PN", "N*", "WD*"})


class Simbad:
    """A fake TAP service. Objects 2, 4, 6 and 8 are galaxies."""

    def __init__(self) -> None:
        self.galaxies = [2, 4, 6, 8]
        self.highest = 8
        # Rows that the closing count adds to the true count of a table.
        self.extra: dict[str, int] = {}
        self.empty_windows = False
        self.queries: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        query = form["QUERY"]
        self.queries.append(query)
        if query == "SELECT * FROM otypedef":
            return httpx.Response(200, text=OTYPEDEF)
        if query == "SELECT MAX(oid) FROM basic":
            return httpx.Response(200, text=f"MAX\n{self.highest}\n")
        table = query.split(" FROM ")[1].split(" ")[0]
        links = table == "h_link"
        if query.startswith("SELECT COUNT(*)"):
            count = self.highest if links else len(self.galaxies)
            return httpx.Response(200, text=f"N\n{count + self.extra.get(table, 0)}\n")
        assert form["MAXREC"] == str(simbad.MAX_ROWS)
        if self.empty_windows:
            return httpx.Response(200, text="")
        first, last = (int(n) for n in query.split("BETWEEN ")[1].split(" AND "))
        ids = range(1, self.highest + 1) if links else self.galaxies
        rows = [f"{oid},x" for oid in ids if first <= oid <= last]
        return httpx.Response(200, text="\n".join(["oid,value", *rows]) + "\n")

    def windows(self) -> list[str]:
        return [query for query in self.queries if "BETWEEN" in query]


@pytest.fixture
def service(monkeypatch) -> Simbad:
    monkeypatch.setattr(fetch, "RETRY_WAIT_SECONDS", 0)
    monkeypatch.setattr(tap, "RETRY_PAUSE_SECONDS", 0)
    monkeypatch.setattr(simbad, "FAMILIES", FAMILIES)
    monkeypatch.setattr(simbad, "WINDOW_OIDS", 4)
    return Simbad()


@pytest.fixture
def downloader(tmp_path, monkeypatch, service) -> SimbadObjectsDownloader:
    monkeypatch.setattr(simbad, "OUT_DIR", tmp_path)
    client = httpx.Client(
        transport=httpx.MockTransport(service),
        headers={"User-Agent": "space-map-bot/0.1 (a@b.test)"},
    )
    return SimbadObjectsDownloader(client)


def names(directory) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


class TestKeptTypes:
    """Which type codes the type tree selects."""

    def test_keeps_a_family_and_the_types_below_it(self, monkeypatch):
        monkeypatch.setattr(simbad, "FAMILIES", FAMILIES)
        assert kept_types(OTYPEDEF) == ["G", "PN", "Psr", "Sy2", "WD?"]

    def test_a_family_missing_from_the_tree_is_an_error(self, monkeypatch):
        monkeypatch.setattr(simbad, "FAMILIES", frozenset({"G", "XB*"}))
        with pytest.raises(DownloadError, match=r"XB\*"):
            kept_types(OTYPEDEF)


class TestExport:
    """The windowed export of each table."""

    def test_writes_one_file_for_each_window(self, downloader, tmp_path):
        downloader.download()
        assert names(tmp_path / "basic") == [
            "00000001-00000004.csv.gz",
            "00000005-00000008.csv.gz",
        ]
        first = tmp_path / "basic/00000001-00000004.csv.gz"
        assert gzip.decompress(first.read_bytes()) == b"oid,value\n2,x\n4,x\n"

    def test_a_window_name_does_not_follow_the_highest_id(
        self, downloader, service, tmp_path
    ):
        service.highest = 6
        service.galaxies = [2, 4, 6]
        downloader.download()
        assert names(tmp_path / "basic")[-1] == "00000005-00000008.csv.gz"

    def test_the_query_names_the_kept_types(self, downloader, service):
        downloader.download()
        basic = next(q for q in service.queries if q.startswith("SELECT b.* FROM"))
        assert "b.otype IN ('G','PN','Psr','Sy2','WD?')" in basic
        assert basic.endswith("AND b.oid BETWEEN 1 AND 4")

    def test_records_the_rows_and_the_count_of_each_table(self, downloader, tmp_path):
        downloader.download()
        meta = json.loads((tmp_path / "metadata.json").read_text())
        assert meta["complete"] is True
        assert meta["record_count"] == 4
        assert meta["rows"]["ident"] == 4
        assert meta["rows"]["h_link"] == 8
        assert meta["counted"] == meta["rows"]
        assert not (tmp_path / "export.json").exists()

    def test_a_full_window_is_split(self, downloader, tmp_path, monkeypatch):
        # Each window of four ids holds two galaxies, so it reaches the limit.
        monkeypatch.setattr(simbad, "MAX_ROWS", 2)
        monkeypatch.setattr(simbad, "TABLES", {"basic": simbad.TABLES["basic"]})
        downloader.download()
        assert names(tmp_path / "basic") == [
            "00000001-00000002.csv.gz",
            "00000003-00000004.csv.gz",
            "00000005-00000006.csv.gz",
            "00000007-00000008.csv.gz",
        ]


class TestCounts:
    """What ends an export with an error."""

    def test_too_few_rows_of_one_table(self, downloader, service, monkeypatch):
        monkeypatch.setattr(simbad, "COUNT_TOLERANCE", 0.0)
        service.extra = {"ident": 1}
        with pytest.raises(DownloadError, match="4 ident rows, SIMBAD counts 5"):
            downloader.download()

    def test_an_empty_answer(self, downloader, service, tmp_path):
        service.empty_windows = True
        with pytest.raises(DownloadError, match="sent no table"):
            downloader.download()
        assert not list((tmp_path / "basic").iterdir())

    def test_a_refused_query(self, tmp_path, monkeypatch):
        monkeypatch.setattr(simbad, "OUT_DIR", tmp_path)
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text="<VOTABLE>error</VOTABLE>")
            )
        )
        with pytest.raises(DownloadError, match="TAP query failed"):
            SimbadObjectsDownloader(client).download()


class TestPasses:
    """One export is one pass over SIMBAD."""

    def interrupt(self, downloader, service, monkeypatch) -> None:
        """Run an export that fails at the closing count."""
        monkeypatch.setattr(simbad, "COUNT_TOLERANCE", 0.0)
        service.extra = {"basic": 1}
        with pytest.raises(DownloadError):
            downloader.download()
        service.extra = {}
        service.queries.clear()

    def test_an_interrupted_export_continues(self, downloader, service, monkeypatch):
        self.interrupt(downloader, service, monkeypatch)
        downloader.download()
        assert service.windows() == []

    def test_an_old_interrupted_export_starts_again(
        self, downloader, service, monkeypatch, tmp_path
    ):
        self.interrupt(downloader, service, monkeypatch)
        state = json.loads((tmp_path / "export.json").read_text())
        old = datetime.now(timezone.utc) - timedelta(days=simbad.RESUME_DAYS + 1)
        state["started_at"] = old.isoformat()
        (tmp_path / "export.json").write_text(json.dumps(state))
        downloader.download()
        assert len(service.windows()) == 2 * len(simbad.TABLES)

    def test_a_changed_type_list_starts_again(
        self, downloader, service, monkeypatch, tmp_path
    ):
        self.interrupt(downloader, service, monkeypatch)
        monkeypatch.setattr(simbad, "FAMILIES", frozenset({"G"}))
        downloader.download()
        assert len(service.windows()) == 2 * len(simbad.TABLES)
        assert json.loads((tmp_path / "metadata.json").read_text())["types"] == [
            "G",
            "Sy2",
        ]

    def test_an_interrupted_new_export_is_not_complete(
        self, downloader, service, monkeypatch
    ):
        downloader.download()
        assert downloader.is_complete(None)
        self.interrupt(downloader, service, monkeypatch)
        assert not downloader.is_complete(None)

    def test_a_new_export_deletes_the_last_one(self, downloader, service, tmp_path):
        downloader.download()
        stale = tmp_path / "basic/00000009-00000012.csv.gz"
        stale.write_bytes(gzip.compress(b"oid,value\n9,x\n"))
        service.queries.clear()
        downloader.download()
        assert not stale.exists()
        assert len(service.windows()) == 2 * len(simbad.TABLES)


class TestWikidataSimbadIds:
    """The identifier list from QLever."""

    @pytest.fixture
    def run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wikidata_simbad, "OUT_DIR", tmp_path)

        def build(counted: int) -> WikidataSimbadIdsDownloader:
            def handler(request: httpx.Request) -> httpx.Response:
                form = parse_qs(request.content.decode())
                if "COUNT" in form["query"][0]:
                    return httpx.Response(200, text=f"?n\n{counted}\n")
                assert form["action"] == ["tsv_export"]
                return httpx.Response(200, text='?item\t?simbad\n<Q1>\t"M 31"\n')

            client = httpx.Client(transport=httpx.MockTransport(handler))
            return WikidataSimbadIdsDownloader(client)

        return build

    def test_writes_the_list(self, run, tmp_path):
        run(1).download()
        body = gzip.decompress((tmp_path / "simbad-ids.tsv.gz").read_bytes())
        assert body == b'?item\t?simbad\n<Q1>\t"M 31"\n'
        meta = json.loads((tmp_path / "metadata.json").read_text())
        assert meta["record_count"] == 1

    def test_a_short_list_keeps_the_last_one(self, run, tmp_path):
        run(1).download()
        with pytest.raises(DownloadError, match="returned 1 identifiers and counts 2"):
            run(2).download()
        body = gzip.decompress((tmp_path / "simbad-ids.tsv.gz").read_bytes())
        assert body == b'?item\t?simbad\n<Q1>\t"M 31"\n'
        assert not (tmp_path / "simbad-ids.tsv.gz.part").exists()
