"""Tests for the record counts of a CDS ReadMe and of a CDS file."""

import gzip

from space_map_data.download.cds import count_records, record_counts

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
