"""Tests for a CDS ReadMe and the files it describes."""

import gzip

import pyarrow as pa
import pytest

from space_map_data.download.cds import (
    byte_by_byte,
    count_records,
    read_fixed_width,
    record_counts,
)

README = """I/311               Hipparcos, the New Reduction       (van Leeuwen, 2007)
================================================================================
File Summary:
--------------------------------------------------------------------------------
 FileName   Lrecl  Records   Explanations
--------------------------------------------------------------------------------
ReadMe         80        .   This file
hip2.dat      276        3   The Astrometric Catalogue
                              (corrected version)
hip7p.dat     129        2   Seven-parameter solutions
notes.doc      97        1
--------------------------------------------------------------------------------

See also:
 I/239 : The Hipparcos and Tycho Catalogues (ESA 1997)

Byte-by-byte Description of file: hip2.dat
--------------------------------------------------------------------------------
   1-  6  I6    ---      HIP     Hipparcos identifier
"""


class TestReadMe:
    """Record counts from the `File Summary` block."""

    def test_counts_only_the_summary_rows(self):
        assert record_counts(README) == {"hip2.dat": 3, "hip7p.dat": 2, "notes.doc": 1}


class TestCountRecords:
    """The lines of a file, as bytes or on disk."""

    def test_counts_plain_and_gzip_bytes(self):
        assert count_records(b"a\nb\n", "a.dat") == 2
        assert count_records(gzip.compress(b"a\nb\nc\n"), "a.dat.gz") == 3

    def test_counts_a_file_on_disk_whatever_its_own_name(self, tmp_path):
        path = tmp_path / "a.dat.gz.part"
        path.write_bytes(gzip.compress(b"a\nb\n"))
        assert count_records(path, "a.dat.gz") == 2

    def test_data_only_leaves_out_headlines_and_blank_lines(self):
        content = b"# name  value\na 1\n\nb 2\n"
        assert count_records(content, "a.dat") == 4
        assert count_records(content, "a.dat", data_only=True) == 2


FORMAT_README = """J/X/1     A test catalogue
================================================================================
Byte-by-byte Description of file: stars.dat other.dat
--------------------------------------------------------------------------------
   Bytes Format Units   Label     Explanations
--------------------------------------------------------------------------------
   1-  6  I6    ---     HIP       Identifier
   8- 13  F6.2  mag     Vmag      ? Magnitude in V; a long explanation that
                                    wraps to a second line
      15  A1    ---     Flag      [AB] Flag
  17- 28  A12   ---     SpType    Spectral type
  30- 34  E5.1  ---     Rate      ? A rate
  36- 49 2F7.2  ---     UW        Weights
--------------------------------------------------------------------------------
Note (1): a note.

Byte-by-byte Description of file: notes.dat
--------------------------------------------------------------------------------
   Bytes Format Units   Label     Explanations
--------------------------------------------------------------------------------
   1-  6  I6    ---     HIP       Identifier
--------------------------------------------------------------------------------
"""
#        HIP    Vmag  F SpType       Rate  UW
LINES = [
    "    12  -1.46 A A1V          1.0E3   1.00   2.00",
    "   +34        B                            ",
    "123456  12.30   K3III/IV      ",
]


class TestByteByByte:
    """Fields from the byte-by-byte description of one file."""

    def test_reads_the_fields_of_a_listed_file(self):
        fields = byte_by_byte(FORMAT_README, "other.dat.gz")
        assert [f.label for f in fields] == [
            "HIP",
            "Vmag",
            "Flag",
            "SpType",
            "Rate",
            "UW",
        ]
        vmag = fields[1]
        assert (vmag.start, vmag.end, vmag.kind, vmag.unit) == (7, 13, "F", "mag")
        assert vmag.explanation.startswith("? Magnitude")
        assert (fields[2].start, fields[2].end) == (14, 15)
        assert fields[5].repeat == 2

    def test_a_file_without_a_description_raises(self):
        with pytest.raises(ValueError, match="missing.dat"):
            byte_by_byte(FORMAT_README, "missing.dat")


class TestReadFixedWidth:
    """Typed columns from a plain or gzip fixed-width file."""

    @pytest.mark.parametrize("name", ["stars.dat", "stars.dat.gz"])
    def test_types_blanks_and_short_lines(self, tmp_path, name):
        content = ("\n".join(LINES) + "\n").encode()
        path = tmp_path / name
        path.write_bytes(gzip.compress(content) if name.endswith(".gz") else content)
        table = read_fixed_width(
            path,
            FORMAT_README,
            {"HIP": "hip", "Vmag": "v", "SpType": "sp", "Rate": "r"},
        )
        assert table.schema.types == [
            pa.int64(),
            pa.float64(),
            pa.string(),
            pa.float64(),
        ]
        assert table.to_pydict() == {
            "hip": [12, 34, 123456],
            "v": [-1.46, None, 12.3],
            "sp": ["A1V", None, "K3III/IV"],
            "r": [1000.0, None, None],
        }

    def test_labels_as_a_list_keep_their_names(self, tmp_path):
        path = tmp_path / "stars.dat"
        path.write_text("\n".join(LINES) + "\n")
        assert read_fixed_width(path, FORMAT_README, ["Flag"]).to_pydict() == {
            "Flag": ["A", "B", None]
        }

    def test_null_markers(self, tmp_path):
        path = tmp_path / "stars.dat"
        path.write_text("    12    --- A ---\n    34   2.00 - B\n")
        table = read_fixed_width(
            path, FORMAT_README, {"Vmag": "v", "SpType": "sp"}, nulls=("---", "-")
        )
        assert table.to_pydict() == {"v": [None, 2.0], "sp": [None, "B"]}

    def test_a_record_ends_only_at_a_newline(self, tmp_path):
        # Latin-1 0x85 is NEL and 0x0c is a form feed: str.splitlines breaks on both.
        path = tmp_path / "stars.dat"
        path.write_bytes(b"    12  -1.46 A A1\x85\x0cV\r\n    34   2.00 B K0III\n")
        table = read_fixed_width(path, FORMAT_README, {"HIP": "hip", "SpType": "sp"})
        assert table.to_pydict() == {"hip": [12, 34], "sp": ["A1\x85\x0cV", "K0III"]}

    def test_unknown_and_repeated_fields_raise(self, tmp_path):
        path = tmp_path / "stars.dat"
        path.write_text("\n".join(LINES) + "\n")
        with pytest.raises(ValueError, match="Bmag"):
            read_fixed_width(path, FORMAT_README, ["Bmag"])
        with pytest.raises(ValueError, match="repeated"):
            read_fixed_width(path, FORMAT_README, ["UW"])
