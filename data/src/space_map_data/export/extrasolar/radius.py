"""The radius of a star, by one source order.

The Metadata row of each point and held star takes its radius and the source
of it from `star_radius`. The Metadata tiles save these radii in the export's
scratch (`save`), and the planet files read their hosts' radii from there
(`load`). Other parts of the export read the Metadata rows. The order:
1. a measurement (`measured_radius`): a paper's radius, then JMDC's angular
   diameter at the star's distance. A held star with no paper of its own
   takes the measurement of its point when it dominates the point's light
   (`measuring_points`);
2. the radius of a planet host in the exoplanet catalogues, each catalogue
   in its order;
3. Gaia DR3 FLAME, then FLAME on GSP-Spec, then GSP-Phot.
A point that holds several stars stands for its first member when that held
star dominates its light (`led_points`), so it has no radius of its own.
Else it keeps its own, as no one star can take it: a point whose light can
blend draws at the size it was measured at.
A host of a transiting planet (`transit_hosts`) takes the catalogue's radius
before a measurement. The catalogue derives the planet's radius from that
star radius, so the two stay consistent.
Gaia fits a normal star, so its radii do not count for a compact star: what
it sees of a pulsar is mostly the companion. The exoplanet catalogues give a
pulsar the radius of a model neutron star, so theirs do not count for a
neutron star. A star with none of these has no radius. A radius keeps the
digits of its source, so it is rounded only once, where it is shown.
"""

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from pyarrow import ipc

from space_map_data.extrasolar import families
from space_map_data.extrasolar.exoplanets.table import SLUG as PLANETS
from space_map_data.extrasolar.ids import cell_of
from space_map_data.extrasolar.measured_radius import MEASURED_COLUMNS, measured_radius
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sky import region_of
from space_map_data.extrasolar.sources.literature import LITERATURE
from space_map_data.utils.arrays import floats

FLAME = "gaia-dr3-flame"
FLAME_SPEC = "gaia-dr3-flame-spec"
GSPPHOT = "gaia-dr3-gspphot"
COMPACT = families.BIT["neutron-star"] | families.BIT["white-dwarf"]
NEUTRON_STAR = families.BIT["neutron-star"]

# The Point source columns that `star_radius` reads.
COLUMNS = (
    *MEASURED_COLUMNS,
    "host_radius",
    "host_radius_source",
    "radius_flame",
    "radius_flame_spec",
    "radius_gspphot",
)
# The planets table columns that `transit_hosts` reads.
TRANSIT_COLUMNS = ("host", "transits")
FIELDS = (
    pa.field("radius", pa.float32()),
    pa.field("radius_source", pa.string()),
)


def host_radius(rows: pa.Table, masks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The planet catalogues' radius of each row of `rows`, NaN for a neutron
    star, and its source. `rows` has `host_radius` and `host_radius_source`,
    `masks` are the families of each row."""
    value = np.where(masks & NEUTRON_STAR, np.nan, floats(rows, "host_radius"))
    return value, rows["host_radius_source"].to_numpy(zero_copy_only=False)


def star_radius(
    rows: pa.Table, masks: np.ndarray, transits: np.ndarray
) -> tuple[pa.Array, pa.Array]:
    """The radius of each row of COLUMNS in nominal solar radii, and its
    source, both null where none. `masks` are the published and estimated
    families of each row, `transits` is true for a host of a transiting
    planet."""
    n = rows.num_rows
    radius = np.full(n, np.nan)
    source = np.full(n, None, object)

    def fill(values: np.ndarray, names: np.ndarray | str) -> None:
        take = np.isnan(radius) & np.isfinite(values) & (values > 0)
        radius[take] = values[take]
        source[take] = names[take] if isinstance(names, np.ndarray) else names

    host, catalogue = host_radius(rows, masks)
    fill(np.where(transits, host, np.nan), catalogue)
    fill(*measured_radius(rows))
    fill(host, catalogue)
    compact = (masks & COMPACT) != 0
    fill(np.where(compact, np.nan, floats(rows, "radius_flame")), FLAME)
    fill(np.where(compact, np.nan, floats(rows, "radius_flame_spec")), FLAME_SPEC)
    fill(np.where(compact, np.nan, floats(rows, "radius_gspphot")), GSPPHOT)
    return (
        pa.array(radius, pa.float32(), from_pandas=True),
        pa.array(source, pa.string()),
    )


def transit_hosts(registry: Registry, regions: Iterable[int]) -> pa.Array:
    """The hosts in `regions` of a planet that the archive says transits."""
    parts = [
        registry.read_table(PLANETS, region, list(TRANSIT_COLUMNS))
        for region in regions
    ]
    found = [part for part in parts if part is not None]
    if not found:
        return pa.array([], pa.int64())
    planets = pa.concat_tables(found)
    return pc.unique(planets["host"].filter(planets["transits"].fill_null(False)))


def _paper(star: pa.Array) -> pa.Array:
    """Whether a paper gives each System `star` its radius."""
    paper = pc.equal(pc.struct_field(star, "radius_source"), LITERATURE.name)
    return paper.fill_null(False)


def measuring_points(held: pa.Table) -> pa.Array:
    """The point whose measurement each `held` star takes, else null: its
    parent, when it dominates the point's light (`star.dominant`) and no
    paper gives its own radius. `held` has `parent` and `star`."""
    star = held["star"].combine_chunks()
    takes = pc.and_(
        pc.struct_field(star, "dominant").fill_null(False), pc.invert(_paper(star))
    )
    return pc.if_else(
        takes, held["parent"].combine_chunks(), pa.scalar(None, pa.int64())
    )


def led_points(held: pa.Table) -> pa.Array:
    """The points that a `held` star dominates (`star.dominant`): each one
    stands for that star. `held` has `parent` and `star`."""
    star = held["star"].combine_chunks()
    dominant = pc.struct_field(star, "dominant").fill_null(False)
    return pc.unique(held["parent"].combine_chunks().filter(dominant).drop_null())


def held_columns(held: pa.Table, points: pa.Table) -> dict[str, pa.Array]:
    """COLUMNS of held stars from their System `star` values: a paper's
    `radius` is a measurement, and `host_radius` is a host's. A star takes
    the measurement of its point (`measuring_points`) from `points`, which
    have `id` and MEASURED_COLUMNS. `held` has `parent` and `star`."""
    star = held["star"].combine_chunks()
    paper = _paper(star)
    by = pc.struct_field(star, "host_radius_source")
    at = pc.index_in(measuring_points(held), value_set=points["id"])
    out = {
        name: points[name].take(at).cast(points.schema.field(name).type)
        for name in MEASURED_COLUMNS
    }
    value = pc.struct_field(star, "radius")
    out["radius_literature"] = pc.coalesce(
        pc.if_else(paper, value, None).cast(pa.float32()),
        out["radius_literature"].cast(pa.float32()),
    )
    return out | {
        "host_radius": pc.struct_field(star, "host_radius"),
        "host_radius_source": by,
    }


def scratch_file(scratch: Path, region: int) -> Path:
    return scratch / "radius" / f"{region:03d}.arrow"


def save(scratch: Path, regions: Iterable[int], rows: pa.Table) -> None:
    """The `id` and FIELDS of the Metadata `rows` with a radius, one file
    for each of `regions`."""
    names = [field.name for field in FIELDS]
    sized = rows.select(["id", *names]).filter(rows["radius"].is_valid())
    region = region_of(cell_of(sized["id"].to_numpy()))
    for number in regions:
        path = scratch_file(scratch, number)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = sized.filter(pa.array(region == number))
        with ipc.new_file(path, part.schema) as writer:
            writer.write_table(part)


def load(scratch: Path, region: int) -> dict[int, tuple[float, str]]:
    """The radius and its source of each star of `region` with a radius
    (`save`)."""
    with ipc.open_file(scratch_file(scratch, region)) as reader:
        table = reader.read_all()
    return dict(
        zip(
            table["id"].to_pylist(),
            zip(
                table["radius"].to_pylist(),
                table["radius_source"].to_pylist(),
                strict=True,
            ),
            strict=True,
        )
    )
