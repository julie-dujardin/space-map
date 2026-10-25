"""The exoplanet part of the extrasolar ingest.

`prepare` reads the catalogues, joins the stars and planets, classes the
planets and builds the pass rows: the host rows of each catalogue, and the
Gaia DR3 rows of the hosts that no positionable Gaia row holds. `add_passes`
runs the three catalogue passes and adds `PlanetsExtension`, which numbers
the planets and writes the Planets part and the planets table at commit.

A host whose Gaia DR3 source is the best neighbour of a Hipparcos star gets
no Gaia row here: the Hipparcos star already holds that DR3 id, and a Gaia
row would replace its Hipparcos astrometry. For the same reason a host with
an unpositionable DR3 source and a HIP number claims its HIP number.
"""

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

from space_map_data.download.providers.exoplanets import gaia as gaia_provider
from space_map_data.extrasolar.engine import ExtensionResult, IngestRun
from space_map_data.extrasolar.exoplanets import (
    catalogues,
    hosts,
    names,
    numbering,
    simbad,
    table,
    twins,
)
from space_map_data.extrasolar.exoplanets.catalogues import (
    ARCHIVE,
    EU,
    LENS,
    OEC,
    P_TYPE,
    Catalogue,
    close,
    reduced,
)
from space_map_data.extrasolar.exoplanets.hosts import Stars, Systems
from space_map_data.extrasolar.exoplanets.join import (
    CHECK_TOLERANCE,
    KEPT_STATUS,
    LEFT_OUT,
    Joined,
    JoinResult,
    designation_key,
    join_planets,
)
from space_map_data.extrasolar.exoplanets.sources import BY_NAME, SOURCES
from space_map_data.extrasolar.exoplanets.table import Record
from space_map_data.extrasolar.ids import cell_of
from space_map_data.extrasolar.placement import COLUMNS, placement
from space_map_data.extrasolar.registry import Registry, ingest_name
from space_map_data.extrasolar.sky import region_of
from space_map_data.extrasolar.sources import gaia
from space_map_data.extrasolar.sources.gaia import GaiaReader
from space_map_data.extrasolar.store import region_file
from space_map_data.extrasolar.tables import POINT_SOURCE

logger = logging.getLogger(__name__)

EXAMPLES = 20


@dataclass(frozen=True)
class Inputs:
    """The downloaded files that the exoplanet ingest reads."""

    archive: Path = catalogues.PSCOMPPARS
    eu: Path = catalogues.EU_CATALOG
    oec: Path = catalogues.OEC_SYSTEMS
    simbad: Path = simbad.SIMBAD_DIR
    neighbourhood: Path = hosts.NEIGHBOURHOOD
    orbits: Path = gaia_provider.OUT_DIR / "nss_two_body_orbit.csv"
    gaia_source: Path = gaia_provider.OUT_DIR / gaia_provider.SOURCE_FILE
    fidelity: Path = gaia_provider.OUT_DIR / gaia_provider.FIDELITY_FILE
    astrophysical: Path = gaia_provider.OUT_DIR / gaia_provider.ASTROPHYSICAL_FILE
    xgboost: Path = gaia_provider.OUT_DIR / gaia_provider.XGBOOST_FILE
    names: Path = names.NAMES_FILE


@dataclass
class TwinSearch:
    targets: list[twins.Target]
    found: twins.Found
    # The first member (catalogue, key) of a star that claims its twin.
    claims: dict[tuple[str, str], twins.Twin]
    # Members of two stars to join: the twin of one is the other's star.
    joins: list[tuple[tuple[str, str], tuple[str, str]]]
    joined: list[str]
    # Members of two stars at one twin that stay two stars of one system.
    links: list[tuple[tuple[str, str], tuple[str, str]]]


@dataclass
class Prepared:
    catalogues: list[Catalogue]
    stars: Stars
    systems: Systems
    join: JoinResult
    records: list[Record]
    excluded: Counter
    named: names.Named
    # Source name → host rows.
    host_rows: dict[str, pa.Table]
    gaia_rows: pa.Table
    gaia_counts: Counter
    hosts: list[int]
    # Names in the IAU lists.
    nameexoworlds: int
    twins: TwinSearch
    # Hosts that claim their HIP number for an unpositionable DR3 source.
    by_hip: list[str]

    def batches(self, source: str) -> list[pa.Table]:
        return [self.host_rows[source]]


def unpositionable_ids(inputs: Inputs) -> set[int]:
    """The DR3 ids of the hosts' Gaia sources without a 5σ parallax."""
    table = pcsv.read_csv(
        inputs.gaia_source,
        convert_options=pcsv.ConvertOptions(
            include_columns=["source_id"], column_types={"source_id": pa.int64()}
        ),
    )
    return set(table["source_id"].to_pylist())


def _read_typed(path: Path, names: tuple[str, ...]) -> pa.Table:
    """A companion CSV with the Point source type of each column in `names`."""
    types = {name: POINT_SOURCE.schema.field(name).type for name in names}
    return pcsv.read_csv(
        path,
        convert_options=pcsv.ConvertOptions(
            column_types={"source_id": pa.int64(), **types}
        ),
    )


def read_gaia_rows(
    inputs: Inputs, wanted: set[int], reader: GaiaReader
) -> tuple[pa.Table, Counter]:
    """Gaia pass rows of the unpositionable sources that a host claims.

    The rows get the joins of the chunk rows, so a column that a companion
    file has no row for stays null.
    """
    counts: Counter = Counter()
    strings = {name: pa.string() for name in ("phot_variable_flag", "libname_gspphot")}
    stars = pcsv.read_csv(
        inputs.gaia_source,
        convert_options=pcsv.ConvertOptions(
            column_types={"source_id": pa.int64(), **strings}
        ),
    )
    # A column that the CSV leaves empty reads as nulls without a type.
    for name in gaia.COLUMNS[1:]:
        at = stars.schema.get_field_index(name)
        stars = stars.set_column(
            at, name, stars[name].cast(POINT_SOURCE.schema.field(name).type)
        )
    source_id = stars["source_id"].to_numpy()
    hipparcos = np.isin(source_id, reader.best.source_id)
    claimed = np.isin(source_id, np.array(sorted(wanted), np.int64))
    counts["unpositionable Gaia sources of hosts"] = int(claimed.sum())
    counts["of which a Hipparcos star holds"] = int((claimed & hipparcos).sum())
    stars = stars.filter(pa.array(claimed & ~hipparcos))
    rows = reader.pass_rows(
        stars,
        _read_typed(inputs.fidelity, gaia.FIDELITY_COLUMNS),
        _read_typed(inputs.astrophysical, gaia.ASTROPHYSICAL_COLUMNS),
        _read_typed(inputs.xgboost, gaia.XGBOOST_COLUMNS),
        [table.rows for table in reader.joined],
        reader.read_orbits(),
    )
    # Each row gets an ID only when a host row claims it.
    return rows.set_column(
        rows.schema.get_field_index("mint"), "mint", pa.array(np.zeros(len(rows), bool))
    ), counts


DEFAULT_INPUTS = Inputs()


def prepare(
    reader: GaiaReader,
    registry: Registry,
    hip_names: dict[int, str],
    inputs: Inputs = DEFAULT_INPUTS,
) -> Prepared:
    """Read and join the catalogues, and build the pass rows.

    `reader` joins the Gaia rows of the hosts as it joins its chunks.
    `registry` gives the stars that a host without ids may be a twin of, and
    `hip_names` the Hipparcos name of each HIP number.
    """
    cats = [
        catalogues.read_archive(inputs.archive),
        catalogues.read_eu(inputs.eu),
        catalogues.read_oec(inputs.oec),
    ]
    hub = simbad.read_simbad(inputs.simbad)
    neighbours = hosts.read_neighbours(inputs.neighbourhood)
    stars = hosts.build_stars(cats, hub, neighbours)
    search = _search_twins(stars, cats, hub, registry)
    if search.joins:
        stars = hosts.build_stars(cats, hub, neighbours, search.joins)
    # A companion at its primary's position is a star of the primary's system.
    systems = hosts.group_systems(
        stars, [(stars.of[a], stars.of[b]) for a, b in search.links]
    )
    joined = join_planets(cats, stars, systems, hub)
    orbits = table.read_sky_orbits(inputs.orbits)

    records: list[Record] = []
    excluded: Counter = Counter()
    for planet in joined.planets:
        star = _star_of(planet, stars)
        if star is None:
            excluded["no host star"] += 1
            continue
        identity = stars.identities[star]
        record = table.merge(
            planet,
            star,
            star,
            systems.of[star],
            orbits.get(identity.gaia_dr3 or 0, []),
            identity.value("mass"),
            tuple(n for s in identity.members.values() for n in s.names),
        )
        if table.too_massive(record):
            excluded["above 60 MJ"] += 1
            continue
        records.append(record)

    host_set = {record.star for record in records}
    systems.choose_keys(stars, host_set)
    for record in records:
        record.key = systems.key[record.system]
        identity = stars.identities[record.star]
        table.kepler(record, identity.value("mass"), identity.value("distance"))
    table.fill_defaults(records)

    star_of = {at: record.star for at, record in enumerate(records)}
    iau_names = names.read_names(inputs.names)
    named = names.place_names(
        iau_names, [record.joined for record in records], stars, star_of
    )
    for at, name in named.planets.items():
        table.name_planet(records[at], name)

    host_list = sorted(host_set)
    host_identities = [stars.identities[i] for i in host_list]
    classes = {i: hub.star_class(stars.identities[i].oid) for i in host_list}
    lensed = hosts.found_by(stars, cats, {catalogues.MICROLENSING})
    claims: dict[int, tuple[str, str, str]] = {}
    unpositionable = unpositionable_ids(inputs) - set(reader.best.source_id.tolist())
    by_hip = []
    for identity in host_identities:
        if identity.hip and identity.gaia_dr3 in unpositionable:
            claims[identity.index] = (*hosts.HIP, str(identity.hip))
            by_hip.append(f"{identity.name}: HIP {identity.hip}")
    for member, twin in search.claims.items():
        claims[stars.of[member]] = twin.claim
    long_names = {
        i.index: hip_names[i.hip] for i in host_identities if i.hip in hip_names
    }
    host_rows = {
        source.name: hosts.host_rows(
            source.name,
            host_identities,
            named.stars,
            classes,
            lensed,
            claims,
            long_names,
        )
        for source in SOURCES
    }
    wanted = {
        i.gaia_dr3 for i in host_identities if i.gaia_dr3 and i.index not in claims
    }
    gaia_rows, gaia_counts = read_gaia_rows(inputs, wanted, reader)
    logger.info(
        "exoplanets: %d planets around %d stars, %d Gaia rows for unpositionable"
        " hosts, %d hosts by their HIP number, %d twins and %d joins of %d stars"
        " without ids",
        len(records),
        len(host_list),
        gaia_rows.num_rows,
        len(by_hip),
        len(search.claims),
        len(search.joined),
        len(search.targets),
    )
    return Prepared(
        cats,
        stars,
        systems,
        joined,
        records,
        excluded,
        named,
        host_rows,
        gaia_rows,
        gaia_counts,
        host_list,
        sum(len(system) for system in iau_names),
        search,
        by_hip,
    )


# Star masses of one star differ by less than this, as a fraction.
MASS_TOLERANCE = 0.2
# A final component: "X B", "X (AB)", "X Ba", or a capital after a number,
# "ITG 15B".
_FINAL_COMPONENT = re.compile(r"(?:\s\(?([A-D][A-Da-d]?)\)?|(?<=\d)([A-D]))$")


def _names(identity: hosts.Identity) -> list[str]:
    return [name for star in identity.members.values() for name in star.names]


def _base(name: str) -> str:
    """A star name without its lens letter and a primary component."""
    found = _FINAL_COMPONENT.search(name.strip())
    if found and (found[1] or found[2]) in ("A", "AB"):
        name = name.strip()[: found.start()]
    return reduced(LENS.sub(r"\1", name))


def _component(name: str) -> str:
    """The component at the end of a star name; "" for none, `A` or `AB`."""
    found = _FINAL_COMPONENT.search(name.strip())
    letters = (found[1] or found[2]) if found else ""
    return "" if letters in ("A", "AB") else letters


def _search_twins(
    stars: Stars, cats: list[Catalogue], hub: simbad.Simbad, registry: Registry
) -> TwinSearch:
    """The twins of the planet hosts without a Gaia DR3 id or HIP number.

    A twin that another star of the join holds makes the two stars one, when
    their component letters agree (`A` and `AB` count as none: Gaia sees a
    pair as one source), or when they share a planet period within 1% and
    their masses agree. Other letters with no such evidence are a companion
    that a catalogue put at its primary's position.
    """
    # A pulsar or a lens is not the star at its catalogue position.
    not_stars = hosts.found_by(
        stars, cats, {catalogues.MICROLENSING, catalogues.PULSAR_TIMING}
    )
    with_planets = {
        identity.index
        for catalogue in cats
        for planet in catalogue.planets
        if planet.status in KEPT_STATUS
        and (identity := stars.identity(catalogue.name, planet.star)) is not None
    }
    targets = [
        target
        for identity in stars.identities
        if not identity.gaia_dr3
        and not identity.hip
        and identity.index in with_planets
        and identity.index not in not_stars
        and hub.star_class(identity.oid) != simbad.PULSAR
        and (target := _twin_target(identity)) is not None
    ]
    holder: dict[tuple[str, str, str], int] = {}
    for identity in stars.identities:
        if identity.gaia_dr3:
            holder[(*hosts.GAIA_DR3, str(identity.gaia_dr3))] = identity.index
        if identity.hip:
            holder[(*hosts.HIP, str(identity.hip))] = identity.index
    found = twins.find(registry, targets, holder.keys())
    first = {
        identity.index: (identity.first.catalogue, identity.first.key)
        for identity in stars.identities
    }
    periods = _periods(stars, cats)
    joins, joined, links = [], [], []
    for key, twin in sorted(found.held.items()):
        star, other = stars.identities[key], stars.identities[holder[twin.claim]]
        why = _same_star(star, other, periods)
        pair = (first[star.index], first[other.index])
        if why:
            joins.append(pair)
            joined.append(
                f"{star.name} ({star.first.catalogue}) is {other.name}: {why}"
            )
        else:
            links.append(pair)
    return TwinSearch(
        targets,
        found,
        {first[key]: twin for key, twin in found.twins.items()},
        joins,
        joined,
        links,
    )


def _periods(stars: Stars, cats: list[Catalogue]) -> dict[int, list[float]]:
    found: dict[int, list[float]] = {}
    for catalogue in cats:
        for planet in catalogue.planets:
            identity = stars.identity(catalogue.name, planet.star)
            period = planet.values.get("period")
            if identity is not None and period is not None and period.value > 0:
                found.setdefault(identity.index, []).append(period.value)
    return found


def _same_star(
    star: hosts.Identity, other: hosts.Identity, periods: dict[int, list[float]]
) -> str | None:
    """Why two stars at one position are one star, None when not shown."""

    if _component(star.name) == _component(other.name):
        return "the same component"
    shared = any(
        close(a, b, 0.01)
        for a in periods.get(star.index, ())
        for b in periods.get(other.index, ())
    )
    mass, other_mass = star.value("mass"), other.value("mass")
    if shared and mass and other_mass and close(mass, other_mass, MASS_TOLERANCE):
        return "a planet period and the star mass"
    return None


def _twin_target(identity: hosts.Identity) -> twins.Target | None:
    position = hosts.reference_position(identity)
    if position is None:
        return None
    parallax = next(
        (
            star.values["parallax"]
            for catalogue in catalogues.CATALOGUES
            if (star := identity.members.get(catalogue)) is not None
            and "parallax" in star.values
        ),
        None,
    )
    error = None
    if parallax is not None and (parallax.upper or parallax.lower):
        error = max(e for e in (parallax.upper, parallax.lower) if e is not None)
    return twins.Target(
        key=identity.index,
        name=identity.name,
        ra=position[0],
        dec=position[1],
        parallax=None if parallax is None else parallax.value,
        parallax_error=error,
        distance=identity.value("distance"),
        g_mag=identity.value("g_mag"),
        v_mag=identity.value("v_mag"),
        k_mag=identity.value("k_mag"),
        companion=hosts.component_letter(identity.name) not in ("", "AB"),
    )


def _star_of(planet: Joined, stars: Stars) -> int | None:
    """The star a planet orbits.

    When the catalogues put the planet on other stars, the one star that its
    designation names wins: "OGLE-2019-BLG-0299L b" orbits OGLE-2019-BLG-0299L,
    which two catalogues confuse with another lens. Then OEC's star comes
    first, then the archive's, then exoplanet.eu's; for a circumbinary planet
    OEC's comes last, since OEC names the first star of the pair and Gaia sees
    the pair as one source. A star with a Gaia DR3 id or HIP number wins over
    one without, then one that SIMBAD knows.
    """
    oec = planet.rows.get(OEC)
    circumbinary = oec is not None and oec.binary == P_TYPE
    order = (ARCHIVE, EU, OEC) if circumbinary else (OEC, ARCHIVE, EU)
    found = [
        identity
        for source in order
        if (row := planet.rows.get(source)) is not None
        and (identity := stars.identity(source, row.star)) is not None
    ]
    if len({identity.index for identity in found}) > 1:
        star_key = designation_key(planet.first.name)[:-1]
        named = {
            identity.index
            for identity in found
            if any(designation_key(name) == star_key for name in _names(identity))
        }
        if len(named) == 1:
            star = named.pop()
            bases = {_base(name) for name in _names(stars.identities[star])}
            # Another star of that name, as USco1621 A for USco 1621, is the
            # same star under the rules below.
            if not any(
                bases & {_base(name) for name in _names(identity)}
                for identity in found
                if identity.index != star
            ):
                return star
    for good in (
        lambda i: i.gaia_dr3 is not None or i.hip is not None,
        lambda i: i.oid is not None,
        lambda i: True,
    ):
        for identity in found:
            if good(identity):
                return identity.index
    return None


def add_passes(run: IngestRun, prepared: Prepared, complete: bool) -> None:
    """Run the catalogue passes and add the planets extension."""
    for source in SOURCES:
        run.add(source, prepared.batches(source.name), complete)
    run.extend(PlanetsExtension(prepared))


# The extension


@dataclass
class PlanetsExtension:
    prepared: Prepared
    name: str = "planets"
    sources: tuple[str, ...] = tuple(source.name for source in SOURCES)

    def build(
        self,
        registry: Registry,
        ids: dict[str, pa.Table],
        ingest: int,
        complete: bool,
    ) -> ExtensionResult:
        prepared = self.prepared
        id_of: dict[tuple[str, str], int] = {}
        for source, rows in ids.items():
            for catalogue_id, id_ in zip(
                rows["catalogue_id"].to_pylist(), rows["id"].to_pylist()
            ):
                id_of[(source, catalogue_id)] = id_
        identity_id, disagree = self._identity_ids(id_of)

        incoming: list[numbering.Incoming] = []
        host_of: dict[int, int] = {}
        system_of: dict[int, int] = {}
        # System ID → rank of its key star, so that joined systems keep the
        # key rule.
        rank: dict[int, tuple] = {}
        without_host = []
        for at, record in enumerate(prepared.records):
            host = identity_id.get(record.star, 0)
            system = identity_id.get(record.key, 0)
            if not host or not system:
                without_host.append(record.text("designation") or "")
                continue
            host_of[at], system_of[at] = host, system
            found = hosts.key_rank(prepared.stars, record.key)
            rank[system] = min(rank.get(system, found), found)
            incoming.append(
                numbering.Incoming(
                    index=at,
                    host=host,
                    ids=tuple(
                        (c["catalogue"], c["release"], c["catalogue_id"])
                        for c in _catalogue_ids(record)
                    ),
                    year=record.year,
                    letter=record.text("letter"),
                    designation=record.text("designation") or "",
                    period=record.get("period"),
                )
            )
        system_of, joined_systems = one_system_per_host(host_of, system_of, rank)
        state = numbering.read_state(registry)
        assignment = numbering.assign(
            incoming, state, _previous(registry), ingest, complete
        )
        rows = [
            table.to_row(prepared.records[at], number[0], number[1], system_of[at])
            for at, number in assignment.number.items()
        ]
        planets = pa.Table.from_pylist(rows, schema=table.SCHEMA)
        planets = numbering.sort_records(planets)
        report, counts = self._report(
            registry, ingest, assignment, planets, identity_id, disagree, without_host
        )
        report += "".join(
            line + "\n"
            for line in _listed(
                "check: systems joined, since one ID is a host of both",
                joined_systems,
                limit=None,
            )
        )
        return ExtensionResult(
            parts={numbering.PART: assignment.records},
            tables={table.SLUG: planets},
            key="host",
            counts=counts,
            report=report,
            unreviewed=assignment.unreviewed + len(disagree),
        )

    def _identity_ids(
        self, id_of: dict[tuple[str, str], int]
    ) -> tuple[dict[int, int], list[str]]:
        """The ID of each host identity, and the identities whose rows differ."""
        found: dict[int, int] = {}
        disagree = []
        for index in self.prepared.hosts:
            identity = self.prepared.stars.identities[index]
            got = {
                source: id_of.get((source, star.key), 0)
                for source, star in identity.members.items()
                if (source, star.key) in id_of
            }
            distinct = {v for v in got.values() if v}
            if len(distinct) > 1:
                disagree.append(
                    f"{identity.name}: "
                    + ", ".join(f"{s} → {v}" for s, v in sorted(got.items()))
                )
            first = next((got[s] for s in (ARCHIVE, EU, OEC) if got.get(s)), 0)
            if first:
                found[index] = first
        for text in disagree:
            logger.warning("host rows of one star got several IDs: %s", text)
        return found, disagree

    def _report(
        self,
        registry: Registry,
        ingest: int,
        assignment: numbering.Assignment,
        planets: pa.Table,
        identity_id: dict[int, int],
        disagree: list[str],
        without_host: list[str],
    ) -> tuple[str, dict[str, int]]:
        prepared = self.prepared
        join = prepared.join
        lines = ["", "Exoplanets", ""]

        lines.append("catalogue rows (confirmed or controversial, with a host star):")
        for source in (ARCHIVE, EU, OEC):
            left_out = ", ".join(
                f"{reason} {join.counts[(source, reason)]:,}"
                for reason in LEFT_OUT
                if join.counts[(source, reason)]
            )
            lines.append(
                f"  {source}: {join.counts[(source, 'rows')]:,}"
                + (f" (left out: {left_out})" if left_out else "")
            )
        lines.append("join:")
        for source, base in ((EU, ARCHIVE), (OEC, f"{ARCHIVE} + {EU}")):
            rules = ", ".join(
                f"{rule} {join.counts[(source, rule)]:,}"
                for rule in ("SIMBAD object", "letter", "period", "designation")
            )
            lines.append(
                f"  {source} → {base}: {rules};"
                f" unmatched {join.counts[(source, 'unmatched')]:,}"
            )
        lines += _listed("ambiguous (a tie between candidates)", join.ambiguous)
        lines += _listed("contested (two rows want one planet)", join.contested)
        lines += _listed(
            "check: matched pairs with periods more than 5% apart", join.period_checks
        )
        lines += _listed(
            "check: unmatched planets with a same-period sibling on a shared host",
            join.missed,
        )
        lines += _listed(
            "check: unmatched planets with a same-letter sibling on a shared host",
            join.same_letter,
            limit=None,
        )

        classes = Counter(planets["class"].to_pylist())
        basis = Counter(planets["class_basis"].to_pylist())
        status = Counter(planets["status"].to_pylist())
        joined_by = Counter(
            "+".join(s for s in (ARCHIVE, EU, OEC) if s in r.joined.rows)
            for r in prepared.records
        )
        lines += [
            "",
            f"planets: {len(join.planets):,} joined, {planets.num_rows:,} in the table",
            "  excluded: "
            + (
                ", ".join(f"{k} {v:,}" for k, v in sorted(prepared.excluded.items()))
                or "none"
            ),
            "  by catalogues: "
            + ", ".join(f"{k} {v:,}" for k, v in joined_by.most_common()),
            "  by class: " + ", ".join(f"{k} {v:,}" for k, v in classes.most_common()),
            "  class basis: " + ", ".join(f"{k} {v:,}" for k, v in basis.most_common()),
            "  by status: " + ", ".join(f"{k} {v:,}" for k, v in status.most_common()),
        ]
        flags: Counter = Counter()
        for kind in ("assumed", "estimated", "computed"):
            for values in planets[kind].to_pylist():
                for value in values or ():
                    flags[(kind, value)] += 1
        for kind in ("assumed", "estimated", "computed"):
            found = sorted((v, n) for (k, v), n in flags.items() if k == kind)
            lines.append(
                f"  {kind}: " + (", ".join(f"{v} {n:,}" for v, n in found) or "none")
            )
        lines += _listed("planets whose star or system key got no ID", without_host)

        stars = prepared.stars
        host_list = prepared.hosts
        claims = hosts.claim_counts([stars.identities[i] for i in host_list])
        keys = set(prepared.systems.key.values())
        lines += [
            "",
            f"host stars: {len(host_list):,} ({len(keys):,} system keys)",
            "  reach the registry by: "
            + ", ".join(f"{k} {v:,}" for k, v in claims.most_common()),
            f"  with an ID: {len(identity_id):,}",
        ]
        gaia_counts = prepared.gaia_counts
        lines.append(
            "  unpositionable Gaia sources of hosts:"
            f" {gaia_counts['unpositionable Gaia sources of hosts']:,}, of which"
            f" {gaia_counts['of which a Hipparcos star holds']:,} a Hipparcos star"
            " holds; Gaia rows added: "
            f"{prepared.gaia_rows.num_rows:,}"
        )
        search = prepared.twins
        found = search.found
        lines.append(
            f"  stars without ids searched for a twin: {len(search.targets):,}"
            " ("
            + ", ".join(f"{k} {v:,}" for k, v in sorted(found.counts.items()))
            + ")"
        )
        lines += _listed(
            "hosts that claim their HIP number, since their DR3 source is"
            " unpositionable",
            prepared.by_hip,
            limit=None,
        )
        lines += _listed(
            "check: twins (hosts without ids that claim a registry star by position,"
            " parallax and magnitude)",
            found.listed(search.targets),
            limit=None,
        )
        lines += _listed(
            "check: stars joined to the star that holds their twin",
            search.joined,
            limit=None,
        )
        lines += _listed("lone candidates that are no twin", found.refused, limit=None)
        lines += _listed("star joins refused", stars.refused)
        lines += _listed("second names of one star in one catalogue", stars.duplicates)
        lines += _listed("ids on several stars, kept by none", stars.dropped_ids)
        lines += _listed("host rows of one star with several IDs", disagree)
        lines += _listed(
            "check: IDs that several stars of the join share (a position match)",
            shared_ids(identity_id, stars),
            limit=None,
        )
        lines += _listed(
            "check: planets of one system from other catalogues with one period,"
            " or of one host with one letter",
            doubles(planets),
            limit=None,
        )
        lines += _listed(
            "check: planets of other hosts with one designation",
            named_twice(planets),
            limit=None,
        )
        lines += self._host_kinds(registry, ingest, identity_id)

        named = prepared.named
        lines += [
            "",
            (
                f"NameExoWorlds: {len(named.planets):,} planet names and"
                f" {len(named.stars):,} star names placed of"
                f" {prepared.nameexoworlds:,}"
            ),
        ]
        lines += _listed("not placed", named.unplaced)

        events = assignment.events
        lines += [
            "",
            (
                f"planet numbers: {assignment.new:,} new, {assignment.kept:,} kept,"
                f" {assignment.moved:,} on a new host"
            ),
        ]
        for kind in (
            "found by letter and period",
            "merged",
            "host changed",
            "split",
            "retired",
            "retired hit",
            "not seen, kept (partial input)",
        ):
            lines += _listed(kind, events.get(kind, []), limit=None)
        if assignment.unreviewed or disagree:
            lines.append(
                "planet merges, host changes and splits: unreviewed, check them"
                " before publishing"
            )
        counts = {
            "planets": planets.num_rows,
            "hosts": len(identity_id),
            "new": assignment.new,
            "kept": assignment.kept,
            "moved": assignment.moved,
            **{
                kind.replace(" ", "_")
                .replace(",", "")
                .replace("(", "")
                .replace(")", ""): len(texts)
                for kind, texts in events.items()
            },
        }
        return "\n".join(lines) + "\n", counts

    def _host_kinds(
        self, registry: Registry, ingest: int, identity_id: dict[int, int]
    ) -> list[str]:
        """Hosts by how they got their ID, and how the export places them.

        One region at a time: the ID records of all regions do not fit in
        memory beside the ingest.
        """
        ids = np.array(sorted(set(identity_id.values())), np.int64)
        if not ids.size:
            return []
        names = {
            id_: self.prepared.stars.identities[index].name
            for index, id_ in identity_id.items()
        }
        directory = registry.tables_dir / POINT_SOURCE.slug / ingest_name(ingest)
        regions = region_of(cell_of(ids))
        known = 0
        kinds: Counter = Counter()
        placed: Counter = Counter()
        no_distance = []
        for region in np.unique(regions).tolist():
            here = ids[regions == region]
            old = registry.id_states([region]).find(here) >= 0
            known += int(old.sum())
            new = set(here[~old].tolist())
            path = region_file(directory, region)
            if not path.exists():
                continue
            rows = pq.read_table(path, columns=HOST_COLUMNS)
            rows = rows.filter(pc.is_in(rows["id"], pa.array(here)))
            where = placement(rows)
            for at, row in enumerate(rows.to_pylist()):
                fidelity = row["fidelity_v2"]
                flagged = fidelity is not None and fidelity < gaia.MIN_FIDELITY
                source = row["astrometry_source"]
                if row["id"] in new:
                    if source == gaia.GAIA_DR3.name and not where.positioned[at]:
                        kind = "Gaia, no 5σ parallax"
                    elif source == gaia.GAIA_DR3.name:
                        kind = "Gaia, flagged by fidelity" if flagged else "Gaia"
                    elif source in BY_NAME:
                        kind = f"literature star, {source}"
                    else:
                        kind = str(source)
                    kinds[kind] += 1
                if where.by_parallax[at]:
                    placed["5σ parallax"] += 1
                elif where.by_catalogue[at]:
                    placed["catalogue distance (flagged)"] += 1
                else:
                    placed["no distance"] += 1
                    no_distance.append(f"{row['id']} {names.get(row['id'], '')}")
        return [
            f"  IDs from earlier ingests: {known:,}",
            f"  IDs minted now: {ids.size - known:,}",
            "  minted by kind: "
            + (", ".join(f"{k} {v:,}" for k, v in sorted(kinds.items())) or "none"),
            "  placement: " + ", ".join(f"{k} {v:,}" for k, v in placed.most_common()),
            *_listed("hosts with no distance", no_distance),
        ]


HOST_COLUMNS = ["id", "astrometry_source", *COLUMNS]


def doubles(planets: pa.Table) -> list[str]:
    """Planets of one system from other catalogues with one period, or of one
    host with one letter.

    A period within 5% counts; a computed period does not. The system is the
    wider group, since one catalogue may put a planet on the other star.
    """
    by_system: dict[int, list[dict]] = {}
    columns = [
        "host",
        "system",
        "designation",
        "letter",
        "period",
        "cross_ids",
        "computed",
    ]
    for row in planets.select(columns).to_pylist():
        by_system.setdefault(row["system"], []).append(row)
    found = []
    for system, rows in by_system.items():
        for at, a in enumerate(rows):
            for b in rows[at + 1 :]:
                if _catalogues(a) & _catalogues(b):
                    continue
                same_letter = (
                    a["host"] == b["host"]
                    and a["letter"]
                    and a["letter"] == b["letter"]
                )
                pa_, pb = _measured_period(a), _measured_period(b)
                if same_letter or close(pa_, pb, CHECK_TOLERANCE):
                    found.append(f"{system}: {a['designation']} and {b['designation']}")
    return found


def one_system_per_host(
    host_of: dict[int, int], system_of: dict[int, int], rank: dict[int, tuple]
) -> tuple[dict[int, int], list[str]]:
    """The system of each planet, so that each host has one.

    Two star identities of the join can get one registry ID and sit in two
    systems. That ID is then one star of both, so the systems are one. The
    joined system takes the key of the lowest `rank` (system ID →
    `hosts.key_rank` of its key star), as `Systems.choose_keys` does.
    Returns the systems and the joins.
    """
    parent: dict[int, int] = {}

    def find(system: int) -> int:
        while parent.get(system, system) != system:
            system = parent[system]
        return system

    by_host: dict[int, set[int]] = defaultdict(set)
    for at, system in system_of.items():
        by_host[host_of[at]].add(system)
    joined = []
    for host, systems in sorted(by_host.items()):
        roots = sorted({find(system) for system in systems}, key=lambda s: (rank[s], s))
        for other in roots[1:]:
            parent[other] = roots[0]
        if len(roots) > 1:
            joined.append(
                f"host {host}: systems {', '.join(map(str, roots))}, key {roots[0]}"
            )
    return {at: find(system) for at, system in system_of.items()}, joined


def hosts_with_several_systems(planets: pa.Table) -> list[str]:
    """The hosts whose planets name more than one system."""
    systems: dict[int, set[int]] = defaultdict(set)
    for host, system in zip(
        planets["host"].to_pylist(), planets["system"].to_pylist(), strict=True
    ):
        systems[host].add(system)
    return [
        f"{host}: {sorted(found)}"
        for host, found in sorted(systems.items())
        if len(found) > 1
    ]


def named_twice(planets: pa.Table) -> list[str]:
    """Planets of other hosts that one designation names: the archive's, or
    an exoplanet.eu or OEC name, compared as `designation_key` does."""
    by_key: dict[str, set[tuple[int, str]]] = defaultdict(set)
    for row in planets.select(["host", "designation", "cross_ids"]).to_pylist():
        found = {row["designation"]} | {
            c["catalogue_id"] for c in row["cross_ids"] if c["catalogue"] in (EU, OEC)
        }
        for name in found:
            by_key[designation_key(name)].add((row["host"], row["designation"]))
    groups = {
        tuple(sorted(rows))
        for rows in by_key.values()
        if len({host for host, _ in rows}) > 1
    }
    return [
        ", ".join(f"{d} on {host}" for host, d in group) for group in sorted(groups)
    ]


def _catalogues(row: dict) -> set[str]:
    return {c["catalogue"] for c in row["cross_ids"] if c["catalogue"] != "iau"}


def _measured_period(row: dict) -> float | None:
    return None if "period" in (row["computed"] or ()) else row["period"]


def shared_ids(identity_id: dict[int, int], stars: Stars) -> list[str]:
    """IDs that the engine gave to several identities, with their names."""
    by_id: dict[int, list[str]] = {}
    for index, id_ in sorted(identity_id.items()):
        identity = stars.identities[index]
        by_id.setdefault(id_, []).append(
            f"{identity.name} ({identity.first.catalogue})"
        )
    return [
        f"{id_}: {', '.join(names)}" for id_, names in by_id.items() if len(names) > 1
    ]


def _catalogue_ids(record: Record) -> list[dict]:
    """The catalogue ids that the Planets part links: the three catalogues."""
    cross_ids = record.values["cross_ids"]
    assert isinstance(cross_ids, list)
    return [c for c in cross_ids if c["catalogue"] in (ARCHIVE, EU, OEC)]


def _previous(registry: Registry) -> numbering.Previous:
    """Letters and periods of the current planets table, by number."""
    previous = numbering.Previous()
    for region in registry.table_regions(table.SLUG):
        rows = registry.read_table(
            table.SLUG, region, ["host", "number", "letter", "period"]
        )
        if rows is None:
            continue
        for row in rows.to_pylist():
            number = (row["host"], row["number"])
            previous.letter[number] = row["letter"]
            previous.period[number] = row["period"]
    return previous


def _listed(title: str, items: list[str], limit: int | None = EXAMPLES) -> list[str]:
    if not items:
        return []
    shown = items if limit is None else items[:limit]
    more = "" if len(shown) == len(items) else f" (first {len(shown)})"
    return [f"{title}: {len(items):,}{more}"] + [f"  {item}" for item in shown]
