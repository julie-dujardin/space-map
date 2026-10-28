"""Tests for the WDS, MSC and El-Badry et al. 2021 downloads."""

import hashlib
import io
import json
import tarfile

import httpx
import numpy as np
import pyarrow as pa
import pytest
from astropy.io import fits

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.stars import el_badry, msc, wds
from space_map_data.download.providers.stars.el_badry import (
    ElBadryBinariesDownloader,
)
from space_map_data.download.providers.stars.msc import MSCDownloader
from space_map_data.download.providers.stars.wds import WDSDownloader
from space_map_data.download.providers.three_d import resumable


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(resumable, "RETRY_WAIT_SECONDS", 0)


# Rows of the catalogue of 2026-10-13, as published.
PAIRS = (
    "<pre>\n"
    "    WDS   Discovr Comp  EPOCH      #  THETA       RHO     Magnitudes\n"
    "14396-6050RHD   1AB    1752 2023  481 218   5  20.5   8.1  0.01  1.33 G2V+K1V   -368+047          -60 5483 NO P 143936.50-605002.3\n"
    "14396-6050LDS 494AC    1920 2016    4 225 212 999.9 999.9  0.14 12.7  G2V+M5Ve  -364+070                   NO P 143936.50-605002.3\n"
    "00000-0530OCC 622      1982 1982    0  -1  -1   0.1   0.1  9.5   9.7  G5        +024-012          -06 6337      000000.08-052939.7\n"
    "00056-1929TOI 378AB    2019 2019    1 312 312   3.3   3.3   .     .                                             000535.83-192920.2\n"
    "00123-2729LDS2101      1954 2017    2  64  57   5.0   1.9 16.0  19.8            +085+027                    X         .         . \n"
)
COMPONENTS = (
    "07346+3153STF1110A     1884 2023   18 221.80  178.300      1.93 10.07 A1V       -206-148 -005+000 +32 1580 NU   073435.86+315317.8 **p DR3 892348694913501952  \n"
    "07346+3153STF1110D     1884 2023   18 221.80  178.300      1.93 10.07 A1V       -206-148 -005+000 +32 1580 NU   073426.53+315104.9 **s .                       \n"
    "04247-0845FOX 138C     1891 2015   11  77.30  151.380      8.59  8.69 G0        -111-171 -006+010 -09  896 NU   042451.97-084437.2 **s \tGaia DR3 3191901432464914048\n"
    "00000-0530OCC 622A     1982 1982    0  -1.00    0.067      9.5   9.7  G5        +024-012          -06 6337      000000.08-052939.7 **p DR3 2443095153084654208 \n"
)
NAMES = (
    "<pre>\n"
    "WDS------- DD-----    Designation 1         Designation 2         Designation 3         Designation 4\n"
    "\n"
    "14396-6050 LDS 494C   Proxima Centauri      V645 Cen              .                     .                        \n"
    "00084+2905 H 5  32    21 And                alp And               Alpheratz             .                        \n"
)


def note(head: str, text: str, reference: str = ".") -> bytes:
    """A line of the notes: id and key, the text at byte 24, the reference at 96."""
    return (
        head.encode().ljust(23) + text.encode().ljust(72) + reference.encode() + b"\n"
    )


NOTES = b"".join(
    [
        b"USNO Double Star Catalogs: Notes\n\n",
        note("00052+4514 ES 9001", "Previously known as ES 1293a."),
        note("           BU 9001", "Previously known as BU  997a."),
        note("07346+3153 STF1110", "alp Gem = Castor.", "A__1935f")[:-1] + b"\r\n",
        note("", "Discovered in 1719 by Bradley and Pound.", "A__1935f"),
        note("06249+1424 A  2722", "dm = 0.6\u2009mag in the I band."),
    ]
)
HOME = (
    "<p>the components of \n157990\n systems based on \n2243347\n means as of\n"
    "Tue Oct 13 11:58:01 AM EDT 2026\n.\n"
)


class TestWDSReaders:
    """The fixed-width files of the WDS, read as tables."""

    def test_reads_the_pairs(self, tmp_path):
        path = tmp_path / wds.PAIRS_FILE
        path.write_text(PAIRS)
        rows = wds.read_pairs(path).to_pylist()
        assert len(rows) == 5
        ab, ac, occultation, faint, dubious = rows
        assert (ab["wds_id"], ab["discoverer"], ab["components"]) == (
            "14396-6050",
            "RHD   1",
            "AB",
        )
        assert (ab["first_date"], ab["pa_last"], ab["sep_last"]) == (1752, 5, 8.1)
        # The code P gives the proper motion per 100 years.
        assert (ab["pm1_ra"], ab["pm1_dec"], ab["pm2_ra"]) == (-3680, 470, None)
        assert ab["ra"] == pytest.approx(219.902083, abs=1e-6)
        assert ab["dec"] == pytest.approx(-60.833972, abs=1e-6)
        assert ac["sep_last"] == wds.SEPARATION_OVERFLOW
        assert occultation["components"] is None
        assert (occultation["pa_first"], occultation["pm1_ra"]) == (None, 24)
        assert (faint["mag1"], faint["mag2"], faint["notes"]) == (None, None, None)
        assert dubious["notes"] == wds.DUBIOUS_CODE
        assert (dubious["ra"], dubious["dec"]) == (None, None)

    def test_reads_the_components_and_their_gaia_sources(self, tmp_path):
        path = tmp_path / wds.GAIA_FILE
        path.write_text(COMPONENTS)
        rows = wds.read_components(path).to_pylist()
        assert [(r["component"], r["primary"], r["source_id"]) for r in rows] == [
            ("A", True, 892348694913501952),
            ("D", False, None),
            ("C", False, 3191901432464914048),
            ("A", True, 2443095153084654208),
        ]
        assert (rows[0]["pa"], rows[0]["sep"]) == (221.8, 178.3)
        assert rows[3]["pa"] is None
        assert rows[1]["ra"] == pytest.approx(113.610542, abs=1e-6)

    def test_reads_the_names(self, tmp_path):
        path = tmp_path / wds.NAMES_FILE
        path.write_text(NAMES)
        rows = wds.read_names(path).to_pylist()
        assert rows == [
            {
                "wds_id": "14396-6050",
                "discoverer": "LDS 494",
                "component": "C",
                "names": ["Proxima Centauri", "V645 Cen"],
            },
            {
                "wds_id": "00084+2905",
                "discoverer": "H 5  32",
                "component": None,
                "names": ["21 And", "alp And", "Alpheratz"],
            },
        ]

    def test_reads_a_note_over_its_lines(self, tmp_path):
        path = tmp_path / wds.NOTES_FILE
        path.write_bytes(NOTES)
        rows = wds.read_notes(path).to_pylist()
        assert [(r["wds_id"], r["key"]) for r in rows] == [
            ("00052+4514", "ES 9001"),
            ("00052+4514", "BU 9001"),
            ("07346+3153", "STF1110"),
            ("06249+1424", "A  2722"),
        ]
        assert rows[2]["text"] == (
            "alp Gem = Castor. Discovered in 1719 by Bradley and Pound."
        )
        assert rows[2]["references"] == ["A__1935f"]
        assert rows[0]["references"] == []
        assert rows[3]["text"] == "dm = 0.6 mag in the I band."

    def test_reads_the_release_of_the_home_page(self):
        release = wds.parse_release(HOME)
        assert (release.pairs, release.means) == (157990, 2243347)
        assert release.day.isoformat() == "2026-10-13"
        with pytest.raises(DownloadError, match="page changed"):
            wds.parse_release("<p>Nothing here.</p>")


class TestWDSDownloader:
    """The files of the WDS, checked against the pair count of the home page."""

    def make(self, tmp_path, monkeypatch, pairs: str) -> WDSDownloader:
        monkeypatch.setattr(wds, "OUT_DIR", tmp_path / "wds")
        bodies = {
            wds.PAIRS_FILE: pairs,
            wds.COMPONENTS_FILE: COMPONENTS,
            wds.GAIA_FILE: COMPONENTS,
            wds.NAMES_FILE: NAMES,
            wds.FORMAT_FILE: "WDS BIBLE\n",
        }
        home = HOME.replace("157990", "5")

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == wds.HOME_URL:
                return httpx.Response(200, text=home)
            assert request.headers["Accept-Encoding"] == "identity"
            name = str(request.url).rsplit("/", 1)[1]
            if name == wds.NOTES_FILE:
                return httpx.Response(200, content=NOTES)
            return httpx.Response(200, content=bodies[name].encode())

        client = httpx.Client(transport=httpx.MockTransport(handler))
        return WDSDownloader(client)

    def test_writes_the_files_and_the_terms(self, tmp_path, monkeypatch):
        downloader = self.make(tmp_path, monkeypatch, PAIRS)
        downloader.download()
        assert (wds.OUT_DIR / wds.PAIRS_FILE).read_text() == PAIRS
        meta = json.loads(downloader.metadata_file.read_text())
        assert (meta["record_count"], meta["version"]) == (5, "2026-10-13")
        assert meta["files"][wds.GAIA_FILE]["rows"] == 4
        assert meta["files"][wds.FORMAT_FILE]["rows"] == 0
        assert meta["terms"]["distribution"] == "non-commercial"
        assert wds.ACKNOWLEDGEMENT in meta["terms"]["quotes"][0]["text"].replace(
            "``", ""
        ).replace("''", "")
        assert downloader.is_complete(None)

    def test_a_pair_count_off_the_home_page_fails(self, tmp_path, monkeypatch):
        short = PAIRS.rsplit("\n", 2)[0] + "\n"
        downloader = self.make(tmp_path, monkeypatch, short)
        with pytest.raises(DownloadError, match="4 pairs, the home page gives 5"):
            downloader.download()
        assert not (wds.OUT_DIR / wds.PAIRS_FILE).exists()


README = """J/A+AS/124/75       Multiple star catalogue (MSC) (Tokovinin 1997)
================================================================================
Byte-by-byte Description of file: comp.tsv
--------------------------------------------------------------------------------
   Bytes Format Units   Label     Explanations
--------------------------------------------------------------------------------
   1- 10  A10   ---     WDS       WDS (J2000) (1)
  12- 19  F8.2  mas     plx       Parallax
  21- 22  A2   ---      Comp      Component label
  24- 29  I6   ---      HIP       Hipparcos number
      31  I1   ---      Gr        Grade (3)
  33- 82  A50  ---      Id        Other identifiers
--------------------------------------------------------------------------------
Note (1): The WDS index may differ.

Byte-by-byte Description of file: sys.tsv
--------------------------------------------------------------------------------
   Bytes Format Units   Label     Explanations
--------------------------------------------------------------------------------
   1- 10  A10   ---     WDS       WDS(J2000)
  12- 14  A3    ---     Primary   Primary component label
  16- 18  A3    ---     Secondary Secondary component label
  20- 22  A3    ---     Parent    Parent label (1)
--------------------------------------------------------------------------------

Byte-by-byte Description of file: orb.tsv
--------------------------------------------------------------------------------
   Bytes Format Units   Label     Explanations
--------------------------------------------------------------------------------
   1- 10  A10   ---     WDS       WDS(J2000)
  12- 19  A7    ---     System    Primary,Secondary
  21- 26  F6.3  ---     e         Eccentricity
--------------------------------------------------------------------------------

Byte-by-byte Description of file: notes.tsv
--------------------------------------------------------------------------------
   Bytes Format Units   Label     Explanations
--------------------------------------------------------------------------------
   1- 10  A10   ---     WDS       WDS(J2000)
  12- 91  A80   ---     Rem       Remark text

Acknowledgements: Andrei Tokovinin
"""
TABLES = {
    msc.COMP_FILE: (
        "14396-6050|  742.10| A| 71683|5|CPD-60_5483, HR_5459, *alp1_Cen, GJ_551\n"
        "14396-6050|  768.07| C| 70890|0|V*_V645_Cen, GJ_551, Proxima\n"
        "04312-3305|   10.04| A|     0|*|2MASS_J04311272-3304583\n"
    ),
    msc.SYS_FILE: "14396-6050|AB |C  |*  \n14396-6050|A  |B  |AB \n\n",
    msc.ORB_FILE: "14396-6050|A,B    | 0.000\n",
    msc.NOTES_FILE: "14396-6050|Proxima is C.\n",
}


def tarball(tables: dict[str, str], readme: str = README) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, text in {msc.README_FILE: readme, **tables}.items():
            data = text.encode("latin-1")
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


PAGE = """<LI>Latest MSC version (June 19, 2026): <A HREF="newmsc-20260619.tar.gz"> newmsc-20260619.tar.gz </A>
<LI> Previous version:  (January 1, 2024): <A HREF="newmsc-20240101.tar.gz"> newmsc-20240101.tar.gz </A>
"""


class TestMSC:
    """The newest tarball of the MSC page, and its tables read by the Readme."""

    def make(self, tmp_path, monkeypatch, content: bytes) -> MSCDownloader:
        monkeypatch.setattr(msc, "OUT_DIR", tmp_path / "msc")
        self.asked: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.asked.append(str(request.url))
            if str(request.url) == msc.PAGE_URL:
                return httpx.Response(200, text=PAGE)
            return httpx.Response(200, content=content)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        return MSCDownloader(client)

    def test_takes_the_newest_tarball_of_the_page(self):
        assert msc.newest_tarball(PAGE)[0] == "newmsc-20260619.tar.gz"
        with pytest.raises(DownloadError, match="links no"):
            msc.newest_tarball("<p>No tarball.</p>")

    def test_writes_and_reads_the_tables(self, tmp_path, monkeypatch):
        downloader = self.make(tmp_path, monkeypatch, tarball(TABLES))
        (msc.OUT_DIR / "newmsc-20240101.tar.gz").write_bytes(b"old")
        downloader.download()
        assert self.asked[1] == msc.PAGE_URL + "newmsc-20260619.tar.gz"
        assert not (msc.OUT_DIR / "newmsc-20240101.tar.gz").exists()
        meta = json.loads(downloader.metadata_file.read_text())
        assert (meta["version"], meta["record_count"]) == ("2026-06-19", 3)
        assert meta["rows"] == {
            "comp.tsv": 3,
            "sys.tsv": 2,
            "orb.tsv": 1,
            "notes.tsv": 1,
        }
        assert meta["terms"]["distribution"] == "non-commercial"

        comp = msc.read_table(msc.COMP_FILE, msc.OUT_DIR)
        assert comp.schema.field("plx").type == pa.float64()
        assert comp.schema.field("HIP").type == pa.int64()
        assert comp["Comp"].to_pylist() == ["A", "C", "A"]
        # A grade that is not a number is null. A zero stays.
        assert comp["Gr"].to_pylist() == [5, 0, None]
        assert comp["HIP"].to_pylist() == [71683, 70890, 0]
        sys = msc.read_table(msc.SYS_FILE, msc.OUT_DIR)
        assert sys["Parent"].to_pylist() == [msc.ROOT_PARENT, "AB"]
        orb = msc.read_table(msc.ORB_FILE, msc.OUT_DIR)
        assert orb["e"].to_pylist() == [0.0]

    def test_a_line_with_a_wrong_field_count_fails(self, tmp_path, monkeypatch):
        tables = {**TABLES, msc.NOTES_FILE: "14396-6050|Proxima | is C.\n"}
        downloader = self.make(tmp_path, monkeypatch, tarball(tables))
        with pytest.raises(DownloadError, match="notes.tsv, line 1: 3 fields"):
            downloader.download()
        assert not (msc.OUT_DIR / msc.NOTES_FILE).exists()

    def test_a_tarball_without_a_table_fails(self, tmp_path, monkeypatch):
        tables = {k: v for k, v in TABLES.items() if k != msc.ORB_FILE}
        downloader = self.make(tmp_path, monkeypatch, tarball(tables))
        with pytest.raises(DownloadError, match="the tarball has no orb.tsv"):
            downloader.download()
        assert not list(msc.OUT_DIR.iterdir())


def catalogue(path, *, epoch: float = 2016.0) -> None:
    """A FITS table with the columns that pairs.parquet takes, and one more."""
    rows = 5
    numbers = np.arange(rows, dtype=np.float64)
    columns = [
        fits.Column("source_id1", "K", array=np.arange(rows) + 100),
        fits.Column("source_id2", "K", array=np.arange(rows) + 200),
        fits.Column("solution_id1", "K", array=np.zeros(rows, np.int64)),
        fits.Column("ref_epoch1", "D", array=np.full(rows, epoch)),
        fits.Column("ref_epoch2", "D", array=np.full(rows, 2016.0)),
        fits.Column("pairdistance", "D", array=numbers / 3600),
        fits.Column("binary_type", "4A", array=np.array(["MSMS", "WD??"] * 2 + ["MS"])),
    ]
    for name, (kind, _, _) in el_badry.PAIR_COLUMNS.items():
        if name in ("source_id1", "source_id2", "sep_arcsec", "binary_type"):
            continue
        values = numbers + 0.5
        if name == "phot_bp_mean_mag2":
            values[1] = np.nan
        columns.append(
            fits.Column(name, "E" if kind == pa.float32() else "D", array=values)
        )
    hdus = fits.HDUList([fits.PrimaryHDU(), fits.BinTableHDU.from_columns(columns)])
    hdus.writeto(path)


class TestElBadry:
    """The FITS of the Zenodo record, and the columns it writes beside it."""

    def test_writes_the_pairs_in_batches(self, tmp_path, monkeypatch):
        monkeypatch.setattr(el_badry, "BATCH_ROWS", 2)
        source = tmp_path / el_badry.SOURCE_FILE
        catalogue(source)
        rows = el_badry.write_pairs(source, tmp_path / el_badry.PAIRS_FILE)
        assert rows == 5
        pairs = el_badry.read_pairs(tmp_path / el_badry.PAIRS_FILE)
        assert pairs.schema == el_badry.PAIRS_SCHEMA
        assert pairs["source_id1"].to_pylist() == [100, 101, 102, 103, 104]
        assert pairs["sep_arcsec"].to_pylist() == pytest.approx([0, 1, 2, 3, 4])
        assert pairs["binary_type"].to_pylist() == [
            "MSMS",
            "WD??",
            "MSMS",
            "WD??",
            "MS",
        ]
        assert pairs["ruwe2"].to_pylist() == [0.5, 1.5, 2.5, 3.5, 4.5]
        # A NaN of the FITS is null.
        assert pairs["phot_bp_mean_mag2"].to_pylist()[:3] == [0.5, None, 2.5]
        some = el_badry.read_pairs(tmp_path / el_badry.PAIRS_FILE, ["sep_AU"])
        assert some.column_names == ["sep_AU"]

    def test_a_position_at_another_epoch_fails(self, tmp_path):
        source = tmp_path / el_badry.SOURCE_FILE
        catalogue(source, epoch=2015.5)
        with pytest.raises(DownloadError, match="ref_epoch1 is not 2016.0"):
            el_badry.write_pairs(source, tmp_path / el_badry.PAIRS_FILE)
        assert not (tmp_path / el_badry.PAIRS_FILE).exists()

    def make(self, tmp_path, monkeypatch, content: bytes, checksum: str):
        monkeypatch.setattr(el_badry, "OUT_DIR", tmp_path / "out")
        record = {
            "files": [
                {
                    "key": el_badry.SOURCE_FILE,
                    "checksum": f"md5:{checksum}",
                    "links": {"self": "https://zenodo.test/catalog"},
                }
            ]
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith(str(el_badry.RECORD)):
                return httpx.Response(200, json=record)
            return httpx.Response(200, content=content)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        return ElBadryBinariesDownloader(client)

    def test_writes_the_catalogue_and_its_pairs(self, tmp_path, monkeypatch):
        catalogue(tmp_path / "upstream.fits.gz")
        content = (tmp_path / "upstream.fits.gz").read_bytes()
        downloader = self.make(
            tmp_path, monkeypatch, content, hashlib.md5(content).hexdigest()
        )
        downloader.download()
        assert (el_badry.OUT_DIR / el_badry.SOURCE_FILE).read_bytes() == content
        meta = json.loads(downloader.metadata_file.read_text())
        assert (meta["record_count"], meta["record"]) == (5, el_badry.RECORD)
        assert meta["terms"]["license"] == "CC BY 4.0"
        columns = json.loads((el_badry.OUT_DIR / el_badry.COLUMNS_FILE).read_text())
        assert [c["name"] for c in columns] == list(el_badry.PAIR_COLUMNS)
        assert columns[0]["datatype"] == "int64"
        assert downloader.is_complete(None)
        # A new column list writes the pairs again.
        monkeypatch.setitem(el_badry.PAIR_COLUMNS, "extra", (pa.int8(), None, ""))
        assert not downloader.is_complete(None)

    def test_a_wrong_checksum_writes_nothing(self, tmp_path, monkeypatch):
        downloader = self.make(tmp_path, monkeypatch, b"not a catalogue", "0" * 32)
        with pytest.raises(DownloadError, match="MD5"):
            downloader.download()
        assert not (el_badry.OUT_DIR / el_badry.SOURCE_FILE).exists()
