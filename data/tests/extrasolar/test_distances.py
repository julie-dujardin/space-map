"""Tests for the distance catalogues and their passes."""

import gzip
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from space_map_data.download.cds import README
from space_map_data.download.providers.stars import gaia_named, ultracoolsheet
from space_map_data.extrasolar.engine import IngestRun
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources import distances, gaia, hipparcos
from space_map_data.extrasolar.sources.distances import (
    BAILER_JONES_2021,
    CLOUDS,
    HUNT_REFFERT_2024,
    MAGELLANIC_CLOUDS,
    REYLE_2021,
    SIMBAD_PARALLAX,
    ULTRACOOLSHEET,
    StoredGaia,
)
from space_map_data.extrasolar.sources.gaia import GAIA_DR3, GAIA_DR3_NAMED
from space_map_data.extrasolar.sources.hipparcos import HIPPARCOS
from space_map_data.extrasolar.sources.simbad import SimbadList
from space_map_data.extrasolar.tables import POINT_SOURCE
from tests.extrasolar.conftest import table_rows
from tests.extrasolar.test_simbad import NO_BEST, named_rows, write_simbad
from tests.extrasolar.test_simbad import star as simbad_star
from tests.extrasolar.test_stars import at, fidelity, gaia_star, gaia_stars, hip_stars

RULE = "-" * 80


def cds_file(
    directory: Path, name: str, fields: list[tuple[str, str]], rows: list[dict]
) -> str:
    """Write `name` (gzip) as fixed-width rows; returns its ReadMe section.

    A field is (label, format), as I4 or F9.4; a missing value is blank.
    """
    lines = [
        f"Byte-by-byte Description of file: {name.removesuffix('.gz')}",
        RULE,
        "   Bytes Format Units   Label     Explanations",
        RULE,
    ]
    spans = []
    start = 1
    for label, form in fields:
        width = int(form[1:].split(".")[0])
        end = start + width - 1
        lines.append(f"{start:4d}-{end:4d}  {form:<7} ---     {label:<9} x")
        spans.append((label, form, width))
        start = end + 2
    lines.append(RULE)
    text = []
    for row in rows:
        parts = []
        for label, form, width in spans:
            value = row.get(label)
            parts.append(_field(value, form, width))
        text.append(" ".join(parts))
    (directory / name).write_bytes(gzip.compress(("\n".join(text) + "\n").encode()))
    return "\n".join(lines) + "\n"


def _field(value: object, form: str, width: int) -> str:
    if value is None:
        return " " * width
    if form[0] == "A":
        return f"{value:<{width}}"
    if form[0] == "I":
        return f"{value:>{width}}"
    decimals = int(form.split(".")[1])
    kind = "e" if form[0] == "E" else "f"
    return f"{value:>{width}.{decimals}{kind}}"[:width]


def readme(directory: Path, *sections: str) -> None:
    head = "J/X/1     A test catalogue\n" + "=" * 80 + "\n"
    (directory / README).write_text(head + "\n".join(sections))


def stored_gaia(
    directory: Path,
    fidelity: dict[int, float],
    named: tuple[int, ...] = (),
    pixels: str = "000000-786431",
) -> StoredGaia:
    """A StoredGaia whose positionable download is the stars of `fidelity`,
    in one chunk."""
    source, flags = directory / "gaia_source", directory / "fidelity"
    source.mkdir(exist_ok=True)
    flags.mkdir(exist_ok=True)
    ids = pa.array(list(fidelity), pa.int64())
    pq.write_table(
        pa.table({"source_id": ids}), source / f"GaiaSource_{pixels}.parquet"
    )
    values = pa.array(list(fidelity.values()), pa.float32())
    pq.write_table(
        pa.table({"source_id": ids, "fidelity_v2": values}),
        flags / f"Fidelity_{pixels}.parquet",
    )
    return StoredGaia(np.array(named, np.int64), source, flags)


REYLE_FIELDS = [
    ("Seq", "I4"),
    ("ObjType", "A6"),
    ("RAdeg", "F13.9"),
    ("DEdeg", "F13.9"),
    ("Epoch", "F6.1"),
    ("plx", "F8.4"),
    ("e_plx", "F8.4"),
    ("pmRA", "F16.9"),
    ("pmDE", "F16.9"),
    ("GCode", "I2"),
    ("Gmag", "F9.6"),
    ("Gest", "F6.2"),
    ("GaiaEDR3", "I19"),
    ("HIP", "A10"),
]


class TestBounds:
    """Distances from parallaxes and the clouds' proper motions."""

    def test_parallax_bounds(self):
        distance, lower, upper = distances.parallax_bounds(
            np.array([100.0, 1.0]), np.array([10.0, 2.0])
        )
        assert distance == pytest.approx([10.0, 1000.0])
        assert lower == pytest.approx([1000 / 110, 1000 / 3])
        assert upper[0] == pytest.approx(1000 / 90) and np.isnan(upper[1])

    def test_orthographic_proper_motion_at_the_centre(self):
        pm_x, pm_y = distances.orthographic_pm(
            np.array([81.28]),
            np.array([-69.78]),
            np.array([1.5]),
            np.array([0.2]),
            (81.28, -69.78),
        )
        assert (pm_x[0], pm_y[0]) == pytest.approx((1.5, 0.2))

    def test_cloud_of(self):
        smc, lmc = CLOUDS
        stars = [
            # In the LMC: no 5σ parallax, its proper motion, G under 20.5.
            (lmc.ra, lmc.dec, 0.01, 0.05, 1.76, 0.30, 15.0),
            # A foreground star moves too fast.
            (lmc.ra, lmc.dec, 0.01, 0.05, 10.0, 10.0, 15.0),
            # A 5σ parallax.
            (lmc.ra, lmc.dec, 1.0, 0.1, 1.76, 0.30, 15.0),
            # Too faint.
            (lmc.ra, lmc.dec, 0.01, 0.05, 1.76, 0.30, 21.0),
            # The SMC sits in the field of the LMC and comes first.
            (smc.ra, smc.dec, 0.01, 0.05, 0.73, -1.23, 15.0),
            # Out of both fields.
            (200.0, 30.0, 0.01, 0.05, 1.76, 0.30, 15.0),
        ]
        columns = [np.array(column, np.float64) for column in zip(*stars)]
        assert distances.cloud_of(*columns).tolist() == [1, -1, -1, -1, 0, -1]


class TestRows:
    """The pass rows of each catalogue."""

    def test_reyle(self, tmp_path):
        ra, dec = at(10)
        section = cds_file(
            tmp_path,
            distances.REYLE_FILE,
            REYLE_FIELDS,
            [
                # Two components share a HIP number; the first claims it.
                {
                    "Seq": 2,
                    "ObjType": "*",
                    "RAdeg": ra,
                    "DEdeg": dec,
                    "Epoch": 2000.0,
                    "plx": 100.0,
                    "e_plx": 1.0,
                    "pmRA": 0.0,
                    "pmDE": 1000.0,
                    "GCode": 10,
                    "Gest": 3.6,
                    "HIP": "HIP 55203",
                },
                {
                    "Seq": 3,
                    "ObjType": "*",
                    "RAdeg": ra,
                    "DEdeg": dec,
                    "Epoch": 2016.0,
                    "plx": 100.0,
                    "e_plx": 1.0,
                    "GCode": 3,
                    "Gmag": 4.6,
                    "HIP": "HIP 55203",
                },
                {
                    "Seq": 1,
                    "ObjType": "BD",
                    "RAdeg": ra,
                    "DEdeg": dec,
                    "Epoch": 2016.0,
                    "plx": 501.557,
                    "e_plx": 0.082,
                    "GCode": 20,
                    "Gest": 25.0,
                    "GaiaEDR3": 5353626573555863424,
                    "HIP": None,
                },
                {
                    "Seq": 4,
                    "ObjType": "Planet",
                    "RAdeg": ra,
                    "DEdeg": dec,
                    "Epoch": 2016.0,
                    "plx": 100.0,
                    "e_plx": 1.0,
                },
                # The ingest does not store this Gaia star: the row is left out.
                {
                    "Seq": 5,
                    "ObjType": "*",
                    "RAdeg": ra,
                    "DEdeg": dec,
                    "Epoch": 2016.0,
                    "plx": 100.0,
                    "e_plx": 1.0,
                    "GaiaEDR3": 77,
                },
            ],
        )
        readme(tmp_path, section)
        stored = stored_gaia(tmp_path, {5353626573555863424: 1.0})
        rows = distances.reyle_rows(stored, tmp_path)
        claims = [c and c[0]["catalogue_id"] for c in rows["claims"].to_pylist()]
        assert claims == ["5353626573555863424", "55203", None]
        assert rows["distance"].to_pylist() == pytest.approx([1000 / 501.557, 10, 10])
        assert rows["distance_lower"].to_pylist()[1] == pytest.approx(1000 / 101)
        assert rows["distance_method"].to_pylist() == ["parallax"] * 3
        # G from the spectral type is used, the arbitrary one of a T dwarf not.
        mags = rows["match_mag"].to_pylist()
        assert mags[0] is None and mags[1:] == pytest.approx([3.6, 4.6])
        moved = (rows["match_dec"][1].as_py() - dec) * 3600
        assert moved == pytest.approx(16.0, rel=1e-3)
        assert rows["catalogue_id"].null_count == 3
        assert not any(rows["mint"].to_pylist())

    def test_ultracoolsheet(self, tmp_path):
        ra, dec = at(10)
        names = [
            "exoplanet",
            "sourceID_Gaia_DR3",
            "ra_j2000_formula",
            "dec_j2000_formula",
            "pmra_formula",
            "pmdec_formula",
            "dist_formula",
            "disterr_formula",
            "dist_formula_source",
            "G_Gaia",
        ]
        lines = [
            ",".join(names),
            f"N,5353626573555863424,{ra},{dec},null,null,1.998,0.0004,dist_plx_formula,16.9",
            f"N,null,{ra},{dec},0,1000,20.5,3.0,dist_W2_formula,null",
            f"Y,null,{ra},{dec},null,null,30.0,2.0,dist_plx_formula,null",
            # The ingest does not store this Gaia star: the row is left out.
            f"N,77,{ra},{dec},null,null,40.0,2.0,dist_plx_formula,null",
        ]
        (tmp_path / ultracoolsheet.MAIN_FILE).write_text("\n".join(lines) + "\n")
        stored = stored_gaia(tmp_path, {}, named=(5353626573555863424,))
        rows = distances.ultracool_rows(stored, tmp_path)
        assert [c and c[0]["catalogue_id"] for c in rows["claims"].to_pylist()] == [
            "5353626573555863424",
            None,
        ]
        assert rows["distance_method"].to_pylist() == ["parallax", "photometric"]
        assert rows["distance_lower"].to_pylist() == pytest.approx([1.9976, 17.5])
        assert rows["distance_upper"].to_pylist() == pytest.approx([1.9984, 23.5])
        moved = (rows["match_dec"][1].as_py() - dec) * 3600
        assert moved == pytest.approx(16.0, rel=1e-3)

    def test_clusters(self, tmp_path):
        ra, dec = at(10)
        clusters = cds_file(
            tmp_path,
            distances.CLUSTERS_FILE,
            [
                ("Name", "A20"),
                ("Type", "A1"),
                ("dist16", "F15.8"),
                ("dist50", "F15.8"),
                ("dist84", "F15.8"),
            ],
            [
                {
                    "Name": "Trumpler_16",
                    "Type": "o",
                    "dist16": 2290.0,
                    "dist50": 2297.0,
                    "dist84": 2304.0,
                },
                {
                    "Name": "NGC_1",
                    "Type": "o",
                    "dist16": 990.0,
                    "dist50": 1000.0,
                    "dist84": 1010.0,
                },
                {
                    "Name": "Moving_1",
                    "Type": "m",
                    "dist16": 90.0,
                    "dist50": 100.0,
                    "dist84": 110.0,
                },
            ],
        )
        member = {
            "Name": "Trumpler_16",
            "inrj": 1,
            "inrt": 1,
            "Prob": 0.9,
            "RAdeg": ra,
            "DEdeg": dec,
        }
        members = cds_file(
            tmp_path,
            distances.MEMBERS_FILE,
            [
                ("Name", "A20"),
                ("GaiaDR3", "I19"),
                ("inrj", "I1"),
                ("inrt", "I1"),
                ("Prob", "F20.18"),
                ("RAdeg", "F24.20"),
                ("DEdeg", "E22.16"),
            ],
            [
                member | {"GaiaDR3": 1},
                # A 5σ parallax places it.
                member | {"GaiaDR3": 2},
                # A 5σ parallax that our fidelity flags.
                member | {"GaiaDR3": 3},
                member | {"GaiaDR3": 4, "Prob": 0.3},
                # In the tidal radius only: a globular cluster has no Jacobi one.
                member | {"GaiaDR3": 5, "inrj": 0},
                member | {"GaiaDR3": 6, "inrj": 0, "inrt": 0},
                member | {"GaiaDR3": 7, "Name": "Moving_1"},
                # The ingest does not store it.
                member | {"GaiaDR3": 8},
                # In two clusters: the more probable one wins.
                member | {"GaiaDR3": 9, "Prob": 0.6},
                member | {"GaiaDR3": 9, "Name": "NGC_1", "Prob": 0.8},
            ],
        )
        readme(tmp_path, clusters, members)
        stored = stored_gaia(tmp_path, {2: 0.9, 3: 0.1}, named=(1, 4, 5, 6, 7, 9))
        rows = distances.cluster_rows(stored, tmp_path)
        assert [c[0]["catalogue_id"] for c in rows["claims"].to_pylist()] == [
            "1",
            "3",
            "5",
            "9",
        ]
        assert rows["distance"].to_pylist() == pytest.approx([2297.0] * 3 + [1000.0])
        assert rows["distance_lower"].to_pylist() == pytest.approx(
            [2290.0] * 3 + [990.0]
        )
        assert rows["distance_lower_percentile"].to_pylist() == [16.0] * 4
        assert rows["distance_upper_percentile"].to_pylist() == [84.0] * 4
        assert rows["distance_method"].to_pylist() == ["cluster"] * 4


class TestStoredGaia:
    """The Gaia DR3 stars that the ingest stores, read chunk by chunk."""

    def test_each_id_is_read_from_its_chunk(self, tmp_path):
        far = (3 << 43) + 5
        stored_gaia(tmp_path, {10: 0.2}, pixels="000000-000001")
        stored = stored_gaia(tmp_path, {far: 0.9}, named=(12,), pixels="000002-000005")
        beyond = 9 << 43
        ids = np.array([far, 11, beyond, 10, 12], np.int64)
        assert stored.holds(ids).tolist() == [True, False, False, True, True]
        assert stored.flagged(ids).tolist() == [False, False, False, True, False]


def named_stars(rows: list[dict]) -> pa.Table:
    return gaia.join_fidelity(gaia_stars(rows), fidelity([]))


class TestNamedStars:
    """The gaia_named rows as the ingest reads them."""

    def test_read_named_has_null_radii(self, tmp_path):
        stars = gaia_stars([gaia_star(11, *at(0), 9.0)]).select(list(gaia.COLUMNS))
        pq.write_table(stars, tmp_path / gaia_named.SOURCE_FILE)
        pq.write_table(fidelity([(11, 0.9)]), tmp_path / gaia_named.FIDELITY_FILE)
        rows = named_rows(gaia.read_named(tmp_path))
        for name in gaia.ASTROPHYSICAL_COLUMNS:
            assert rows[name].null_count == 1
        assert rows["fidelity_v2"].to_pylist() == [pytest.approx(0.9)]
        assert rows["mint"].to_pylist() == [False]

    def test_read_named_joins_the_source_tables(self, tmp_path):
        stars = gaia_stars([gaia_star(11, *at(0), 9.0)]).select(list(gaia.COLUMNS))
        pq.write_table(stars, tmp_path / gaia_named.SOURCE_FILE)
        pq.write_table(fidelity([(11, 0.9)]), tmp_path / gaia_named.FIDELITY_FILE)
        apogee = gaia.SourceTable.of(
            pa.table({"source_id": pa.array([11], pa.int64()), "apogee_id": ["2M1"]}),
            ("apogee_id",),
        )
        rows = named_rows(gaia.read_named(tmp_path), (apogee,))
        assert rows["apogee_id"].to_pylist() == ["2M1"]
        assert rows["mh_xgboost"].to_pylist() == [None]
        assert rows["parallax_nss"].to_pylist() == [None]


class TestDistancePasses:
    """The distance group through the engine, first source in order wins."""

    def test_ingest(self, tmp_path):
        root = tmp_path / "root"
        lmc = CLOUDS[1]
        p = {key: at(60 * key) for key in range(1, 6)}
        stored = gaia.engine_rows(
            gaia.join_fidelity(
                gaia_stars([gaia_star(1, *p[1], 5.0), gaia_star(2, *p[2], 6.0)]),
                fidelity([]),
            ),
            NO_BEST,
        )
        named = named_stars(
            [
                gaia_star(11, *p[3], 9.0) | {"parallax": 0.1, "parallax_error": 0.2},
                # In the LMC, and in the Bailer-Jones table.
                gaia_star(12, lmc.ra, lmc.dec, 12.0)
                | {"parallax": 0.0, "parallax_error": 0.05, "pmra": 1.7, "pmdec": 0.3},
            ]
        )
        rows_named = named_rows(named)
        # A SIMBAD-like minting row joins each named star.
        hip, _ = hipparcos.engine_rows(
            hip_stars(
                [
                    {"hip": 30, "ra": p[3][0], "dec": p[3][1], "v_mag": 9.0},
                    {"hip": 40, "ra": lmc.ra, "dec": lmc.dec, "v_mag": 12.0},
                ]
            ),
            NO_BEST,
        )
        bj = tmp_path / "bj.parquet"
        pq.write_table(
            pa.table(
                {
                    "source_id": pa.array([11, 12, 99], pa.int64()),
                    "r_med_geo": pa.array([3000.0, 20000.0, 5.0], pa.float32()),
                    "r_lo_geo": pa.array([2000.0, 15000.0, 4.0], pa.float32()),
                    "r_hi_geo": pa.array([5000.0, 30000.0, 6.0], pa.float32()),
                    "flag": ["10033"] * 3,
                }
            ),
            bj,
        )
        rows_bj = distances.bailer_jones_rows(named, bj)
        assert rows_bj.num_rows == 2
        assert rows_bj["distance_lower_percentile"].to_pylist() == [16.0, 16.0]
        assert rows_bj["distance_upper_percentile"].to_pylist() == [84.0, 84.0]
        simbad_list = SimbadList.read(
            write_simbad(
                tmp_path / "simbad",
                [
                    simbad_star(201, *p[3], "Gaia DR3 11", plx_value=2.0, plx_err=0.1),
                    # One Gaia id, a larger relative error.
                    simbad_star(202, *p[3], "Gaia DR3 11", plx_value=2.5, plx_err=0.2),
                    # Under 5σ.
                    simbad_star(
                        203, lmc.ra, lmc.dec, "Gaia DR3 12", plx_value=0.5, plx_err=0.2
                    ),
                ],
            )
        )
        rows_simbad = distances.simbad_parallax_rows(simbad_list, named)
        assert rows_simbad["distance"].to_pylist() == [500.0]
        assert rows_simbad["distance_upper"].to_pylist() == [pytest.approx(1000 / 1.9)]
        reyle = distances.rows(
            np.array([p[1][0], p[4][0], p[2][0]]),
            np.array([p[1][1], p[4][1], p[2][1]]),
            # Gaia 1 by its id; nothing at p[4]; on Gaia 2, a Gaia id that the
            # ingest does not store.
            [("gaia", "dr3", "1"), None, ("gaia", "dr3", "77")],
            np.array([100.0, 7.0, 50.0]),
            np.array([99.0, 6.0, 49.0]),
            np.array([101.0, 8.0, 51.0]),
            ["parallax"] * 3,
            np.array([np.nan, 5.0, np.nan]),
            0.3,
        )
        held = stored_gaia(tmp_path, {1: 1.0, 2: 1.0}, named=(11, 12))
        reyle = distances.stored_claims(reyle, held, REYLE_2021.name)
        assert reyle.num_rows == 2
        with IngestRun.start(root, root / "backup") as run:
            run.add(GAIA_DR3, [stored])
            run.add(GAIA_DR3_NAMED, [rows_named])
            run.add(HIPPARCOS, [hip])
            run.add(REYLE_2021, [reyle])
            run.add(ULTRACOOLSHEET, [reyle.slice(0, 0)])
            run.add(HUNT_REFFERT_2024, [reyle.slice(0, 0)])
            run.add(MAGELLANIC_CLOUDS, [distances.magellanic_rows(named)])
            run.add(BAILER_JONES_2021, [rows_bj])
            run.add(SIMBAD_PARALLAX, [rows_simbad])
            result = run.commit()
        assert result.entry["counts"]["minted"] == 4
        registry = Registry(root)
        ids = {
            n: int(registry.lookup("gaia", "dr3", [str(n)])[0]) for n in (1, 2, 11, 12)
        }
        point = {r["id"]: r for r in table_rows(root, POINT_SOURCE.slug).to_pylist()}
        found = {
            n: (
                point[ids[n]]["distance_source"],
                point[ids[n]]["distance_method"],
                point[ids[n]]["distance"],
            )
            for n in ids
        }
        assert found == {
            1: ("reyle-2021", "parallax", 100.0),
            2: (None, None, None),
            # SIMBAD's parallax comes before the Galaxy prior.
            11: ("simbad-parallax", "parallax", 500.0),
            # The cloud comes before the Galaxy prior.
            12: ("magellanic-clouds", "galaxy", 49590.0),
        }
        assert point[ids[12]]["distance_upper"] == pytest.approx(50137.0)
        # The distance rows add no cross-ids, and mint nothing.
        meta = {r["id"]: r for r in table_rows(root, "metadata").to_pylist()}
        catalogues = {x["catalogue"] for r in meta.values() for x in r["cross_ids"]}
        assert catalogues == {"gaia", "hip"}
        gaia_ids = {
            x["catalogue_id"]
            for r in meta.values()
            for x in r["cross_ids"]
            if x["catalogue"] == "gaia"
        }
        assert gaia_ids == {"1", "2", "11", "12"}
        assert len(meta) == 4
