"""Tests for the class catalogues that join the Gaia rows: GCVS and SPICY."""

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from space_map_data.extrasolar.sources import gcvs, spicy
from space_map_data.extrasolar.sources.simbad import SimbadList
from tests.extrasolar.systems_fakes import simbad_object

NO_DR2 = np.iinfo(np.int64).min


# The "|" columns of a gcvs5.txt line.
SEPARATORS = (7, 19, 42, 53, 63, 76, 89, 92, 105, 111, 132, 138, 156, 168, 180, 196)


def gcvs_line(name: str, vartype: str, remark: str = "") -> str:
    """A line of gcvs5.txt with only the fields that the ingest reads."""
    line = [" "] * 240
    for at in SEPARATORS:
        line[at] = "|"
    for column, text in (
        (gcvs._NAME, name),
        (gcvs._TYPE, vartype),
        (gcvs._REMARK, remark),
    ):
        line[column] = text.ljust(column.stop - column.start)
    return "".join(line)


def write_resolved(path: Path, rows: list[tuple[str, str, str, str]]) -> Path:
    """A names.csv of gcvs_simbad: name, oid, Gaia DR3 id, HIP number."""
    lines = ["name,oid,main_id,otype,gaia_dr3,hip"]
    lines += [f"{name},{oid},,*,{gaia},{hip}" for name, oid, gaia, hip in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


class TestGcvsDesignation:
    """The SIMBAD spelling of a GCVS designation."""

    @pytest.mark.parametrize(
        ("text", "name"),
        [
            ("V0645 Cen  ", "V645 Cen"),
            ("alf 2 CVn  ", "alf02 CVn"),
            ("EQ    PegA*", "EQ Peg A"),
            ("V1659 Sco* ", "V1659 Sco"),
            ("R     CrA *", "R CrA"),
            ("YZ    CMi *", "YZ CMi"),
            ("mu.   Cep *", "mu. Cep"),
            ("khi   Cyg *", "chi Cyg"),
            ("khi 1 Ori *", "chi01 Ori"),
            ("u.    Her *", "u Her"),
        ],
    )
    def test_spelling(self, text, name):
        assert gcvs.designation(text) == name

    @pytest.mark.parametrize(
        "text", ["", "Cen", "alf x CVn", "V0645 cen", "LMC  V1970", "N5457V0011"]
    )
    def test_no_designation(self, text):
        assert gcvs.designation(text) is None


class TestGcvsEntries:
    """The entries of gcvs5.txt that exist."""

    def test_read_entries(self, tmp_path):
        path = tmp_path / "gcvs5.txt"
        # V3721 Oph merges the remark with the next field: its "|" is missing.
        merged = gcvs_line("V3721 Oph  ", "XN")
        merged = merged[: gcvs._REMARK.stop] + " " + merged[gcvs._REMARK.stop + 1 :]
        lines = [
            gcvs_line("S     Dor *", "SDOR", remark="=LMC  V1970"),
            gcvs_line("VV    And  ", "M", remark="Not exists"),
            gcvs_line("V0464 Aql  ", "EA", remark="=V0446 Aql"),
            gcvs_line("AB    Cet  ", ""),
            merged,
            "a line that is no row",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="koi8-r")
        assert gcvs.read_entries(path) == [("S Dor", "SDOR"), ("V3721 Oph", "XN")]


class TestGcvsStars:
    """A GCVS star is the one SIMBAD row that holds the light of its entry."""

    def test_read_stars(self, tmp_path):
        path = tmp_path / "gcvs5.txt"
        lines = [
            gcvs_line("V0645 Cen  ", "UV+BY"),
            gcvs_line("EQ    PegA*", "UV"),
            # A system of one row gives that row.
            gcvs_line("FF    And *", "UV+BY"),
            # A system of two rows does not say which component flares.
            gcvs_line("AW    Cnc *", "UV"),
            # Without a Gaia DR3 id the HIP number joins.
            gcvs_line("alf   Lyr *", "DSCTC"),
            # SIMBAD gives these two the same Gaia id; the first stays.
            gcvs_line("AB    Cet  ", "EA"),
            gcvs_line("AC    Cet  ", "BY"),
            # Not in the SIMBAD list: the gcvs_simbad ids join.
            gcvs_line("V0466 Boo  ", "UV"),
            gcvs_line("DQ    Cnc  ", "UV"),
            gcvs_line("MZ    Tau  ", "UV"),
            gcvs_line("XX    Tau  ", "UV"),
            # A system hands its HIP number to its primary row.
            gcvs_line("QQ    Lyr  ", "UV"),
            # A system does not hand its HIP number to a far component.
            gcvs_line("QR    Lyr  ", "UV"),
            # The Hipparcos row of a best neighbour is the star of its Gaia row.
            gcvs_line("BB    Lyr  ", "UV"),
            gcvs_line("BC    Lyr  ", "UV"),
            # A HIP number whose best neighbour is another source is not on
            # the star of the Gaia row.
            gcvs_line("BD    Lyr  ", "UV"),
            gcvs_line("BE    Lyr  ", "UV"),
            # Outside the list, the HIP number joins unless its best
            # neighbour is another Gaia source.
            gcvs_line("V0467 Boo  ", "UV"),
            gcvs_line("V0468 Boo  ", "UV"),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="koi8-r")
        objects = [
            simbad_object(
                1,
                "NAME Proxima",
                0,
                0,
                gaia="5853498713190525696",
                identifiers=("V* V645 Cen",),
            ),
            simbad_object(
                2, "V* EQ Peg A", 1, 0, gaia="100", identifiers=("V* EQ Peg A",)
            ),
            simbad_object(3, "V* FF And", 2, 0, identifiers=("V* FF And",)),
            simbad_object(4, "V* FF And A", 2, 0, v=10.0, gaia="200"),
            simbad_object(5, "V* AB Cet", 3, 0, gaia="300", identifiers=("V* AB Cet",)),
            simbad_object(6, "V* AC Cet", 3, 0, gaia="300", identifiers=("V* AC Cet",)),
            simbad_object(7, "V* AW Cnc", 4, 0, identifiers=("V* AW Cnc",)),
            simbad_object(8, "V* AW Cnc A", 4, 0, v=10.0, gaia="400"),
            simbad_object(9, "V* AW Cnc B", 4, 0, v=11.0, gaia="401"),
            simbad_object(
                10, "* alf Lyr", 5, 0, hip="91262", identifiers=("V* alf Lyr",)
            ),
            simbad_object(11, "XX Tau", 6, 0, gaia="600"),
            simbad_object(12, "* q Lyr", 7, 0, hip="5000"),
            simbad_object(13, "Q Lyr B", 7, 0, v=9.0, identifiers=("V* QQ Lyr",)),
            simbad_object(
                14, "V* QR Lyr", 8, 0, hip="6000", identifiers=("V* QR Lyr",)
            ),
            simbad_object(15, "R Lyr B", 8.01, 0, v=9.0),
            simbad_object(
                16, "V* BB Lyr", 9, 0, hip="7000", identifiers=("V* BB Lyr",)
            ),
            simbad_object(
                17, "V* BC Lyr", 9, 0, gaia="700", identifiers=("V* BC Lyr",)
            ),
            simbad_object(
                18,
                "V* BD Lyr",
                10,
                0,
                gaia="710",
                hip="7100",
                identifiers=("V* BD Lyr",),
            ),
            simbad_object(
                19, "V* BE Lyr", 11, 0, gaia="711", identifiers=("V* BE Lyr",)
            ),
        ]
        simbad = SimbadList(
            {o.oid: o for o in objects},
            {3: [4], 7: [8, 9], 12: [13], 14: [15]},
            {},
            frozenset(),
            frozenset(),
        )
        resolved = write_resolved(
            tmp_path / "names.csv",
            [
                ("V466 Boo", "20", "500", ""),
                ("DQ Cnc", "21", "", ""),
                ("MZ Tau", "22", "", "1234"),
                # A designation of a listed object takes the list's row.
                ("XX Tau", "11", "999", ""),
                ("V467 Boo", "23", "800", "8000"),
                ("V468 Boo", "24", "900", "9000"),
            ],
        )
        best = {7000: 700, 7100: 711, 9000: 901}
        rows = gcvs.read_stars(simbad, simbad.handed(), best, path, resolved)
        rows = rows.to_pylist()
        assert [(r["source_id"], r["hip"], r["gcvs_name"]) for r in rows] == [
            (5853498713190525696, 0, "V645 Cen"),
            (100, 0, "EQ Peg A"),
            (200, 0, "FF And"),
            (0, 91262, "alf Lyr"),
            (300, 0, "AB Cet"),
            (500, 0, "V466 Boo"),
            (0, 1234, "MZ Tau"),
            (600, 0, "XX Tau"),
            (0, 5000, "QQ Lyr"),
            (0, 7000, "BB Lyr"),
            (710, 0, "BD Lyr"),
            (711, 0, "BE Lyr"),
            (0, 8000, "V467 Boo"),
            (900, 0, "V468 Boo"),
        ]
        assert rows[0]["vartype_gcvs"] == "UV+BY"


def write_spicy(path: Path, rows: list[tuple[int, int, str, float]]) -> Path:
    spicy_id, dr2, classes, alpha = zip(*rows, strict=True)
    columns = fits.ColDefs(
        [
            fits.Column("SPICY", "K", array=np.array(spicy_id)),
            fits.Column("class", "9A", array=np.array(classes)),
            fits.Column("alpha", "D", array=np.array(alpha)),
            fits.Column("GaiaDR2", "K", array=np.array(dr2)),
        ]
    )
    fits.BinTableHDU.from_columns(columns).writeto(path)
    return path


def write_neighbourhood(path: Path, rows: list[tuple[int, int, float]]) -> Path:
    lines = ["dr2_source_id,dr3_source_id,angular_distance,magnitude_difference"]
    lines += [f"{dr2},{dr3},{distance},0.01" for dr2, dr3, distance in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


class TestSpicyStars:
    """A SPICY candidate takes the nearest DR3 neighbour of its DR2 id."""

    def test_read_stars(self, tmp_path, monkeypatch):
        monkeypatch.setattr(spicy, "ROWS", 5)
        table = write_spicy(
            tmp_path / "table1.fits",
            [
                (1, 11, "ClassI", 1.2),
                (2, 12, "FS", 0.1),
                (3, NO_DR2, "ClassII", -0.8),
                (4, 14, "ClassII", -1.0),
                (5, 15, "ClassIII", -2.0),
            ],
        )
        neighbourhood = write_neighbourhood(
            tmp_path / "dr2_neighbourhood.csv",
            [
                (11, 111, 5.0),
                (11, 112, 40.0),
                (12, 120, 3.0),
                # 14 and 15 reach one DR3 source; 15 is nearer.
                (14, 140, 9.0),
                (15, 140, 2.0),
            ],
        )
        rows = spicy.read_stars(table, neighbourhood).to_pylist()
        assert [(r["source_id"], r["spicy_id"], r["class_spicy"]) for r in rows] == [
            (111, 1, "ClassI"),
            (120, 2, "FS"),
            (140, 5, "ClassIII"),
        ]
        assert rows[0]["alpha_spicy"] == pytest.approx(1.2)

    def test_no_candidate_with_a_neighbour(self, tmp_path, monkeypatch):
        monkeypatch.setattr(spicy, "ROWS", 1)
        table = write_spicy(tmp_path / "table1.fits", [(1, 11, "ClassI", 1.0)])
        neighbourhood = write_neighbourhood(tmp_path / "n.csv", [(12, 120, 1.0)])
        assert spicy.read_stars(table, neighbourhood).num_rows == 0

    def test_the_row_count_is_checked(self, tmp_path):
        table = write_spicy(tmp_path / "table1.fits", [(1, 11, "ClassI", 1.0)])
        neighbourhood = write_neighbourhood(tmp_path / "n.csv", [(11, 111, 1.0)])
        with pytest.raises(ValueError, match="SPICY has"):
            spicy.read_stars(table, neighbourhood)
