"""The star systems in a small ingest: passes, IDs, links and the report."""

import dataclasses
from collections import Counter

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from space_map_data.export.extrasolar import systems as export_systems
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import IngestRun, Source
from space_map_data.extrasolar.ids import cell_of, table_of
from space_map_data.extrasolar.match import SYSTEM_KIND, Pairs, PositionMatcher
from space_map_data.extrasolar.placement import placement
from space_map_data.extrasolar.registry import IdStates, Registry
from space_map_data.extrasolar.sources import wikidata
from space_map_data.extrasolar.sources.distances import REYLE_2021
from space_map_data.extrasolar.sources.gaia import GAIA_DR3
from space_map_data.extrasolar.sources.hipparcos import HIPPARCOS
from space_map_data.extrasolar.sources.simbad import SIMBAD, SimbadList, SimbadObject
from space_map_data.extrasolar.systems import ingest as systems_ingest
from space_map_data.extrasolar.systems.msc import msc_nodes
from space_map_data.extrasolar.systems.pairs import el_badry_pairs, orbit_pairs
from space_map_data.extrasolar.systems.planets import PLANETS_INPUT
from space_map_data.extrasolar.systems.prepare import Inputs
from space_map_data.extrasolar.systems.registry import SOURCE_LEVEL, SOURCE_PIXEL_SHIFT
from space_map_data.extrasolar.systems.report import target_keys
from space_map_data.extrasolar.systems.simbad import SimbadIndex, read_simbad
from space_map_data.extrasolar.tables import (
    CROSS_ID,
    METADATA,
    POINT_SOURCE,
    SYSTEM,
    SYSTEM_TABLE,
    merge_by_source_order,
)
from tests.extrasolar.systems_fakes import (
    FakeResolver,
    msc_comp,
    msc_pair,
    simbad_index,
    simbad_object,
    wds_catalogue,
    wds_component,
    wds_pair,
)

# HIP number → ra, dec, G, parallax and its error (mas).
STARS = {
    "71683": (219.902, -60.834, 0.0, 754.8, 4.1),
    "71681": (219.896, -60.8375, 1.3, 796.9, 25.9),
    "70890": (217.43, -62.68, 8.9, 768.1, 1.0),
    # A pair of the MSC: A holds Aa and Ab, B has no parallax.
    "1001": (10.0, 10.0, 6.0, 20.0, 0.5),
    "1002": (10.0015, 10.0, 7.0, None, None),
    # A pair that the WDS gives by position only.
    "1003": (30.0, 5.0, 8.0, 10.0, 0.2),
    "1004": (30.001, 5.0, 9.0, 10.0, 0.2),
}
# The 10 pc sample's distance of α Cen A and B: more precise than Hipparcos.
REYLE = {"71683": 1.3466, "71681": 1.3466}
P_TYPE = "P-type"


def rows_for(run: IngestRun, source: Source, values: dict[str, list]) -> pa.Table:
    """Pass rows with every column of `source`, null where not given."""
    n = len(next(iter(values.values())))
    fields = {f.name: f for f in run._source_fields(source)}
    columns = {}
    for name in [*fields, *values]:
        if name in values:
            kind = fields[name].type if name in fields else None
            columns[name] = pa.array(values[name], kind)
        else:
            columns[name] = pa.nulls(n, fields[name].type)
    return pa.table(columns)


def hipparcos_rows(run: IngestRun, stars: dict = STARS) -> pa.Table:
    hips = list(stars)
    ra, dec, mag, plx, err = (list(v) for v in zip(*stars.values()))
    return rows_for(
        run,
        HIPPARCOS,
        {
            "catalogue_id": hips,
            "mint": [True] * len(hips),
            "match_ra": ra,
            "match_dec": dec,
            "match_mag": mag,
            "match_error": [0.01] * len(hips),
            "ra": ra,
            "dec": dec,
            "parallax": plx,
            "parallax_error": err,
            "epoch": [2016.0] * len(hips),
            "class": ["star"] * len(hips),
            "name": [f"HIP {hip}" for hip in hips],
        },
    )


def reyle_rows(run: IngestRun) -> pa.Table:
    hips = list(REYLE)
    return rows_for(
        run,
        REYLE_2021,
        {
            "catalogue_id": [f"GJ {hip}" for hip in hips],
            "mint": [False] * len(hips),
            "match_ra": [STARS[h][0] for h in hips],
            "match_dec": [STARS[h][1] for h in hips],
            "claims": [
                [dict(zip(CROSS_ID.names, ("hip", "2007", hip)))] for hip in hips
            ],
            "distance": [REYLE[h] for h in hips],
            "distance_lower": [REYLE[h] - 0.0004 for h in hips],
            "distance_upper": [REYLE[h] + 0.0004 for h in hips],
            "distance_method": ["parallax"] * len(hips),
        },
    )


WDS_SYSTEMS = {"02000+0500": [wds_pair("A", "B", 3.6, notes="V", mag1=8.3, mag2=9.3)]}
WDS_COMPONENTS = {
    ("02000+0500", "A"): wds_component(ra=30.0, dec=5.0),
    ("02000+0500", "B"): wds_component(ra=30.001, dec=5.0),
}


def inputs(
    planets: pa.Table,
    wds_systems: dict = WDS_SYSTEMS,
    wds_components: dict = WDS_COMPONENTS,
    el_badry: pa.Table | None = None,
    orbits: pa.Table | None = None,
) -> tuple[Inputs, SimbadIndex]:
    comp = [
        msc_comp("14396-6050", "A", HIP=71683),
        msc_comp("14396-6050", "B", HIP=71681),
        msc_comp("14396-6050", "C", HIP=70890),
        msc_comp("00400+1000", "A", HIP=1001),
        msc_comp("00400+1000", "B", HIP=1002),
    ]
    pairs = [
        msc_pair("14396-6050", "AB", "C", "*", Sep=131.0, Sunit="'"),
        msc_pair("14396-6050", "A", "B", "AB", Sep=17.5, Sunit='"'),
        msc_pair("00400+1000", "A", "B", "*", Sep=5.3, Sunit='"'),
        msc_pair("00400+1000", "Aa", "Ab", "A", Sep=8.0, Sunit="m", P=10, Punit="d"),
    ]
    index = simbad_index(
        [
            simbad_object(1, "* alf Cen", 219.9, -60.83, otype="SB*"),
            simbad_object(2, "* alf Cen A", 219.902, -60.834, v=0.01, hip="71683"),
            simbad_object(3, "* alf Cen B", 219.896, -60.8375, v=1.33, hip="71681"),
        ],
        [(1, 2), (1, 3)],
    )
    return (
        Inputs(
            msc=msc_nodes(comp, pairs, []),
            simbad=read_simbad(index.stars),
            simbad_index=index,
            wds=wds_catalogue(wds_systems, wds_components),
            el_badry=el_badry,
            orbits=orbits,
            planets=planets,
        ),
        index,
    )


def ingest(
    root,
    stars: dict = STARS,
    host: str = "1002",
    simbad: dict | None = None,
    gaia: dict | None = None,
    **more,
) -> tuple[systems_ingest.SystemsExtension, str]:
    """An ingest of `stars`, with a P-type planet of `host`, the SIMBAD rows
    `simbad` (oid → ra, dec, V) and the Gaia DR3 rows `gaia`. `more` goes to
    `inputs`."""
    with IngestRun.start(root, root / "backup") as run:
        if gaia:
            run.add(GAIA_DR3, [gaia_rows(run, gaia)])
        run.add(HIPPARCOS, [hipparcos_rows(run, stars)])
        run.add(REYLE_2021, [reyle_rows(run)])
        if simbad:
            run.add(SIMBAD, [simbad_rows(run, simbad)])
        hip = run.row_keys(HIPPARCOS.name)
        key_of = dict(zip(hip["catalogue_id"].to_pylist(), hip["key"].to_pylist()))
        planets = pa.table(
            {
                "host": [key_of[host]],
                "number": [0],
                "designation": ["P2 b"],
                "class": ["planet"],
                "mass": [1.0],
                "period": [400.0],
                "binary_type": [P_TYPE],
                "star_ids": [None],
            },
            schema=PLANETS_INPUT,
        )
        found, index = inputs(planets, **more)
        extension = systems_ingest.add_systems(run, found, index, True)
        result = run.commit()
    return extension, result.report


def gaia_rows(run: IngestRun, sources: dict) -> pa.Table:
    """Gaia DR3 rows of source_id → ra, dec, G, parallax and fidelity. A row
    under the fidelity cut does not mint."""
    ids = [str(source) for source in sources]
    ra, dec, mag, plx, fidelity = (list(v) for v in zip(*sources.values()))
    return rows_for(
        run,
        GAIA_DR3,
        {
            "catalogue_id": ids,
            "mint": [f >= 0.5 for f in fidelity],
            "match_ra": ra,
            "match_dec": dec,
            "match_mag": mag,
            "match_error": [0.001] * len(ids),
            "ra": ra,
            "dec": dec,
            "parallax": plx,
            "parallax_error": [0.1] * len(ids),
            "fidelity_v2": fidelity,
            "epoch": [2016.0] * len(ids),
            "class": ["star"] * len(ids),
            "name": [f"Gaia DR3 {source}" for source in ids],
        },
    )


def simbad_rows(run: IngestRun, objects: dict) -> pa.Table:
    oids = list(objects)
    ra, dec, mag = (list(v) for v in zip(*objects.values()))
    return rows_for(
        run,
        SIMBAD,
        {
            "catalogue_id": oids,
            "mint": [True] * len(oids),
            "match_ra": ra,
            "match_dec": dec,
            "match_mag": mag,
            "match_error": [0.01] * len(oids),
            "ra": ra,
            "dec": dec,
            "epoch": [2016.0] * len(oids),
            "class": ["star"] * len(oids),
        },
    )


def table(registry: Registry, slug: str) -> pa.Table:
    parts = [
        registry.read_table(slug, region) for region in registry.table_regions(slug)
    ]
    return pa.concat_tables([p for p in parts if p is not None])


def ids_of(registry: Registry, hips: list[str]) -> list[int]:
    return [int(i) for i in registry.lookup("hip", "2007", hips)]


@pytest.fixture
def registry_after_two(tmp_path):
    root = tmp_path / "registry"
    first, report = ingest(root)
    registry = Registry(root)
    systems_one = table(registry, SYSTEM.slug)
    second, report_two = ingest(root)
    return Registry(root), systems_one, report, report_two, first, second


class TestSystemsIngest:
    """α Cen, an MSC pair with an inner pair, and a WDS pair by position."""

    def test_system_ids_and_rows(self, registry_after_two):
        registry, _, report, _, _, _ = registry_after_two
        system = table(registry, SYSTEM.slug)
        resolved = system.filter(pc.invert(system["point"]))
        # α Cen, α Cen AB, the MSC pair and the WDS pair.
        assert resolved.num_rows == 4
        assert set(table_of(resolved["id"].to_numpy()).tolist()) == {3}
        # A point that holds Aa and Ab keeps its own ID.
        points = system.filter(system["point"])
        (p1,) = ids_of(registry, ["1001"])
        assert points["id"].to_pylist() == [p1]
        # Each resolved system is in the cell of its primary.
        for row in resolved.to_pylist():
            primary = system_primary_cell(row)
            assert cell_of(row["id"]) == primary
        assert "Systems at the commit" in report
        assert "system IDs: minted 4, kept 0" in report

    def test_previous_systems_reads_only_system_ids(
        self, registry_after_two, monkeypatch
    ):
        registry = registry_after_two[0]
        seen: list[pa.Table] = []
        build = IdStates.build

        def spy(records: pa.Table) -> IdStates:
            seen.append(records)
            return build(records)

        monkeypatch.setattr(IdStates, "build", spy)
        system = table(registry, SYSTEM.slug)
        resolved = system.filter(pc.invert(system["point"]))["id"].to_pylist()
        found = systems_ingest._previous_systems(registry)
        assert found.tolist() == sorted(resolved)
        records = pa.concat_tables(seen)
        assert set(table_of(records["id"].to_numpy()).tolist()) == {SYSTEM_TABLE}

    def test_ids_hold_across_ingests(self, registry_after_two):
        registry, first, _, report_two, _, _ = registry_after_two
        second = table(registry, SYSTEM.slug)
        assert sorted(second["id"].to_pylist()) == sorted(first["id"].to_pylist())
        assert "system IDs: minted 0, kept 4, retired or merged 0" in report_two

    def test_links_and_metadata(self, registry_after_two):
        registry = registry_after_two[0]
        system = table(registry, SYSTEM.slug)
        meta = table(registry, METADATA.slug)
        by_id = {row["id"]: row for row in system.to_pylist()}
        a, b, c = ids_of(registry, ["71683", "71681", "70890"])
        root = next(
            row
            for row in by_id.values()
            if row["parent"] is None
            and row["stars"] == 3
            and any(m["id"] == c for m in row["members"])
        )
        pair = by_id[next(m["id"] for m in root["members"] if m["kind"] == "system")]
        assert {m["id"] for m in pair["members"]} == {a, b}
        assert pair["root"] == root["id"] and pair["parent"] == root["id"]
        assert pair["primary"] == a
        assert [node["id"] for node in root["tree"]] == sorted([root["id"], pair["id"]])
        assert pair["tree"] is None
        rows = {row["id"]: row for row in meta.to_pylist()}
        assert rows[a]["system"] == root["id"] and rows[c]["system"] == root["id"]
        assert rows[pair["id"]]["system"] == root["id"]
        assert rows[root["id"]]["system"] is None
        assert rows[root["id"]]["class"] == "multiple star"
        assert rows[pair["id"]]["class"] == "binary star"
        assert rows[pair["id"]]["name"] == "Alpha Centauri"
        assert rows[a]["class"] == "star"
        cross = {
            (x["catalogue"], x["release"], x["catalogue_id"])
            for x in rows[pair["id"]]["cross_ids"]
        }
        # The system's claims, apart from the ids of the objects.
        assert ("star-system", "msc", "14396-6050 AB") in cross
        assert ("star-system", "simbad", "1") in cross
        assert not any(c == "simbad" for c, _, _ in cross)
        # The System bit of the mask.
        assert rows[pair["id"]]["mask"] & (1 << 3)
        (p1,) = ids_of(registry, ["1001"])
        assert rows[p1]["class"] == "binary star"

    def test_class_changes_in_the_report(self, registry_after_two):
        report = registry_after_two[2]
        assert "class changes:\n  star → binary star: 1\n" in report

    def test_system_distance_and_the_group_rule(self, registry_after_two):
        registry = registry_after_two[0]
        point = table(registry, POINT_SOURCE.slug)
        rows = {row["id"]: row for row in point.to_pylist()}
        a, b, p2 = ids_of(registry, ["71683", "71681", "1002"])
        # α Cen A and B keep the distance of the group rule.
        for star in (a, b):
            assert rows[star]["distance_source"] == REYLE_2021.name
        placed = placement(point)
        at = {row: i for i, row in enumerate(point["id"].to_pylist())}
        assert placed.by_group[at[a]] and placed.by_group[at[b]]
        # B of the MSC pair has no parallax: it takes 50 pc from A.
        assert rows[p2]["distance_source"] == "star-systems"
        assert rows[p2]["distance_method"] == "system"
        assert rows[p2]["distance"] == pytest.approx(50.0)
        assert placed.by_group[at[p2]]

    def test_wds_components_match_by_position(self, registry_after_two):
        registry = registry_after_two[0]
        found = registry.lookup("wds", "component", ["02000+0500 A", "02000+0500 B"])
        assert found.tolist() == ids_of(registry, ["1003", "1004"])

    def test_circumbinary_host(self, registry_after_two):
        registry, _, _, _, _, second = registry_after_two
        system = table(registry, SYSTEM.slug)
        (p2,) = ids_of(registry, ["1002"])
        pair = next(
            row["id"]
            for row in system.to_pylist()
            if any(m["id"] == p2 for m in row["members"])
        )
        assert second.host(0) == pair
        assert second.root(p2) == pair
        assert table_of(pair) == 3


class TestHostInNoTree:
    """A P-type host that no tree lists is a point that holds two stars."""

    def test_the_host_has_a_system_row(self, tmp_path):
        root = tmp_path / "registry"
        stars = STARS | {"2001": (50.0, 20.0, 9.0, 15.0, 0.2)}
        extension, _ = ingest(root, stars, host="2001")
        registry = Registry(root)
        (lone,) = ids_of(registry, ["2001"])
        assert lone in table(registry, SYSTEM.slug)["id"].to_pylist()
        assert extension.host(0) == lone


def source_id(ra: float, dec: float, n: int) -> int:
    """A Gaia DR3 source_id in the HEALPix pixel of this position."""
    pixel = int(sky.cells(np.array([ra]), np.array([dec]), SOURCE_LEVEL)[0])
    return (pixel << SOURCE_PIXEL_SHIFT) + n


# Gaia DR3 rows: ra, dec, G, parallax, fidelity. A row under the fidelity cut
# does not mint, and no minting row here claims it.
GAIA_ROWS = {
    # An El-Badry pair of a minted source and one that is not.
    "minted": (60.0, 10.0, 10.0, 10.0, 0.9),
    "pair": (60.002, 10.0, 12.0, 10.0, 0.1),
    # B of a WDS pair, with a Gaia orbit.
    "orbit": (75.01, 25.0, 11.0, 8.0, 0.1),
    # Where the position pass finds B of another WDS pair.
    "matched": (90.01, 30.0, 11.0, 5.0, 0.1),
}
GAIA = {name: source_id(*row[:2], n) for n, (name, row) in enumerate(GAIA_ROWS.items())}


def with_unminted() -> dict:
    """The ingest's arguments for objects that the commit does not mint."""
    systems = WDS_SYSTEMS | {
        "05000+2500": [wds_pair("A", "B", 32.6, notes="V", mag1=8.3, mag2=11.0)],
        "06000+3000": [
            wds_pair("A", "B", 31.2, notes="V", mag1=8.3, mag2=11.0),
            wds_pair("A", "C", 72.0, notes="V", mag1=8.3, mag2=12.0),
        ],
    }
    components = WDS_COMPONENTS | {
        ("05000+2500", "A"): wds_component(ra=75.0, dec=25.0),
        ("05000+2500", "B"): wds_component(source_id=GAIA["orbit"], ra=75.01, dec=25.0),
        ("06000+3000", "A"): wds_component(ra=90.0, dec=30.0),
        # The position pass matches B to 5004 and C to nothing.
        ("06000+3000", "B"): wds_component(ra=90.01, dec=30.0),
        ("06000+3000", "C"): wds_component(ra=90.0, dec=30.02),
    }
    el_badry = el_badry_pairs(
        pa.table(
            {
                "source_id1": [GAIA["minted"]],
                "source_id2": [GAIA["pair"]],
                "ra1": [60.0],
                "dec1": [10.0],
                "ra2": [60.002],
                "dec2": [10.0],
                "parallax1": [10.0],
                "parallax2": [10.0],
                "phot_g_mean_mag1": [10.0],
                "phot_g_mean_mag2": [12.0],
                "sep_arcsec": [7.09],
                "R_chance_align": [1e-6],
                "binary_type": ["MSMS"],
            }
        )
    )
    orbits = orbit_pairs(
        pa.table(
            {
                "source_id": [GAIA["orbit"]],
                "nss_solution_type": ["SB1"],
                "period": [10.0],
                "eccentricity": [0.1],
                "m1": [1.0],
                "m2": [0.5],
            }
        )
    )
    return {
        "stars": STARS
        | {"1008": (75.0, 25.0, 8.0, 8.0, 0.2), "1009": (90.0, 30.0, 8.0, 5.0, 0.2)},
        "gaia": {GAIA[name]: row for name, row in GAIA_ROWS.items()},
        "wds_systems": systems,
        "wds_components": components,
        "el_badry": el_badry,
        "orbits": orbits,
    }


@pytest.fixture
def unminted_two(tmp_path):
    root = tmp_path / "registry"
    _, report = ingest(root, **with_unminted())
    first = table(Registry(root), SYSTEM.slug)
    _, report_two = ingest(root, **with_unminted())
    return Registry(root), first, report, report_two


def node_of(system: pa.Table, member: int) -> dict:
    """The System row that lists `member`."""
    return next(
        row
        for row in system.to_pylist()
        if any(m["id"] == member for m in row["members"])
    )


def entry_ids(member: dict) -> set[tuple[str, str, str]]:
    return {
        (x["catalogue"], x["release"], x["catalogue_id"]) for x in member["ids"] or []
    }


class TestUnmintedObjects:
    """A star whose object the commit does not mint is an entry, and a point
    whose object it does not mint is no node."""

    def test_every_star_and_node_has_an_id(self, unminted_two):
        registry, _, report, report_two = unminted_two
        system = table(registry, SYSTEM.slug)
        members = [m for row in system.to_pylist() for m in row["members"]]
        assert all(m["id"] is not None for m in members if m["kind"] != "entry")
        assert not export_systems.Systems.of(system).check()
        assert "rows with no ID 0\n" in report and "rows with no ID 0\n" in report_two

    def test_el_badry_pair_with_an_unminted_star(self, unminted_two):
        registry = unminted_two[0]
        assert registry.lookup("gaia", "dr3", [str(GAIA["pair"])]).tolist() == [0]
        (star,) = registry.lookup("gaia", "dr3", [str(GAIA["minted"])]).tolist()
        node = node_of(table(registry, SYSTEM.slug), star)
        assert sorted(m["kind"] for m in node["members"]) == ["entry", "star"]
        (entry,) = [m for m in node["members"] if m["kind"] == "entry"]
        assert ("gaia", "dr3", str(GAIA["pair"])) in entry_ids(entry)
        meta = {row["id"]: row for row in table(registry, METADATA.slug).to_pylist()}
        assert meta[star]["system"] == node["id"]
        assert meta[star]["class"] == "star"

    def test_wds_components_of_no_minted_object(self, unminted_two):
        registry, _, report, _ = unminted_two
        (a,) = ids_of(registry, ["1009"])
        node = node_of(table(registry, SYSTEM.slug), a)
        entries = sorted(m["letter"] for m in node["members"] if m["kind"] == "entry")
        # B matches a Gaia row that gets no ID, and C matches nothing.
        assert entries == ["B", "C"]
        found = registry.lookup("wds", "component", ["06000+3000 B", "06000+3000 C"])
        assert found.tolist() == [0, 0]
        # Two minted objects of the first pair, and A here.
        assert "WDS components matched by position 4," in report

    def test_point_whose_object_is_not_minted(self, unminted_two):
        registry, _, report, _ = unminted_two
        (a,) = ids_of(registry, ["1008"])
        system = table(registry, SYSTEM.slug)
        node = node_of(system, a)
        # B holds a Gaia orbit, but its object gets no ID: B is an entry.
        (entry,) = [m for m in node["members"] if m["kind"] == "entry"]
        assert ("gaia", "dr3", str(GAIA["orbit"])) in entry_ids(entry)
        assert sorted(m["kind"] for m in node["members"]) == ["entry", "star"]
        assert system.filter(system["point"])["id"].to_pylist() == ids_of(
            registry, ["1001"]
        )
        assert "orbits of no object 1" in report

    def test_counts(self, unminted_two):
        report = unminted_two[2]
        assert "pass: entries whose id reaches an object that is not minted 3\n" in (
            report
        )
        # B of both new WDS pairs goes to the position pass.
        assert "ids of objects that are not minted wds/id 2," in report
        # The pair's and the orbit's source, each once, though the builder
        # looks up one of them twice.
        assert "ids of objects that are not minted gaia/dr3 2," in report

    def test_second_ingest_keeps_the_ids_and_the_entries(self, unminted_two):
        registry, first, _, report_two = unminted_two
        second = table(registry, SYSTEM.slug)
        assert sorted(second["id"].to_pylist()) == sorted(first["id"].to_pylist())
        assert "system IDs: minted 0, kept 7, retired or merged 0" in report_two

        lost = {str(GAIA["pair"]), str(GAIA["orbit"]), "06000+3000 B"}

        def entries(system: pa.Table) -> list[tuple[int, str]]:
            """The entries of the stars of objects that get no ID."""
            return sorted(
                (row["id"], m["letter"] or "")
                for row in system.to_pylist()
                for m in row["members"]
                if m["kind"] == "entry"
                and any(x["catalogue_id"] in lost for x in m["ids"] or [])
            )

        assert len(entries(first)) == 3
        assert entries(second) == entries(first)


class TestUnmintedKeys:
    """The engine's objects that no minting row made or joined."""

    def test_a_minting_row_joins_one(self, tmp_path):
        with IngestRun.start(tmp_path / "registry", tmp_path / "backup") as run:
            names = ("pair", "orbit")
            run.add(GAIA_DR3, [gaia_rows(run, {GAIA[n]: GAIA_ROWS[n] for n in names})])
            # A Hipparcos star on the first source joins it.
            star = {"3001": (*GAIA_ROWS["pair"][:4], 0.2)}
            run.add(HIPPARCOS, [hipparcos_rows(run, star)])
            rows = run.row_keys(GAIA_DR3.name)
            key = dict(zip(rows["catalogue_id"].to_pylist(), rows["key"].to_pylist()))
            assert run.unminted().tolist() == [key[str(GAIA["orbit"])]]


class TestPointsWithNoClaim:
    """A point that the run gives nothing to claim stops the step. The
    resolver gives each key a claim, so such a point is a fault of the
    resolver."""

    def test_it_raises(self, tmp_path, monkeypatch):
        claims = systems_ingest.RunResolver.claims

        def without(resolver, keys):
            found = claims(resolver, keys)
            rows = resolver.run.row_keys(HIPPARCOS.name)
            hips = dict(zip(rows["catalogue_id"].to_pylist(), rows["key"].to_pylist()))
            drop = pc.equal(found["key"], hips["1004"])
            for name in CROSS_ID.names:
                at = found.schema.get_field_index(name)
                none = pa.scalar(None, found.schema.field(name).type)
                found = found.set_column(at, name, pc.if_else(drop, none, found[name]))
            return found

        monkeypatch.setattr(systems_ingest.RunResolver, "claims", without)
        with pytest.raises(ValueError, match="1 points have no claim"):
            ingest(tmp_path / "registry")


class TestReportTargets:
    """A target that names a SIMBAD system object finds its primary row."""

    def test_acrux(self):
        index = simbad_index(
            [
                simbad_object(1, "* alf Cru", 186.65, -63.1),
                simbad_object(2, "* alf01 Cru", 186.65, -63.1, v=1.3, hip="60718"),
                simbad_object(3, "* alf02 Cru", 186.65, -63.1, v=1.7),
            ],
            [(1, 2), (1, 3)],
        )
        resolver = FakeResolver({("simbad", "oid", "2"): 7}, [])
        assert dict(target_keys(index, resolver))["Acrux"] == 7


class TestRunReads:
    """The step reads each region's links once and the pass rows once."""

    def test_reads(self, tmp_path, monkeypatch):
        links: Counter = Counter()
        scans: list[int] = []
        read_links, read_rows = IngestRun.links, IngestRun.pass_rows

        def counted_links(run, region, *args, **kwargs):
            links[region] += 1
            return read_links(run, region, *args, **kwargs)

        def counted_rows(run, keys, columns):
            scans.append(len(keys))
            return read_rows(run, keys, columns)

        monkeypatch.setattr(IngestRun, "links", counted_links)
        monkeypatch.setattr(IngestRun, "pass_rows", counted_rows)
        ingest(tmp_path / "registry")
        assert links and max(links.values()) == 1
        assert len(scans) == 1

    def test_a_catalogue_that_is_not_linked(self, tmp_path):
        with IngestRun.start(tmp_path / "registry", tmp_path / "backup") as run:
            resolver = systems_ingest.RunResolver(run, True)
            with pytest.raises(ValueError, match="no links of gcvs/name"):
                resolver.keys("gcvs", "name", pa.array(["V1"]))


class TestSystemObjectBecomesARow:
    """A SIMBAD system object that the next ingest stores as a star."""

    def test_the_star_and_the_systems_keep_apart(self, tmp_path):
        root = tmp_path / "registry"
        ingest(root)
        first = table(Registry(root), SYSTEM.slug)
        resolved = set(first.filter(pc.invert(first["point"]))["id"].to_pylist())
        # SIMBAD 1 is "* alf Cen", the system object of the trees.
        _, report = ingest(root, simbad={"1": (219.95, -60.80, 0.0)})
        registry = Registry(root)
        (star,) = registry.lookup("simbad", "oid", ["1"]).tolist()
        assert star and table_of(star) == 1
        second = table(registry, SYSTEM.slug)
        assert resolved <= set(second["id"].to_pylist())
        assert "retired or merged 0" in report


class TestSystemsWithoutCatalogueIds:
    """Systems that claim their primary keep their IDs when labels change."""

    def test_ids_hold(self, tmp_path, monkeypatch):
        labels = iter([None, "new"])
        build = systems_ingest.build

        def without_ids(inputs, resolver):
            systems = build(inputs, resolver)
            nodes, label = systems.nodes, next(labels)
            n = nodes.num_rows
            for name, values in (
                (
                    "catalogue_ids",
                    pa.nulls(n, nodes.schema.field("catalogue_ids").type),
                ),
                ("label", pa.array([label] * n, pa.string())),
            ):
                at = nodes.schema.get_field_index(name)
                nodes = nodes.set_column(at, name, values)
            return dataclasses.replace(systems, nodes=nodes)

        monkeypatch.setattr(systems_ingest, "build", without_ids)
        root = tmp_path / "registry"
        _, report = ingest(root)
        first = table(Registry(root), SYSTEM.slug)
        _, report_two = ingest(root)
        second = table(Registry(root), SYSTEM.slug)
        # α Cen and α Cen AB share the primary A.
        assert "pass: resolved systems that claim their primary 4" in report
        assert "claimed twice" not in report
        assert sorted(second["id"].to_pylist()) == sorted(first["id"].to_pylist())
        assert "system IDs: minted 0, kept 4, retired or merged 0" in report_two

    def test_nesting_rank(self):
        primaries = np.array([7, 7, 9, 7])
        depth = np.array([0, 2, 0, 1])
        rank = systems_ingest._nesting_rank(primaries, depth)
        assert rank.tolist() == [2, 0, 0, 1]


class TestClassOrder:
    """A specific class wins over "binary star", which wins over "star"."""

    @staticmethod
    def merged(rows: list[tuple[str, str]]) -> tuple[str, str]:
        table = pa.table(
            {
                "id": pa.array([1] * len(rows), pa.int64()),
                "source": [source for source, _ in rows],
                "name": pa.nulls(len(rows), pa.string()),
                "class": [name for _, name in rows],
            }
        )
        (row,) = merge_by_source_order(METADATA, table).to_pylist()
        return row["class"], row["class_source"]

    def test_a_white_dwarf_of_simbad_beats_the_default_of_a_host(self):
        rows = [
            ("nasa-exoplanet-archive", "star"),
            ("simbad", "white dwarf"),
            ("gaia-dr3", "star"),
        ]
        assert self.merged(rows) == ("white dwarf", "simbad")

    def test_a_pulsar_that_holds_two_stars_stays_a_pulsar(self):
        rows = [
            ("nasa-exoplanet-archive", "pulsar"),
            ("gaia-dr3", "star"),
            ("star-systems", "binary star"),
        ]
        assert self.merged(rows) == ("pulsar", "nasa-exoplanet-archive")

    def test_a_star_that_holds_two_stars_is_a_binary_star(self):
        rows = [("hipparcos-2007", "star"), ("star-systems", "binary star")]
        assert self.merged(rows) == ("binary star", "star-systems")
        assert self.merged([("simbad", "star")]) == ("star", "simbad")


def system_primary_cell(row: dict) -> int:
    return int(sky.cells(np.array([row["ra"]]), np.array([row["dec"]]))[0])


class TestSystemKind:
    """A system node is never the match of a star, also with no kind."""

    def test_kinds(self):
        matcher = PositionMatcher()
        n = 4
        pairs = Pairs(
            separation=np.zeros(n),
            row_error=np.full(n, 0.1),
            row_size=np.full(n, np.nan),
            row_mag=np.full(n, np.nan),
            row_kind=pa.array(["star", None, SYSTEM_KIND, "star"]),
            key_error=np.full(n, 0.1),
            key_size=np.full(n, np.nan),
            key_mag=np.full(n, np.nan),
            key_kind=pa.array([SYSTEM_KIND, SYSTEM_KIND, SYSTEM_KIND, None]),
        )
        score = matcher.score(pairs)
        assert np.isnan(score[:2]).all()
        assert np.isfinite(score[2:]).all()


class TestWikidataToSystems:
    """An item that claims the HIP number of a system object names the system."""

    def test_route(self):
        stars = SimbadList(
            {
                1: SimbadObject(1, "* alf Gem", 113.6, 31.9, hip="36850"),
                2: SimbadObject(2, "* alf Gem A", 113.6, 31.9),
                3: SimbadObject(3, "* alf Gem B", 113.6, 31.9, gaia="892"),
                4: SimbadObject(4, "* bet Gem", 116.3, 28.0, hip="37826"),
            },
            {1: [2, 3]},
            {},
        )
        rows = pa.table(
            {
                "catalogue_id": ["Q1", "Q2", "Q3"],
                "claims": pa.array(
                    [
                        [dict(zip(CROSS_ID.names, ("hip", "2007", "36850")))],
                        [dict(zip(CROSS_ID.names, ("hip", "2007", "37826")))],
                        [dict(zip(CROSS_ID.names, ("gaia", "dr3", "892")))],
                    ],
                    pa.list_(CROSS_ID),
                ),
            }
        )
        claim = dict(zip(CROSS_ID.names, ("star-system", "simbad", "1")))
        routed, moved = wikidata.to_systems(rows, stars, {"1": claim})
        claims = [
            "/".join(c[0][name] for name in CROSS_ID.names)
            for c in routed["claims"].to_pylist()
        ]
        assert claims == ["star-system/simbad/1", "hip/2007/37826", "gaia/dr3/892"]
        assert moved == ["Q1 → * alf Gem"]
        # A system that is no node of the ingest keeps nothing.
        routed, moved = wikidata.to_systems(rows, stars, {})
        assert moved == []
