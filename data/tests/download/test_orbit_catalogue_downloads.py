"""Tests for the ORB6 and SBX downloads."""

import json
from urllib.parse import parse_qs

import httpx
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import orb6, sbx
from space_map_data.download.providers.stars.orb6 import ORB6Downloader
from space_map_data.download.providers.stars.sbx import SBXDownloader
from space_map_data.download.providers.three_d import resumable
from tests.download.orbit_catalogue_files import (
    ORB6_LINES,
    SBX_ALIAS,
    SBX_ORBITS,
    SBX_SYSTEMS,
)

ORB6_TEXT = "\n".join(ORB6_LINES) + "\n"
HOME = """(last catalog update :
Tue Oct 13 03:10:02 PM EDT 2026
)<br>
As of the above date, the <i>Sixth Catalog</i> included
5
 of
4
 systems (from a "master file" database"""


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(resumable, "RETRY_WAIT_SECONDS", 0)


class TestORB6Reader:
    """The fixed-width orbits file, read as a table."""

    @pytest.fixture
    def rows(self, tmp_path) -> dict[str, dict]:
        path = tmp_path / orb6.ORBITS_FILE
        path.write_text(ORB6_TEXT, encoding="latin-1")
        table = orb6.read_orbits(path)
        assert table.schema.field("hip").type == pa.int32()
        return {f"{r['discoverer']} {r['components']}": r for r in table.to_pylist()}

    def test_reads_every_orbit_and_skips_the_headers(self, rows):
        assert sorted(rows) == [
            "GHE   7 Aa,Ab",
            "LDS 494 AC",
            "MCA  30 Aa",
            "RHD   1 AB",
            "STF2032 Aa,Ab",
        ]

    def test_reads_the_fields_of_alpha_centauri(self, rows):
        ab = rows["RHD   1 AB"]
        assert (ab["wds_id"], ab["hd"], ab["hip"], ab["ads"]) == (
            "14396-6050",
            128620,
            71683,
            None,
        )
        assert (ab["period"], ab["period_unit"], ab["period_error"]) == (
            79.762,
            "y",
            0.019,
        )
        assert (ab["semi_major_axis"], ab["semi_major_axis_unit"]) == (17.493, "a")
        assert (ab["inclination"], ab["node"], ab["node_flag"]) == (
            79.243,
            205.073,
            None,
        )
        assert (ab["t_periastron"], ab["t_periastron_unit"]) == (1955.564, "y")
        assert (ab["eccentricity"], ab["arg_periastron"]) == (0.51947, 231.519)
        assert (ab["equinox"], ab["last_observation"], ab["grade"]) == (None, None, 2)
        assert (ab["notes"], ab["reference"]) == (True, "Ake2021")
        assert (ab["mag1"], ab["mag2"]) == (pytest.approx(-0.01), pytest.approx(1.33))
        assert ab["ra"] == pytest.approx(219.902083, abs=1e-6)
        assert ab["dec"] == pytest.approx(-60.833972, abs=1e-6)

    def test_keeps_each_unit_code(self, rows):
        proxima = rows["LDS 494 AC"]
        assert (proxima["period_unit"], proxima["semi_major_axis_unit"]) == ("c", "M")
        assert (proxima["t_periastron"], proxima["t_periastron_unit"]) == (2850.0, "c")
        assert proxima["equinox"] == 2000
        sigma_crb = rows["STF2032 Aa,Ab"]
        assert (sigma_crb["period"], sigma_crb["period_unit"]) == (1641.299649, "m")
        assert sigma_crb["t_periastron_unit"] == "d"
        # A lone "." is null; the 0.0 beside it stays.
        assert (sigma_crb["eccentricity"], sigma_crb["eccentricity_error"]) == (
            0.0,
            None,
        )
        assert rows["GHE   7 Aa,Ab"]["t_periastron_unit"] == "j"
        astrometric = rows["MCA  30 Aa"]
        assert (astrometric["grade"], astrometric["period_unit"]) == (
            orb6.ASTROMETRIC_GRADE,
            "h",
        )

    def test_reads_the_release_of_the_home_page(self):
        orbits, systems, day = orb6.parse_release(HOME)
        assert (orbits, systems, day.isoformat()) == (5, 4, "2026-10-13")
        with pytest.raises(DownloadError, match="page changed"):
            orb6.parse_release("<p>Nothing here.</p>")


class TestORB6Downloader:
    """The orbits file, checked against the count of the home page."""

    def make(self, tmp_path, monkeypatch, orbits: str) -> ORB6Downloader:
        monkeypatch.setattr(orb6, "OUT_DIR", tmp_path / "orb6")

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == orb6.HOME_URL:
                return httpx.Response(200, text=HOME)
            if str(request.url) == orb6.FILES[orb6.ORBITS_FILE]:
                return httpx.Response(200, content=orbits.encode("latin-1"))
            return httpx.Response(200, content=b"column format\n")

        return ORB6Downloader(httpx.Client(transport=httpx.MockTransport(handler)))

    def test_writes_the_files_and_the_terms(self, tmp_path, monkeypatch):
        downloader = self.make(tmp_path, monkeypatch, ORB6_TEXT)
        downloader.download()
        assert orb6.count_rows(orb6.OUT_DIR / orb6.ORBITS_FILE) == 5
        meta = json.loads(downloader.metadata_file.read_text())
        assert (meta["record_count"], meta["systems"], meta["version"]) == (
            5,
            4,
            "2026-10-13",
        )
        assert meta["terms"]["distribution"] == "non-commercial"
        assert downloader.is_complete(None)

    def test_an_orbit_count_off_the_home_page_fails(self, tmp_path, monkeypatch):
        short = "\n".join(ORB6_LINES[:-1]) + "\n"
        downloader = self.make(tmp_path, monkeypatch, short)
        with pytest.raises(DownloadError, match="4 orbits, the page gives 5"):
            downloader.download()
        assert not (orb6.OUT_DIR / orb6.ORBITS_FILE).exists()


SBX_TABLES = {
    sbx.SYSTEMS: SBX_SYSTEMS,
    sbx.ORBITS: SBX_ORBITS,
    sbx.ALIAS: SBX_ALIAS,
    sbx.CONFIGURATIONS: "child1,child2,family,in_high_order,in_quadruple,in_triple,parent,sn\n"
    ',,"{1729,1730}",0,0,1,1730,1729\n',
    sbx.DUPLICATES: "sn,sn_duplicate\n374,2544\n",
}


class TestSBX:
    """The tables of the SBX TAP service, checked against its counts."""

    def make(self, tmp_path, monkeypatch, counts: dict[str, int]) -> SBXDownloader:
        monkeypatch.setattr(sbx, "OUT_DIR", tmp_path / "sbx")

        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == sbx.TAP_URL
            query = parse_qs(request.content.decode())["QUERY"][0]
            name = query.rsplit(" ", 1)[1]
            if query.startswith("SELECT COUNT(*)"):
                return httpx.Response(200, text=f"COUNT_ALL\n{counts[name]}\n")
            return httpx.Response(200, content=SBX_TABLES[name].encode())

        return SBXDownloader(httpx.Client(transport=httpx.MockTransport(handler)))

    def test_writes_and_reads_the_tables(self, tmp_path, monkeypatch):
        counts = {sbx.SYSTEMS: 3, sbx.ORBITS: 3, sbx.ALIAS: 4}
        counts |= {sbx.CONFIGURATIONS: 1, sbx.DUPLICATES: 1}
        downloader = self.make(tmp_path, monkeypatch, counts)
        downloader.download()
        meta = json.loads(downloader.metadata_file.read_text())
        assert (meta["record_count"], meta["rows"]) == (3, counts)
        assert meta["terms"]["distribution"] == "open"

        orbits = sbx.read_table(sbx.ORBITS, sbx.OUT_DIR)
        assert orbits.schema.field("num_RV1").type == pa.int64()
        assert orbits.schema.field("periastron_time").type == pa.float64()
        alpha_cen = orbits.filter(pc.equal(orbits["sn"], 815)).to_pylist()[0]
        assert (alpha_cen["K1"], alpha_cen["epoch_reference"]) == (5.0, "JD")
        systems = sbx.read_table(sbx.SYSTEMS, sbx.OUT_DIR).to_pylist()
        # Text is trimmed.
        assert all(s["st1"] is None or s["st1"] == s["st1"].strip() for s in systems)

    def test_a_count_off_the_service_fails(self, tmp_path, monkeypatch):
        counts = {sbx.SYSTEMS: 3, sbx.ORBITS: 4, sbx.ALIAS: 4}
        counts |= {sbx.CONFIGURATIONS: 1, sbx.DUPLICATES: 1}
        downloader = self.make(tmp_path, monkeypatch, counts)
        with pytest.raises(DownloadError, match="orbits: 3 rows, the service counts 4"):
            downloader.download()
        assert not (sbx.OUT_DIR / "orbits.csv").exists()
