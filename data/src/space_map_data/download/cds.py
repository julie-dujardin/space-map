"""The CDS catalogue archive: its address, and the ReadMe of a catalogue.

The ReadMe lists each data file with its record count. Its byte-by-byte
description gives the fixed-width format of each file, which
`read_fixed_width` reads.
"""

import fnmatch
import gzip
import io
import re
from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

CDS_URL = "https://cdsarc.cds.unistra.fr/ftp"
README = "ReadMe"

_SUMMARY_ROW = re.compile(r"^\s*(\S+)\s+\d+\s+(\d+)(?:\s|$)")
_BYTE_BY_BYTE = re.compile(r"^Byte-by-byte Description of files?:\s*(.*)$")
# A field line starts in the Bytes column. A wrapped explanation starts far
# to the right, so it does not match.
_FIELD_ROW = re.compile(
    r"^ {0,8}(\d+)(?:\s*-\s*(\d+))?\s+(\d*[AIFED]\d+(?:\.\d+)?)\s+(\S+)\s+(\S+)\s*(.*)$"
)
_FORMAT = re.compile(r"^(\d*)([AIFED])(\d+)(?:\.\d+)?$")


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
    with (
        io.BytesIO(source) if isinstance(source, bytes) else source.open("rb") as raw,
        gzip.open(raw) if name.endswith(".gz") else nullcontext(raw) as lines,
    ):
        if data_only:
            return sum(1 for line in lines if line.strip() and line[:1] != b"#")
        return sum(1 for _ in lines)


@dataclass(frozen=True)
class Field:
    """One field of a fixed-width file, from a byte-by-byte description."""

    # 0-based start and exclusive end, in bytes.
    start: int
    end: int
    # A, I, F, E or D.
    kind: str
    # More than 1 for a repeated format such as 15F7.2.
    repeat: int
    unit: str
    label: str
    explanation: str


def byte_by_byte(readme: str, name: str) -> list[Field]:
    """The fields of the file `name` (with or without .gz) in a ReadMe."""
    name = name.removesuffix(".gz")
    lines = readme.splitlines()
    for at, line in enumerate(lines):
        match = _BYTE_BY_BYTE.match(line)
        if match is None:
            continue
        names = re.split(r"[\s,]+", match[1].strip())
        if not any(fnmatch.fnmatch(name, pattern) for pattern in names):
            continue
        return _fields(lines[at + 1 :], name)
    raise ValueError(f"the ReadMe has no byte-by-byte description of {name}")


def _fields(lines: list[str], name: str) -> list[Field]:
    fields: list[Field] = []
    rules = 0
    for line in lines:
        if line.startswith("---"):
            rules += 1
            # Two rules frame the column titles. The third rule ends the table.
            if rules == 3:
                break
            continue
        if rules < 2:
            continue
        match = _FIELD_ROW.match(line)
        if match is None:
            continue
        start = int(match[1])
        end = int(match[2] or start)
        form = _FORMAT.match(match[3])
        if form is None:
            raise ValueError(f"{name}: unknown format {match[3]}")
        fields.append(
            Field(
                start=start - 1,
                end=end,
                kind=form[2],
                repeat=int(form[1] or 1),
                unit=match[4],
                label=match[5],
                explanation=match[6].strip(),
            )
        )
    if not fields:
        raise ValueError(f"{name}: the byte-by-byte description has no fields")
    return fields


def read_fixed_width(
    path: Path,
    readme: str,
    labels: Mapping[str, str] | list[str],
    nulls: tuple[str, ...] = (),
) -> pa.Table:
    """Read the fields with these labels from a CDS file, plain or gzip.

    `labels` maps each label to its column name, or lists labels kept as
    names. A blank field is null, and so is a field equal to one of `nulls`.
    A is a string, I is int64, F, E and D are float64. A file is read as
    Latin-1, so a character is one byte and the byte positions hold.
    """
    names = dict(labels) if isinstance(labels, Mapping) else {k: k for k in labels}
    fields = byte_by_byte(readme, path.name)
    by_label: dict[str, Field] = {}
    for field in fields:
        if field.label in names and by_label.setdefault(field.label, field) != field:
            raise ValueError(f"{path.name}: two fields are labelled {field.label}")
    missing = sorted(set(names) - set(by_label))
    if missing:
        raise ValueError(f"{path.name}: no fields labelled {missing}")
    with gzip.open(path) if path.name.endswith(".gz") else path.open("rb") as raw:
        text = raw.read().decode("latin-1")
    # str.splitlines also breaks on bytes such as 0x0c and 0x85 inside a field.
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    if not lines[-1]:
        lines.pop()
    columns = {}
    for label, column in names.items():
        field = by_label[label]
        if field.repeat > 1:
            raise ValueError(f"{path.name}: {label} is a repeated field")
        values = pc.utf8_trim_whitespace(
            pa.array([line[field.start : field.end] for line in lines], pa.string())
        )
        values = pc.if_else(
            pc.is_in(values, value_set=pa.array(["", *nulls], pa.string())),
            None,
            values,
        )
        if field.kind == "I":
            # Arrow cannot parse a plus sign in an integer.
            values = pc.replace_substring_regex(values, r"^\+", "").cast(pa.int64())
        elif field.kind != "A":
            values = values.cast(pa.float64())
        columns[column] = values
    return pa.table(columns)
