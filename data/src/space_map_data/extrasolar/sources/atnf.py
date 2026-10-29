"""The ATNF Pulsar Catalogue (Manchester et al. 2005) as an ingest source.

ATNF names each pulsar by its J name, and some also by a B name. The
atnf_simbad download resolves both names in SIMBAD. A pulsar takes the object
of its J name, else the object of its B name. SIMBAD also gives the short form
of a J name (J0537-69) to the pulsar of the full name (J0537-6910), and ATNF
can list another pulsar under that short form. So of two pulsars with one
object, the one whose J name has more declination digits keeps it. With equal
digits, no pulsar keeps it.

A pulsar joins the row of its object in the SIMBAD pass by oid, at each
ingest. It only adds values to that row, so the pulsars never mint and hold
no catalogue id in the registry. A pulsar whose object has no row there is
left out.

Licence: GPL v3 or later. Cite Manchester et al. 2005, AJ 129, 1993, and give
the URL https://www.atnf.csiro.au/research/pulsar/psrcat.
"""

import csv
import logging
import re
import tarfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.utils.paths import SOURCES_CATALOGUES_DIR, SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

ATNF_FILE = (
    SOURCES_CATALOGUES_DIR / "stellar-remnants" / "atnf-psrcat" / "psrcat_pkg.tar.gz"
)
DB_MEMBER = "psrcat_tar/psrcat.db"
SIMBAD_FILE = SOURCES_STARS_DIR / "atnf-simbad" / "names.csv"
COLUMNS = ("atnf_name", "type_atnf")
# psrcat.db: a line is a parameter, its value, then an optional error and
# reference. A line that starts with "@" ends an entry, "#" starts a comment.
_END = "@"
_COMMENT = "#"
_KEYS = ("PSRJ", "PSRB", "TYPE")
# The declination digits of a J name: 2 in J0537-69, 4 in J0537-6910.
_DECLINATION = re.compile(r"J\d{4}[+-](?P<digits>\d+)")


@dataclass(frozen=True)
class Pulsar:
    """An ATNF entry: its J name, its B name and its type as published."""

    psrj: str
    psrb: str | None = None
    type: str | None = None

    @property
    def names(self) -> tuple[str, ...]:
        """Its J name, then its B name."""
        return (self.psrj,) if self.psrb is None else (self.psrj, self.psrb)

    @property
    def precision(self) -> int:
        found = _DECLINATION.match(self.psrj)
        return 0 if found is None else len(found["digits"])


def parse_pulsars(text: str) -> list[Pulsar]:
    """The entries of a psrcat.db, in catalogue order."""
    pulsars: list[Pulsar] = []
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith(_COMMENT):
            continue
        if line.startswith(_END):
            if "PSRJ" in fields:
                pulsars.append(
                    Pulsar(fields["PSRJ"], fields.get("PSRB"), fields.get("TYPE"))
                )
            else:
                logger.warning("ATNF: an entry has no J name: %s", fields)
            fields = {}
            continue
        words = line.split()
        if len(words) > 1 and words[0] in _KEYS:
            fields[words[0]] = words[1]
    if fields:
        logger.warning("ATNF: the last entry has no end line: %s", fields)
    logger.info(
        "ATNF: %d pulsars, %d with a B name, %d with a type",
        len(pulsars),
        sum(pulsar.psrb is not None for pulsar in pulsars),
        sum(pulsar.type is not None for pulsar in pulsars),
    )
    return pulsars


def read_pulsars(path: Path = ATNF_FILE) -> list[Pulsar]:
    """The entries of psrcat.db in the ATNF package."""
    with tarfile.open(path) as archive:
        member = archive.extractfile(DB_MEMBER)
        if member is None:
            raise ValueError(f"{path}: {DB_MEMBER} is not a file")
        return parse_pulsars(member.read().decode())


def read_simbad(path: Path = SIMBAD_FILE) -> dict[str, int]:
    """The SIMBAD oid of each name that SIMBAD resolves."""
    with path.open(newline="") as fh:
        return {
            row["name"]: int(row["oid"]) for row in csv.DictReader(fh) if row["oid"]
        }


def read_stars(path: Path = ATNF_FILE, simbad_file: Path = SIMBAD_FILE) -> pa.Table:
    """One row per SIMBAD object of a pulsar: its oid, the pulsar's J name and
    its type."""
    resolved = read_simbad(simbad_file)
    by_object: dict[int, list[Pulsar]] = defaultdict(list)
    left_out: Counter[str] = Counter()
    for pulsar in read_pulsars(path):
        oids = [resolved[name] for name in pulsar.names if name in resolved]
        if not oids:
            left_out["not in SIMBAD"] += 1
            logger.debug("ATNF: SIMBAD knows no name of %s", pulsar.psrj)
            continue
        if len(set(oids)) > 1:
            logger.info(
                "ATNF: SIMBAD gives %s the objects %s; the J name wins",
                pulsar.names,
                oids,
            )
        by_object[oids[0]].append(pulsar)
    found: list[tuple[int, Pulsar]] = []
    for oid, pulsars in sorted(by_object.items()):
        best = max(pulsar.precision for pulsar in pulsars)
        kept = [pulsar for pulsar in pulsars if pulsar.precision == best]
        if len(pulsars) > 1:
            logger.info(
                "ATNF: SIMBAD %d is the object of %s; it keeps %s",
                oid,
                [pulsar.psrj for pulsar in pulsars],
                kept[0].psrj if len(kept) == 1 else "none",
            )
            left_out["the object of another pulsar"] += len(pulsars) - (len(kept) == 1)
        if len(kept) == 1:
            found.append((oid, kept[0]))
    logger.info(
        "ATNF: %d pulsars with a SIMBAD object; left out %s", len(found), dict(left_out)
    )
    return pa.table(
        {
            "oid": pa.array([oid for oid, _ in found], pa.int64()),
            "atnf_name": pa.array([pulsar.psrj for _, pulsar in found], pa.string()),
            "type_atnf": pa.array([pulsar.type for _, pulsar in found], pa.string()),
        }
    )


def join_by_oid(rows: pa.Table, pulsars: pa.Table) -> pa.Table:
    """SIMBAD pass rows with COLUMNS set from the pulsar of the same oid; null
    where none has it. The rows stay the same, so a pulsar mints nothing."""
    oids = pc.cast(rows["catalogue_id"], pa.int64())
    at = pc.index_in(oids, value_set=pulsars["oid"])
    for name in COLUMNS:
        index = rows.schema.get_field_index(name)
        column = pulsars[name].take(at).cast(rows.schema.field(name).type)
        rows = rows.set_column(index, name, column)
    missed = pulsars.filter(pc.invert(pc.is_in(pulsars["oid"], value_set=oids)))
    logger.info(
        "ATNF: %d pulsars join a SIMBAD row, %d reach no row",
        pulsars.num_rows - missed.num_rows,
        missed.num_rows,
    )
    for row in missed.to_pylist():
        logger.debug(
            "ATNF: %s, SIMBAD %d, reaches no row", row["atnf_name"], row["oid"]
        )
    return rows
