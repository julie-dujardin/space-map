"""The General Catalogue of Variable Stars (GCVS 5.1) as an ingest source.

A GCVS entry names a variable star or a system. Its row is the one SIMBAD row
that holds its light: the object of its `V*` identifier, the point that holds
that object, or the only row of a system. A system of several rows is left
out, because the GCVS does not say which component varies. The objects come
from the simbad_stars list, else from the gcvs_simbad download. An object
outside the list has no components there, so only its own ids count.

A row of the list joins by its Gaia DR3 id, else by its HIP number, its own
or the one that `SimbadList.handed` gives it. An object outside the list
joins by its HIP number, unless the Gaia best neighbour of that number is
another source. Its Gaia DR3 id can lack a 5σ parallax, and then no Gaia row
holds it. An entry without an id or a type is left out, as is an entry that
the GCVS marks as not existing or as another GCVS entry. Two entries that
reach one star keep the first in GCVS order. The rows join at each ingest and
hold no catalogue id in the registry.

Licence: none stated. Cite Samus et al. 2017, Astronomy Reports 61, 80. Only
the designations and the variability types are used.
"""

import csv
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar.sources.simbad import SimbadList
from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR, SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

GCVS_FILE = SOURCES_CATALOGUES_DIR / "stellar-parameters" / "gcvs" / "gcvs5.txt"
SIMBAD_FILE = SOURCES_STARS_DIR / "gcvs-simbad" / "names.csv"
COLUMNS = ("gcvs_name", "vartype_gcvs")
# Character columns of a gcvs5.txt line. Some lines merge two later fields,
# so a split on "|" can read the wrong field.
_NAME = slice(8, 19)
_TYPE = slice(43, 53)
_REMARK = slice(169, 180)
_NOT_EXISTING = "Not exists"
# "V0645" is "V645" in SIMBAD.
_V_NUMBER = re.compile(r"V0*(?P<number>\d+)")
# The constellation, then the component letter of a star of a pair: "PegA".
_CONSTELLATION = re.compile(r"(?P<constellation>[A-Z][A-Za-z]{2})(?P<component>[A-Z]?)")
# The GCVS letters that SIMBAD spells otherwise.
_SIMBAD_LETTERS = {"khi": "chi", "u.": "u"}


def designation(text: str) -> str | None:
    """The SIMBAD spelling of a GCVS designation, without "V* ".

    "V0645 Cen" is "V645 Cen", "alf 2 CVn" is "alf02 CVn", "khi Cyg" is
    "chi Cyg", "EQ    PegA" is "EQ Peg A".
    """
    words = text.strip().rstrip("*").split()
    if len(words) not in (2, 3):
        return None
    tail = _CONSTELLATION.fullmatch(words[-1])
    if tail is None:
        return None
    star = _SIMBAD_LETTERS.get(words[0], words[0])
    if len(words) == 3:
        if not words[1].isdigit():
            return None
        star = f"{star}{int(words[1]):02d}"
    elif number := _V_NUMBER.fullmatch(star):
        star = f"V{number['number']}"
    name = f"{star} {tail['constellation']}"
    return f"{name} {tail['component']}" if tail["component"] else name


def read_entries(path: Path = GCVS_FILE) -> list[tuple[str, str]]:
    """The designation and variability type of each existing GCVS entry."""
    entries: list[tuple[str, str]] = []
    left_out: Counter[str] = Counter()
    for line in path.read_text(encoding="koi8-r").splitlines():
        if len(line) < _REMARK.stop or any(
            line[column.start - 1] != "|" for column in (_NAME, _TYPE, _REMARK)
        ):
            left_out["a line out of the fixed columns"] += 1
            logger.debug("GCVS: cannot read the line %r", line[:40])
            continue
        name = designation(line[_NAME])
        if name is None:
            left_out["a designation that does not parse"] += 1
            logger.debug("GCVS: cannot read the designation %r", line[_NAME])
            continue
        # The remark also holds the designation in another galaxy ("=LMC V1970").
        remark = line[_REMARK].strip()
        if remark == _NOT_EXISTING:
            left_out["not existing"] += 1
            continue
        if remark.startswith("=") and designation(remark[1:]) is not None:
            left_out["another GCVS entry"] += 1
            continue
        vartype = line[_TYPE].strip()
        if not vartype:
            left_out["no type"] += 1
            logger.debug("GCVS: %s has no type", name)
            continue
        entries.append((name, vartype))
    logger.info("GCVS: %d entries; left out %s", len(entries), dict(left_out))
    return entries


@dataclass(frozen=True)
class Resolved:
    """The SIMBAD object of a designation, with its ids (0 for none)."""

    oid: int
    gaia: int
    hip: int


def read_simbad(path: Path = SIMBAD_FILE) -> dict[str, Resolved]:
    """The SIMBAD object of each designation that SIMBAD resolves."""
    found: dict[str, tuple[int, set[int], set[int]]] = {}
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if not row["oid"]:
                continue
            _, gaia, hip = found.setdefault(
                row["name"], (int(row["oid"]), set(), set())
            )
            if row["gaia_dr3"]:
                gaia.add(int(row["gaia_dr3"]))
            # "HIP 12345A" names a component of a Hipparcos star.
            if row["hip"].isdigit():
                hip.add(int(row["hip"]))
    resolved = {}
    for name, (oid, gaia, hip) in found.items():
        if len(gaia) > 1 or len(hip) > 1:
            logger.warning(
                "GCVS: SIMBAD gives %s the ids %s %s; it uses none", name, gaia, hip
            )
        resolved[name] = Resolved(
            oid,
            gaia.pop() if len(gaia) == 1 else 0,
            hip.pop() if len(hip) == 1 else 0,
        )
    return resolved


def _ids(
    name: str,
    listed: dict[str, int],
    resolved: dict[str, Resolved],
    simbad: SimbadList,
    handed: dict[int, dict[str, str]],
) -> tuple[int, int, bool] | str:
    """The Gaia DR3 id and HIP number of the row of an entry (0 for none), and
    whether the row is in the SIMBAD list; else why it has no row."""
    oid = listed.get(name)
    if oid is None and (found := resolved.get(name)) is not None:
        if found.oid not in simbad.objects:
            if found.gaia or found.hip:
                return found.gaia, found.hip, False
            return "no id"
        oid = found.oid
    if oid is None:
        return "not in SIMBAD"
    rows = simbad.rows_of(oid)
    if len(rows) != 1:
        return "a system of several rows" if rows else "no row"
    row = simbad.objects[rows[0]]
    gaia = int(row.gaia or 0)
    hip = int(row.hip or handed.get(rows[0], {}).get("hip") or 0)
    return (gaia, hip, True) if gaia or hip else "no id"


def read_stars(
    simbad: SimbadList,
    handed: dict[int, dict[str, str]],
    best: dict[int, int],
    path: Path = GCVS_FILE,
    simbad_file: Path = SIMBAD_FILE,
) -> pa.Table:
    """One row per star of a GCVS entry: the Gaia DR3 id, else the HIP number,
    that it joins by (0 for none), its designation and type.

    `handed` is `simbad.handed()`, `best` the Gaia best neighbour of each HIP
    number.
    """
    listed = {
        identifier.removeprefix("V* "): oid
        for oid, found in simbad.objects.items()
        for identifier in found.identifiers
        if identifier.startswith("V* ")
    }
    resolved = read_simbad(simbad_file)
    source_ids, hips, names, types = [], [], [], []
    seen: dict[tuple[str, int], str] = {}
    left_out: Counter[str] = Counter()
    for name, vartype in read_entries(path):
        ids = _ids(name, listed, resolved, simbad, handed)
        if isinstance(ids, str):
            left_out[ids] += 1
            logger.debug("GCVS: %s has %s", name, ids)
            continue
        gaia, hip, in_list = ids
        # A Hipparcos row is the star of its Gaia best neighbour.
        same = bool(hip) and (not gaia or best.get(hip) in (None, gaia))
        by_hip = same and (not gaia or not in_list)
        star = {("gaia", gaia)} - {("gaia", 0)}
        if same:
            star.add(("hip", hip))
            if hip in best:
                star.add(("gaia", best[hip]))
        if other := next((seen[key] for key in sorted(star) if key in seen), None):
            left_out["the star of another entry"] += 1
            logger.debug("GCVS: %s has the star of %s", name, other)
            continue
        seen |= dict.fromkeys(star, name)
        source_ids.append(0 if by_hip else gaia)
        hips.append(hip if by_hip else 0)
        names.append(name)
        types.append(vartype)
    by_gaia = int(np.count_nonzero(source_ids))
    logger.info(
        "GCVS: %d stars to join by Gaia DR3 id, %d by HIP number; left out %s",
        by_gaia,
        len(source_ids) - by_gaia,
        dict(left_out),
    )
    return pa.table(
        {
            "source_id": pa.array(np.array(source_ids, np.int64)),
            "hip": pa.array(np.array(hips, np.int64)),
            "gcvs_name": pa.array(names, pa.string()),
            "vartype_gcvs": pa.array(types, pa.string()),
        }
    )
