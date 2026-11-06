"""Tests for the dust-map downloads."""

import hashlib
import json
import logging

import httpx
import pytest

from space_map_data.constants.manifests.catalogues import DISTRIBUTIONS
from space_map_data.download import common
from space_map_data.download.common import PROVIDERS_CLASSES
from space_map_data.download.downloader import (
    Downloader,
    DownloadError,
    DownloadSkipped,
)
from space_map_data.download.providers.dust import remote
from space_map_data.download.providers.dust.maps import (
    BayestarDustDownloader,
    DecapsDustDownloader,
    DharmawardenaDustDownloader,
    EdenhoferDustDownloader,
    GaiaExtinctionMapDownloader,
    PlanckDustDownloader,
)
from space_map_data.download.providers.dust.remote import (
    DATAVERSE_URL,
    DustMapDownloader,
    dataverse_listing,
    head_file,
    zenodo_listing,
)
from space_map_data.download.providers.three_d import resumable
from space_map_data.download.zenodo import ZENODO_URL

DUST_PROVIDERS = [
    cls for cls in PROVIDERS_CLASSES if issubclass(cls, DustMapDownloader)
]


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(resumable, "RETRY_WAIT_SECONDS", 0)


def md5(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()


class Host:
    """Fake Zenodo, Dataverse and plain servers. It records the file requests."""

    def __init__(self) -> None:
        self.answers: dict[str, httpx.Response] = {}
        self.files: dict[str, bytes] = {}
        self.fetched: list[str] = []
        self.heads: list[httpx.Request] = []

    def add_zenodo(
        self, number: int, files: dict[str, bytes], license: str | None = "cc-by-4.0"
    ) -> None:
        entries = []
        for name, content in files.items():
            url = f"https://zenodo.test/{number}/{name}"
            self.files[url] = content
            entries.append(
                {
                    "key": name,
                    "size": len(content),
                    "checksum": f"md5:{md5(content)}",
                    "links": {"self": url},
                }
            )
        metadata = {"license": {"id": license}} if license else {}
        body = {"metadata": metadata, "files": entries}
        self.answers[f"{ZENODO_URL}/{number}"] = httpx.Response(200, json=body)

    def add_dataverse(
        self, doi: str, files: dict[str, bytes], license: str = "CC0 1.0"
    ) -> None:
        entries = []
        for index, (name, content) in enumerate(files.items()):
            url = f"{DATAVERSE_URL}/access/datafile/{index}"
            self.files[url] = content
            data = {"id": index, "filesize": len(content), "md5": md5(content)}
            entries.append({"label": name, "dataFile": data})
        body = {"data": {"license": {"name": license}, "files": entries}}
        self.answers[f"dataverse:{doi}"] = httpx.Response(200, json=body)

    def add_gaia(self, base: str, table: str, name: str, content: bytes) -> None:
        self.files[f"{base}{table}/{name}"] = content
        self.files[f"{base}{table}/_MD5SUM.txt"] = f"{md5(content)}  {name}\n".encode()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        doi = request.url.params.get("persistentId")
        if doi:
            return self.answers[f"dataverse:{doi.removeprefix('doi:')}"]
        if url in self.answers:
            return self.answers[url]
        if url not in self.files:
            return httpx.Response(404)
        content = self.files[url]
        if request.method == "HEAD":
            self.heads.append(request)
            return httpx.Response(200, headers={"content-length": str(len(content))})
        if not url.endswith("_MD5SUM.txt"):
            self.fetched.append(url)
        return httpx.Response(200, content=content)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def host() -> Host:
    return Host()


class TestListings:
    """What the hosts say about their files."""

    def test_zenodo_files_and_licence(self, host):
        host.add_zenodo(1, {"a.fits": b"abc"})
        listing = zenodo_listing(host.client(), 1)
        assert listing.license == "cc-by-4.0"
        file = listing.files["a.fits"]
        assert (file.size, file.md5) == (3, md5(b"abc"))
        assert file.url == "https://zenodo.test/1/a.fits"
        assert json.loads(listing.records["record.json"])["files"]

    def test_a_record_without_licence_has_none(self, host):
        host.add_zenodo(1, {"a": b"x"}, license=None)
        assert zenodo_listing(host.client(), 1).license is None

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"files": [], "metadata": {"license": {}}},
            {"files": [{"key": "a", "checksum": "md5:0", "links": {"self": "u"}}]},
        ],
    )
    def test_an_unexpected_zenodo_record_fails(self, host, body):
        host.answers[f"{ZENODO_URL}/1"] = httpx.Response(200, json=body)
        with pytest.raises(DownloadError, match="unexpected"):
            zenodo_listing(host.client(), 1)

    def test_dataverse_files_and_licence(self, host):
        body = {
            "data": {
                "license": {"name": "CC0 1.0"},
                "files": [
                    {
                        "label": "map.h5",
                        "dataFile": {"id": 7, "filesize": 5, "md5": "ab" * 16},
                    },
                    {
                        "label": "sum.fits",
                        "dataFile": {
                            "id": 8,
                            "filesize": 6,
                            "checksum": {"type": "MD5", "value": "cd" * 16},
                        },
                    },
                    {"label": "none.fits", "dataFile": {"id": 9, "filesize": 6}},
                ],
            }
        }
        host.answers["dataverse:10.1/X"] = httpx.Response(200, json=body)
        listing = dataverse_listing(host.client(), "10.1/X")
        assert listing.license == "CC0 1.0"
        assert listing.files["map.h5"].url.endswith("/access/datafile/7")
        assert listing.files["map.h5"].md5 == "ab" * 16
        assert listing.files["sum.fits"].md5 == "cd" * 16
        assert listing.files["none.fits"].md5 is None
        assert json.loads(listing.records["record.json"]) == body

    @pytest.mark.parametrize("license", [{}, {"uri": "x"}])
    def test_a_dataverse_licence_without_name_fails(self, host, license):
        body = {"data": {"license": license, "files": []}}
        host.answers["dataverse:10.1/X"] = httpx.Response(200, json=body)
        with pytest.raises(DownloadError, match="unexpected"):
            dataverse_listing(host.client(), "10.1/X")

    def test_head_gives_the_size_of_the_stored_file(self, host):
        host.files["https://plain.test/a.fits"] = b"abcd"
        file = head_file(host.client(), "https://plain.test/a.fits", "a.fits", None)
        assert (file.name, file.size, file.md5) == ("a.fits", 4, None)
        assert host.heads[0].headers["accept-encoding"] == "identity"

    def test_head_fails_without_a_size_or_a_file(self, host):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        )
        with pytest.raises(DownloadError, match="Content-Length"):
            head_file(client, "https://plain.test/a", "a", None)
        with pytest.raises(DownloadError, match="HTTP 404"):
            head_file(host.client(), "https://plain.test/b", "b", None)


class Edenhofer:
    """The Edenhofer provider on a disk in tmp_path and two fake records."""

    def __init__(self, host: Host, tmp_path, monkeypatch) -> None:
        self.host = host
        host.add_zenodo(EdenhoferDustDownloader.record, {"m.fits": b"map", "r": b"x"})
        host.add_zenodo(EdenhoferDustDownloader.curve_record, {"c.txt": b"curve"})
        monkeypatch.setattr(EdenhoferDustDownloader, "directory", tmp_path / "e")
        self.monkeypatch = monkeypatch
        self.set_wanted("m.fits", "r", "zgr23/c.txt")

    def set_wanted(self, *names: str) -> None:
        self.monkeypatch.setattr(EdenhoferDustDownloader, "wanted", names)

    def make(self) -> EdenhoferDustDownloader:
        return EdenhoferDustDownloader(self.host.client())


@pytest.fixture
def eden(host, tmp_path, monkeypatch) -> Edenhofer:
    return Edenhofer(host, tmp_path, monkeypatch)


class TestDownloads:
    """Fetch, check and record the wanted files."""

    def test_fetches_the_files_and_both_records(self, eden):
        downloader = eden.make()
        downloader.download()
        out = downloader.out_dir
        assert (out / "m.fits").read_bytes() == b"map"
        assert (out / "zgr23" / "c.txt").read_bytes() == b"curve"
        for record, number in (
            ("record.json", EdenhoferDustDownloader.record),
            ("zgr23/record.json", EdenhoferDustDownloader.curve_record),
        ):
            assert json.loads((out / record).read_text())["files"][0]["links"][
                "self"
            ].startswith(f"https://zenodo.test/{number}/")
        meta = json.loads(downloader.metadata_file.read_text())
        assert meta["wanted"] == ["m.fits", "r", "zgr23/c.txt"]
        assert meta["record_count"] == 3
        assert meta["license_stated"] == "cc-by-4.0"
        assert meta["terms"] == downloader.terms
        assert meta["sources"] == list(downloader.sources)
        by_name = {f["name"]: f for f in meta["files"]}
        assert by_name["zgr23/c.txt"]["md5"] == md5(b"curve")
        assert by_name["zgr23/c.txt"]["url"].endswith("7811871/c.txt")
        assert downloader.is_complete(None)

    @pytest.mark.parametrize("field", ["wanted", "sources", "terms"])
    def test_a_changed_provider_is_not_complete(self, eden, field):
        downloader = eden.make()
        downloader.download()
        changes = {
            "wanted": ("m.fits",),
            "sources": ("https://zenodo.org/api/records/1",),
            "terms": {**downloader.terms, "distribution": "undecided"},
        }
        eden.monkeypatch.setattr(EdenhoferDustDownloader, field, changes[field])
        assert not downloader.is_complete(None)

    def test_a_stored_file_is_not_fetched_again(self, eden, caplog):
        eden.make().download()
        eden.host.fetched.clear()
        with caplog.at_level(logging.INFO):
            eden.make().download()
        assert eden.host.fetched == []
        assert "m.fits is stored" in caplog.text

    def test_a_normal_run_does_not_read_a_stored_file(self, eden, monkeypatch):
        eden.make().download()

        def fail(path):
            raise AssertionError(f"hashed {path}")

        monkeypatch.setattr(remote, "md5_of", fail)
        eden.make().download()

    def test_only_a_forced_run_repairs_damaged_bytes_of_the_right_size(self, eden):
        downloader = eden.make()
        downloader.download()
        (downloader.out_dir / "m.fits").write_bytes(b"xyz")
        eden.host.fetched.clear()
        eden.make().download()
        assert eden.host.fetched == []
        eden.make().download(force=True)
        assert eden.host.fetched == ["https://zenodo.test/10658339/m.fits"]
        assert (downloader.out_dir / "m.fits").read_bytes() == b"map"

    def test_a_forced_run_keeps_a_file_whose_bytes_match(self, eden):
        eden.make().download()
        eden.host.fetched.clear()
        eden.make().download(force=True)
        assert eden.host.fetched == []

    def test_a_file_republished_with_the_same_size_is_fetched_again(self, eden):
        eden.make().download()
        eden.host.add_zenodo(
            EdenhoferDustDownloader.record, {"m.fits": b"MAP", "r": b"x"}
        )
        eden.host.fetched.clear()
        eden.make().download()
        assert eden.host.fetched == ["https://zenodo.test/10658339/m.fits"]
        assert (eden.make().out_dir / "m.fits").read_bytes() == b"MAP"

    def test_a_file_without_a_record_is_kept_when_its_bytes_match(self, eden):
        downloader = eden.make()
        (downloader.out_dir / "m.fits").write_bytes(b"map")
        downloader.download()
        assert "https://zenodo.test/10658339/m.fits" not in eden.host.fetched

    def test_a_file_without_a_record_is_replaced_when_its_bytes_differ(self, eden):
        downloader = eden.make()
        (downloader.out_dir / "m.fits").write_bytes(b"old")
        downloader.download()
        assert (downloader.out_dir / "m.fits").read_bytes() == b"map"

    def test_a_wrong_checksum_writes_nothing(self, eden):
        eden.host.files["https://zenodo.test/10658339/m.fits"] = b"xyz"
        downloader = eden.make()
        with pytest.raises(DownloadError, match="MD5"):
            downloader.download()
        assert not (downloader.out_dir / "m.fits").exists()
        assert not downloader.metadata_file.exists()

    def test_a_wrong_size_writes_nothing(self, eden):
        eden.host.files["https://zenodo.test/10658339/m.fits"] = b"mapmap"
        downloader = eden.make()
        with pytest.raises(DownloadError, match="6 bytes, the host lists 3"):
            downloader.download()
        assert not (downloader.out_dir / "m.fits").exists()

    def test_a_changed_licence_stops_the_run(self, eden):
        for record in (
            EdenhoferDustDownloader.record,
            EdenhoferDustDownloader.curve_record,
        ):
            eden.host.add_zenodo(record, {"m.fits": b"map"}, "cc-by-nc-4.0")
        downloader = eden.make()
        with pytest.raises(DownloadError, match="licence"):
            downloader.download()
        assert eden.host.fetched == []

    def test_a_curve_under_another_licence_stops_the_run(self, eden):
        eden.host.add_zenodo(
            EdenhoferDustDownloader.curve_record, {"c.txt": b"curve"}, "cc0-1.0"
        )
        with pytest.raises(DownloadError, match="another licence"):
            eden.make().download()

    def test_a_missing_file_stops_the_run(self, eden):
        eden.set_wanted("m.fits", "gone.fits")
        with pytest.raises(DownloadError, match="gone.fits"):
            eden.make().download()
        assert eden.host.fetched == []

    def test_a_record_limit_fetches_nothing_and_ends_as_skipped(self, eden):
        downloader = eden.make()
        with pytest.raises(DownloadSkipped, match="3 files to fetch"):
            downloader.download(limit=50_000)
        assert eden.host.fetched == []
        assert not downloader.metadata_file.exists()
        assert not downloader.is_complete(50_000)

    def test_a_record_limit_still_records_a_change_of_terms(self, eden):
        eden.make().download()
        eden.monkeypatch.setattr(
            EdenhoferDustDownloader, "terms", {"distribution": "undecided"}
        )
        downloader = eden.make()
        assert not downloader.is_complete(50_000)
        downloader.download(limit=50_000)
        assert downloader.is_complete(50_000)
        assert eden.host.fetched.count("https://zenodo.test/10658339/m.fits") == 1

    def test_a_file_that_is_no_longer_wanted_is_deleted(self, eden):
        downloader = eden.make()
        downloader.download()
        (downloader.out_dir / "other.bin").write_bytes(b"?")
        eden.set_wanted("m.fits", "zgr23/c.txt")
        downloader.download()
        out = downloader.out_dir
        assert not (out / "r").exists()
        assert not (out / "other.bin").exists()
        for kept in ("m.fits", "zgr23/c.txt", "record.json", "zgr23/record.json"):
            assert (out / kept).exists()
        assert downloader.metadata_file.exists()


class TestOtherHosts:
    """The Dataverse, plain-server and Gaia maps."""

    def test_a_dataverse_map(self, host, tmp_path, monkeypatch):
        host.add_dataverse(
            BayestarDustDownloader.doi, {"b.h5": b"cube", "x.fits": b"?"}
        )
        monkeypatch.setattr(BayestarDustDownloader, "directory", tmp_path / "b")
        monkeypatch.setattr(BayestarDustDownloader, "wanted", ("b.h5",))
        downloader = BayestarDustDownloader(host.client())
        downloader.download()
        assert (downloader.out_dir / "b.h5").read_bytes() == b"cube"
        assert not (downloader.out_dir / "x.fits").exists()
        meta = json.loads(downloader.metadata_file.read_text())
        assert meta["license_stated"] == "CC0 1.0"
        assert meta["files"][0]["md5"] == md5(b"cube")
        assert (downloader.out_dir / "record.json").exists()
        assert downloader.is_complete(None)

    def test_a_plain_file_has_no_checksum_and_stays_when_the_size_holds(
        self, host, tmp_path, monkeypatch, caplog
    ):
        url = "https://plain.test/p.fits"
        host.files[url] = b"planck"
        monkeypatch.setattr(PlanckDustDownloader, "directory", tmp_path / "p")
        monkeypatch.setattr(PlanckDustDownloader, "url", url)
        monkeypatch.setattr(PlanckDustDownloader, "file", "p.fits")
        monkeypatch.setattr(PlanckDustDownloader, "wanted", ("p.fits",))
        downloader = PlanckDustDownloader(host.client())
        downloader.download()
        assert (downloader.out_dir / "p.fits").read_bytes() == b"planck"
        assert (
            json.loads(downloader.metadata_file.read_text())["files"][0]["md5"] is None
        )
        host.fetched.clear()
        with caplog.at_level(logging.INFO):
            downloader.download()
        assert host.fetched == []
        assert "the host lists no MD5 and the size matches" in caplog.text
        (downloader.out_dir / "p.fits").write_bytes(b"PLANCK")
        downloader.download()
        assert host.fetched == []
        downloader.download(force=True)
        assert host.fetched == [url]
        assert (downloader.out_dir / "p.fits").read_bytes() == b"planck"
        host.files[url] = b"planck2"
        downloader.download()
        assert (downloader.out_dir / "p.fits").read_bytes() == b"planck2"

    def test_the_gaia_chunks_are_listed_with_their_checksums(
        self, host, tmp_path, monkeypatch
    ):
        base = "https://gaia.test/"
        host.add_gaia(base, "t1", "a.csv.gz", b"chunk one")
        host.add_gaia(base, "t2", "b.csv.gz", b"chunk two")
        monkeypatch.setattr(GaiaExtinctionMapDownloader, "page_url", base)
        monkeypatch.setattr(GaiaExtinctionMapDownloader, "directory", tmp_path / "g")
        monkeypatch.setattr(
            GaiaExtinctionMapDownloader, "wanted", ("t1/a.csv.gz", "t2/b.csv.gz")
        )
        monkeypatch.setattr(
            GaiaExtinctionMapDownloader,
            "keep",
            frozenset({"t1/_MD5SUM.txt", "t2/_MD5SUM.txt"}),
        )
        downloader = GaiaExtinctionMapDownloader(host.client())
        downloader.download()
        assert (downloader.out_dir / "t2" / "b.csv.gz").read_bytes() == b"chunk two"
        meta = json.loads(downloader.metadata_file.read_text())
        assert meta["source_url"] == base
        assert meta["files"][0]["md5"] == md5(b"chunk one")
        # The MD5 lists stay through the next run.
        downloader.download()
        assert (downloader.out_dir / "t1" / "_MD5SUM.txt").exists()

    def test_a_chunk_without_a_checksum_line_fails(self, host, tmp_path, monkeypatch):
        base = "https://gaia.test/"
        host.add_gaia(base, "t1", "a.csv.gz", b"chunk one")
        host.files[f"{base}t1/_MD5SUM.txt"] = f"{md5(b'x')}  other.csv.gz\n".encode()
        monkeypatch.setattr(GaiaExtinctionMapDownloader, "page_url", base)
        monkeypatch.setattr(GaiaExtinctionMapDownloader, "directory", tmp_path / "g")
        monkeypatch.setattr(GaiaExtinctionMapDownloader, "wanted", ("t1/a.csv.gz",))
        with pytest.raises(DownloadError, match="no MD5 for a.csv.gz"):
            GaiaExtinctionMapDownloader(host.client()).download()


class TestRunner:
    """How the runner records a provider that has work left and did none."""

    def test_a_skipped_provider_is_recorded_as_skipped_with_its_reason(
        self, tmp_path, monkeypatch
    ):
        class Declines(Downloader):
            name = "declines"

            def __init__(self, client: httpx.Client) -> None:
                super().__init__(client)
                self.out_dir = tmp_path

            def is_complete(self, limit):
                return False

            def download(self, limit=None, **kwargs):
                raise DownloadSkipped("2 files to fetch")

        monkeypatch.setattr(common, "SOURCES", {"declines": Declines})
        monkeypatch.setattr(common, "DOWNLOAD_DIR", tmp_path)
        monkeypatch.setattr(
            common, "load_config", lambda: {"download": {"user_agent": "test"}}
        )
        (result,) = common.download(["declines"], limit=1)
        assert (result.ok, result.skipped, result.error) == (
            True,
            True,
            "2 files to fetch",
        )

    @pytest.mark.parametrize("breaks", ["init", "is_complete"])
    def test_a_provider_that_breaks_before_its_download_does_not_stop_the_job(
        self, tmp_path, monkeypatch, breaks
    ):
        class Broken(Downloader):
            name = "broken"

            def __init__(self, client: httpx.Client) -> None:
                if breaks == "init":
                    raise OSError("no directory")
                super().__init__(client)

            def is_complete(self, limit):
                raise ValueError("unreadable metadata")

            def download(self, limit=None, **kwargs):
                raise AssertionError("not reached")

        class Fine(Downloader):
            name = "fine"

            def __init__(self, client: httpx.Client) -> None:
                super().__init__(client)

            def is_complete(self, limit):
                return True

            def download(self, limit=None, **kwargs):
                raise AssertionError("not reached")

        monkeypatch.setattr(common, "SOURCES", {"broken": Broken, "fine": Fine})
        monkeypatch.setattr(common, "DOWNLOAD_DIR", tmp_path)
        monkeypatch.setattr(
            common, "load_config", lambda: {"download": {"user_agent": "test"}}
        )
        broken, fine = common.download(["broken", "fine"], limit=1)
        assert not broken.ok
        assert broken.error is not None
        assert (fine.ok, fine.skipped) == (True, True)

    def test_force_reaches_the_provider(self, tmp_path, monkeypatch):
        seen = []

        class Records(Downloader):
            name = "records"

            def __init__(self, client: httpx.Client) -> None:
                super().__init__(client)
                self.out_dir = tmp_path

            def download(self, limit=None, **kwargs):
                seen.append(kwargs["force"])

        monkeypatch.setattr(common, "SOURCES", {"records": Records})
        monkeypatch.setattr(common, "DOWNLOAD_DIR", tmp_path)
        monkeypatch.setattr(
            common, "load_config", lambda: {"download": {"user_agent": "test"}}
        )
        common.download(["records"], limit=1, force=True)
        common.download(["records"], limit=1)
        assert seen == [True, False]


class TestTerms:
    """The reuse terms that each provider records."""

    @pytest.mark.parametrize("cls", DUST_PROVIDERS, ids=lambda cls: cls.name)
    def test_the_tier_is_one_of_the_manifest_tiers(self, cls):
        assert cls.terms["distribution"] in DISTRIBUTIONS

    @pytest.mark.parametrize("cls", DUST_PROVIDERS, ids=lambda cls: cls.name)
    def test_a_source_without_a_licence_is_never_open(self, cls):
        if cls.terms["license"] is None:
            assert cls.terms["distribution"] != "open"

    @pytest.mark.parametrize("cls", DUST_PROVIDERS, ids=lambda cls: cls.name)
    def test_a_quote_cites_an_address_that_carries_it(self, cls):
        quotes = cls.terms["quotes"]
        assert all(
            quote["url"].startswith("https://") and quote["text"] for quote in quotes
        )
        # A Zenodo or Dataverse licence is quoted from the API, not the page.
        if cls.expected_license is not None:
            assert all("/api/" in quote["url"] for quote in quotes)

    @pytest.mark.parametrize(
        ("cls", "release"),
        [
            (EdenhoferDustDownloader, "Gaia DR3"),
            (BayestarDustDownloader, "Gaia DR2"),
            (DecapsDustDownloader, "Gaia DR3"),
            (DharmawardenaDustDownloader, "Gaia DR2"),
        ],
        ids=lambda value: getattr(value, "name", value),
    )
    def test_a_map_built_from_gaia_stars_is_non_commercial(self, cls, release):
        # As the catalogue manifests tier a source derived from Gaia.
        assert cls.terms["distribution"] == "non-commercial"
        assert f"Derived from {release} (CC BY-NC 3.0 IGO)" in cls.terms["license"]

    def test_the_edenhofer_terms_name_the_curve_record(self):
        terms = EdenhoferDustDownloader.terms
        record = EdenhoferDustDownloader.curve_record
        assert str(record) in terms["note"]
        assert any(str(record) in quote["url"] for quote in terms["quotes"])
