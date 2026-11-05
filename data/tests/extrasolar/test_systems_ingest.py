"""The star systems in a small ingest: passes, IDs, links and the report."""

import copy
import dataclasses
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from space_map_data.download.providers.stars import msc
from space_map_data.download.providers.stars.wikidata_stars import StarItem
from space_map_data.export.extrasolar import systems as export_systems
from space_map_data.extrasolar import frame, sky
from space_map_data.extrasolar.engine import IngestRun, Source
from space_map_data.extrasolar.exoplanets.sources import ARCHIVE_SOURCE
from space_map_data.extrasolar.ids import cell_of, table_of
from space_map_data.extrasolar.match import SYSTEM_KIND, Pairs, PositionMatcher
from space_map_data.extrasolar.placement import placement
from space_map_data.extrasolar.registry import IdStates, Registry
from space_map_data.extrasolar.sources import wikidata
from space_map_data.extrasolar.sources.distances import REYLE_2021
from space_map_data.extrasolar.sources.gaia import GAIA_DR3
from space_map_data.extrasolar.sources.hipparcos import HIPPARCOS
from space_map_data.extrasolar.sources.simbad import SIMBAD, UNSEEN, SimbadList
from space_map_data.extrasolar.systems import assemble, drawn
from space_map_data.extrasolar.systems import ingest as systems_ingest
from space_map_data.extrasolar.systems.msc import msc_nodes
from space_map_data.extrasolar.systems.orbits import msc_orbits
from space_map_data.extrasolar.systems.pairs import el_badry_pairs, orbit_pairs
from space_map_data.extrasolar.systems.parallax import IN_CLUSTER
from space_map_data.extrasolar.systems.planets import PLANETS_INPUT
from space_map_data.extrasolar.systems.prepare import Inputs
from space_map_data.extrasolar.systems.reduce import UNBOUND
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
from tests.download.orbit_catalogue_files import MSC_LINES, MSC_ORB_README
from tests.extrasolar import conftest
from tests.extrasolar.conftest import offset
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
    catalogue_orbits: pa.Table | None = None,
    spectral_types: tuple[str | None, str | None] = ("G2V", "K1V"),
    msc_rows: tuple[list[dict], list[dict]] = ([], []),
    clusters: pa.Table | None = None,
) -> tuple[Inputs, SimbadIndex]:
    comp = [
        *msc_rows[0],
        msc_comp("14396-6050", "A", HIP=71683),
        msc_comp("14396-6050", "B", HIP=71681),
        msc_comp("14396-6050", "C", HIP=70890),
        msc_comp("00400+1000", "A", HIP=1001),
        msc_comp("00400+1000", "B", HIP=1002),
    ]
    pairs = [
        *msc_rows[1],
        msc_pair("14396-6050", "AB", "C", "*", Sep=131.0, Sunit="'"),
        msc_pair("14396-6050", "A", "B", "AB", Sep=17.5, Sunit='"'),
        msc_pair("00400+1000", "A", "B", "*", Sep=5.3, Sunit='"'),
        msc_pair(
            "00400+1000",
            "Aa",
            "Ab",
            "A",
            Sep=8.0,
            Sunit="m",
            P=10,
            Punit="d",
            SP1=spectral_types[0],
            SP2=spectral_types[1],
        ),
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
            catalogue_orbits=catalogue_orbits,
            clusters=clusters,
        ),
        index,
    )


def ingest(
    root,
    stars: dict = STARS,
    host: str = "1002",
    simbad: dict | None = None,
    gaia: dict | None = None,
    passes: tuple[tuple[Source, Callable[[IngestRun], pa.Table]], ...] = (),
    items: tuple[StarItem, ...] = (),
    item_simbad: SimbadList | None = None,
    record: dict | None = None,
    max_retired: int | None = None,
    **more,
) -> tuple[systems_ingest.SystemsExtension, str]:
    """An ingest of `stars`, with a P-type planet of `host`, the SIMBAD rows
    `simbad` (oid → ra, dec, V), the Gaia DR3 rows `gaia`, the rows of
    `passes` and, after the systems, the Wikidata `items`. `item_simbad`
    stands in for the SIMBAD list of the items. `record` replaces values of
    the planet. `more` goes to `inputs`."""
    with IngestRun.start(root, root / "backup") as run:
        if gaia:
            run.add(GAIA_DR3, [gaia_rows(run, gaia)])
        run.add(HIPPARCOS, [hipparcos_rows(run, stars)])
        run.add(REYLE_2021, [reyle_rows(run)])
        if simbad:
            run.add(SIMBAD, [simbad_rows(run, simbad)])
        for source, rows in passes:
            run.add(source, [rows(run)])
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
            }
            | (record or {}),
            schema=PLANETS_INPUT,
        )
        found, index = inputs(planets, **more)
        extension = systems_ingest.add_systems(run, found, index, True)
        if items:
            positions = {hip: values[:2] for hip, values in stars.items()}
            rows = wikidata.engine_rows(items, positions, {})
            rows, lines = wikidata.attach(
                rows, items, run, extension.plan, item_simbad or index.stars
            )
            extension.items_placed(lines)
            run.add(wikidata.WIKIDATA, [rows])
        result = run.commit(max_retired=max_retired)
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
            "match_kind": ["star" if m is not None else UNSEEN for m in mag],
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
        resolved = system.filter(
            pc.and_(pc.invert(system["point"]), pc.greater(system["stars"], 1))
        )
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

    def test_held_stars(self, registry_after_two):
        """Aa and Ab, which the point of HIP 1001 holds, have IDs of the System
        table in its cell, rows of their own, and a place in the tree."""
        registry, _, report, report_two, _, _ = registry_after_two
        system = {row["id"]: row for row in table(registry, SYSTEM.slug).to_pylist()}
        (p1,) = ids_of(registry, ["1001"])
        members = system[p1]["members"]
        assert [(m["letter"], m["kind"]) for m in members] == [
            ("Aa", "held star"),
            ("Ab", "held star"),
        ]
        for member in members:
            row = system[member["id"]]
            assert table_of(member["id"]) == SYSTEM_TABLE
            assert cell_of(member["id"]) == cell_of(p1)
            assert row["parent"] == p1 and row["root"] == system[p1]["root"]
            assert row["stars"] == 1 and not row["point"]
            assert row["depth"] == system[p1]["depth"] + 1
            assert row["label"] == member["letter"] and row["members"] == []
            assert row["distance"] == system[p1]["distance"] > 0
            # Their spectral types make them held stars.
            assert row["star"]["spectral_type"] in ("G2V", "K1V")
            assert row["star"]["mass"] is None and row["star"]["references"] == []
        root = system[system[p1]["root"]]
        tree = {entry["id"]: entry for entry in root["tree"]}
        assert {m["id"] for m in members} <= set(tree)
        meta = {row["id"]: row for row in table(registry, METADATA.slug).to_pylist()}
        for member in members:
            assert meta[member["id"]]["system"] == system[p1]["root"]
            assert meta[member["id"]]["class"] == "star"
        assert "held star IDs: minted 2, kept 0" in report
        assert "held star IDs: minted 0, kept 2" in report_two

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


class TestMscComponents:
    """MSC components that no id links match by position in a pass of their
    own, beside the WDS pass, whose ids can name other stars."""

    def test_they_match_by_position(self, tmp_path):
        root = tmp_path / "registry"
        w = "04000+1500"
        stars = STARS | {
            "2001": (60.0, 15.0, 9.0, 15.0, 0.2),
            "2002": (60.01, 15.0, 10.0, 15.0, 0.2),
        }
        rows = (
            [
                msc_comp(w, "A", RAdeg=60.0, DEdeg=15.0, Vmag=9.3),
                msc_comp(w, "B", RAdeg=60.01, DEdeg=15.0, Vmag=10.3),
            ],
            [msc_pair(w, "A", "B", "*", Sep=34.8, Sunit='"')],
        )
        ingest(root, stars, msc_rows=rows)
        registry = Registry(root)
        found = registry.lookup("msc", "component", [f"{w} A", f"{w} B"])
        assert found.tolist() == ids_of(registry, ["2001", "2002"])
        found = registry.lookup("wds", "component", ["02000+0500 A", "02000+0500 B"])
        assert found.tolist() == ids_of(registry, ["1003", "1004"])


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


# Gaia DR3 rows: the stars of a WDS pair, of an El-Badry pair, and a member that
# is not minted. Each pair is 150″ apart at 100 pc.
NEIGHBOURS = {
    "wds a": (120.0, 40.0, 10.0, 10.0, 0.9),
    "wds b": (120.0, 40.04167, 11.0, 10.0, 0.9),
    "pair a": (130.0, 45.0, 10.0, 10.0, 0.9),
    "pair b": (130.0, 45.04167, 11.0, 10.0, 0.9),
    "unminted": (130.1, 45.0, 12.0, 10.0, 0.1),
}
NEIGHBOUR = {
    name: source_id(*row[:2], n + 10)
    for n, (name, row) in enumerate(NEIGHBOURS.items())
}


def neighbours(clusters: pa.Table | None) -> dict:
    """The ingest's arguments for two pairs that may be in one star cluster."""
    return {
        "gaia": {NEIGHBOUR[name]: row for name, row in NEIGHBOURS.items()},
        "wds_systems": WDS_SYSTEMS
        | {"08000+4000": [wds_pair("A", "B", 150.0, notes="V", mag1=10.0, mag2=11.0)]},
        "wds_components": WDS_COMPONENTS
        | {
            ("08000+4000", "A"): wds_component(
                source_id=NEIGHBOUR["wds a"], ra=120.0, dec=40.0
            ),
            ("08000+4000", "B"): wds_component(
                source_id=NEIGHBOUR["wds b"], ra=120.0, dec=40.04167
            ),
        },
        "el_badry": el_badry_pairs(
            pa.table(
                {
                    "source_id1": [NEIGHBOUR["pair a"]],
                    "source_id2": [NEIGHBOUR["pair b"]],
                    "ra1": [130.0],
                    "dec1": [45.0],
                    "ra2": [130.0],
                    "dec2": [45.04167],
                    "parallax1": [10.0],
                    "parallax2": [10.0],
                    "phot_g_mean_mag1": [10.0],
                    "phot_g_mean_mag2": [11.0],
                    "sep_arcsec": [150.0],
                    "R_chance_align": [0.01],
                    "binary_type": ["MSMS"],
                }
            )
        ),
        "clusters": clusters,
    }


def in_systems(root: Path) -> set[int]:
    """The IDs of the stars of the neighbours that a system lists."""
    registry = Registry(root)
    stars = registry.lookup("gaia", "dr3", [str(i) for i in NEIGHBOUR.values()])
    system = table(registry, SYSTEM.slug).to_pylist()
    members = {m["id"] for row in system for m in row["members"]}
    return members & set(stars.tolist())


class TestClusterMembers:
    """The links of the run give the members of a star cluster their objects."""

    def test_the_pairs_stand_without_a_cluster(self, tmp_path):
        root = tmp_path / "registry"
        ingest(root, **neighbours(None))
        assert len(in_systems(root)) == 4

    def test_neighbours_are_no_system(self, tmp_path):
        """A member that the commit does not mint and an id that the run does
        not hold are no object, and the commit takes the rest."""
        root = tmp_path / "registry"
        unknown = source_id(10.0, -30.0, 99)
        members = pa.table(
            {
                "source_id": pa.array([*NEIGHBOUR.values(), unknown], pa.int64()),
                "cluster": ["NGC_2682"] * (len(NEIGHBOUR) + 1),
            }
        )
        _, report = ingest(root, **neighbours(members))
        assert not in_systems(root)
        assert f"{UNBOUND}: {IN_CLUSTER}: 2" in report


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
        # B matches a Gaia row that gets no ID, and C matches nothing. A letter
        # alone earns no ID.
        lines = sorted((m["letter"], m["kind"], m["id"]) for m in node["members"])
        assert lines[1:] == [("B", "entry", None), ("C", "entry", None)]
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

        def entries(system: pa.Table) -> list[tuple[int, str, str, int]]:
            """The members of the stars of objects that get no ID."""
            return sorted(
                (row["id"], m["letter"] or "", m["kind"], m["id"] or 0)
                for row in system.to_pylist()
                for m in row["members"]
                if any(x["catalogue_id"] in lost for x in m["ids"] or [])
            )

        # The El-Badry star has no value of its own; B of the orbit and of
        # the WDS have only their letters.
        kinds = sorted(kind for _, _, kind, _ in entries(first))
        assert kinds == ["entry", "entry", "entry"]
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


class TestHeldStarOfANodeWithNoID:
    """A held star with an ID whose node has none gets no System row: it
    takes no other node's place."""

    def test_no_row(self):
        nodes = pa.Table.from_pylist(
            [
                {"node": 0, "root": 0, "depth": 0, "ra": 1.0, "dec": 1.0},
                {"node": 500, "root": 500, "depth": 0, "ra": 2.0, "dec": 2.0},
            ],
            schema=assemble.NODES,
        )
        members = pa.Table.from_pylist(
            [
                {"node": 0, "kind": "entry", "member": 0},
                {"node": 500, "kind": "entry", "member": 0},
            ],
            schema=assemble.MEMBERS,
        )
        held = pa.Table.from_pylist(
            [
                {"member": 0, "number": 1, "letter": "B"},
                {"member": 1, "number": 2, "letter": "C"},
            ],
            schema=drawn.HELD_STARS,
        )

        def node_id(numbers: np.ndarray) -> np.ndarray:
            return np.where(numbers == 2, 500, 0)

        with_held, kinds = systems_ingest._with_held(
            nodes, members, held, np.array([900, 901]), node_id
        )
        added = with_held.slice(nodes.num_rows).to_pylist()
        assert [(r["node"], r["parent"], r["root"], r["ra"]) for r in added] == [
            (901, 500, 500, 2.0)
        ]
        assert kinds["kind"].to_pylist() == ["entry", "held star"]


class TestPointsWithNoClaim:
    """A point that the run gives nothing to claim stops the step. The
    resolver gives each key a claim, so such a point is a fault of the
    resolver."""

    def test_it_raises(self, tmp_path, monkeypatch):
        claims = systems_ingest.RunResolver.claims

        def without(resolver, keys, **kwargs):
            found = claims(resolver, keys, **kwargs)
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


class TestLettersAlone:
    """A held star that a later ingest knows only by its letter."""

    def test_it_retires_and_its_line_stays(self, tmp_path):
        root = tmp_path / "registry"
        ingest(root)
        registry = Registry(root)
        (p1,) = ids_of(registry, ["1001"])
        system = {row["id"]: row for row in table(registry, SYSTEM.slug).to_pylist()}
        retired = [m["id"] for m in system[p1]["members"]]
        _, report = ingest(root, spectral_types=(None, None), max_retired=2)
        registry = Registry(root)
        system = {row["id"]: row for row in table(registry, SYSTEM.slug).to_pylist()}
        members = system[p1]["members"]
        assert [(m["letter"], m["kind"], m["id"]) for m in members] == [
            ("Aa", "entry", None),
            ("Ab", "entry", None),
        ]
        assert not set(retired) & set(system)
        assert "held star IDs: minted 0, kept 0" in report
        assert "retired or merged 2" in report


class TestBrownDwarfRecord:
    """CD-35 2722 B, as an ingest sees it: SIMBAD lists it with no magnitude,
    so the WDS component of B cannot match it by position."""

    W = "04400+2000"

    @pytest.fixture
    def done(self, tmp_path):
        root = tmp_path / "registry"
        b = offset(70.0, 20.0, 2.9, 90.0)
        extension, report = ingest(
            root,
            stars=STARS | {"1010": (70.0, 20.0, 8.0, 10.0, 0.2)},
            host="1010",
            record={
                "designation": ["X b"],
                "class": ["brown dwarf"],
                "mass": [33.5],
                "binary_type": [None],
                "star_ids": [[dict(zip(CROSS_ID.names, ("simbad", "oid", "7")))]],
            },
            simbad={"7": (70.0, 20.0, None)},
            wds_systems=WDS_SYSTEMS
            | {
                self.W: [
                    wds_pair("A", "B", 2.9, mag1=8.0, mag2=19.0, position_angle=90.0)
                ]
            },
            wds_components=WDS_COMPONENTS
            | {
                (self.W, "A"): wds_component(ra=70.0, dec=20.0),
                (self.W, "B"): wds_component(ra=b[0], dec=b[1]),
            },
        )
        return Registry(root), extension, report

    def test_the_match_does_not_reach_it(self, done):
        registry, _, _ = done
        assert registry.lookup("wds", "component", [f"{self.W} B"]).tolist() == [0]

    def test_its_slot_holds_its_star(self, done):
        registry, _, _ = done
        (host,) = ids_of(registry, ["1010"])
        (star,) = registry.lookup("simbad", "oid", ["7"]).tolist()
        node = node_of(table(registry, SYSTEM.slug), host)
        assert [(m["letter"], m["kind"], m["id"]) for m in node["members"]] == [
            ("A", "star", host),
            ("B", "star", star),
        ]

    def test_the_two_link_each_other(self, done):
        registry, extension, report = done
        (star,) = registry.lookup("simbad", "oid", ["7"]).tolist()
        assert extension.star(0) == star
        assert "brown dwarf records linked to their star: 1" in report

    def test_a_planet_of_the_star_goes_to_its_system(self, done):
        """Its planets go to the file of the system, as the host's."""
        registry, extension, _ = done
        (host,) = ids_of(registry, ["1010"])
        (star,) = registry.lookup("simbad", "oid", ["7"]).tolist()
        assert extension.root(star) == extension.root(host) != 0


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
    """A node is a binary or multiple star. Else a specific class wins over
    the generic "star"."""

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

    def test_a_pulsar_that_holds_two_stars_is_a_binary_star(self):
        rows = [
            ("nasa-exoplanet-archive", "pulsar"),
            ("gaia-dr3", "star"),
            ("star-systems", "binary star"),
        ]
        assert self.merged(rows) == ("binary star", "star-systems")

    def test_a_star_that_holds_two_stars_is_a_binary_star(self):
        rows = [("hipparcos-2007", "star"), ("star-systems", "binary star")]
        assert self.merged(rows) == ("binary star", "star-systems")
        assert self.merged([("simbad", "star")]) == ("star", "simbad")


class TestNameOrder:
    """The IAU name, the exoplanet catalogues, then a Wikidata label. A
    Wikidata label that is a catalogue number beats only the Gaia DR3 id."""

    @staticmethod
    def merged(rows: list[tuple[str, str]]) -> tuple[str, str]:
        table = pa.table(
            {
                "id": pa.array([1] * len(rows), pa.int64()),
                "source": [source for source, _ in rows],
                "name": [name for _, name in rows],
                "class": pa.nulls(len(rows), pa.string()),
            }
        )
        (row,) = merge_by_source_order(METADATA, table).to_pylist()
        return row["name"], row["name_source"]

    def test_a_planet_host_keeps_the_name_of_its_catalogues(self):
        rows = [("wikidata", "V471 Tauri"), ("nasa-exoplanet-archive", "V471 Tau")]
        assert self.merged(rows) == ("V471 Tau", "nasa-exoplanet-archive")
        rows = [("wikidata", "68 Cas"), ("simbad", "HD 4142")]
        assert self.merged(rows) == ("68 Cas", "wikidata")

    def test_a_catalogue_number_of_wikidata_beats_only_the_gaia_id(self):
        gaia = ("gaia-dr3", "Gaia DR3 4472832130942575872")
        for label in ("HD 33643", "BD+47 612", "2MASS J05321406+8246044"):
            rows = [("wikidata", label), ("hipparcos-2007", "HIP 24323"), gaia]
            assert self.merged(rows) == ("HIP 24323", "hipparcos-2007")
            assert self.merged([("wikidata", label), gaia]) == (label, "wikidata")


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


def star_item(
    qid: str,
    label: str,
    hip: str,
    articles: int = 1,
    stars: tuple[str, ...] = ("Q523",),
    systems: tuple[str, ...] = (),
) -> StarItem:
    """An item of one HIP number; Q523 is a star, Q50053 a binary star."""
    return StarItem(
        qid=qid,
        gaia_dr3=(),
        hip=(hip,),
        hd=(),
        label_en=label,
        label_mul=None,
        articles=articles,
        star_classes=stars,
        system_classes=systems,
    )


class TestWikidataItems:
    """Star items stay on their stars, system items go to their nodes."""

    ITEMS = (
        star_item("Q2090157", "Alpha Centauri A", "71683", 9),
        # A star of the same number with fewer articles.
        star_item("Q901", "Rigil Kentaurus", "71683"),
        # Its label names a component.
        star_item("Q1052548", "Alpha Centauri B", "71681", 4, systems=("Q13890",)),
        star_item("Q14266", "Proxima Centauri", "70890", 12),
        # SIMBAD's system object of α Cen AB holds this number.
        star_item("Q902", "Alpha Centauri AB", "71683", 7, (), ("Q50053",)),
        # A pair point and a star of the MSC pair.
        star_item("Q903", "HIP 1001", "1001", 1, ("Q523",), ("Q50053",)),
        star_item("Q904", "MSC 00400+1000", "1002", 3, ("Q523",), ("Q50053",)),
    )

    @pytest.fixture
    def registry(self, tmp_path):
        _, index = inputs(PLANETS_INPUT.empty_table())
        stars = copy.deepcopy(index.stars)
        # α Cen's system object takes the number of α Cen A, as SIMBAD's
        # Mizar takes the number of Mizar A.
        stars.objects[1].hip = "71683"
        root = tmp_path / "registry"
        _, report = ingest(root, items=self.ITEMS, item_simbad=stars)
        return Registry(root), report

    def test_where_the_items_go(self, registry):
        registry, report = registry
        a, b, c, p1 = ids_of(registry, ["71683", "71681", "70890", "1001"])
        system = {row["id"]: row for row in table(registry, SYSTEM.slug).to_pylist()}
        pair = next(
            row["id"]
            for row in system.values()
            if {m["id"] for m in row["members"]} == {a, b}
        )
        msc_root = system[p1]["root"]
        qids = ["Q2090157", "Q901", "Q1052548", "Q14266", "Q902", "Q903", "Q904"]
        found = registry.lookup("wikidata", "qid", qids).tolist()
        assert found == [a, 0, b, c, pair, p1, msc_root]
        meta = {row["id"]: row for row in table(registry, METADATA.slug).to_pylist()}
        assert meta[pair]["name"] == "Alpha Centauri AB"
        assert "conflicts: 0" in report
        assert (
            "Wikidata items that reach an object: star 3, mixed 3, system 1" in report
        )
        assert f"  {wikidata.TO_ROOT}: 1\n    Q904 MSC 00400+1000" in report
        assert f"  {wikidata.OUTRANKED}: 1\n    Q901 Rigil Kentaurus" in report


class TestWikidataClaims:
    """A claim reaches the object of its newest link in the row's region and
    its neighbours, as the engine finds it."""

    def test_a_link_of_the_run_wins_over_an_older_link_in_a_later_region(
        self, root, backup
    ):
        """HIP 7 took star 1 in the first ingest, filed in the later region.
        The run links it to star 2, filed in the earlier region of the row."""
        ends = conftest.straddle(100)
        regions = {
            end: sky.region_of(int(sky.cells(np.array(end[:1]), np.array(end[1:]))[0]))
            for end in ends
        }
        row, old = sorted(ends, key=regions.__getitem__)
        new = offset(*row, 1.0, 90)
        gaia = conftest.gaia_rows(
            [
                {"id": 1, "ra": old[0], "dec": old[1], "mag": 5.0},
                {"id": 2, "ra": new[0], "dec": new[1], "mag": 5.0},
            ]
        )
        hip = conftest.hip_rows([{"id": 7, "ra": row[0], "dec": row[1], "mag": 5.0}])
        tables = ((conftest.POINT,), conftest.META)
        with IngestRun.start(root, backup, *tables) as run:
            run.add(conftest.GAIA, [gaia])
            run.add(conftest.HIP, [hip])
            run.commit()
        first, second = (conftest.id_of(root, conftest.GAIA, n) for n in (1, 2))
        assert conftest.id_of(root, conftest.HIP, 7) == first

        notes = Source("notes", "notes", "x", home=1, permanent=False)
        found = ("hip", "2007", "7")
        rows = conftest.name_rows(
            [
                {
                    "id": "n",
                    "ra": row[0],
                    "dec": row[1],
                    "claims": [conftest.claim(*found)],
                }
            ]
        )
        with IngestRun.start(root, backup, *tables) as run:
            run.add(conftest.GAIA, [gaia])
            exclude = pa.array([[first]], pa.list_(pa.int64()))
            run.add(conftest.HIP, [hip.append_column("match_exclude", exclude)])
            keys = wikidata._keys(run, rows, [found])
            run.add(notes, [rows])
            run.commit()
        assert keys == {found: second}
        assert conftest.id_of(root, notes, "n") == second


# Gaia DR3 points: ra, dec, G, parallax, fidelity. The first three hold two
# stars by a Gaia orbit. The lone white dwarf has a companion of its own.
CLASSED = {
    "brown dwarfs": (120.0, -20.0, 17.0, 40.0, 0.9),
    "white dwarf and M dwarf": (125.0, -20.0, 15.0, 40.0, 0.9),
    "pulsar": (130.0, -20.0, 16.0, 40.0, 0.9),
    "lone white dwarf": (135.0, -20.0, 15.0, 40.0, 0.9),
    "companion": (135.002, -20.0, 12.0, 40.0, 0.9),
}
CLASSED_GAIA = {
    name: source_id(*row[:2], 10 + n) for n, (name, row) in enumerate(CLASSED.items())
}


def class_rows(source: Source, classes: dict[str, str]) -> Callable:
    """Rows of `source` at the CLASSED points, with these classes."""
    names = list(classes)

    def rows(run: IngestRun) -> pa.Table:
        return rows_for(
            run,
            source,
            {
                "catalogue_id": names,
                "mint": [False] * len(names),
                "match_ra": [CLASSED[n][0] for n in names],
                "match_dec": [CLASSED[n][1] for n in names],
                "match_mag": [CLASSED[n][2] for n in names],
                "match_error": [0.01] * len(names),
                "class": [classes[n] for n in names],
            },
        )

    return rows


class TestNodeClass:
    """A point that holds several objects is a binary or multiple star,
    whatever class a catalogue gives it. Its members say what the objects
    are. A point of one object keeps its class."""

    @pytest.fixture(scope="class")
    def classes(self, tmp_path_factory) -> tuple[dict[str, str | None], str]:
        root = tmp_path_factory.mktemp("classes") / "registry"
        held = ["brown dwarfs", "white dwarf and M dwarf", "pulsar"]
        orbits = orbit_pairs(
            pa.table(
                {
                    "source_id": [CLASSED_GAIA[n] for n in held],
                    "nss_solution_type": ["SB1"] * 3,
                    "period": [10.0] * 3,
                    "eccentricity": [0.1] * 3,
                    "m1": [0.07, 0.6, 1.4],
                    "m2": [0.05, 0.3, 0.3],
                }
            )
        )
        pair = {
            "source_id1": [CLASSED_GAIA["lone white dwarf"]],
            "source_id2": [CLASSED_GAIA["companion"]],
            "ra1": [135.0],
            "dec1": [-20.0],
            "ra2": [135.002],
            "dec2": [-20.0],
            "parallax1": [40.0],
            "parallax2": [40.0],
            "phot_g_mean_mag1": [15.0],
            "phot_g_mean_mag2": [12.0],
            "sep_arcsec": [6.77],
            "R_chance_align": [1e-6],
            "binary_type": ["WDMS"],
        }
        simbad = {
            "brown dwarfs": "brown dwarf",
            "white dwarf and M dwarf": "white dwarf",
            "lone white dwarf": "white dwarf",
        }
        _, report = ingest(
            root,
            gaia={CLASSED_GAIA[n]: row for n, row in CLASSED.items()},
            passes=(
                (SIMBAD, class_rows(SIMBAD, simbad)),
                (ARCHIVE_SOURCE, class_rows(ARCHIVE_SOURCE, {"pulsar": "pulsar"})),
            ),
            orbits=orbits,
            el_badry=el_badry_pairs(pa.table(pair)),
        )
        registry = Registry(root)
        names = list(CLASSED)
        ids = registry.lookup("gaia", "dr3", [str(CLASSED_GAIA[n]) for n in names])
        meta = {row["id"]: row for row in table(registry, METADATA.slug).to_pylist()}
        return {n: meta[int(i)]["class"] for n, i in zip(names, ids)}, report

    @pytest.mark.parametrize(
        "name", ["brown dwarfs", "white dwarf and M dwarf", "pulsar"]
    )
    def test_a_point_of_two_stars_is_a_binary_star(self, classes, name):
        assert classes[0][name] == "binary star"

    def test_a_lone_white_dwarf_stays_a_white_dwarf(self, classes):
        assert classes[0]["lone white dwarf"] == "white dwarf"
        assert classes[0]["companion"] == "star"

    def test_the_report_counts_the_changes(self, classes):
        report = classes[1]
        for before in ("brown dwarf", "white dwarf", "pulsar"):
            assert f"  {before} → binary star: 1\n" in report


class TestComponentOnItsPairsPoint:
    """η CrB: Gaia sees A and B as one point, which A's Gaia id reaches. B's
    position lands on it too, but B passes no id to it."""

    W = "09200+3000"

    def args(self, a: dict | None = None) -> dict:
        """The ingest inputs. `a` replaces the WDS row of A."""
        point = source_id(140.0, 30.0, 40)
        b = offset(140.0, 30.0, 0.3, 0.0)
        return {
            "gaia": {point: (140.0, 30.0, 5.0, 50.0, 0.9)},
            "wds_systems": WDS_SYSTEMS
            | {self.W: [wds_pair("A", "B", 0.3, notes="NO", mag1=5.6, mag2=5.9)]},
            "wds_components": WDS_COMPONENTS
            | {
                (self.W, "A"): a or wds_component(source_id=point, ra=140.0, dec=30.0),
                (self.W, "B"): wds_component(ra=b[0], dec=b[1]),
            },
        }

    def test_no_component_id_on_the_point(self, tmp_path):
        root = tmp_path / "registry"
        for _ in range(2):
            _, report = ingest(root, **self.args())
            registry = Registry(root)
            assert registry.lookup("wds", "component", [f"{self.W} B"]).tolist() == [0]
            (point,) = registry.lookup("gaia", "dr3", [str(source_id(140.0, 30.0, 40))])
            meta = {
                row["id"]: row for row in table(registry, METADATA.slug).to_pylist()
            }
            catalogues = {x["catalogue"] for x in meta[int(point)]["cross_ids"]}
            assert "wds" not in catalogues
            system = {
                row["id"]: row for row in table(registry, SYSTEM.slug).to_pylist()
            }
            assert system[int(point)]["point"] and system[int(point)]["stars"] == 2
            letters = [m["letter"] for m in system[int(point)]["members"]]
            assert letters == ["A", "B"]
        # The pair by position keeps its links.
        assert "WDS components matched by position 2," in report

    def test_a_link_of_an_earlier_ingest_to_the_point(self, tmp_path):
        """In the first ingest A has no Gaia id and no position, so B takes
        the point by position. Then A's Gaia id reaches the point, so B's
        row is free again: B is an entry inside the point."""
        root = tmp_path / "registry"
        ingest(root, **self.args(wds_component()))
        point = str(source_id(140.0, 30.0, 40))
        registry = Registry(root)
        assert registry.lookup("wds", "component", [f"{self.W} B"]).tolist() == [
            registry.lookup("gaia", "dr3", [point])[0]
        ]
        for _ in range(2):
            _, report = ingest(root, **self.args())
            # B's row makes its own object, which is not minted.
            assert "WDS components matched by position 2," in report
            registry = Registry(root)
            (key,) = registry.lookup("gaia", "dr3", [point])
            system = {
                row["id"]: row for row in table(registry, SYSTEM.slug).to_pylist()
            }
            assert system[int(key)]["point"] and system[int(key)]["stars"] == 2
            members = system[int(key)]["members"]
            assert [(m["letter"], m["kind"]) for m in members] == [
                ("A", "entry"),
                ("B", "entry"),
            ]
            (wds,) = [
                s for s in registry.ingests[-1]["sources"] if s["catalogue"] == "wds"
            ]
            assert wds["excluded_links"] == 1


class TestPairOrbits:
    """The MSC orbit of α Cen A and B on the System row of α Cen AB, ready to
    draw, and its node for the planets."""

    @pytest.fixture(scope="class")
    def drawn(self, tmp_path_factory):
        folder = tmp_path_factory.mktemp("orbits")
        (folder / msc.README_FILE).write_text(MSC_ORB_README, encoding="latin-1")
        (folder / msc.ORB_FILE).write_text(
            "\n".join(MSC_LINES) + "\n", encoding="latin-1"
        )
        root = folder / "registry"
        extension, report = ingest(root, catalogue_orbits=msc_orbits(folder))
        return Registry(root), extension, report

    def test_the_orbit_of_alpha_cen_ab(self, drawn):
        registry, extension, report = drawn
        a, b = ids_of(registry, ["71683", "71681"])
        system = table(registry, SYSTEM.slug).to_pylist()
        (ab,) = [
            row for row in system if {m["id"] for m in row["members"] or []} == {a, b}
        ]
        orbit = ab["orbit"]
        assert orbit["period_source"] == "msc" and orbit["centre"] == "barycentre"
        assert orbit["semi_major_axis_arcsec"] == 17.66
        assert orbit["semi_major_axis"] == pytest.approx(17.66 * REYLE["71683"])
        assert (orbit["node"], orbit["arg_periastron"]) == (204.75, 232.30)
        assert orbit["node_ascending"] and orbit["assumed"] == []
        assert orbit["barycentre"] == pytest.approx(4.61 / (4.61 + 5.45))
        expected = frame.ecliptic_angles(
            frame.direction(ab["ra"], ab["dec"]), 79.32, 204.75, 232.30
        )
        assert (orbit["i"], orbit["om"], orbit["w"]) == pytest.approx(expected)
        assert extension.node(ab["id"]) == 204.75
        others = [row for row in system if row["id"] != ab["id"]]
        assert all(row["orbit"] is None for row in others)
        assert "drawn: orbits 1" in report
