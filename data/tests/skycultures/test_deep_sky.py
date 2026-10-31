"""Tests for the catalogue places of deep-sky objects."""

import gzip
import io
import tarfile
from pathlib import Path

import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.skycultures import deep_sky
from space_map_data.skycultures.deep_sky import (
    BAUMGARDT,
    HECATE,
    HUNT_REFFERT,
    compact,
    read_places,
    simbad_key,
)

IDENT = {
    1: ["M  44", "NGC  2632", "Cl Melotte   88"],
    2: ["NGC  5139"],
    3: ["M  31", "NGC   224", "LEDA 2557"],
    4: ["M  42"],
    5: ["Barnard 33"],
    6: ["M  17", "NGC  6618"],
    7: ["Stock  2"],
}
BASIC = {1: (130.05, 19.62), 2: (201.7, -47.5), 3: (10.68, 41.27), 4: (83.8, -5.4)}
BASIC[5] = (85.2, -2.5)
BASIC[6] = (275.2, -16.2)
BASIC[7] = (33.6, 59.5)
HUNT_README = """
Byte-by-byte Description of file: clusters.dat
--------------------------------------------------------------------------------
   Bytes Format Units   Label      Explanations
--------------------------------------------------------------------------------
   1-  10  A10   ---      Name       Name
  12-  12  A1    ---      Type       Type
  14-  33  A20   ---      AllNames   All names
  35-  44  F10.1 pc       dist50     Distance
--------------------------------------------------------------------------------
"""
HECATE_README = """
Byte-by-byte Description of file: hecate.dat
--------------------------------------------------------------------------------
   Bytes Format Units   Label      Explanations
--------------------------------------------------------------------------------
   1-  7 I7     ---     PGC        PGC number
   9- 16 F8.4   Mpc     D          ? Distance
--------------------------------------------------------------------------------
"""


def _gzip(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(text.encode()))


def catalogue_files(root: Path) -> Path:
    """The local catalogues with one object of each kind."""
    ident = "id,oidref\n" + "".join(
        f'"{name}",{oid}\n' for oid, names in IDENT.items() for name in names
    )
    _gzip(root / "simbad/ident/00000001-00000009.csv.gz", ident)
    basic = "oid,ra,dec\n" + "".join(
        f"{oid},{ra},{dec}\n" for oid, (ra, dec) in BASIC.items()
    )
    _gzip(root / "simbad/basic/00000001-00000009.csv.gz", basic)
    # No oid of the fixture falls in its range, so its text is never read.
    (root / "simbad/basic/00000010-00000019.csv.gz").write_text("not gzip")
    hunt = root / "star-clusters" / HUNT_REFFERT
    _gzip(
        hunt / "clusters.dat.gz",
        "".join(
            f"{name:<10} {kind} {names:<20} {distance:>10.1f}\n"
            for name, kind, names, distance in (
                ("NGC_2632", "o", "NGC_2632,M_44", 183.5),
                ("NGC_6618", "m", "NGC_6618", 605.5),
                ("Stock_2", "o", "Stock_2", 370.0),
                ("Theia_1", "o", "Theia_1,Stock_2", 900.0),
            )
        ),
    )
    (hunt / "ReadMe").write_text(HUNT_README)
    globulars = root / "star-clusters" / BAUMGARDT
    globulars.mkdir(parents=True)
    (globulars / "combined_table.txt").write_text(
        "# Cluster RA DEC R_Sun\n"
        "NGC_5139       201.69700  -47.47950   5.43   0.05    6.49\n"
    )
    hecate = root / "galaxies" / HECATE
    _gzip(hecate / "hecate.dat.gz", f"{2557:>7} {0.7722:>8.4f}\n")
    (hecate / "ReadMe").write_text(HECATE_README)
    openngc = root / "galaxies/openngc"
    openngc.mkdir(parents=True)
    table = b"Name;RA;Dec\nNGC6888;20:12:06.55;+38:21:17.8\nIC0405;;\n"
    with tarfile.open(openngc / "OpenNGC-test.tar.gz", "w:gz") as archive:
        info = tarfile.TarInfo("OpenNGC/database_files/NGC.csv")
        info.size = len(table)
        archive.addfile(info, io.BytesIO(table))
    return root


class TestSpelling:
    """Designations of the cultures as SIMBAD writes them."""

    @pytest.mark.parametrize(
        ("designation", "key"),
        [
            ("DSO:NGC 6530", "NGC6530"),
            ("M  7", "M7"),
            ("B33", "BARNARD33"),
            ("CR399", "CLCOLLINDER399"),
            ("Mel 25", "CLMELOTTE25"),
            ("ST23", "CLSTOCK23"),
            ("PGC143", "LEDA143"),
            ("PK307-04.1", "PK307-041"),
            ("coalsack nebula", "NAMECOALSACKNEBULA"),
            ("Cl Melotte   22", "CLMELOTTE22"),
        ],
    )
    def test_keys(self, designation, key):
        assert simbad_key(designation) == key

    def test_compact(self):
        assert compact("Melotte_22 x") == "MELOTTE22X"


class TestReadPlaces:
    """Direction and distance of each kind of object."""

    NAMES = ("M44", "NGC 5139", "M31", "M42", "B33", "NGC6888", "IC405", "Nope")

    @pytest.fixture
    def places(self, tmp_path):
        names = [*self.NAMES, "M17", "Stock 2"]
        return read_places(names, catalogue_files(tmp_path))

    def test_an_open_cluster_by_another_identifier(self, places):
        assert places["M44"] == (130.05, 19.62, 183.5, HUNT_REFFERT)

    def test_a_moving_group_is_no_cluster(self, places):
        assert places["M17"] == (275.2, -16.2, None, None)

    def test_a_shared_alias_takes_the_row_of_that_name(self, places):
        assert places["Stock 2"] == (33.6, 59.5, 370.0, HUNT_REFFERT)

    def test_a_globular_cluster(self, places):
        assert places["NGC 5139"] == (201.7, -47.5, 5430.0, BAUMGARDT)

    def test_a_galaxy_by_its_leda_number(self, places):
        assert places["M31"] == pytest.approx((10.68, 41.27, 772200.0, HECATE))

    def test_no_distance_keeps_the_direction(self, places):
        assert places["M42"] == (83.8, -5.4, None, None)
        assert places["B33"] == (85.2, -2.5, None, None)

    def test_openngc_gives_what_simbad_lacks(self, places):
        place = places["NGC6888"]
        assert place.ra == pytest.approx(303.027, abs=1e-3)
        assert place.dec == pytest.approx(38.355, abs=1e-3)
        assert place.distance is None

    def test_no_catalogue_gives_no_place(self, places, caplog):
        assert "Nope" not in places
        assert "IC405" not in places
        assert deep_sky.Place(1.0, 2.0).source is None

    def test_the_newest_openngc_release_stands(self, tmp_path):
        root = catalogue_files(tmp_path)
        (root / "galaxies/openngc/OpenNGC-a.tar.gz").write_text("not a tar")
        assert read_places(["NGC6888"], root)["NGC6888"].ra == pytest.approx(
            303.027, abs=1e-3
        )

    @pytest.mark.parametrize(
        "missing",
        ["star-clusters/hunt-reffert-2024/ReadMe", "galaxies/hecate/hecate.dat.gz"],
    )
    def test_a_missing_catalogue_stops_the_run(self, tmp_path, missing):
        root = catalogue_files(tmp_path)
        (root / missing).unlink()
        with pytest.raises(DownloadError, match="is missing"):
            read_places(["M44"], root)

    def test_an_empty_folder_stops_the_run(self, tmp_path):
        root = catalogue_files(tmp_path)
        (root / "galaxies/openngc/OpenNGC-test.tar.gz").unlink()
        with pytest.raises(DownloadError, match="has no"):
            read_places(["M44"], root)
