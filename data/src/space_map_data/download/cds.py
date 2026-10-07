"""The CDS catalogue archive: its address, and the record counts of a ReadMe.

The ReadMe of a catalogue lists each data file with its record count.
"""

import gzip
import io
import re
from pathlib import Path

CDS_URL = "https://cdsarc.cds.unistra.fr/ftp"
README = "ReadMe"

_SUMMARY_ROW = re.compile(r"^\s*(\S+)\s+\d+\s+(\d+)(?:\s|$)")


def record_counts(readme: str) -> dict[str, int]:
    """The record count of each file, from the `File Summary` of a ReadMe."""
    counts: dict[str, int] = {}
    in_summary = False
    for line in readme.splitlines():
        if line.startswith("File Summary"):
            in_summary = True
        elif in_summary and line.startswith(("See also", "Byte-by-byte")):
            break
        elif in_summary and (match := _SUMMARY_ROW.match(line)):
            counts[match[1]] = int(match[2])
    return counts


def count_records(source: bytes | Path, name: str, *, data_only: bool = False) -> int:
    """The lines of the CDS file `name`, given as bytes or as a path.

    `data_only` leaves out the blank lines and the `#` headlines. Some ReadMes
    do not count them.
    """
    with io.BytesIO(source) if isinstance(source, bytes) else source.open("rb") as raw:
        lines = gzip.open(raw) if name.endswith(".gz") else raw
        if data_only:
            return sum(1 for line in lines if line.strip() and line[:1] != b"#")
        return sum(1 for _ in lines)
