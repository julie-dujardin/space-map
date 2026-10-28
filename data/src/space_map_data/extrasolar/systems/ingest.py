"""The star systems in the extrasolar ingest.

`add_systems` comes after the distance passes and before Wikidata:
1. It builds the trees (`build`) from the run so far, with `RunResolver`. A
   member's catalogue ids reach their objects through the links of the
   registry and of the passes. The WDS components with no other id are the
   rows of the wds-components pass, which never mints and matches by
   position. The facts of an object are its rows so far, merged by source
   order. An object that the commit does not mint is no object for the
   builder, so a star of it is an entry.
2. The star-systems pass gives a row to each node and to each star of a
   system. A resolved system mints an ID of the System table, in the cell of
   its primary's position. Its catalogue ids (the SIMBAD system object, WDS,
   MSC, the El-Badry pair) are its claims, so the next ingest keeps its ID. A
   point claims one of its own ids. The rows carry the System columns, the
   class and the name of a node, and the system distance and the spectral
   type of a star.
3. `SystemsExtension` sets the links between IDs at the commit, when every
   ID is minted: `parent`, `root`, `primary`, `members` and `tree` of
   System, and `system` of Metadata. It gives the planets extension the
   host of a circumbinary planet and the root of each host.
"""

import json
import logging
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.download.providers.stars import el_badry, msc, wds
from space_map_data.extrasolar.engine import (
    ExtensionResult,
    IngestRun,
    Source,
)
from space_map_data.extrasolar.exoplanets.catalogues import ARCHIVE, EU, OEC
from space_map_data.extrasolar.exoplanets.ingest import Prepared
from space_map_data.extrasolar.exoplanets.simbad import Simbad
from space_map_data.extrasolar.ids import table_of
from space_map_data.extrasolar.match import SYSTEM_KIND
from space_map_data.extrasolar.placement import COLUMNS, placement
from space_map_data.extrasolar.registry import LIVE, Registry, latest_index
from space_map_data.extrasolar.sources.gaia import GaiaReader
from space_map_data.extrasolar.sources.simbad import SIMBAD, SimbadList
from space_map_data.extrasolar.systems import assemble
from space_map_data.extrasolar.systems.assemble import ENTRY, Systems
from space_map_data.extrasolar.systems.build import build
from space_map_data.extrasolar.systems.msc import read_msc, refuted_pairs
from space_map_data.extrasolar.systems.nodes import (
    GAIA_DR3,
    OBJECT_CATALOGUES,
    SIMBAD_OID,
    WDS_ID,
)
from space_map_data.extrasolar.systems.pairs import (
    ORBIT_COLUMNS,
    orbit_pairs,
    read_el_badry,
)
from space_map_data.extrasolar.systems.planets import (
    PLANETS_INPUT,
    planet_star_ids,
    read_oec_trees,
    read_planet_systems,
)
from space_map_data.extrasolar.systems.prepare import Inputs
from space_map_data.extrasolar.systems.registry import gaia_keys, point_facts
from space_map_data.extrasolar.systems.report import report_lines, target_keys
from space_map_data.extrasolar.systems.simbad import SimbadIndex, read_simbad
from space_map_data.extrasolar.systems.wds import WDS_MATCHER, WdsCatalogue
from space_map_data.extrasolar.tables import (
    CROSS_ID,
    METADATA,
    POINT_SOURCE,
    SOURCE_COLUMN,
    STAR_SYSTEMS,
    SYSTEM,
    SYSTEM_MEMBER,
    SYSTEM_NODE,
    SYSTEM_TABLE,
    TableDef,
    merge_by_source_order,
)
from space_map_data.utils.arrays import find_sorted, map_sorted

logger = logging.getLogger(__name__)

# WDS components that no catalogue id links. Their ids become the stars'.
WDS_COMPONENTS = Source(
    name="wds-components",
    catalogue="wds",
    release="component",
    home=1,
    matcher=WDS_MATCHER,
    kind="star",
)
# The nodes and the stars of the systems. The claims link the rows.
SYSTEMS = Source(
    name=STAR_SYSTEMS,
    catalogue="star-system",
    release="row",
    home=SYSTEM_TABLE,
    kind=SYSTEM_KIND,
    labels=True,
)
# A resolved system claims its catalogue ids under this catalogue, with the
# catalogue of the id as the release. So the row of an object never reaches a
# system through the object's own id. A system with no catalogue id claims
# its primary's id and its nesting rank among the systems of that primary.
SYSTEM_CLAIMS = "star-system"
PRIMARY_CLAIM = (SYSTEM_CLAIMS, "primary")
SYSTEM_METHOD = "system"
EXAMPLES = 20
# The catalogues beside Gaia DR3 that the builder looks up.
LINKED = tuple(pair for pair in OBJECT_CATALOGUES if pair != GAIA_DR3)

# The Point source columns that the facts read.
FACT_COLUMNS = frozenset(
    {
        *COLUMNS,
        "simbad_sp_type",
        "sp_type",
        "host_spectral_type",
        "non_single_star",
    }
)


def _with_groups(table: TableDef, wanted: frozenset[str]) -> TableDef:
    """`table` with only the groups that hold a wanted column."""
    groups = tuple(
        group
        for group in table.groups
        if set(group.names) & wanted or group.source_column in wanted
    )
    return TableDef(None, table.slug, groups)


FACT_POINT = _with_groups(POINT_SOURCE, FACT_COLUMNS)
# The columns of the star-systems rows in the tables.
SOURCE_FIELDS = tuple(
    column
    for table in (SYSTEM, POINT_SOURCE, METADATA)
    for group in table.groups_of(STAR_SYSTEMS)
    for column in group.columns
)
FACT_METADATA = TableDef(None, METADATA.slug, METADATA.groups)
FACT_FIELDS = [f.name for t in (FACT_POINT, FACT_METADATA) for f in t.group_fields]
CLASS = _with_groups(METADATA, frozenset({"class"}))


class RunResolver:
    """Answers the builder from the run: its links, a pass and its rows.

    It reads the links of every region once, at the first lookup. The
    wds-components pass after it adds no Gaia DR3 link and joins no objects,
    so the links hold for the whole build. The Gaia DR3 links go to a file
    per region, which the lookups map. The resolver keeps one catalogue id of
    each object that the builder holds, which the object's row of the
    star-systems pass claims.

    An object that the commit does not mint, such as a Gaia DR3 source under
    the fidelity cut that no minting row claims, has no ID to draw or to
    link. So the resolver gives no object for it, and the builder makes its
    star an entry.
    """

    def __init__(self, run: IngestRun, complete: bool) -> None:
        self.run = run
        self.complete = complete
        self.counts: Counter = Counter()
        self._links_dir = run.staging / "systems-links"
        self._others: dict[tuple[str, str], tuple[pa.Array, np.ndarray]] | None = None
        self._unminted: np.ndarray | None = None
        # The ids that the lookups gave, then the own ids of the facts' rows.
        self._found: list[tuple[str, str, pa.Array, np.ndarray]] = []
        self._own: list[tuple[str, str, pa.Array, np.ndarray]] = []
        # "<catalogue>/<release>/<id>" of each id whose object is not minted.
        self._lost: list[pa.Array] = []
        self.facts_table: pa.Table | None = None
        # The merged class of each fact key before the star-systems pass.
        self.classes = CLASS.schema.empty_table()
        # Keys whose distance group would place nothing.
        self.unseen = np.zeros(0, np.int64)

    def _regions(self) -> list[int]:
        found = set(self.run.registry.part_regions("xids"))
        for state in self.run.passes:
            found |= state.regions
        return sorted(found)

    def objects(self, keys: np.ndarray) -> np.ndarray:
        """`keys` with 0 for each object that the commit does not mint."""
        if self._unminted is None:
            started = time.monotonic()
            self._unminted = self.run.unminted()
            logger.info(
                "systems: %d objects of the run are not minted, in %.0f s",
                self._unminted.size,
                time.monotonic() - started,
            )
        keys = np.asarray(keys, np.int64)
        return np.where(find_sorted(self._unminted, keys) >= 0, 0, keys)

    def _drop_unminted(
        self, catalogue: str, release: str, ids: pa.Array, keys: np.ndarray
    ) -> np.ndarray:
        """`keys` of `ids` with 0 for each object that is not minted. Keeps
        the ids that lose their object."""
        minted = self.objects(keys)
        lost = (keys != 0) & (minted == 0)
        if lost.any():
            texts = ids.filter(pa.array(lost)).cast(pa.string())
            self._lost.append(
                pc.binary_join_element_wise(f"{catalogue}/{release}", texts, "/")
            )
            name = f"ids of objects that are not minted {catalogue}/{release}"
            self.counts[name] += int(lost.sum())
        return minted

    @property
    def lost(self) -> pa.Array:
        """ "<catalogue>/<release>/<id>" of each id whose object is not minted."""
        return pa.concat_arrays([pa.array([], pa.string()), *self._lost])

    def keys(self, catalogue: str, release: str, ids: pa.Array) -> np.ndarray:
        others = self._links()
        if (catalogue, release) == GAIA_DR3:
            values = ids.cast(pa.int64()).to_numpy()
            keys = gaia_keys(values, self._gaia_region)
        elif (catalogue, release) in others:
            known, objects = others[(catalogue, release)]
            at = latest_index(ids.cast(pa.string()), known)
            keys = np.zeros(at.size, np.int64)
            keys[at >= 0] = objects[at[at >= 0]]
        else:
            raise ValueError(f"systems: no links of {catalogue}/{release} are read")
        keys = self._drop_unminted(catalogue, release, ids, keys)
        hit = keys != 0
        found = ids.filter(pa.array(hit)).cast(pa.string())
        self._found.append((catalogue, release, found, keys[hit]))
        self.counts[f"keys asked {catalogue}/{release}"] += len(ids)
        self.counts[f"keys found {catalogue}/{release}"] += int(hit.sum())
        return keys

    def _links(self) -> dict[tuple[str, str], tuple[pa.Array, np.ndarray]]:
        """The ids of each LINKED catalogue with their objects, oldest first.

        The first call also writes the sorted Gaia DR3 ids of each region with
        their objects.
        """
        if self._others is not None:
            return self._others
        started = time.monotonic()
        self._links_dir.mkdir(parents=True, exist_ok=True)
        parts = [
            pa.schema(list(CROSS_ID))
            .empty_table()
            .append_column("key", pa.array([], pa.int64()))
        ]
        gaia_ids = 0
        for region in self._regions():
            links = self.run.links(region, [GAIA_DR3, *LINKED])
            gaia = pc.and_(
                pc.equal(links["catalogue"], GAIA_DR3[0]),
                pc.equal(links["release"], GAIA_DR3[1]),
            )
            found = links.filter(gaia)
            ids = found["catalogue_id"].cast(pa.int64()).to_numpy()
            keys = found["key"].to_numpy()
            order = np.argsort(ids, kind="stable")
            ids, keys = ids[order], keys[order]
            # The latest link of an id holds.
            last = np.r_[ids[1:] != ids[:-1], True] if ids.size else ids.astype(bool)
            np.save(self._gaia_path(region), np.stack([ids[last], keys[last]]))
            gaia_ids += int(last.sum())
            parts.append(links.filter(pc.invert(gaia)).cast(parts[0].schema))
        others = pa.concat_tables(parts)
        self._others = {}
        for catalogue, release in LINKED:
            picked = others.filter(
                pc.and_(
                    pc.equal(others["catalogue"], catalogue),
                    pc.equal(others["release"], release),
                )
            )
            self._others[(catalogue, release)] = (
                picked["catalogue_id"].combine_chunks(),
                picked["key"].to_numpy(),
            )
        logger.info(
            "systems: links of gaia/dr3 %d, %s in %.0f s",
            gaia_ids,
            {f"{c}/{r}": len(v[1]) for (c, r), v in self._others.items()},
            time.monotonic() - started,
        )
        return self._others

    def _gaia_path(self, region: int) -> Path:
        return self._links_dir / f"{region:03d}.npy"

    def _gaia_region(self, region: int) -> tuple[np.ndarray, np.ndarray]:
        path = self._gaia_path(region)
        if not path.exists():
            empty = np.zeros(0, np.int64)
            return empty, empty
        both = np.load(path, mmap_mode="r")
        return both[0], both[1]

    def match(self, rows: pa.Table) -> np.ndarray:
        """Run the wds-components pass. A row that made a new object, or
        matched one that is not minted, has 0."""
        ids = rows["catalogue_id"].combine_chunks()
        named = ids.is_valid().to_numpy(zero_copy_only=False)
        values = ids.to_numpy(zero_copy_only=False)
        _, first = np.unique(values[named].astype(str), return_index=True)
        unique = np.flatnonzero(named)[np.sort(first)]
        if (~named).any():
            logger.info("systems: %d WDS rows without an id", int((~named).sum()))
        self.run.add(WDS_COMPONENTS, [rows.take(pa.array(unique))], self.complete)
        found = self.run.row_keys(WDS_COMPONENTS.name)
        keys = np.where(found["new"].to_numpy(zero_copy_only=False), 0, found["key"])
        keys = self._drop_unminted(
            *WDS_ID, found["catalogue_id"].combine_chunks(), keys
        )
        by_id = dict(zip(found["catalogue_id"].to_pylist(), keys.tolist()))
        out = np.array(
            [by_id.get(v, 0) if v is not None else 0 for v in ids.to_pylist()],
            np.int64,
        )
        hit = keys != 0
        matched = found["catalogue_id"].combine_chunks().filter(pa.array(hit))
        self._found.append(
            (WDS_COMPONENTS.catalogue, WDS_COMPONENTS.release, matched, keys[hit])
        )
        self.counts["WDS components matched by position"] += int((out != 0).sum())
        return out

    def facts(self, keys: np.ndarray) -> pa.Table:
        keys = np.unique(np.asarray(keys, np.int64))
        keys = keys[keys != 0]
        started = time.monotonic()
        positions = self.run.positions(keys)
        rows_of = self.run.pass_rows(keys, FACT_FIELDS)
        point = self.run.merged(FACT_POINT, rows_of)
        meta = self.run.merged(FACT_METADATA, rows_of)
        self._own_ids(rows_of)
        del rows_of
        table = point_facts(positions, point, meta)
        # A distance group places only a row that is seen.
        seen = placement(point).seen
        self.unseen = np.sort(point["id"].to_numpy()[~seen])
        self.classes = meta.select(CLASS.schema.names)
        by_type = meta.filter(pc.equal(meta["class_source"], SIMBAD.name))
        for name, count in Counter(by_type["class"].to_pylist()).items():
            if name != "star":
                self.counts[f"objects of the trees with the class {name}"] += count
        logger.info(
            "systems: facts of %d objects in %.0f s",
            table.num_rows,
            time.monotonic() - started,
        )
        self.facts_table = table
        return table

    def _own_ids(self, rows_of: dict[str, pa.Table]) -> None:
        """Keep the own catalogue id of each row that links its object.

        A key that no lookup gave, such as a planet host, takes the id of its
        first row in source order.
        """
        for name, rows in rows_of.items():
            source = self.run.sources[name]
            if source.labels or not source.permanent:
                continue
            named = rows.filter(pc.is_valid(rows["catalogue_id"]))
            self._own.append(
                (
                    source.catalogue,
                    source.release,
                    named["catalogue_id"].combine_chunks().cast(pa.string()),
                    named["key"].to_numpy(),
                )
            )

    def claims(self, keys: np.ndarray) -> pa.Table:
        """One catalogue id of each of `keys`: `key`, `catalogue`, `release`,
        `catalogue_id`, null where the run holds none. An id that a lookup
        gave comes first."""
        keys = np.asarray(keys, np.int64)
        taken = np.zeros(keys.size, bool)
        rows, parts = [], []
        for catalogue, release, ids, hits in [*self._found, *self._own]:
            order = np.argsort(hits, kind="stable")
            at = find_sorted(hits[order], keys)
            new = np.flatnonzero((at >= 0) & ~taken)
            taken[new] = True
            rows.append(new)
            n = new.size
            parts.append(
                pa.table(
                    {
                        "catalogue": pa.array([catalogue] * n, pa.string()),
                        "release": pa.array([release] * n, pa.string()),
                        "catalogue_id": ids.take(pa.array(order[at[new]])),
                    }
                )
            )
        empty = pa.schema(list(CROSS_ID)).empty_table()
        found = pa.concat_tables([empty, *parts]) if parts else empty
        at = np.full(keys.size, -1, np.int64)
        if rows:
            at[np.concatenate(rows)] = np.arange(found.num_rows)
        index = pa.array(at, mask=at < 0)
        return pa.table(
            {
                "key": pa.array(keys),
                **{name: found[name].take(index) for name in CROSS_ID.names},
            }
        )


def run_planets(run: IngestRun, prepared: Prepared, hub: Simbad) -> pa.Table:
    """PLANETS_INPUT from the planet records, with the run key of each host."""
    key_of: dict[tuple[str, str], int] = {}
    for source in (ARCHIVE, EU, OEC):
        rows = run.row_keys(source)
        for catalogue_id, key in zip(
            rows["catalogue_id"].to_pylist(), rows["key"].to_pylist()
        ):
            key_of[(source, catalogue_id)] = key
    found: dict[str, list] = defaultdict(list)
    for record in prepared.records:
        identity = prepared.stars.identities[record.star]
        host = next(
            (
                key_of[(source, star.key)]
                for source in (ARCHIVE, EU, OEC)
                if (star := identity.members.get(source)) is not None
                and (source, star.key) in key_of
            ),
            0,
        )
        cross_ids = record.values.get("cross_ids") or []
        assert isinstance(cross_ids, list)
        names = [
            (c["catalogue"], c["catalogue_id"])
            for c in cross_ids
            if c["catalogue"] in (EU, OEC)
        ]
        star_ids = planet_star_ids(hub, names)
        found["host"].append(host)
        found["number"].append(0)
        found["designation"].append(record.text("designation"))
        found["class"].append(record.text("class"))
        found["mass"].append(record.get("mass"))
        found["period"].append(record.get("period"))
        found["binary_type"].append(record.text("binary_type"))
        found["star_ids"].append(
            [dict(zip(CROSS_ID.names, item)) for item in star_ids] or None
        )
    return pa.table(
        {name: found[name] for name in PLANETS_INPUT.names}, schema=PLANETS_INPUT
    )


@dataclass
class Plan:
    """The rows of the star-systems pass, and what the commit needs."""

    systems: Systems
    # Node numbers and point keys, sorted, with the label of their row.
    node_numbers: np.ndarray
    node_labels: pa.Array
    point_keys: np.ndarray
    point_labels: pa.Array
    rows: pa.Table
    # Planet record index → the label of its circumbinary host.
    hosts: dict[int, str]
    # The claim of the resolved system of each SIMBAD system oid.
    system_claims: dict[str, dict] = field(default_factory=dict)
    # "<before> → <after>" of the merged class of each point that holds
    # several stars.
    classes: Counter = field(default_factory=Counter)
    counts: Counter = field(default_factory=Counter)


def _node_names(systems: Systems) -> dict[int, str]:
    """The best name of each node."""
    names = systems.names
    order = np.lexsort((names["rank"].to_numpy(), names["node"].to_numpy()))
    found: dict[int, str] = {}
    for node, name in zip(
        names["node"].take(pa.array(order)).to_pylist(),
        names["name"].take(pa.array(order)).to_pylist(),
    ):
        if name:
            found.setdefault(node, name)
    return found


def _nesting_rank(primaries: np.ndarray, depth: np.ndarray) -> np.ndarray:
    """For each node, the number of nodes of the same primary that it holds."""
    order = np.lexsort((-depth.astype(np.int64), primaries))
    rank = np.empty(order.size, np.int64)
    if order.size:
        ordered = primaries[order]
        starts = np.r_[True, ordered[1:] != ordered[:-1]]
        first = np.maximum.accumulate(np.where(starts, np.arange(order.size), 0))
        rank[order] = np.arange(order.size) - first
    return rank


def _resolved_claims(
    rows: pa.Table, resolver: RunResolver, counts: Counter
) -> pa.ListArray:
    """The claims of each resolved node: its catalogue ids, else its
    primary's id and its rank, null where it has neither.

    The rank counts the resolved nodes of the same primary inside the node.
    So a new outer node of a system changes no rank.
    """
    ids = rows["catalogue_ids"].combine_chunks()
    flat = pc.list_flatten(ids)
    own = pa.StructArray.from_arrays(
        [
            pa.array([SYSTEM_CLAIMS] * len(flat), pa.string()),
            flat.field("catalogue"),
            flat.field("catalogue_id"),
        ],
        fields=list(CROSS_ID),
    )
    lonely = np.flatnonzero(pc.list_value_length(ids).fill_null(0).to_numpy() == 0)
    primaries = rows["primary"].to_numpy()
    rank = _nesting_rank(primaries, rows["depth"].to_numpy())[lonely]
    found = resolver.claims(primaries[lonely])
    text = pc.binary_join_element_wise(
        *(found[name] for name in CROSS_ID.names), "/"
    ).combine_chunks()
    has = text.is_valid().to_numpy(zero_copy_only=False)
    counts["resolved systems that claim their primary"] += int(has.sum())
    counts["resolved systems with nothing to claim"] += int((~has).sum())
    primary = pa.StructArray.from_arrays(
        [
            pa.array([PRIMARY_CLAIM[0]] * int(has.sum()), pa.string()),
            pa.array([PRIMARY_CLAIM[1]] * int(has.sum()), pa.string()),
            pc.binary_join_element_wise(
                text.filter(pa.array(has)),
                pa.array(rank[has].astype(str), pa.string()),
                " ",
            ),
        ],
        fields=list(CROSS_ID),
    )
    # Each claim in the order of its row.
    row_of = np.concatenate([pc.list_parent_indices(ids).to_numpy(), lonely[has]])
    order = np.argsort(row_of, kind="stable")
    sizes = np.bincount(row_of, minlength=rows.num_rows)
    offsets = pa.array(np.r_[0, np.cumsum(sizes)].astype(np.int32))
    values = pa.concat_arrays([own, primary]).take(pa.array(order))
    return pa.ListArray.from_arrays(offsets, values, mask=pa.array(sizes == 0))


def _class_changes(before: pa.Table, keys: np.ndarray, classes: pa.Array) -> Counter:
    """The changes of the merged class that the star-systems rows of `keys`
    make. `before` is the merged class of the passes before.

    The merge of the old winner and the new row ranks as the commit's merge
    of every row, so it gives the class at the commit.
    """
    old = before.filter(pc.is_in(before["id"], value_set=pa.array(keys)))
    rows = pa.concat_tables(
        [
            pa.table(
                {
                    "id": old["id"],
                    SOURCE_COLUMN: old["class_source"],
                    "class": old["class"],
                }
            ),
            pa.table(
                {
                    "id": pa.array(keys, pa.int64()),
                    SOURCE_COLUMN: pa.array([STAR_SYSTEMS] * keys.size, pa.string()),
                    "class": classes,
                }
            ),
        ]
    )
    after = merge_by_source_order(CLASS, rows)
    was = dict(zip(old["id"].to_pylist(), old["class"].to_pylist()))
    found: Counter = Counter()
    for key, name in zip(after["id"].to_pylist(), after["class"].to_pylist()):
        previous = was.get(key)
        if previous != name:
            found[f"{previous or 'none'} → {name}"] += 1
    return found


def _one_claim(claims: pa.Table) -> pa.ListArray:
    """A list of the one claim of each row of `claims` (CROSS_ID columns)."""
    struct = pa.StructArray.from_arrays(
        [claims[name].combine_chunks() for name in CROSS_ID.names],
        fields=list(CROSS_ID),
    )
    offsets = pa.array(np.arange(claims.num_rows + 1, dtype=np.int32))
    return pa.ListArray.from_arrays(offsets, struct)


def pass_rows(systems: Systems, resolver: RunResolver, planets: pa.Table) -> Plan:
    """The rows of the star-systems pass: one per node and one per star."""
    counts: Counter = Counter()
    facts = resolver.facts_table
    assert facts is not None
    fact_keys = facts["key"].to_numpy()
    fact_order = np.argsort(fact_keys)
    fact_keys = fact_keys[fact_order]

    def fact(keys: np.ndarray, name: str) -> pa.Array:
        """A column of the facts of `keys`, null where a key has none."""
        at = find_sorted(fact_keys, keys)
        index = pa.array(fact_order[np.maximum(at, 0)], mask=at < 0)
        return facts[name].combine_chunks().take(index)

    # The claim and the label of each point, by key.
    points = systems.points
    point_keys = np.sort(points["key"].to_numpy())
    point_claims = resolver.claims(point_keys)
    point_labels = pc.binary_join_element_wise(
        *(point_claims[name] for name in CROSS_ID.names), "/"
    ).combine_chunks()
    linked = point_labels.is_valid().to_numpy(zero_copy_only=False)
    if not linked.all():
        counts["points with no catalogue id, made entries"] += int((~linked).sum())
        logger.warning("systems: %d points have no catalogue id", int((~linked).sum()))
        systems = _as_entries(systems, point_keys[~linked])
        points = systems.points
        point_keys = point_keys[linked]
        point_claims = point_claims.filter(pa.array(linked))
        point_labels = point_labels.filter(pa.array(linked))
    point_index = np.argsort(points["key"].to_numpy())

    def point_at(keys: np.ndarray) -> np.ndarray:
        """The position of each key among the sorted points, -1 where none."""
        return find_sorted(point_keys, keys)

    nodes = systems.nodes
    numbers = nodes["node"].to_numpy()
    node_keys = nodes["key"].to_numpy()
    resolved = node_keys == 0
    names = _node_names(systems)
    labels = np.empty(numbers.size, object)

    # A resolved system claims its catalogue ids, else its primary's id.
    resolved_rows = nodes.filter(pa.array(resolved))
    claimed = _resolved_claims(resolved_rows, resolver, counts)
    # A row's label is its first claim where no row before has it, else its
    # node number.
    resolved_numbers = resolved_rows["node"].to_numpy()
    offsets = claimed.offsets.to_numpy()
    named = np.flatnonzero(np.diff(offsets) > 0)
    first = claimed.values.take(pa.array(offsets[named]))
    text = pc.binary_join_element_wise(
        "node ",
        pc.binary_join_element_wise(
            *(first.field(name) for name in CROSS_ID.names), "/"
        ),
        "",
    ).to_numpy(zero_copy_only=False)
    _, unique = np.unique(text, return_index=True)
    resolved_labels = np.array([f"node {n}" for n in resolved_numbers.tolist()], object)
    resolved_labels[named[unique]] = text[unique]
    labels[resolved] = resolved_labels
    resolved_table = {
        "catalogue_id": pa.array(resolved_labels, pa.string()),
        "mint": pa.array(np.ones(resolved_rows.num_rows, bool)),
        "claims": claimed,
        "name": pa.array(
            [names.get(int(node)) for node in resolved_numbers], pa.string()
        ),
    }

    # A point that holds several stars claims one of its own ids.
    point_rows = nodes.filter(pa.array(~resolved))
    at = point_at(point_rows["key"].to_numpy())
    has = at >= 0
    point_rows = point_rows.filter(pa.array(has))
    at = at[has]
    labels[np.flatnonzero(~resolved)[has]] = point_labels.take(pa.array(at)).to_numpy(
        zero_copy_only=False
    )
    point_table = {
        "catalogue_id": point_labels.take(pa.array(at)),
        "mint": pa.array(np.zeros(at.size, bool)),
        "claims": _one_claim(point_claims.take(pa.array(at))),
        "name": pa.nulls(at.size, pa.string()),
    }
    counts["rows of resolved systems"] = resolved_rows.num_rows
    counts["rows of points that hold several stars"] = point_rows.num_rows

    # The distances of the stars that no step places, of seen rows only.
    distances = systems.distances
    placed = ~np.isin(distances["key"].to_numpy(), resolver.unseen)
    counts["system distances left out: flagged stars that no other catalogue sees"] = (
        int((~placed).sum())
    )
    counts["entries whose id reaches an object that is not minted"] = _lost_entries(
        systems.members, resolver.lost
    )
    by_key = _sorted(
        distances["key"].to_numpy()[placed], distances["distance"].to_numpy()[placed]
    )

    def node_columns(rows: pa.Table, table: dict, keys: np.ndarray) -> pa.Table:
        distance = map_sorted(*by_key, keys, np.nan)
        table |= {
            "match_ra": rows["ra"],
            "match_dec": rows["dec"],
            "match_mag": fact(rows["primary"].to_numpy(), "mag"),
            **{
                name: rows[name]
                for name in (
                    "point",
                    "depth",
                    "stars",
                    "ra",
                    "dec",
                    "label",
                    "spectral_type",
                    "evidence",
                    "sources",
                    "class",
                )
            },
            "distance": pa.array(distance, pa.float32(), from_pandas=True),
            "distance_method": _method(distance),
        }
        return pa.table(table)

    resolved_part = node_columns(
        resolved_rows, resolved_table, np.zeros(resolved_rows.num_rows, np.int64)
    )
    point_part = node_columns(point_rows, point_table, point_rows["key"].to_numpy())
    counts["points that hold several stars placed by system distance"] = int(
        pc.sum(pc.is_valid(point_part["distance"])).as_py() or 0
    )

    # A star of a system: its system distance and its own spectral type.
    single = points["node"].to_numpy()[point_index] == 0
    star_at = np.flatnonzero(single)
    star_keys = point_keys[star_at]
    star_points = points.take(pa.array(point_index[star_at]))
    distance = map_sorted(*by_key, star_keys, np.nan)
    moved = star_points["spectral_type_moved"].fill_null(False).to_numpy()
    star_table = {
        "catalogue_id": point_labels.take(pa.array(star_at)),
        "mint": pa.array(np.zeros(star_at.size, bool)),
        "match_ra": fact(star_keys, "ra"),
        "match_dec": fact(star_keys, "dec"),
        "match_mag": fact(star_keys, "mag"),
        "claims": _one_claim(point_claims.take(pa.array(star_at))),
        "distance": pa.array(distance, pa.float32(), from_pandas=True),
        "distance_method": _method(distance),
        "composite_moved": pa.array(moved, mask=~moved),
        "member_spectral_type": pc.if_else(
            pa.array(moved), star_points["spectral_type"].combine_chunks(), None
        ),
    }
    counts["rows of stars"] = int(star_at.size)
    counts["stars placed by system distance"] = int(np.isfinite(distance).sum())
    counts["composite spectral types moved"] = int(moved.sum())
    parts = [resolved_part, point_part, pa.table(star_table)]
    # With an empty part, the engine's take of these rows fails (pyarrow 25).
    rows = pa.concat_tables(
        [part for part in parts if part.num_rows] or parts[:1],
        promote_options="default",
    )
    for column in SOURCE_FIELDS:
        if column.name not in rows.column_names:
            rows = rows.append_column(column, pa.nulls(rows.num_rows, column.type))

    # Circumbinary hosts, by planet record.
    record_of: dict[tuple[int, str], list[int]] = defaultdict(list)
    for at_row, (host, designation) in enumerate(
        zip(planets["host"].to_pylist(), planets["designation"].to_pylist())
    ):
        record_of[(host, designation)].append(at_row)
    node_label = dict(zip(numbers.tolist(), labels.tolist()))
    hosts: dict[int, str] = {}
    for row in systems.hosts.to_pylist():
        if row["key"]:
            found = int(point_at(np.array([row["key"]], np.int64))[0])
            label = point_labels[found].as_py() if found >= 0 else None
        else:
            label = node_label.get(row["node"])
        if label is None:
            counts["circumbinary planets whose host has no row"] += 1
            continue
        for record in record_of.get((row["host"], row["designation"]), []):
            hosts[record] = label
    items = pc.list_flatten(claimed)
    oids = items.filter(
        pc.and_(
            pc.equal(items.field("catalogue"), SYSTEM_CLAIMS),
            pc.equal(items.field("release"), SIMBAD_OID[0]),
        )
    )
    system_claims = {item["catalogue_id"]: item for item in oids.to_pylist()}
    classes = _class_changes(
        resolver.classes, point_rows["key"].to_numpy(), point_rows["class"]
    )
    order = np.argsort(numbers)
    return Plan(
        systems,
        numbers[order],
        pa.array(labels[order], pa.string()),
        point_keys,
        point_labels,
        rows,
        hosts,
        system_claims,
        classes,
        counts,
    )


def _as_entries(systems: Systems, keys: np.ndarray) -> Systems:
    """`systems` with each point of `keys` as an entry of the node that lists
    it, and no node of its own. Such a point has no row that links it, so it
    gets no ID."""
    wanted = pa.array(keys, pa.int64())
    nodes, members = systems.nodes, systems.members
    gone = nodes.filter(pc.is_in(nodes["key"], value_set=wanted))["node"]
    gone = gone.combine_chunks()
    demoted = pc.or_(
        pc.and_(
            pc.equal(members["kind"], assemble.STAR),
            pc.is_in(members["key"], value_set=wanted),
        ),
        pc.and_(
            pc.equal(members["kind"], assemble.SYSTEM),
            pc.is_in(members["member"], value_set=gone),
        ),
    )
    zero = pa.scalar(0, pa.int64())
    for name, value in (("kind", pa.scalar(ENTRY)), ("key", zero), ("member", zero)):
        at = members.schema.get_field_index(name)
        members = members.set_column(
            at, name, pc.if_else(demoted, value, members[name])
        )

    def without(table: pa.Table, column: str, values: pa.Array) -> pa.Table:
        return table.filter(pc.invert(pc.is_in(table[column], value_set=values)))

    return replace(
        systems,
        nodes=without(nodes, "node", gone),
        members=without(members, "node", gone),
        points=without(systems.points, "key", wanted),
        distances=without(systems.distances, "key", wanted),
        names=without(systems.names, "node", gone),
    )


def _lost_entries(members: pa.Table, lost: pa.Array) -> int:
    """The entries that hold an id of `lost` ("<catalogue>/<release>/<id>")."""
    ids = members.filter(pc.equal(members["kind"], ENTRY))["ids"].combine_chunks()
    flat = pc.list_flatten(ids)
    texts = pc.binary_join_element_wise(
        *(flat.field(name) for name in CROSS_ID.names), "/"
    )
    hit = pc.is_in(texts, value_set=lost).fill_null(False)
    rows = pc.list_parent_indices(ids).to_numpy()
    return int(np.unique(rows[hit.to_numpy(zero_copy_only=False)]).size)


def _method(distance: np.ndarray) -> pa.Array:
    """The `distance_method` of the rows with a system distance, else null."""
    return pa.array(
        np.full(distance.size, SYSTEM_METHOD), pa.string(), mask=~np.isfinite(distance)
    )


def _sorted(keys: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(keys, kind="stable")
    return keys[order], values[order]


def _ids_of(labels: pa.Array, rows: pa.Table) -> np.ndarray:
    """The ID of the row of each label, 0 where it has none."""
    at = pc.index_in(labels, value_set=rows["catalogue_id"].combine_chunks())
    ids = rows["id"].combine_chunks().take(at)
    return ids.fill_null(0).to_numpy()


def _previous_systems(registry: Registry) -> np.ndarray:
    """The live IDs of the System table before this ingest."""
    found = [np.zeros(0, np.int64)]
    for region in registry.part_regions("ids"):
        records = registry.read_part("ids", region, ["id", "status"])
        ids = records["id"].to_numpy()
        status = records["status"].to_numpy(zero_copy_only=False)
        mine = table_of(ids) == SYSTEM_TABLE
        if not mine.any():
            continue
        # The latest record of an ID holds.
        ids, status = ids[mine][::-1], status[mine][::-1]
        _, last = np.unique(ids, return_index=True)
        found.append(ids[last][status[last] == LIVE])
    return np.unique(np.concatenate(found))


@dataclass
class SystemsExtension:
    """The links between the IDs of the systems, set at the commit."""

    plan: Plan
    run: IngestRun
    lines: list[str]
    targets: list[tuple[str, int]]
    name: str = "systems"
    sources: tuple[str, ...] = (STAR_SYSTEMS,)
    _hosts: dict[int, int] = field(default_factory=dict)
    _root_keys: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))
    _root_values: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))

    def items_moved(self, moved: list[str]) -> None:
        """Report the Wikidata items that go to a system, not to its star."""
        self.lines.append(f"Wikidata items about a system: {len(moved):,}")
        self.lines += [f"  {text}" for text in moved[:EXAMPLES]]

    def host(self, record: int) -> int:
        """The ID of the circumbinary host of a planet record, else 0."""
        return self._hosts.get(record, 0)

    def root(self, id_: int) -> int:
        """The root of the system of an ID, else 0."""
        at = find_sorted(self._root_keys, np.array([id_], np.int64))[0]
        return int(self._root_values[at]) if at >= 0 else 0

    def build(
        self,
        registry: Registry,
        ids: dict[str, pa.Table],
        ingest: int,
        complete: bool,
    ) -> ExtensionResult:
        plan, systems = self.plan, self.plan.systems
        rows = ids[STAR_SYSTEMS]
        node_ids = _ids_of(plan.node_labels, rows)
        point_ids = _ids_of(plan.point_labels, rows)

        def node_id(numbers: np.ndarray) -> np.ndarray:
            return map_sorted(plan.node_numbers, node_ids, numbers, 0)

        def point_id(keys: np.ndarray) -> np.ndarray:
            return map_sorted(plan.point_keys, point_ids, keys, 0)

        id_systems = _with_ids(systems, node_id, point_id)
        nodes, members, points = id_systems.nodes, id_systems.members, id_systems.points
        system = _system_patch(nodes, members)
        metadata = _metadata_patch(nodes, points)
        records = list(self.plan.hosts)
        host_ids = _ids_of(
            pa.array([self.plan.hosts[r] for r in records], pa.string()), rows
        )
        self._hosts = {r: int(i) for r, i in zip(records, host_ids.tolist()) if i}
        member_ids = np.concatenate(
            [nodes["node"].to_numpy(), points["key"].to_numpy()]
        )
        member_roots = np.concatenate(
            [nodes["root"].to_numpy(), points["root"].to_numpy()]
        )
        keep = (member_ids > 0) & (member_roots > 0)
        self._root_keys, self._root_values = _sorted(
            member_ids[keep], member_roots[keep]
        )

        resolved = nodes.filter(pc.invert(nodes["point"]))["node"].to_numpy()
        previous = _previous_systems(registry)
        counts = dict(plan.counts)
        counts |= {
            "system rows": system.num_rows,
            "metadata system": metadata.num_rows,
            "minted": int((~np.isin(resolved, previous) & (resolved > 0)).sum()),
            "kept": int(np.isin(resolved, previous).sum()),
            "gone": int((~np.isin(previous, resolved)).sum()),
            "no id": int((node_ids == 0).sum() + (point_ids == 0).sum()),
        }
        id_targets = [
            (label, int(point_id(np.array([key], np.int64))[0]) if key else 0)
            for label, key in self.targets
        ]
        lines = report_lines(id_systems, id_targets, classes=plan.classes)
        lines += [*self.lines, "", "Systems at the commit", ""]
        lines.append(
            f"system IDs: minted {counts['minted']:,}, kept {counts['kept']:,},"
            f" retired or merged {counts['gone']:,}"
        )
        lines.append(
            f"System rows: {system.num_rows:,}; Metadata `system` on"
            f" {metadata.num_rows:,} IDs; rows with no ID {counts['no id']:,}"
        )
        lines += [f"pass: {k} {v:,}" for k, v in sorted(plan.counts.items())]
        lines += _engine_lines(self.run)
        lines.append(f"circumbinary hosts: {len(self._hosts):,}")
        report = "\n".join(lines) + "\n"
        return ExtensionResult(
            parts={},
            tables={},
            key="id",
            counts=counts,
            report=report,
            patches={SYSTEM.slug: system, METADATA.slug: metadata},
        )


IdMap = Callable[[np.ndarray], np.ndarray]


def _with_ids(systems: Systems, node_id: IdMap, point_id: IdMap) -> Systems:
    """`systems` with the IDs of the nodes and points in place of their
    numbers and keys."""

    def mapped(table: pa.Table, columns: dict[str, IdMap]) -> pa.Table:
        for name, to in columns.items():
            values = to(table[name].to_numpy())
            table = table.set_column(
                table.schema.get_field_index(name), name, pa.array(values, pa.int64())
            )
        return table

    nodes = mapped(
        systems.nodes,
        {
            "node": node_id,
            "key": point_id,
            "parent": node_id,
            "root": node_id,
            "primary": point_id,
        },
    )
    members = mapped(
        systems.members, {"node": node_id, "key": point_id, "member": node_id}
    )
    points = mapped(
        systems.points,
        {"key": point_id, "node": node_id, "parent": node_id, "root": node_id},
    )
    distances = mapped(
        systems.distances, {"key": point_id, "node": node_id, "donor": point_id}
    )
    hosts = mapped(systems.hosts, {"node": node_id, "key": point_id})
    names = mapped(systems.names, {"node": node_id})
    return Systems(
        nodes,
        members,
        points,
        systems.absorbed,
        distances,
        hosts,
        systems.overlaps,
        names,
        systems.events,
        systems.counts,
    )


def _grouped(keys: np.ndarray, by: np.ndarray, values: pa.StructArray) -> pa.Array:
    """For each of `keys` (sorted, unique) the list of `values` whose `by` is
    that key, in the order of `values`."""
    picked = np.flatnonzero(np.isin(by, keys))
    order = picked[np.argsort(by[picked], kind="stable")]
    start = np.searchsorted(by[order], keys, "left")
    offsets = np.r_[start, order.size].astype(np.int32)
    return pa.ListArray.from_arrays(pa.array(offsets), values.take(pa.array(order)))


def _system_patch(nodes: pa.Table, members: pa.Table) -> pa.Table:
    """The links of each System row."""
    nodes = nodes.filter(pc.greater(nodes["node"], 0))
    nodes = nodes.take(pc.sort_indices(nodes["node"]))
    ids = nodes["node"].to_numpy()
    first = np.unique(ids, return_index=True)[1]
    if first.size < ids.size:
        logger.warning("systems: %d nodes share an ID", ids.size - first.size)
        nodes = nodes.take(pa.array(first))
        ids = ids[first]
    kind = members["kind"].to_numpy(zero_copy_only=False)
    member_id = np.where(
        members["member"].to_numpy() > 0,
        members["member"].to_numpy(),
        members["key"].to_numpy(),
    )
    struct = pa.StructArray.from_arrays(
        [
            pa.array(member_id, pa.int64(), mask=(kind == ENTRY) | (member_id == 0)),
            *(
                members[name].combine_chunks().cast(SYSTEM_MEMBER.field(name).type)
                for name in SYSTEM_MEMBER.names[1:]
            ),
        ],
        fields=list(SYSTEM_MEMBER),
    )
    member_lists = _grouped(ids, members["node"].to_numpy(), struct)
    parent = nodes["parent"].to_numpy()
    tree_struct = pa.StructArray.from_arrays(
        [
            pa.array(ids, pa.int64()),
            pa.array(parent, pa.int64(), mask=parent == 0),
            nodes["point"].combine_chunks(),
            nodes["stars"].combine_chunks().cast(pa.int32()),
            nodes["class"].combine_chunks(),
            nodes["label"].combine_chunks(),
        ],
        fields=list(SYSTEM_NODE),
    )
    roots = nodes["root"].to_numpy()
    is_root = parent == 0
    trees = _grouped(ids, np.where(roots > 0, roots, -1), tree_struct)
    trees = pc.if_else(pa.array(is_root), trees, pa.nulls(len(ids), trees.type))
    primary = nodes["primary"].to_numpy()
    return pa.table(
        {
            "id": pa.array(ids, pa.int64()),
            "parent": pa.array(parent, pa.int64(), mask=parent == 0),
            "root": pa.array(roots, pa.int64(), mask=roots == 0),
            "primary": pa.array(primary, pa.int64(), mask=primary == 0),
            "members": member_lists,
            "tree": trees,
        }
    )


def _metadata_patch(nodes: pa.Table, points: pa.Table) -> pa.Table:
    """The `system` of each node but the root, and of each star of a system."""
    node_ids, node_roots = nodes["node"].to_numpy(), nodes["root"].to_numpy()
    inner = (nodes["parent"].to_numpy() > 0) & (node_ids > 0)
    single = points["node"].to_numpy() == 0
    star_ids, star_roots = points["key"].to_numpy(), points["root"].to_numpy()
    star = single & (star_ids > 0)
    ids = np.concatenate([node_ids[inner], star_ids[star]])
    roots = np.concatenate([node_roots[inner], star_roots[star]])
    keep = (roots > 0) & (roots != ids)
    ids, roots = ids[keep], roots[keep]
    first = np.unique(ids, return_index=True)[1]
    return pa.table(
        {"id": pa.array(ids[first], pa.int64()), "system": pa.array(roots[first])}
    )


def _engine_lines(run: IngestRun, examples: int = EXAMPLES) -> list[str]:
    """The joins and conflicts of the run that the system rows made."""
    marks = (f"{SYSTEMS.catalogue}/{SYSTEMS.release}/", f"{WDS_COMPONENTS.catalogue}/")
    lines = []
    for title, texts in (("joins", run.joins), ("conflicts", run.conflicts)):
        mine = [text for text in texts if any(mark in text for mark in marks)]
        lines.append(f"{title} by system or WDS rows: {len(mine):,}")
        lines += [f"  {text}" for text in mine[:examples]]
    return lines


# The downloads that the systems read, beside those of the stars.
INPUT_DIRS = (wds.OUT_DIR, msc.OUT_DIR, el_badry.OUT_DIR)


def check_inputs(directories: Iterable[Path] = INPUT_DIRS) -> None:
    """Fail before the ingest starts when a download of the systems is
    missing or incomplete."""
    for directory in directories:
        path = directory / "metadata.json"
        if not path.exists() or not json.loads(path.read_text()).get("complete"):
            raise FileNotFoundError(
                f"{directory}: no complete download; run space-map-download"
                " --sources wds msc el_badry_binaries"
            )


def read_inputs(
    run: IngestRun,
    simbad_list: SimbadList,
    prepared: Prepared,
    hub: Simbad,
    reader: GaiaReader,
) -> tuple[Inputs, SimbadIndex]:
    """The tree sources, the Gaia orbits and the planets of the run."""
    index = SimbadIndex.build(simbad_list)
    orbits = reader.read_orbits().rows.select(["source_id", *ORBIT_COLUMNS])
    inputs = Inputs(
        msc=read_msc(),
        refuted=refuted_pairs(),
        simbad=read_simbad(simbad_list),
        simbad_index=index,
        planet_systems=read_planet_systems(
            prepared.stars, prepared.systems, read_oec_trees()
        ),
        wds=WdsCatalogue.read(),
        el_badry=read_el_badry(),
        orbits=orbit_pairs(orbits),
        planets=run_planets(run, prepared, hub),
    )
    return inputs, index


def add_systems(
    run: IngestRun, inputs: Inputs, index: SimbadIndex | None, complete: bool
) -> SystemsExtension:
    """Build the systems from the run so far, run the wds-components and
    star-systems passes, and add the extension that links them.

    `inputs.planets` are the planet records in order, with run keys as hosts.
    """
    started = time.monotonic()
    resolver = RunResolver(run, complete)
    planets = (
        inputs.planets if inputs.planets is not None else PLANETS_INPUT.empty_table()
    )
    at = planets.schema.get_field_index("host")
    hosts = resolver.objects(planets["host"].to_numpy())
    planets = planets.set_column(at, "host", pa.array(hosts, pa.int64()))
    systems = build(replace(inputs, planets=planets), resolver)
    built = time.monotonic()
    targets = target_keys(index, resolver)
    plan = pass_rows(systems, resolver, planets)
    lines = [
        "resolver: "
        + ", ".join(f"{k} {v:,}" for k, v in sorted(resolver.counts.items()))
    ]
    # The pass needs none of the facts and links.
    del resolver
    run.add(SYSTEMS, [plan.rows], complete)
    plan.rows = plan.rows.slice(0, 0)
    lines.append(
        f"timings: build {built - started:.0f} s,"
        f" passes {time.monotonic() - built:.0f} s"
    )
    extension = SystemsExtension(plan, run, lines, targets)
    run.extend(extension)
    logger.info("systems: done in %.0f s", time.monotonic() - started)
    return extension
