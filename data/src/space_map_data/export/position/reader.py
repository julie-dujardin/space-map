"""Read back the position files the export writes.

Only the fields that say which objects a file holds and when it can place
them. The export stamps each object's placement windows from these, so the
windows describe the files that ship and not the database behind them.
"""

import gzip
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from space_map_data.export.position.format import (
    BODY_HEADER_SIZE,
    HEADER_SIZE,
    SUBFORMAT_KEPLERIAN,
    align8,
    unpack_body_header,
    unpack_chebyshev_header,
    unpack_elements_header,
)

# Float32 Keplerian columns that follow `epoch_jd`, in file order. With
# `epoch_jd` they are the elements a row needs before it can be propagated.
_KEPLER_COLUMNS = ("a", "e", "i", "om", "w", "ma", "n")


@dataclass(frozen=True)
class ElementsFile:
    """The rows of one elements file.

    `placeable` is False for a row that ships a missing element: the frontend
    cannot propagate it.
    """

    version: int
    start_jd: float
    end_jd: float
    id_type: int
    ids: np.ndarray
    visible_from_days: np.ndarray
    placeable: np.ndarray


@dataclass(frozen=True)
class ChebyshevBody:
    """One body of a chebyshev file, with the span of each of its segments."""

    id_type: int
    obj_id_value: int
    visible_from_days: float
    starts: np.ndarray
    ends: np.ndarray


@dataclass(frozen=True)
class ChebyshevFile:
    """The bodies of one chebyshev file."""

    version: int
    bodies: list[ChebyshevBody]


def read_elements_file(path: Path) -> ElementsFile:
    """Read the ids and gates of an elements file of any sub-format."""
    buf = gzip.decompress(path.read_bytes())
    header = unpack_elements_header(buf)
    n = header.row_count
    # Every sub-format ends with the `visible_from_days` column.
    visible_from_days = np.frombuffer(buf, "<f4", n, len(buf) - align8(4 * n))
    placeable = np.ones(n, dtype=bool)
    # Only the Keplerian writer lets a row through with a missing element.
    if header.sub_format == SUBFORMAT_KEPLERIAN:
        # id, object_type, parent_id and scale come before `epoch_jd`.
        offset = HEADER_SIZE + 2 * align8(4 * n) + 2 * align8(n)
        placeable &= np.isfinite(np.frombuffer(buf, "<f8", n, offset))
        offset += 8 * n
        for _column in _KEPLER_COLUMNS:
            placeable &= np.isfinite(np.frombuffer(buf, "<f4", n, offset))
            offset += align8(4 * n)
    return ElementsFile(
        version=header.version,
        start_jd=header.start_jd,
        end_jd=header.end_jd,
        id_type=header.id_type,
        ids=np.frombuffer(buf, "<i4", n, HEADER_SIZE),
        visible_from_days=visible_from_days,
        placeable=placeable,
    )


def read_chebyshev_file(path: Path) -> ChebyshevFile:
    """Read the body headers and segment spans of a chebyshev file."""
    buf = gzip.decompress(path.read_bytes())
    header = unpack_chebyshev_header(buf)
    coeff_size = 8 if header.float64_coeffs else 4
    bodies: list[ChebyshevBody] = []
    offset = HEADER_SIZE
    for _ in range(header.body_count):
        body = unpack_body_header(buf, offset)
        offset += BODY_HEADER_SIZE
        # A segment is its (start, end) pair, then the coefficients of 3 axes.
        segment_size = 16 + 3 * body.coeffs_per_axis * coeff_size
        spans = np.ndarray(
            (body.segment_count, 2),
            dtype="<f8",
            buffer=buf,
            offset=offset,
            strides=(segment_size, 8),
        )
        offset += body.segment_count * segment_size
        bodies.append(
            ChebyshevBody(
                id_type=body.id_type,
                obj_id_value=body.obj_id_value,
                visible_from_days=body.visible_from_days,
                starts=spans[:, 0],
                ends=spans[:, 1],
            )
        )
    return ChebyshevFile(version=header.version, bodies=bodies)
