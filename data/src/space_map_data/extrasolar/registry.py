"""The registry of extrasolar IDs, and the tables built beside it.

The registry lists every minted ID and maps each catalogue id to it. Each
ingest reads it and adds to it. It is never served and never rebuilt from the
downloads, so it only grows: a deleted record frees a serial, and an old URL
then shows another object. A status change is a new record, and the latest
record wins.

Layout under REGISTRY_ROOT (<n> is the ingest number in 6 digits, <r> the
region in 3 digits):

    registry/manifest.json                  committed state, replaced atomically
    registry/lock                           flock, by one ingest or shared by readers
    registry/segments/<n>/ids/<r>.parquet   one segment per ingest, never changed
    registry/segments/<n>/xids/<r>.parquet
    registry/segments/<n>/positions/<r>.parquet
    registry/segments/<n>/merges.parquet    only when the ingest merged IDs
    registry/segments/<n>/report.txt
    registry/staging/<n>/                   scratch of the running ingest
    tables/<slug>/<n>/<r>.parquet           the tables that ingest <n> built

Parts, each sorted by cell and then ID inside a region file:
- ids: (id, status, alias_target, ingest). Status is live, alias or retired.
- xids: (catalogue, release, catalogue_id) → id, with how it was linked
  (mint, claim or position), the match score of a position link and the
  ingest. The links of a source that the ingest log marks as not permanent
  hold until the next ingest, which makes them again. Read xids with
  `read_xids`, which leaves out the links that no longer hold.
- positions: the J2016.0 ICRS position, proper motion, magnitude, position
  error, size and kind of each minted ID, for matching.
- planets: (host, number) and the catalogue ids of a planet. Defined, empty.
- the ingest log: the manifest's `ingests`, with each ingest's merges in its
  merges.parquet.

A segment exists only once the manifest names it. The manifest also names the
current version of each table, so the registry and the tables switch together,
and a failed ingest leaves the previous ones in force.

One host mints: the manifest records the host that created the registry, and
a writer refuses on any other. A copy elsewhere is read-only. A reader, such
as the export, shares the lock with other readers on any host, so no ingest
writes while it reads.
"""

import fcntl
import json
import logging
import shutil
import socket
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from space_map_data.extrasolar.ids import CELL_MASK, cell_of
from space_map_data.extrasolar.sky import REGION_LEVEL, region_of
from space_map_data.extrasolar.store import (
    copy_synced,
    read_parquet,
    region_file,
    write_json,
)
from space_map_data.utils.arrays import find_sorted
from space_map_data.utils.paths import REGISTRY_BACKUP_DIR, REGISTRY_ROOT

logger = logging.getLogger(__name__)

LIVE, ALIAS, RETIRED = "live", "alias", "retired"
STATUS_CODES = {LIVE: 0, ALIAS: 1, RETIRED: 2}
MINT, CLAIM, POSITION = "mint", "claim", "position"

IDS = pa.schema(
    [
        ("id", pa.int64()),
        ("status", pa.string()),
        ("alias_target", pa.int64()),
        ("ingest", pa.uint32()),
    ]
)
XIDS = pa.schema(
    [
        ("catalogue", pa.string()),
        ("release", pa.string()),
        ("catalogue_id", pa.string()),
        ("id", pa.int64()),
        ("link", pa.string()),
        ("score", pa.float32()),
        ("ingest", pa.uint32()),
    ]
)
POSITIONS = pa.schema(
    [
        ("id", pa.int64()),
        ("ra", pa.float64()),
        ("dec", pa.float64()),
        ("pmra", pa.float32()),
        ("pmdec", pa.float32()),
        ("mag", pa.float32()),
        ("pos_error", pa.float32()),
        ("size", pa.float32()),
        ("kind", pa.string()),
        ("source", pa.string()),
        ("ingest", pa.uint32()),
    ]
)
PLANETS = pa.schema(
    [
        ("host", pa.int64()),
        ("number", pa.uint16()),
        ("catalogue", pa.string()),
        ("release", pa.string()),
        ("catalogue_id", pa.string()),
        ("ingest", pa.uint32()),
    ]
)
MERGES = pa.schema(
    [("survivor", pa.int64()), ("loser", pa.int64()), ("evidence", pa.string())]
)
PARTS = {"ids": IDS, "xids": XIDS, "positions": POSITIONS}
MERGES_FILE = "merges.parquet"
REPORT_FILE = "report.txt"


class RegistryError(Exception):
    pass


class RegistryBusy(RegistryError):
    pass


class NoRegistry(RegistryError):
    pass


class WrongHost(RegistryError):
    pass


def ingest_name(ingest: int) -> str:
    return f"{ingest:06d}"


def sort_by_cell(table: pa.Table, *more: str) -> pa.Table:
    """`table` sorted by the cell of its `id`, then by ID and `more`."""
    keyed = table.append_column("_cell", pc.bit_wise_and(table["id"], CELL_MASK))
    keys = [("_cell", "ascending"), ("id", "ascending")]
    order = pc.sort_indices(keyed, sort_keys=keys + [(m, "ascending") for m in more])
    return table.take(order)


@dataclass
class IdStates:
    """The latest status of each ID of some regions, sorted by ID."""

    id: np.ndarray
    status: np.ndarray
    # 0 when there is no target.
    target: np.ndarray
    first_ingest: np.ndarray

    @classmethod
    def build(cls, records: pa.Table) -> IdStates:
        ids = records["id"].to_numpy()
        if not ids.size:
            empty = np.zeros(0, np.int64)
            return cls(empty, np.zeros(0, np.uint8), empty, empty)
        ingest = records["ingest"].to_numpy().astype(np.int64)
        names = pa.array(list(STATUS_CODES))
        status = pc.index_in(records["status"], value_set=names).to_numpy()
        target = records["alias_target"].fill_null(0).to_numpy()
        order = np.lexsort((ingest, ids))
        ids = ids[order]
        first = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]])
        last = np.r_[first[1:], ids.size] - 1
        return cls(
            ids[first],
            status[order][last].astype(np.uint8),
            target[order][last],
            ingest[order][first],
        )

    def find(self, ids: np.ndarray) -> np.ndarray:
        """Positions of `ids` in this table, -1 where missing."""
        return find_sorted(self.id, ids)

    def has_status(self, ids: np.ndarray, status: str) -> np.ndarray:
        if not self.id.size:
            return np.zeros(len(ids), bool)
        at = self.find(ids)
        return (at >= 0) & (self.status[np.maximum(at, 0)] == STATUS_CODES[status])


def _temporary(entry: dict) -> list[tuple[str, str]]:
    """(catalogue, release) of the sources that the ingest ran as not permanent."""
    return [
        (source["catalogue"], source["release"])
        for source in entry["sources"]
        if not source["permanent"]
    ]


def latest_index(catalogue_id: pa.Array, value_set: pa.Array) -> np.ndarray:
    """For each catalogue id, the position of its last copy in `value_set`."""
    reverse = pc.index_in(catalogue_id, value_set=value_set[::-1])
    found = reverse.fill_null(-1).to_numpy().astype(np.int64)
    return np.where(found >= 0, len(value_set) - 1 - found, -1)


class Registry:
    def __init__(self, root: Path = REGISTRY_ROOT) -> None:
        self.root = root
        self.dir = root / "registry"
        self.tables_dir = root / "tables"
        self.manifest_path = self.dir / "manifest.json"
        self.manifest = self._read_manifest()
        self._locked = False
        self._aliases: dict[int, int] | None = None

    def _read_manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {}
        manifest = json.loads(self.manifest_path.read_text())
        if manifest["region_level"] != REGION_LEVEL:
            raise RegistryError(
                f"{self.manifest_path} is stored by level-{manifest['region_level']}"
                f" regions, the code uses level {REGION_LEVEL}"
            )
        return manifest

    # Reading

    @property
    def ingests(self) -> list[dict]:
        return self.manifest.get("ingests", [])

    @property
    def last_ingest(self) -> int:
        return self.ingests[-1]["ingest"] if self.ingests else 0

    @property
    def temporary_catalogues(self) -> set[tuple[str, str]]:
        """(catalogue, release) of each source that an ingest ran as not
        permanent. Their links can change at each ingest."""
        return {pair for entry in self.ingests for pair in _temporary(entry)}

    def segment_dir(self, ingest: int) -> Path:
        return self.dir / "segments" / ingest_name(ingest)

    def part_files(self, part: str, region: int) -> list[Path]:
        files = [
            region_file(self.segment_dir(entry["ingest"]) / part, region)
            for entry in self.ingests
        ]
        return [path for path in files if path.exists()]

    def part_regions(self, part: str) -> list[int]:
        found: set[int] = set()
        for entry in self.ingests:
            directory = self.segment_dir(entry["ingest"]) / part
            if directory.is_dir():
                found.update(int(path.stem) for path in directory.glob("*.parquet"))
        return sorted(found)

    def read_part(
        self, part: str, region: int, columns: list[str] | None = None
    ) -> pa.Table:
        """Every record of `part` in `region`, oldest ingest first."""
        return read_parquet(self.part_files(part, region), PARTS[part], columns)

    def read_xids(
        self, region: int, columns: list[str] | None = None, *, rebuild: bool = False
    ) -> pa.Table:
        """The xids of `region` that hold, oldest ingest first.

        `rebuild` also leaves out the links that the next ingest makes again.
        """
        wanted = XIDS.names if columns is None else columns
        read = list(dict.fromkeys([*wanted, "catalogue", "release"]))
        tables = []
        for entry in self.ingests:
            path = region_file(self.segment_dir(entry["ingest"]) / "xids", region)
            if not path.exists():
                continue
            table = pq.read_table(path, columns=read)
            temporary = [f"{c}/{r}" for c, r in _temporary(entry)]
            if temporary and (rebuild or entry["ingest"] != self.last_ingest):
                named = pc.binary_join_element_wise(
                    table["catalogue"], table["release"], "/"
                )
                table = table.filter(pc.invert(pc.is_in(named, pa.array(temporary))))
            tables.append(table.select(wanted))
        if not tables:
            return pa.schema([XIDS.field(name) for name in wanted]).empty_table()
        return pa.concat_tables(tables)

    def id_states(self, regions: Iterable[int]) -> IdStates:
        tables = [self.read_part("ids", region) for region in regions]
        return IdStates.build(pa.concat_tables(tables) if tables else IDS.empty_table())

    def positions(self, region: int, states: IdStates | None = None) -> pa.Table:
        """The latest position of each live ID of `region`."""
        records = self.read_part("positions", region)
        if not records.num_rows:
            return records
        ids = records["id"].to_numpy()
        _, last = np.unique(ids[::-1], return_index=True)
        latest = records.take(np.sort(ids.size - 1 - last))
        if states is None:
            states = self.id_states([region])
        live = states.has_status(latest["id"].to_numpy(), LIVE)
        return latest.filter(pa.array(live))

    def aliases(self) -> dict[int, int]:
        """Every alias in the registry: loser → survivor as recorded."""
        if self._aliases is None:
            found: dict[int, int] = {}
            for entry in self.ingests:
                path = self.segment_dir(entry["ingest"]) / MERGES_FILE
                if path.exists():
                    merges = pq.read_table(path, columns=["loser", "survivor"])
                    found.update(
                        zip(merges["loser"].to_pylist(), merges["survivor"].to_pylist())
                    )
            self._aliases = found
        return self._aliases

    def live_end(self, ids: np.ndarray) -> np.ndarray:
        """`ids` with each alias followed to the end of its chain."""
        aliases = self.aliases()
        if not aliases:
            return ids
        out = ids.copy()
        for at in np.flatnonzero(np.isin(ids, list(aliases))):
            id_ = int(ids[at])
            while id_ in aliases:
                id_ = aliases[id_]
            out[at] = id_
        return out

    def lookup(
        self,
        catalogue: str,
        release: str,
        catalogue_ids: Iterable[str] | pa.Array,
        regions: Iterable[int] | None = None,
    ) -> np.ndarray:
        """The live ID of each catalogue id, 0 where none.

        Searches `regions`, or every region when None. Aliases are followed;
        a retired ID gives 0.
        """
        query = pa.array(catalogue_ids, pa.string())
        best = np.zeros(len(query), np.int64)
        best_ingest = np.full(len(query), -1, np.int64)
        for region in self.part_regions("xids") if regions is None else regions:
            xids = self.read_xids(region)
            xids = xids.filter(
                pc.and_(
                    pc.equal(xids["catalogue"], catalogue),
                    pc.equal(xids["release"], release),
                )
            )
            if not xids.num_rows:
                continue
            at = latest_index(query, xids["catalogue_id"].combine_chunks())
            hit = at >= 0
            ingest = np.where(hit, xids["ingest"].to_numpy()[np.maximum(at, 0)], -1)
            newer = hit & (ingest > best_ingest)
            best[newer] = xids["id"].to_numpy()[at[newer]]
            best_ingest[newer] = ingest[newer]
        best = self.live_end(best)
        found = best > 0
        if found.any():
            regions = sorted(set(region_of(cell_of(best[found])).tolist()))
            best[self.id_states(regions).has_status(best, RETIRED)] = 0
        return best

    def merges(self, ingest: int) -> pa.Table:
        path = self.segment_dir(ingest) / MERGES_FILE
        return pq.read_table(path) if path.exists() else MERGES.empty_table()

    def unreviewed(self) -> list[int]:
        """The ingests whose merges no one has reviewed yet."""
        return [
            entry["ingest"]
            for entry in self.ingests
            if entry["counts"]["merged"] and entry["reviewed"] is None
        ]

    def report(self, ingest: int) -> str:
        return (self.segment_dir(ingest) / REPORT_FILE).read_text()

    # The table store

    def table_dir(self, slug: str) -> Path | None:
        version = self.manifest.get("tables", {}).get(slug)
        if version is None:
            return None
        return self.tables_dir / slug / ingest_name(version)

    def table_regions(self, slug: str) -> list[int]:
        directory = self.table_dir(slug)
        if directory is None:
            return []
        return sorted(int(path.stem) for path in directory.glob("*.parquet"))

    def read_table(
        self, slug: str, region: int, columns: list[str] | None = None
    ) -> pa.Table | None:
        """The rows of `region` in the current table, None when it has none.

        `columns` limits the read to these columns, in this order.
        """
        directory = self.table_dir(slug)
        if directory is None:
            return None
        path = region_file(directory, region)
        return pq.read_table(path, columns=columns) if path.exists() else None

    @contextmanager
    def reader(self) -> Generator[Registry]:
        """Hold the lock together with other readers, so no ingest writes.

        The manifest is read again under the lock. The lock handle stays out
        of `self`, so the registry can be pickled while the lock is held.
        """
        if not self.dir.is_dir():
            raise NoRegistry(f"no registry in {self.root}")
        with (self.dir / "lock").open("a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RegistryBusy(
                    f"{self.dir} is locked by an ingest; read it when the ingest ends"
                ) from None
            self.manifest = self._read_manifest()
            self._aliases = None
            if not self.manifest:
                raise NoRegistry(f"no registry in {self.root}")
            yield self

    # Writing

    @contextmanager
    def writer(self) -> Generator[Registry]:
        """Hold the minting lock, on the host that created the registry."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / "lock").open("a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RegistryBusy(
                    f"{self.dir} is locked by an ingest or an export"
                ) from None
            self.manifest = self._read_manifest()
            self._aliases = None
            host = socket.gethostname()
            if self.manifest and self.manifest["host"] != host:
                raise WrongHost(
                    f"{self.dir} was created on {self.manifest['host']}; "
                    f"this is {host}, so it is a read-only copy"
                )
            self._locked = True
            try:
                yield self
            finally:
                self._locked = False

    def _require_lock(self) -> None:
        if not self._locked:
            raise RegistryError("write without the registry lock")

    def clean(self) -> None:
        """Remove what a failed ingest left: staging, segments, table versions."""
        self._require_lock()
        committed = {ingest_name(entry["ingest"]) for entry in self.ingests}
        segments = self.dir / "segments"
        for path in sorted(segments.glob("*")) if segments.is_dir() else []:
            if path.name not in committed:
                logger.warning("removing uncommitted segment %s", path)
                shutil.rmtree(path)
        staging = self.dir / "staging"
        for path in sorted(staging.glob("*")):
            logger.warning("removing the staging of a failed ingest: %s", path)
            shutil.rmtree(path)
        current = self.manifest.get("tables", {})
        for table_dir in sorted(self.tables_dir.glob("*")):
            keep = current.get(table_dir.name)
            for version in sorted(table_dir.glob("*")):
                if keep is None or version.name != ingest_name(keep):
                    logger.warning("removing table version %s", version)
                    shutil.rmtree(version)

    def commit(self, entry: dict, tables: dict[str, int]) -> None:
        """Make the segment and tables of `entry["ingest"]` the current state."""
        self._require_lock()
        manifest = {
            "host": self.manifest.get("host", socket.gethostname()),
            "created": self.manifest.get("created", datetime.now(UTC).isoformat()),
            "region_level": REGION_LEVEL,
            "ingests": [*self.ingests, entry],
            "tables": tables,
        }
        write_json(self.manifest_path, manifest)
        self.manifest = manifest
        self._aliases = None

    def mark_reviewed(self, ingest: int) -> None:
        self._require_lock()
        entries = [entry for entry in self.ingests if entry["ingest"] == ingest]
        if not entries:
            raise RegistryError(f"no committed ingest {ingest}")
        entries[0]["reviewed"] = datetime.now(UTC).isoformat()
        write_json(self.manifest_path, self.manifest)

    def backup(self, backup_root: Path = REGISTRY_BACKUP_DIR) -> Path:
        """Copy each segment that the backup lacks, then the manifest."""
        target = backup_root / self.manifest["host"]
        for entry in self.ingests:
            name = ingest_name(entry["ingest"])
            done = target / "segments" / name
            if done.exists():
                continue
            part = done.with_name(name + ".part")
            if part.exists():
                shutil.rmtree(part)
            source = self.segment_dir(entry["ingest"])
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    copy_synced(path, part / path.relative_to(source))
            part.mkdir(parents=True, exist_ok=True)
            part.rename(done)
        manifest_part = target / "manifest.json.part"
        copy_synced(self.manifest_path, manifest_part)
        manifest_part.replace(target / "manifest.json")
        logger.info("registry backed up to %s", target)
        return target
