"""Tests for the class catalogues that join the rows of a pass: GCVS, SPICY
and ATNF."""

import io
import tarfile
from pathlib import Path

import numpy as np
import pyarrow.compute as pc
import pytest
from astropy.io import fits

from space_map_data.extrasolar.engine import IngestRun
from space_map_data.extrasolar.sources import atnf, gcvs, simbad, spicy
from space_map_data.extrasolar.sources.simbad import SIMBAD, SimbadList
from space_map_data.extrasolar.tables import POINT_SOURCE
from tests.extrasolar.conftest import id_of, offset, table_rows
from tests.extrasolar.systems_fakes import simbad_object
from tests.extrasolar.test_simbad import star, write_simbad
from tests.extrasolar.test_stars import DEC, RA

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


# A psrcat.db with the cases of the SIMBAD join.
PSRCAT = """#CATALOGUE 2.8.1
#
# Number of pulsars is 10
#
PSRJ     J0146+6145                    gk98
RAJ      01:46:22.407             2    gk98
TYPE     AXP,NRAD
@-----------------------------------------------------------------
PSRJ     J0534+2200                    tml93
PSRB     B0531+21                      ss68
# P_0, nc = 0 (lgw+13 versus lps93).
TYPE     ,HE[cgm+11],HE[aab+22]
@-----------------------------------------------------------------
PSRJ     J0537-69
@-----------------------------------------------------------------
PSRJ     J0537-6910                    mgz+98
@-----------------------------------------------------------------
PSRJ     J1647+6608
@-----------------------------------------------------------------
PSRJ     J1647+6609
@-----------------------------------------------------------------
PSRJ     J1312+1810A                   kzhs99
PSRB     B1310+18                      kzhs99
@-----------------------------------------------------------------
PSRJ     J1844-0346
TYPE     NRAD,AXP(?)
@-----------------------------------------------------------------
PSRJ     J0104+6029_P                  yly+25
@-----------------------------------------------------------------
PSRB     B0000+00
@-----------------------------------------------------------------
"""
# The names of PSRCAT that SIMBAD resolves, with their oid.
RESOLVED = {
    "J0146+6145": 10,
    "B0531+21": 20,
    "J0537-69": 30,
    "J0537-6910": 30,
    "J1647+6608": 40,
    "J1647+6609": 40,
    "J1312+1810A": 50,
    "B1310+18": 51,
    "J1844-0346": 60,
}


def write_psrcat(path: Path, text: str = PSRCAT) -> Path:
    """The ATNF package with only its psrcat.db."""
    data = text.encode()
    info = tarfile.TarInfo(atnf.DB_MEMBER)
    info.size = len(data)
    with tarfile.open(path, "w:gz") as archive:
        archive.addfile(info, io.BytesIO(data))
    return path


def write_pulsar_names(path: Path, names: list[str]) -> Path:
    """A names.csv of atnf_simbad: each name with its oid, empty for none."""
    lines = ["name,oid,main_id,otype"]
    lines += [f"{name},{RESOLVED.get(name, '')},,Psr" for name in names]
    path.write_text("\n".join(lines) + "\n")
    return path


def pulsar_names() -> list[str]:
    return [name for p in atnf.parse_pulsars(PSRCAT) for name in p.names]


class TestAtnfPulsars:
    """The entries of psrcat.db and their types as published."""

    def test_parse_pulsars(self):
        pulsars = atnf.parse_pulsars(PSRCAT)
        # The entry without a J name is left out.
        assert len(pulsars) == 9
        assert pulsars[0] == atnf.Pulsar("J0146+6145", None, "AXP,NRAD")
        assert pulsars[1] == atnf.Pulsar(
            "J0534+2200", "B0531+21", ",HE[cgm+11],HE[aab+22]"
        )
        assert pulsars[2] == atnf.Pulsar("J0537-69")
        assert pulsars[7].type == "NRAD,AXP(?)"

    def test_read_pulsars_from_the_package(self, tmp_path):
        path = write_psrcat(tmp_path / "psrcat_pkg.tar.gz")
        assert atnf.read_pulsars(path) == atnf.parse_pulsars(PSRCAT)

    @pytest.mark.parametrize(
        ("psrj", "digits"),
        [("J0537-69", 2), ("J0537-6910", 4), ("J1911+0101A", 4), ("J1858-0736_P", 4)],
    )
    def test_the_digits_of_a_j_name(self, psrj, digits):
        assert atnf.Pulsar(psrj).precision == digits


class TestAtnfStars:
    """A pulsar takes the SIMBAD object of its names, one pulsar per object."""

    def test_read_stars(self, tmp_path):
        path = write_psrcat(tmp_path / "psrcat_pkg.tar.gz")
        names = write_pulsar_names(tmp_path / "names.csv", pulsar_names())
        rows = atnf.read_stars(path, names).to_pylist()
        assert [(r["oid"], r["atnf_name"], r["type_atnf"]) for r in rows] == [
            (10, "J0146+6145", "AXP,NRAD"),
            # Only the B name resolves.
            (20, "J0534+2200", ",HE[cgm+11],HE[aab+22]"),
            # SIMBAD gives the short name to the pulsar of the full name.
            (30, "J0537-6910", None),
            # The J name wins over the B name. Object 40 has two pulsars
            # whose names have equal digits, so neither keeps it.
            (50, "J1312+1810A", None),
            (60, "J1844-0346", "NRAD,AXP(?)"),
        ]


class TestAtnfJoin:
    """The pulsars join the SIMBAD rows by oid and never mint."""

    def test_join_by_oid(self, tmp_path):
        directory = write_simbad(
            tmp_path / "simbad",
            [
                star(10, *offset(RA, DEC, 60, 0), "PSR J0146+6145", otype="Psr"),
                star(20, *offset(RA, DEC, 120, 0), "PSR B0531+21", otype="Psr"),
                star(70, *offset(RA, DEC, 180, 0), "HD 1"),
            ],
        )
        listed = SimbadList.read(directory)
        rows, _ = simbad.engine_rows(listed, listed.handed(), set(), {}, {})
        assert rows["type_atnf"].null_count == rows.num_rows
        pulsars = atnf.read_stars(
            write_psrcat(tmp_path / "psrcat_pkg.tar.gz"),
            write_pulsar_names(tmp_path / "names.csv", pulsar_names()),
        )
        # Objects 30, 50 and 60 have no SIMBAD row, so they add none.
        joined = atnf.join_by_oid(rows, pulsars)
        assert joined.num_rows == rows.num_rows
        assert joined.drop_columns(list(atnf.COLUMNS)).equals(
            rows.drop_columns(list(atnf.COLUMNS))
        )
        assert joined["atnf_name"].to_pylist() == ["J0146+6145", "J0534+2200", None]
        assert joined["type_atnf"].to_pylist() == [
            "AXP,NRAD",
            ",HE[cgm+11],HE[aab+22]",
            None,
        ]

        root = tmp_path / "root"
        with IngestRun.start(root, root / "backup") as run:
            run.add(SIMBAD, [joined])
            result = run.commit()
        assert result.entry["counts"]["minted"] == 3
        point = table_rows(root, POINT_SOURCE.slug)
        assert point.num_rows == 3
        magnetar = point.filter(pc.equal(point["id"], id_of(root, SIMBAD, 10)))
        assert magnetar["type_atnf"].to_pylist() == ["AXP,NRAD"]
        assert magnetar["atnf_source"].to_pylist() == ["simbad"]
        other = point.filter(pc.equal(point["id"], id_of(root, SIMBAD, 70)))
        assert other["atnf_source"].to_pylist() == [None]
