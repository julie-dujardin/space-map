"""The normalized form of a tree source: one table of nodes.

Each source reader gives one table with the columns of NODES. A node is a
star or a group of stars as the source lists it. A node with no children is a
member: one star, or a group that the source does not split. A node with
children groups them. `parent` links a node to its group, and -1 marks a
root. `system` is the source's key of the tree.

`ids` holds the catalogue ids of the node. Some reach a stored object
(OBJECT_CATALOGUES), some reach one through SIMBAD's identifiers
(SIMBAD_CATALOGUES), and some name the node as a system (SYSTEM_CATALOGUES):
they become the catalogue ids of a new system.

The values of a member describe the member, and its orbit in its group: the
separation, position angle and period from the group's primary, and how the
pair is known.
"""

from collections.abc import Iterable

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar.exoplanets.catalogues import ARCHIVE, EU, OEC
from space_map_data.extrasolar.tables import CROSS_ID

# The tree sources, in source order for the structure.
MSC = "msc"
SIMBAD = "simbad"
PLANETS = "planet-catalogues"
WDS = "wds"
EL_BADRY = "el-badry-2021"
GAIA_ORBITS = "gaia-dr3-orbits"
TREE_SOURCES = (MSC, SIMBAD, PLANETS, WDS, EL_BADRY, GAIA_ORBITS)
# A point that SIMBAD types as a close pair. It ranks after the trees.
SIMBAD_TYPE = "simbad-type"
INTERIOR_SOURCES = (*TREE_SOURCES, SIMBAD_TYPE)

GAIA_DR3 = ("gaia", "dr3")
HIP = ("hip", "2007")
HD = ("hd", "1949")
SIMBAD_OID = ("simbad", "oid")
PLANET_HOSTS = (
    (ARCHIVE, "pscomppars"),
    (EU, "catalog"),
    (OEC, "systems"),
)
# Ids that the registry links to objects, best first for a member.
OBJECT_CATALOGUES = (SIMBAD_OID, GAIA_DR3, *PLANET_HOSTS, HIP, HD)
# Ids that reach an object only through SIMBAD's identifiers.
HR = ("hr", "bsc")
GCVS = ("gcvs", "name")
SIMBAD_CATALOGUES = (GAIA_DR3, HIP, HD, HR, GCVS)
# Ids of a system node.
WDS_ID = ("wds", "id")
MSC_ID = ("msc", "id")
EL_BADRY_PAIR = ("el-badry", "2021")
SYSTEM_CATALOGUES = (SIMBAD_OID, WDS_ID, MSC_ID, EL_BADRY_PAIR)

# How a pair or a member is known.
VISUAL = "visual"
VISUAL_ORBIT = "visual orbit"
PROPER_MOTION = "common proper motion"
PARALLAX = "common parallax"
SPECTROSCOPIC = "spectroscopic"
SPECTROSCOPIC_ORBIT = "spectroscopic orbit"
ECLIPSING = "eclipsing"
ASTROMETRIC = "astrometric"
ASTROMETRIC_ORBIT = "astrometric orbit"
OCCULTATION = "occultation"
CATALOGUE = "catalogue"

NODES = pa.schema(
    [
        ("source", pa.string()),
        ("system", pa.string()),
        ("node", pa.int64()),
        ("parent", pa.int64()),
        # The component letters as the source writes them ("A", "Aa", "AB"),
        # or SIMBAD's main identifier.
        ("label", pa.string()),
        # The children have no hierarchy among them (a trapezium).
        ("flat", pa.bool_()),
        ("ids", pa.list_(CROSS_ID)),
        # ICRS in degrees at `epoch` (Julian year); mas/yr, pmra on ra·cos dec.
        ("ra", pa.float64()),
        ("dec", pa.float64()),
        ("epoch", pa.float32()),
        ("pmra", pa.float32()),
        ("pmdec", pa.float32()),
        ("parallax", pa.float32()),
        ("v_mag", pa.float32()),
        ("g_mag", pa.float32()),
        ("spectral_type", pa.string()),
        # Solar masses.
        ("mass", pa.float32()),
        # The orbit in the group, from the group's primary: arcsec, deg, d.
        ("separation", pa.float64()),
        ("position_angle", pa.float32()),
        ("period", pa.float64()),
        ("eccentricity", pa.float32()),
        ("semi_major_axis", pa.float32()),
        ("known", pa.list_(pa.string())),
        # Null when the source says the pair is physical, else UNVERIFIED or
        # DUBIOUS: the builder keeps the member only where data agree.
        ("evidence", pa.string()),
    ]
)
UNVERIFIED = "unverified"
DUBIOUS = "dubious"
NAMES = NODES.names


class NodeList:
    """Collects the nodes of a source one at a time."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.columns: dict[str, list] = {name: [] for name in NAMES}

    def __len__(self) -> int:
        return len(self.columns["node"])

    def add(
        self,
        system: str,
        parent: int,
        label: str | None,
        ids: Iterable[tuple[str, str, str]] = (),
        **values,
    ) -> int:
        """Add a node and return its number."""
        node = len(self)
        row = {
            "source": self.source,
            "system": system,
            "node": node,
            "parent": parent,
            "label": label,
            "flat": values.pop("flat", False),
            "ids": [dict(zip(CROSS_ID.names, i)) for i in ids] or None,
            **values,
        }
        unknown = set(row) - set(NAMES)
        if unknown:
            raise ValueError(f"unknown node columns {sorted(unknown)}")
        for name in NAMES:
            self.columns[name].append(row.get(name))
        return node

    def table(self) -> pa.Table:
        return pa.table(self.columns, schema=NODES)


def number(value: float | None) -> float | None:
    """None for NaN, so a missing value stays null in the table."""
    return None if value is None or not np.isfinite(value) else value


def id_lists(
    columns: Iterable[tuple[tuple[str, str], pa.Array]], size: int
) -> pa.Array:
    """The `ids` column from id columns of one catalogue each.

    A null id is left out. Each column has `size` values.
    """
    flat_catalogue, flat_release, flat_id, owner = [], [], [], []
    for (catalogue, release), values in columns:
        values = values.cast(pa.string())
        valid = np.flatnonzero(values.is_valid().to_numpy(zero_copy_only=False))
        flat_id.append(values.take(pa.array(valid)))
        flat_catalogue.append(np.full(valid.size, catalogue, object))
        flat_release.append(np.full(valid.size, release, object))
        owner.append(valid)
    rows = np.concatenate(owner) if owner else np.zeros(0, np.int64)
    order = np.argsort(rows, kind="stable")
    structs = pa.StructArray.from_arrays(
        [
            pa.array(np.concatenate(flat_catalogue)[order], pa.string()),
            pa.array(np.concatenate(flat_release)[order], pa.string()),
            pa.concat_arrays(flat_id).take(pa.array(order)),
        ],
        fields=list(CROSS_ID),
    )
    offsets = np.searchsorted(rows[order], np.arange(size + 1)).astype(np.int32)
    return pa.ListArray.from_arrays(pa.array(offsets), structs)


def children_of(parents: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The children of each node as (order, start): the children of node n
    are order[start[n]:start[n + 1]]. `parents` is -1 at a root."""
    order = np.argsort(parents, kind="stable")
    start = np.searchsorted(parents[order], np.arange(parents.size + 1))
    return order, start
