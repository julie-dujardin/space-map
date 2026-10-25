"""Tests for the Gaia, Hipparcos, IAU name and Wikidata sources and the star ingest."""

import dataclasses
import gzip
import json
import sys
from pathlib import Path

import astropy.units as u
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from astropy.coordinates import SkyCoord
from astropy.time import Time

from space_map_data.download.cds import README
from space_map_data.download.providers.stars import gaia_source
from space_map_data.download.providers.stars.wikidata_stars import StarItem
from space_map_data.export.objects.stars import read_star_objects
from space_map_data.extrasolar import stars
from space_map_data.extrasolar.engine import IngestResult, IngestRun
from space_map_data.extrasolar.exoplanets.sources import SOURCES as EXOPLANET_SOURCES
from space_map_data.extrasolar.registry import Registry, RegistryError
from space_map_data.extrasolar.sources import (
    apogee,
    gaia,
    gaia_orbits,
    hipparcos,
    lamost,
    names,
    pastel,
    wikidata,
)
from space_map_data.extrasolar.sources.distances import (
    BAILER_JONES_2021,
    HUNT_REFFERT_2024,
    MAGELLANIC_CLOUDS,
    REYLE_2021,
    SIMBAD_PARALLAX,
    ULTRACOOLSHEET,
)
from space_map_data.extrasolar.sources.gaia import (
    GAIA_DR3,
    GAIA_DR3_NAMED,
    BestNeighbours,
)
from space_map_data.extrasolar.sources.hipparcos import HIPPARCOS, HIPPARCOS_1997
from space_map_data.extrasolar.sources.literature import LITERATURE
from space_map_data.extrasolar.sources.names import IAU_WGSN
from space_map_data.extrasolar.sources.simbad import SIMBAD
from space_map_data.extrasolar.sources.wikidata import WIKIDATA
from space_map_data.extrasolar.tables import (
    BINARY_ORBIT,
    METADATA,
    POINT_SOURCE,
    TABLES,
)
from space_map_data.ingest import __main__ as ingest_cli
from space_map_data.utils.paths import (
    DERIVED_SKYCULTURES_DIR,
    REGISTRY_BACKUP_DIR,
    REGISTRY_ROOT,
)
from tests.extrasolar.conftest import centre, offset, table_rows
from tests.extrasolar.test_gaia_orbits import build as build_orbits
from tests.extrasolar.test_gaia_orbits import solution

RA, DEC = centre(6_000_321)
# In the order of the distance group.
DISTANCE_SOURCES = (
    LITERATURE,
    SIMBAD_PARALLAX,
    REYLE_2021,
    ULTRACOOLSHEET,
    HUNT_REFFERT_2024,
    MAGELLANIC_CLOUDS,
    BAILER_JONES_2021,
)


def at(arcsec: float, angle: float = 0.0) -> tuple[float, float]:
    return offset(RA, DEC, arcsec, angle)


NO_ORBITS = build_orbits([])


def gaia_stars(rows: list[dict]) -> pa.Table:
    """Gaia rows with every downloaded and joined column; the others are null."""
    columns = {}
    for name in (
        *gaia.COLUMNS,
        *gaia.ASTROPHYSICAL_COLUMNS,
        *gaia.GSPSPEC_CALIBRATED,
        *gaia.XGBOOST_COLUMNS,
    ):
        kind = (
            pa.int64() if name == "source_id" else POINT_SOURCE.schema.field(name).type
        )
        columns[name] = pa.array([row.get(name) for row in rows], kind)
    for name in gaia_orbits.COLUMNS:
        kind = BINARY_ORBIT.schema.field(name).type
        columns[name] = pa.array([row.get(name) for row in rows], kind)
    return pa.table(columns)


def gaia_star(source_id: int, ra: float, dec: float, g: float) -> dict:
    return {
        "source_id": source_id,
        "ra": ra,
        "dec": dec,
        "ra_error": 0.03,
        "dec_error": 0.04,
        "parallax": 10.0,
        "parallax_error": 0.05,
        "pmra": 0.0,
        "pmdec": 0.0,
        "phot_g_mean_mag": g,
    }


def fidelity(rows: list[tuple[int, float]]) -> pa.Table:
    return pa.table(
        {
            "source_id": pa.array([r[0] for r in rows], pa.int64()),
            "fidelity_v2": pa.array([r[1] for r in rows], pa.float32()),
            "norm_dg": pa.array([0.0] * len(rows), pa.float32()),
        }
    )


def astrophysical(ids: list[int], **values: list) -> pa.Table:
    """An astrophysical parameters chunk; the columns not given are null."""
    columns = {"source_id": pa.array(ids, pa.int64())}
    for name in gaia.ASTROPHYSICAL_COLUMNS:
        kind = POINT_SOURCE.schema.field(name).type
        columns[name] = pa.array(values.get(name, [None] * len(ids)), kind)
    return pa.table(columns)


def xgboost(rows: list[tuple[int, float, bool]]) -> pa.Table:
    """XGBoost rows: source_id, [M/H] and the vetted flag; the rest are null."""
    columns = {"source_id": pa.array([r[0] for r in rows], pa.int64())}
    for name in gaia.XGBOOST_COLUMNS:
        kind = POINT_SOURCE.schema.field(name).type
        columns[name] = pa.nulls(len(rows), kind)
    columns["mh_xgboost"] = pa.array([r[1] for r in rows], pa.float32())
    columns["in_vetted_rgb_sample"] = pa.array([r[2] for r in rows])
    return pa.table(columns)


def hip_stars(rows: list[dict]) -> pa.Table:
    """Rows as `hipparcos.read_stars` gives them, at rest at J1991.25.

    A row without "ra" is an entry that the new reduction drops: it has
    "ra_hms" and "dec_dms", and no astrometry.
    """
    float_names = [
        name
        for name in (
            *hipparcos.HIP2_FIELDS.values(),
            *hipparcos.HIP_MAIN_FIELDS.values(),
            "hp_max",
            "hp_min",
        )
        if name not in ("hip", "hd", "sp_type")
    ]
    astrometry = set(hipparcos.HIP2_FIELDS.values())
    columns = {"hip": pa.array([r["hip"] for r in rows], pa.int64())}
    for name in float_names:
        columns[name] = pa.array(
            [
                None
                if name in astrometry and "ra" not in r
                else r.get(name, 0.0 if "error" in name or "pm" in name else None)
                for r in rows
            ],
            pa.float64(),
        )
    for name in ("ra", "dec"):
        columns[f"{name}_rad"] = pa.array(
            [np.radians(r[name]) if name in r else None for r in rows], pa.float64()
        )
    for name in ("sp_type", "ra_hms", "dec_dms", "hvar_type", "xhip_name"):
        columns[name] = pa.array([r.get(name) for r in rows], pa.string())
    columns["hd"] = pa.array([r.get("hd") for r in rows], pa.int64())
    for name in ("feh_xhip", "feh_xhip_error"):
        columns[name] = pa.array([r.get(name) for r in rows], pa.float64())
    columns["feh_xhip_quality"] = pa.array(
        [r.get("feh_xhip_quality") for r in rows], pa.string()
    )
    return pa.table(columns)


def hms(ra: float) -> str:
    """RA in degrees as the "h m s" text of hip_main."""
    hours, rest = divmod(round(ra / 15 * 3600, 2), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{int(hours):02d} {int(minutes):02d} {seconds:05.2f}"


def dms(dec: float) -> str:
    """Dec in degrees as the "±d m s" text of hip_main."""
    degrees, rest = divmod(round(abs(dec) * 3600, 1), 3600)
    minutes, seconds = divmod(rest, 60)
    sign = "-" if dec < 0 else "+"
    return f"{sign}{int(degrees):02d} {int(minutes):02d} {seconds:04.1f}"


def iau_entry(name: str, **more: str) -> dict:
    entry = dict.fromkeys(("HIP", "Designation", "RA", "DEC", "mag", "band"), "")
    entry[names.iau_names.NAME_COLUMN] = name
    return entry | more


def item(
    qid: str, label: str | None = None, articles: int = 1, **ids: tuple[str, ...]
) -> StarItem:
    return StarItem(
        qid=qid,
        gaia_dr3=ids.get("gaia", ()),
        hip=ids.get("hip", ()),
        hd=ids.get("hd", ()),
        label_en=label,
        label_mul=None,
        articles=articles,
    )


def write_names(path: Path, entries: list[dict]) -> Path:
    path.write_text(json.dumps(entries))
    return path


class TestTables:
    """The source names and columns that the table definitions expect."""

    def test_every_gaia_column_is_stored(self):
        stored = set(POINT_SOURCE.schema.names)
        dropped = set(gaia_source.COLUMNS) - stored
        assert dropped == {"source_id", "parallax_over_error"}
        assert {"fidelity_v2", "norm_dg", "epoch"} <= stored

    def test_the_sources_feed_their_groups(self):
        for table in (*TABLES, METADATA):
            for group in table.groups:
                assert set(group.sources) <= {
                    GAIA_DR3.name,
                    GAIA_DR3_NAMED.name,
                    HIPPARCOS.name,
                    HIPPARCOS_1997.name,
                    SIMBAD.name,
                    IAU_WGSN.name,
                    *(source.name for source in EXOPLANET_SOURCES),
                    WIKIDATA.name,
                    *(source.name for source in DISTANCE_SOURCES),
                }
        distance = {g.name: g for g in POINT_SOURCE.groups}["distance"]
        assert distance.sources == tuple(source.name for source in DISTANCE_SOURCES)
        # A planet host shows the name that its planets' designations use.
        assert METADATA.groups[0].sources == (
            IAU_WGSN.name,
            *(source.name for source in EXOPLANET_SOURCES),
            WIKIDATA.name,
            SIMBAD.name,
            HIPPARCOS.name,
            HIPPARCOS_1997.name,
            GAIA_DR3.name,
            GAIA_DR3_NAMED.name,
        )

    def test_the_joined_catalogues_fill_their_groups(self):
        groups = {group.name: group for group in POINT_SOURCE.groups}
        for name, columns in (
            ("pastel", pastel.COLUMNS),
            ("apogee", apogee.COLUMNS),
            ("lamost", lamost.COLUMNS),
        ):
            assert groups[name].names == list(columns)
        assert gaia.JOINED_COLUMNS == (
            *pastel.COLUMNS,
            *apogee.COLUMNS,
            *lamost.COLUMNS,
        )
        assert hipparcos.PASTEL_COLUMNS == pastel.COLUMNS
        assert groups["pastel"].sources == (
            GAIA_DR3.name,
            GAIA_DR3_NAMED.name,
            HIPPARCOS.name,
            HIPPARCOS_1997.name,
        )


class TestGaiaRows:
    """The fidelity join, the mint flags and the Hipparcos claims."""

    def test_fidelity_join_and_mint_flags(self):
        table = gaia_stars([gaia_star(i, RA, DEC, 5.0) for i in (1, 2, 3)])
        # Fidelity rows in another order; star 2 has none.
        joined = gaia.join_fidelity(table, fidelity([(3, 0.2), (1, 0.9)]))
        rows = gaia.engine_rows(
            joined, BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64))
        )
        assert rows["fidelity_v2"].to_pylist() == pytest.approx([0.9, None, 0.2])
        assert rows["mint"].to_pylist() == [True, True, False]
        assert rows["catalogue_id"].to_pylist() == ["1", "2", "3"]
        assert rows["name"].to_pylist()[0] == "Gaia DR3 1"
        assert rows["epoch"].to_pylist() == [2016.0] * 3
        assert rows["match_error"].to_pylist()[0] == pytest.approx(5e-5)

    def test_a_best_neighbour_claims_its_hip_number(self):
        table = gaia_stars([gaia_star(i, RA, DEC, 5.0) for i in (7, 8)])
        best = BestNeighbours(np.array([5, 8]), np.array([41, 42]))
        rows = gaia.engine_rows(gaia.join_fidelity(table, fidelity([])), best)
        assert rows["claims"].to_pylist() == [
            None,
            [{"catalogue": "hip", "release": "2007", "catalogue_id": "42"}],
        ]

    def test_pixel_ranges(self):
        assert gaia_source.pixel_range("GaiaSource_000012-003111.parquet") == (12, 3111)
        assert gaia_source.pixel_range("GaiaSource_000000-000001.csv.gz") == (0, 1)
        pixel = int(gaia.sky.cells(np.array([RA]), np.array([DEC]), 8)[0])
        inside = gaia.in_ranges(
            np.array([RA]), np.array([DEC]), [(0, 1), (pixel, pixel)]
        )
        assert inside.tolist() == [True]

    def test_parameter_join_preserves_order_missing_values_and_bounds(self, tmp_path):
        reader = gaia.GaiaReader(
            BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64)),
            source_dir=tmp_path,
            fidelity_dir=tmp_path,
            astrophysical_dir=tmp_path,
            xgboost_dir=tmp_path,
            orbits=NO_ORBITS,
        )
        path = tmp_path / "GaiaSource_000001-000002.parquet"
        stars = gaia_stars([gaia_star(i, RA, DEC, 5.0) for i in (1, 2, 3)])
        pq.write_table(stars.select(gaia.COLUMNS), path)
        pq.write_table(
            fidelity([(1, 0.9), (2, 0.9), (3, 0.9)]), reader.fidelity_path(path)
        )
        given = {
            "radius_gspphot": [0.2, 2.0],
            "radius_gspphot_lower": [0.1, 1.8],
            "radius_gspphot_upper": [0.3, 2.2],
            "lum_flame": [0.004, 30.0],
            "mass_flame": [None, 1.4],
            "evolstage_flame": [None, 512],
            "flags_flame": ["20", "10"],
        }
        pq.write_table(astrophysical([3, 1], **given), reader.astrophysical_path(path))
        pq.write_table(xgboost([]), reader.xgboost_path(path))
        (rows,) = reader.batches([path])
        assert rows["catalogue_id"].to_pylist() == ["1", "2", "3"]
        for name, (third, first) in given.items():
            expected = [first, None, third]
            if isinstance(first, float):
                expected = pytest.approx(expected)
            assert rows[name].to_pylist() == expected, name
        assert rows["radius_flame"].to_pylist() == [None, None, None]

    def test_missing_radius_chunk_fails_before_reading(self, tmp_path):
        reader = gaia.GaiaReader(
            BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64)),
            fidelity_dir=tmp_path,
            astrophysical_dir=tmp_path,
            xgboost_dir=tmp_path,
            orbits=NO_ORBITS,
        )
        path = tmp_path / "GaiaSource_000001-000002.parquet"
        pq.write_table(fidelity([]), reader.fidelity_path(path))
        pq.write_table(xgboost([]), reader.xgboost_path(path))
        with pytest.raises(
            FileNotFoundError, match="no astrophysical parameters chunk"
        ):
            list(reader.batches([path]))

    def test_xgboost_join_keeps_stars_without_a_row(self, tmp_path):
        reader = gaia.GaiaReader(
            BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64)),
            source_dir=tmp_path,
            fidelity_dir=tmp_path,
            astrophysical_dir=tmp_path,
            xgboost_dir=tmp_path,
            orbits=NO_ORBITS,
        )
        path = tmp_path / "GaiaSource_000001-000002.parquet"
        stars = gaia_stars([gaia_star(i, RA, DEC, 5.0) for i in (1, 2, 3)])
        pq.write_table(stars.select(gaia.COLUMNS), path)
        pq.write_table(
            fidelity([(1, 0.9), (2, 0.9), (3, 0.9)]), reader.fidelity_path(path)
        )
        pq.write_table(astrophysical([]), reader.astrophysical_path(path))
        pq.write_table(
            xgboost([(3, -1.25, True), (1, 0.125, False)]), reader.xgboost_path(path)
        )
        [rows] = list(reader.batches([path]))
        assert rows["mh_xgboost"].to_pylist() == [0.125, None, -1.25]
        assert rows["in_vetted_rgb_sample"].to_pylist() == [False, None, True]
        assert reader.counts["xgboost"] == 2

    def test_orbit_join_and_counts(self, tmp_path):
        orbits = build_orbits(
            [
                solution(3, "Orbital", parallax=10.5),
                solution(3, "SB1"),
                solution(2, "SB1"),
                # Not among the stars.
                solution(4, "EclipsingBinary"),
            ]
        )
        reader = gaia.GaiaReader(
            BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64)),
            source_dir=tmp_path,
            fidelity_dir=tmp_path,
            astrophysical_dir=tmp_path,
            xgboost_dir=tmp_path,
            orbits=orbits,
        )
        path = tmp_path / "GaiaSource_000000-000002.parquet"
        stars = gaia_stars([gaia_star(i, RA, DEC, 5.0) for i in (1, 2, 3)])
        pq.write_table(stars.select(gaia.COLUMNS), path)
        pq.write_table(
            fidelity([(1, 0.9), (2, 0.2), (3, 0.9)]), reader.fidelity_path(path)
        )
        pq.write_table(astrophysical([]), reader.astrophysical_path(path))
        pq.write_table(xgboost([]), reader.xgboost_path(path))
        [rows] = list(reader.batches([path]))
        assert rows["nss_solution_type"].to_pylist() == [None, "SB1", "Orbital"]
        assert rows["parallax_nss"].to_pylist() == [None, None, 10.5]
        assert rows["parallax"].to_pylist() == [10.0] * 3
        assert (reader.counts["orbits"], reader.counts["flagged_orbits"]) == (2, 1)
        assert reader.orbit_report["joined"] == 2
        assert reader.orbit_report["left_out_by_pair"] == {"Orbital over SB1": 1}
        assert reader.orbit_report["outside"] == 1

    def test_missing_xgboost_chunk_fails_before_reading(self, tmp_path):
        reader = gaia.GaiaReader(
            BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64)),
            fidelity_dir=tmp_path,
            astrophysical_dir=tmp_path,
            xgboost_dir=tmp_path,
            orbits=NO_ORBITS,
        )
        path = tmp_path / "GaiaSource_000001-000002.parquet"
        pq.write_table(fidelity([]), reader.fidelity_path(path))
        pq.write_table(astrophysical([]), reader.astrophysical_path(path))
        with pytest.raises(FileNotFoundError, match="no XGBoost parameters chunk"):
            list(reader.batches([path]))


class TestHipparcos:
    """Epoch propagation, the G estimate, designations and the rows."""

    def test_propagation_matches_astropy(self):
        ra = np.array([269.45, 10.0, 200.0, 0.1])
        dec = np.array([4.69, 89.9, -60.0, 0.0])
        pmra = np.array([-797.8, 5000.0, -3775.4, 0.0])
        pmdec = np.array([10326.9, -2000.0, 769.3, 1000.0])
        moved_ra, moved_dec = hipparcos.propagate(ra, dec, pmra, pmdec, 24.75)
        start = SkyCoord(
            ra=ra * u.deg,
            dec=dec * u.deg,
            pm_ra_cosdec=pmra * u.mas / u.yr,
            pm_dec=pmdec * u.mas / u.yr,
            distance=10 * u.pc,
            radial_velocity=0 * u.km / u.s,
            obstime=Time(1991.25, format="jyear"),
        )
        expected = start.apply_space_motion(new_obstime=Time(2016.0, format="jyear"))
        apart = SkyCoord(moved_ra * u.deg, moved_dec * u.deg).separation(expected)
        assert apart.to_value(u.mas).max() < 1.0
        assert moved_dec[3] * 3600 == pytest.approx(24.75, abs=1e-6)

    def test_g_estimate(self):
        g = hipparcos.g_estimate(
            np.array([5.0, 5.0, np.nan, np.nan, 5.0, 5.0, 5.0]),
            np.array([0.0, 1.0, 0.5, np.nan, 2.4, 3.0, -0.4]),
            np.array([5.5, 5.5, 6.0, np.nan, 5.5, 5.5, 5.5]),
        )
        assert g[0] == pytest.approx(5.0 - 0.02907)
        assert g[1] == pytest.approx(5.0 - 0.02907 - 0.02385 - 0.2297 - 0.001768)
        assert g[2] == pytest.approx(6.0 - 0.28)
        assert np.isnan(g[3])
        # B − V is clipped to the fit range of the relation.
        assert g[5] == pytest.approx(g[4])
        assert g[6] == pytest.approx(
            5.0 - 0.02907 + 0.02385 * 0.3 - 0.2297 * 0.09 + 0.001768 * 0.027
        )

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("9 Alpha Canis Majoris (Sirius)", "Alpha Canis Majoris"),
            ("24 Nu-1 Draconis (Kuma)", "Nu1 Draconis"),
            ("Tau Phoenicis", "Tau Phoenicis"),
            ("29 Piscium", "29 Piscium"),
            ("98 k Tauri", "98 Tauri"),
            ("21 YZ Cassiopeiae", "21 Cassiopeiae"),
            ("c Puppis", "c Puppis"),
            ("b2 Persei (HR 1333)", "b2 Persei"),
            ("27 Comae Berenices (HR 4851)", "27 Comae Berenices"),
            ("HR 9079", None),
            ("Gliese 551 C (Proxima Cen)", None),
            ("CG Andromedae", None),
            ("Barnard's Star", None),
            (None, None),
        ],
    )
    def test_designation(self, name, expected):
        assert hipparcos.designation(name) == expected

    def test_rows_claims_and_names(self):
        table = hip_stars(
            [
                {
                    "hip": 1,
                    "ra": RA,
                    "dec": DEC,
                    "v_mag": 5.0,
                    "b_v": 0.0,
                    "hd": 100,
                    "xhip_name": "58 Alpha Orionis (Betelgeuse)",
                },
                {"hip": 2, "ra": RA, "dec": DEC, "v_mag": 6.0, "b_v": 0.0, "hd": 200},
                # HD 300 is on two stars.
                {
                    "hip": 3,
                    "ra": RA,
                    "dec": DEC,
                    "v_mag": 7.0,
                    "hd": 300,
                    "hp_mag": 7.3,
                },
                {"hip": 4, "ra": RA, "dec": DEC, "hd": 300, "pmdec": 1000.0},
            ]
        )
        best = BestNeighbours(np.array([77]), np.array([2]))
        rows, rough = hipparcos.engine_rows(table, best)
        assert rough.num_rows == 0
        assert rows["name"].to_pylist() == ["Alpha Orionis", "HD 200", "HIP 3", "HIP 4"]
        claims = [
            [
                f"{c['catalogue']}/{c['release']}/{c['catalogue_id']}"
                for c in found or []
            ]
            for found in rows["claims"].to_pylist()
        ]
        assert claims == [["hd/1949/100"], ["gaia/dr3/77", "hd/1949/200"], [], []]
        assert rows["mint"].to_pylist() == [True] * 4
        assert rows["epoch"].to_pylist() == [1991.25] * 4
        assert rows["ra"].to_pylist()[0] == pytest.approx(RA)
        assert rows["match_mag"].to_pylist()[:3] == pytest.approx(
            [5.0 - 0.02907, 6.0 - 0.02907, 7.3 - 0.28]
        )
        assert rows["match_mag"].to_pylist()[3] is None
        moved = rows["match_dec"].to_pylist()[3] - DEC
        assert moved * 3600 == pytest.approx(24.75, rel=1e-3)

    def test_a_red_or_variable_star_matches_without_its_magnitude(self):
        table = hip_stars(
            [
                {"hip": 1, "ra": RA, "dec": DEC, "v_mag": 5.0, "b_v": 1.4, "v_i": 3.2},
                {
                    "hip": 2,
                    "ra": RA,
                    "dec": DEC,
                    "v_mag": 5.0,
                    "b_v": 0.0,
                    "hp_max": 4.0,
                    "hp_min": 6.0,
                    "hvar_type": "P",
                },
                # The change of Hp comes from duplicity.
                {
                    "hip": 3,
                    "ra": RA,
                    "dec": DEC,
                    "v_mag": 5.0,
                    "b_v": 0.0,
                    "hp_max": 4.0,
                    "hp_min": 6.0,
                    "hvar_type": "D",
                },
                {
                    "hip": 4,
                    "ra": RA,
                    "dec": DEC,
                    "v_mag": 5.0,
                    "b_v": 0.0,
                    "hp_max": 4.0,
                    "hp_min": 6.0,
                },
                {"hip": 5, "ra": RA, "dec": DEC, "v_mag": 5.0, "b_v": 0.0, "v_i": 2.4},
                # A rough row keeps its estimate.
                {
                    "hip": 6,
                    "ra_hms": hms(RA),
                    "dec_dms": dms(DEC),
                    "v_mag": 5.0,
                    "b_v": 0.0,
                    "v_i": 3.2,
                },
            ]
        )
        rows, rough = hipparcos.engine_rows(
            table, BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64))
        )
        estimate = pytest.approx(5.0 - 0.02907)
        assert rows["match_mag"].to_pylist() == [None, None, *[estimate] * 3]
        assert rough["match_mag"].to_pylist() == [estimate]

    def test_sexagesimal(self):
        values = hipparcos.sexagesimal(
            pa.array(["06 45 08.92", "-16 42 58.0", "-00 30 00.0", " +00 00 36.0"])
        )
        assert values == pytest.approx(
            [6 + 45 / 60 + 8.92 / 3600, -(16 + 42 / 60 + 58 / 3600), -0.5, 0.01]
        )

    def test_rough_rows_of_the_dropped_entries(self):
        table = hip_stars(
            [
                {"hip": 1, "ra": RA, "dec": DEC, "v_mag": 5.0, "b_v": 0.0, "hd": 300},
                {
                    "hip": 2,
                    "ra_hms": hms(RA),
                    "dec_dms": dms(DEC),
                    "v_mag": 6.0,
                    "b_v": 0.0,
                    "hd": 200,
                },
                # HD 300 is on a star of the new reduction too.
                {
                    "hip": 3,
                    "ra_hms": hms(RA),
                    "dec_dms": dms(-DEC),
                    "v_mag": 7.0,
                    "hp_mag": 7.3,
                    "hd": 300,
                },
            ]
        )
        best = BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64))
        rows, rough = hipparcos.engine_rows(table, best)
        assert rows["catalogue_id"].to_pylist() == ["1"]
        assert rough["catalogue_id"].to_pylist() == ["2", "3"]
        apart = gaia.sky.separation(
            rough["match_ra"].to_numpy(),
            rough["match_dec"].to_numpy(),
            np.array([RA, RA]),
            np.array([DEC, -DEC]),
        )
        assert (apart < 0.1).all()
        assert rough["ra"].to_pylist() == pytest.approx(rough["match_ra"].to_pylist())
        assert rough["match_error"].to_pylist() == [4.0, 4.0]
        assert rough["match_mag"].to_pylist() == pytest.approx(
            [6.0 - 0.02907, 7.3 - 0.28]
        )
        assert rough["parallax"].null_count == rough["pmra"].null_count == 2
        assert rough["epoch"].to_pylist() == [1991.25] * 2
        assert rough["name"].to_pylist() == ["HD 200", "HIP 3"]
        assert rough["claims"].to_pylist() == [
            [{"catalogue": "hd", "release": "1949", "catalogue_id": "200"}],
            None,
        ]
        assert rows["claims"].to_pylist() == [None]

    def test_read_stars_joins_the_three_catalogues(self, tmp_path):
        def catalogue(directory: str, *files: tuple[str, list[str], list[str]]):
            readme = []
            path = tmp_path / directory
            path.mkdir()
            for file, fields, lines in files:
                readme += [
                    f"Byte-by-byte Description of file: {file.removesuffix('.gz')}",
                    "-" * 80,
                    "Bytes",
                    "-" * 80,
                ]
                for at, label in enumerate(fields):
                    start = 1 + 12 * at
                    kind = (
                        "I6"
                        if label in ("HIP", "HD")
                        else "A11"
                        if label
                        in ("SpType", "Name", "q_[Fe/H]", "RAhms", "DEdms", "HvarType")
                        else "F11.4"
                    )
                    readme.append(
                        f"{start:4d}-{start + 10:3d}  {kind:6s} ---  {label}  x"
                    )
                readme.append("-" * 80)
                content = ("\n".join(lines) + "\n").encode()
                if file.endswith(".gz"):
                    content = gzip.compress(content)
                (path / file).write_bytes(content)
            (path / README).write_text("\n".join(readme) + "\n")
            return path

        def line(*values: object) -> str:
            return " ".join(f"{'' if v is None else v:>11}" for v in values)

        hip2_fields = list(hipparcos.HIP2_FIELDS)
        main_fields = [*hipparcos.HIP_MAIN_FIELDS, *hipparcos.HIP_MAIN_MATCH_FIELDS]
        hip2 = catalogue(
            "hip2",
            (
                hipparcos.HIP2_FILE,
                hip2_fields,
                [line(1, 0.1, 0.2, *[1.0] * 8), line(2, 0.3, 0.4, *[2.0] * 8)],
            ),
        )
        main = catalogue(
            "main",
            (
                hipparcos.HIP_MAIN_FILE,
                main_fields,
                [
                    line(
                        2, 4.0, 0.01, 4.1, 0.5, 0.01, 0.6, 0.01, "G2V", 200, *[None] * 5
                    ),
                    line(
                        1,
                        3.0,
                        0.01,
                        3.1,
                        0.4,
                        0.01,
                        0.5,
                        0.01,
                        "K0III",
                        None,
                        *[None] * 5,
                    ),
                    # The new reduction drops it.
                    line(
                        9,
                        1.0,
                        0.01,
                        1.1,
                        0.1,
                        0.01,
                        0.1,
                        0.01,
                        "B0",
                        900,
                        "12 00 00.00",
                        "-45 00 00.0",
                        0.9,
                        1.3,
                        "D",
                    ),
                ],
            ),
        )
        xhip = catalogue(
            "xhip",
            (hipparcos.XHIP_FILE, ["HIP", "Name"], [line(2, "Tau Ceti")]),
            (
                hipparcos.XHIP_MAIN_FILE,
                list(hipparcos.XHIP_METALLICITY_FIELDS),
                [line(2, -0.5, 9.99, "C"), line(1, 0.1, 0.05, "A")],
            ),
        )
        table = hipparcos.read_stars(hip2, main, xhip)
        assert table["hip"].to_pylist() == [1, 2, 9]
        assert table["sp_type"].to_pylist() == ["K0III", "G2V", "B0"]
        assert table["hd"].to_pylist() == [None, 200, 900]
        assert table["xhip_name"].to_pylist() == [None, "Tau Ceti", None]
        assert table["ra_rad"].to_pylist() == [0.1, 0.3, None]
        assert table["ra_hms"].to_pylist() == [None, None, "12 00 00.00"]
        assert table["hp_min"].to_pylist() == [None, None, 1.3]
        assert table["hvar_type"].to_pylist() == [None, None, "D"]
        assert table["feh_xhip"].to_pylist() == [0.1, -0.5, None]
        # 9.99 means no error.
        assert table["feh_xhip_error"].to_pylist() == [0.05, None, None]
        assert table["feh_xhip_quality"].to_pylist() == ["A", "C", None]


class TestNames:
    """Claims, positions and magnitudes of the IAU names."""

    def test_rows(self, tmp_path):
        path = write_names(
            tmp_path / "names.json",
            [
                iau_entry("Izar", HIP="72105", mag="2.45", RA="1", DEC="2"),
                iau_entry("Pulcherrima", HIP="72105", mag="4.80", RA="1", DEC="2.001"),
                iau_entry(
                    "Stella", Designation="HD 116798", RA="3", DEC="4", mag="7.6"
                ),
                iau_entry("Dusty", RA="5", DEC="6", mag="11.7", band="K"),
                # A wrong listed position gives way to the HIP position.
                iau_entry("Moved", HIP="11", RA="50", DEC="60"),
                iau_entry("Lost", Designation="WASP-121"),
            ],
        )
        rows = names.engine_rows({"11": (7.0, 8.0)}, path)
        assert rows["catalogue_id"].to_pylist() == [
            "Izar",
            "Pulcherrima",
            "Stella",
            "Dusty",
            "Moved",
        ]
        assert rows["claims"].to_pylist() == [
            [{"catalogue": "hip", "release": "2007", "catalogue_id": "72105"}],
            None,
            [{"catalogue": "hd", "release": "1949", "catalogue_id": "116798"}],
            None,
            [{"catalogue": "hip", "release": "2007", "catalogue_id": "11"}],
        ]
        assert rows["match_mag"].to_pylist() == pytest.approx(
            [2.45, 4.8, 7.6, None, None]
        )
        assert rows["match_ra"].to_pylist()[0] == 1.0
        assert (rows["match_ra"][4].as_py(), rows["match_dec"][4].as_py()) == (7.0, 8.0)
        assert rows["mint"].to_pylist() == [False] * 5
        assert rows["name"].to_pylist() == rows["catalogue_id"].to_pylist()


class TestWikidata:
    """The claim, position and name of each Wikidata item."""

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Teegarden's Star", "Teegarden's Star"),
            ("NAME Barnard's Star", "Barnard's Star"),
            ("T Tauri", "T Tauri"),
            ("Gliese 105", "Gliese 105"),
            ("CD Ceti", "CD Ceti"),
            ("Gaia BH1", "Gaia BH1"),
            ("HD 19121", None),
            ("HR 926", None),
            ("HIP 17453", None),
            ("BD +20°307", None),
            ("BD+21 255", None),
            ("2MASS J03140344+1603056", None),
            ("2MASSW J0208183+254253", None),
            ("TYC 1234-567-1", None),
            ("Gaia DR3 4472832130942575872", None),
            ("V* R Leo", None),
            ("** STF 123", None),
            (None, None),
        ],
    )
    def test_label_name(self, label, expected):
        assert wikidata.label_name(item("Q1", label)) == expected

    def test_the_multilingual_label_stands_in_for_english(self):
        named = dataclasses.replace(item("Q1", None), label_mul="Wolf 359")
        assert wikidata.label_name(named) == "Wolf 359"

    def test_one_claim_hipparcos_first(self):
        hip = {"10": (1.0, 2.0)}
        hd = {"300": (5.0, 6.0)}
        proxima = 5853498713190525696
        items = [
            item("Q1", "A", hip=("10",), gaia=(str(proxima),)),
            # Two Gaia sources: the HD number decides.
            item("Q2", "B", gaia=("1", "2"), hd=("300",)),
            item("Q3", "C", gaia=(str(proxima + 1),)),
            # A HIP number with no Hipparcos row gives way to the Gaia id.
            item("Q4", "D", hip=("99",), gaia=(str(proxima),)),
            item("Q5", "E", hip=("10", "11")),
            item("Q6", "F", hd=("404",)),
            # A second item of HD 300 with more articles: the engine gives the
            # star to the first row, so it comes first.
            item("Q7", "Gamma", articles=9, hd=("300",)),
        ]
        rows = wikidata.engine_rows(items, hip, hd)
        assert rows["catalogue_id"].to_pylist() == ["Q7", "Q1", "Q2", "Q3", "Q4"]
        hd_300 = {"catalogue": "hd", "release": "1949", "catalogue_id": "300"}
        assert [claims[0] for claims in rows["claims"].to_pylist()] == [
            hd_300,
            {"catalogue": "hip", "release": "2007", "catalogue_id": "10"},
            hd_300,
            {"catalogue": "gaia", "release": "dr3", "catalogue_id": str(proxima + 1)},
            {"catalogue": "gaia", "release": "dr3", "catalogue_id": str(proxima)},
        ]
        assert (
            rows["match_ra"][1].as_py() == 1.0 and rows["match_dec"][0].as_py() == 6.0
        )
        # The centre of the Gaia id's level-12 pixel, 0.03° from Proxima.
        assert rows["match_ra"][3].as_py() == pytest.approx(217.43, abs=0.1)
        assert rows["match_dec"][3].as_py() == pytest.approx(-62.68, abs=0.05)
        assert rows["mint"].to_pylist() == [False] * 5
        assert rows["name"].to_pylist() == ["Gamma", "A", "B", "C", "D"]

    def test_most_articles_first_then_lowest_qid(self):
        hip = {str(n): (1.0, 2.0) for n in range(1, 5)}
        items = [
            item("Q100", articles=2, hip=("1",)),
            item("Q20", articles=2, hip=("2",)),
            item("Q3", articles=1, hip=("3",)),
            item("Q9", articles=12, hip=("4",)),
        ]
        rows = wikidata.engine_rows(items, hip, {})
        assert rows["catalogue_id"].to_pylist() == ["Q9", "Q20", "Q100", "Q3"]

    def test_hd_positions(self):
        rows = pa.table(
            {
                "match_ra": [1.0, 3.0],
                "match_dec": [2.0, 4.0],
                "claims": pa.array(
                    [
                        [
                            {
                                "catalogue": "gaia",
                                "release": "dr3",
                                "catalogue_id": "7",
                            },
                            {"catalogue": "hd", "release": "1949", "catalogue_id": "8"},
                        ],
                        None,
                    ],
                    pa.list_(wikidata.CROSS_ID),
                ),
            }
        )
        assert wikidata.hd_positions(rows) == {"8": (1.0, 2.0)}


class TestStarIngest:
    """Gaia, Hipparcos, the names and Wikidata through the engine."""

    def run(
        self, root: Path, names_path: Path, items: list[StarItem] | None = None
    ) -> IngestResult:
        p = {key: at(60 * key) for key in range(1, 10)}
        table = gaia_stars(
            [
                gaia_star(1, *p[1], 5.0),
                gaia_star(2, *p[2], 6.0),
                gaia_star(3, *p[3], 7.0),
                gaia_star(4, *p[4], 8.0),
                gaia_star(5, *p[5], 9.0),
                gaia_star(6, *p[6], 4.0),
                # 6″ from the rough position of HIP 70, 0.4 mag under its light.
                gaia_star(7, *offset(*p[7], 6, 90), 6.4),
                # 0.1″ from HIP 50, 1.5 mag over its estimate.
                gaia_star(8, *offset(*p[8], 0.1, 0), 3.0),
            ]
        )
        best = BestNeighbours(np.array([1, 2, 99]), np.array([10, 20, 40]))
        flags = fidelity(
            [(1, 0.9), (2, 0.2), (3, 0.9), (4, 0.3), (6, 0.9), (7, 0.9), (8, 0.9)]
        )
        orbits = build_orbits([solution(3, "Orbital", parallax=10.25)])
        table = orbits.join(table.drop_columns(list(gaia_orbits.COLUMNS)))
        gaia_rows = gaia.engine_rows(gaia.join_fidelity(table, flags), best)
        far = at(900)
        hip, rough = hipparcos.engine_rows(
            hip_stars(
                [
                    {
                        "hip": 10,
                        "ra": p[1][0],
                        "dec": p[1][1],
                        "v_mag": 5.0,
                        "b_v": 0.0,
                    },
                    {
                        "hip": 20,
                        "ra": p[2][0],
                        "dec": p[2][1],
                        "v_mag": 6.0,
                        "b_v": 0.0,
                        "xhip_name": "58 Alpha Orionis (Betelgeuse)",
                    },
                    # No best neighbour: 0.5″ from Gaia 3, same magnitude.
                    {
                        "hip": 30,
                        "ra": at(180.5)[0],
                        "dec": at(180.5)[1],
                        "v_mag": 7.0,
                        "b_v": 0.0,
                        "hd": 300,
                    },
                    # Its best neighbour is not stored; Gaia 6 sits on it.
                    {
                        "hip": 40,
                        "ra": p[6][0],
                        "dec": p[6][1],
                        "v_mag": 4.0,
                        "b_v": 0.0,
                    },
                    {
                        "hip": 50,
                        "ra": p[8][0],
                        "dec": p[8][1],
                        "v_mag": 5.0,
                        "b_v": 1.4,
                        "v_i": 3.2,
                    },
                    {
                        "hip": 60,
                        "ra": p[9][0],
                        "dec": p[9][1],
                        "v_mag": 8.0,
                        "b_v": 0.0,
                    },
                    {
                        "hip": 70,
                        "ra_hms": hms(p[7][0]),
                        "dec_dms": dms(p[7][1]),
                        "v_mag": 6.0,
                        "b_v": 0.0,
                        "hd": 700,
                    },
                    {
                        "hip": 80,
                        "ra_hms": hms(far[0]),
                        "dec_dms": dms(far[1]),
                        "v_mag": 3.8,
                        "b_v": 0.6,
                    },
                ]
            ),
            best,
        )
        positions = {
            hip_id: (ra, dec)
            for rows in (hip, rough)
            for hip_id, ra, dec in zip(
                rows["catalogue_id"].to_pylist(),
                rows["match_ra"].to_pylist(),
                rows["match_dec"].to_pylist(),
            )
        }
        name_rows = names.engine_rows(positions, names_path)
        item_rows = wikidata.engine_rows(
            items or [],
            positions,
            {**wikidata.hd_positions(hip), **wikidata.hd_positions(rough)},
        )
        with IngestRun.start(root, root / "backup") as run:
            run.add(GAIA_DR3, [gaia_rows])
            run.add(HIPPARCOS, [hip])
            run.add(HIPPARCOS_1997, [rough])
            run.add(IAU_WGSN, [name_rows])
            run.add(WIKIDATA, [item_rows])
            return run.commit()

    def test_ids_names_and_summary(self, tmp_path):
        root = tmp_path / "root"
        five = at(300.3)
        names_path = write_names(
            tmp_path / "names.json",
            [
                iau_entry("Alpha", HIP="10"),
                iau_entry("Beta", RA=str(five[0]), DEC=str(five[1]), mag="9.1"),
                iau_entry("Gamma", RA=str(at(600)[0]), DEC=str(at(600)[1]), mag="3"),
                iau_entry("Delta", HIP="80"),
            ],
        )
        result = self.run(root, names_path)
        counts = result.entry["counts"]
        # Gaia 1, 2 (by HIP 20), 3, 5 to 8 and HIP 60 and 80; Gaia 4 and
        # Gamma stay out.
        assert counts["minted"] == 9 and counts["unminted"] == 2
        assert counts["conflicts"] == 0
        registry = Registry(root)

        def id_of(catalogue: str, release: str, value: object) -> int:
            return int(registry.lookup(catalogue, release, [str(value)])[0])

        def gaia_id(value: int) -> int:
            return id_of("gaia", "dr3", value)

        assert id_of("hip", "2007", 10) == gaia_id(1) != 0
        assert id_of("hip", "2007", 20) == gaia_id(2) != 0
        assert id_of("hip", "2007", 30) == gaia_id(3) != 0
        assert id_of("hd", "1949", 300) == gaia_id(3)
        assert gaia_id(4) == 0
        # The best neighbour that is not stored joins the stored star.
        assert id_of("hip", "2007", 40) == gaia_id(6) == gaia_id(99) != 0
        assert id_of("hip", "2007", 50) == gaia_id(8) != 0
        assert id_of("hip", "2007", 70) == gaia_id(7) == id_of("hd", "1949", 700) != 0
        hip_60, hip_80 = id_of("hip", "2007", 60), id_of("hip", "2007", 80)
        gaia_ids = {gaia_id(n) for n in (1, 2, 3, 5, 6, 7, 8)}
        assert hip_60 not in gaia_ids | {0} and hip_80 not in gaia_ids | {0, hip_60}
        assert id_of("iau", "wgsn", "Beta") == gaia_id(5)
        assert id_of("iau", "wgsn", "Delta") == hip_80

        meta = {row["id"]: row for row in table_rows(root, "metadata").to_pylist()}
        point = {row["id"]: row for row in table_rows(root, "point-source").to_pylist()}
        assert {n: meta[gaia_id(n)]["name"] for n in (1, 2, 3, 5, 6, 7, 8)} == {
            1: "Alpha",
            2: "Alpha Orionis",
            3: "HD 300",
            5: "Beta",
            6: "HIP 40",
            7: "HD 700",
            8: "HIP 50",
        }
        assert meta[hip_60]["name"] == "HIP 60"
        assert meta[hip_60]["class"] == "star"
        assert meta[hip_80]["name"] == "Delta"
        flagged = point[gaia_id(2)]
        assert flagged["astrometry_source"] == "gaia-dr3"
        assert flagged["fidelity_v2"] == pytest.approx(0.2)
        assert flagged["v_mag"] == 6.0 and flagged["epoch"] == 2016.0
        assert point[gaia_id(5)]["fidelity_v2"] is None
        alone = point[hip_60]
        assert alone["astrometry_source"] == "hipparcos-2007"
        assert alone["epoch"] == 1991.25 and alone["phot_g_mean_mag"] is None
        matched = point[gaia_id(7)]
        assert matched["astrometry_source"] == "gaia-dr3"
        assert matched["hipparcos_photometry_source"] == "hipparcos-1997"
        rough = point[hip_80]
        assert rough["astrometry_source"] == "hipparcos-1997"
        assert rough["epoch"] == 1991.25 and rough["parallax"] is None
        assert rough["ra"] == pytest.approx(at(900)[0], abs=1e-4)
        assert {i: meta[i]["mask"] for i in meta} == {
            i: 6 if i == gaia_id(3) else 2 for i in meta
        }
        [orbit] = table_rows(root, "binary-orbit").to_pylist()
        assert orbit["id"] == gaia_id(3)
        assert orbit["nss_solution_type"] == "Orbital"
        assert orbit["parallax_nss"] == 10.25 and orbit["orbit_source"] == "gaia-dr3"
        assert orbit["corr_vec"][0] == 0.5 and orbit["masses_source"] is None

        summary = stars.summary(registry, names.read_names(names_path), 0)
        assert "point-source rows: 9" in summary
        assert "binary-orbit rows: 1" in summary
        assert "Hipparcos stars without a Gaia DR3 row: 2" in summary
        assert "IAU names: 3 placed, 1 unplaced\n  Gamma" in summary
        assert not any(row["object"] for row in meta.values())

        # A rerun mints nothing and keeps every ID.
        again = self.run(root, names_path)
        assert again.entry["counts"]["minted"] == 0
        assert {row["id"] for row in table_rows(root, "metadata").to_pylist()} == set(
            meta
        )

    def test_wikidata_items_name_and_flag_their_stars(self, tmp_path, monkeypatch):
        # The test's Gaia ids hold no pixel: they are placed by hand.
        monkeypatch.setattr(wikidata, "gaia_position", lambda source_id: at(360))
        root = tmp_path / "root"
        names_path = write_names(
            tmp_path / "names.json", [iau_entry("Alpha", HIP="10")]
        )
        items = [
            item("Q1", "Alpha Ceti", hip=("10",)),
            item("Q2", "Betelgeuse", hip=("20",)),
            item("Q3", "HD 300", hip=("30",)),
            item("Q4", "Teegarden's Star", gaia=("6",)),
            # A second item of the star of Q1, by its Gaia id. Of two items
            # with as many articles, the lower QID keeps the star.
            item("Q5", "Alpha", gaia=("1",)),
            # Gaia 4 is not stored: the item reaches no star and mints nothing.
            item("Q6", "Faint", gaia=("4",)),
        ]
        result = self.run(root, names_path, items)
        counts = result.entry["counts"]
        assert counts["minted"] == 9 and counts["conflicts"] == 0
        assert result.entry["sources"][-1]["outranked"] == 1
        assert result.entry["sources"][-1]["permanent"] is False
        registry = Registry(root)

        def id_of(catalogue: str, release: str, value: object) -> int:
            return int(registry.lookup(catalogue, release, [str(value)])[0])

        assert id_of("wikidata", "qid", "Q1") == id_of("hip", "2007", 10) != 0
        assert id_of("wikidata", "qid", "Q4") == id_of("gaia", "dr3", 6) != 0
        assert id_of("wikidata", "qid", "Q5") == 0
        assert id_of("wikidata", "qid", "Q6") == 0
        meta = {row["id"]: row for row in table_rows(root, "metadata").to_pylist()}

        def row(catalogue: str, release: str, value: object) -> dict:
            return meta[id_of(catalogue, release, value)]

        # The IAU name comes first, the Wikidata label before Hipparcos.
        assert row("hip", "2007", 10)["name"] == "Alpha"
        assert row("hip", "2007", 20)["name"] == "Betelgeuse"
        assert row("hip", "2007", 20)["name_source"] == "wikidata"
        assert row("hip", "2007", 30)["name"] == "HD 300"
        assert row("gaia", "dr3", 6)["name"] == "Teegarden's Star"
        assert {id_ for id_, r in meta.items() if r["object"]} == {
            id_of("wikidata", "qid", q) for q in ("Q1", "Q2", "Q3", "Q4")
        }
        assert {
            "catalogue": "wikidata",
            "release": "qid",
            "catalogue_id": "Q2",
        } in row("hip", "2007", 20)["cross_ids"]

        summary = stars.summary(registry, names.read_names(names_path), 6)
        assert "Wikidata items: 4 placed of 6 with a claim" in summary

        found = sorted(read_star_objects(root), key=lambda star: star.qid or "")
        assert [(star.qid, star.name) for star in found] == [
            ("Q1", "Alpha"),
            ("Q2", "Betelgeuse"),
            ("Q3", "HD 300"),
            ("Q4", "Teegarden's Star"),
        ]
        assert found[1].id == id_of("hip", "2007", 20)

    def test_the_item_with_most_articles_keeps_its_star(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wikidata, "gaia_position", lambda source_id: at(60))
        root = tmp_path / "root"
        names_path = write_names(tmp_path / "names.json", [])
        items = [
            # HIP 10 and Gaia 1 are one star; the HD 300 of HIP 30 is Gaia 3's.
            item("Q1", "Gamma2 Arietis", articles=1, hip=("10",)),
            item("Q2", "Gamma Arietis", articles=11, gaia=("1",)),
            item("Q3", "Sirius A", articles=2, hip=("30",)),
            item("Q4", "Sirius", articles=12, hd=("300",)),
        ]
        result = self.run(root, names_path, items)
        assert result.entry["counts"]["conflicts"] == 0
        assert result.entry["sources"][-1]["outranked"] == 2
        registry = Registry(root)

        def id_of(catalogue: str, release: str, value: object) -> int:
            return int(registry.lookup(catalogue, release, [str(value)])[0])

        assert id_of("wikidata", "qid", "Q2") == id_of("hip", "2007", 10) != 0
        assert id_of("wikidata", "qid", "Q4") == id_of("hip", "2007", 30) != 0
        assert id_of("wikidata", "qid", "Q1") == id_of("wikidata", "qid", "Q3") == 0
        meta = {row["id"]: row for row in table_rows(root, "metadata").to_pylist()}
        assert meta[id_of("hip", "2007", 10)]["name"] == "Gamma Arietis"
        assert meta[id_of("hip", "2007", 30)]["name"] == "Sirius"

    def test_wikidata_links_are_made_again_at_each_ingest(self, tmp_path):
        root = tmp_path / "root"
        names_path = write_names(tmp_path / "names.json", [])
        self.run(
            root,
            names_path,
            [
                item("Q1", "Betelgeuse", hip=("10",)),
                item("Q2", "Rigel", hip=("20",)),
                item("Q3", "Old", hip=("30",)),
            ],
        )
        registry = Registry(root)
        hip_10, hip_20, hip_30 = (
            int(registry.lookup("hip", "2007", [n])[0]) for n in ("10", "20", "30")
        )
        # Q1 moves to HIP 20, Q4 takes HIP 10, Q3 is gone.
        again = self.run(
            root,
            names_path,
            [
                item("Q1", "Betelgeuse", hip=("20",)),
                item("Q2", "Rigel", hip=("20",)),
                item("Q4", "Bellatrix", hip=("10",)),
            ],
        )
        counts = again.entry["counts"]
        assert (counts["minted"], counts["merged"], counts["conflicts"]) == (0, 0, 0)
        registry = Registry(root)
        assert registry.lookup(
            "wikidata", "qid", ["Q1", "Q2", "Q3", "Q4"]
        ).tolist() == [
            hip_20,
            0,
            0,
            hip_10,
        ]
        meta = {row["id"]: row for row in table_rows(root, "metadata").to_pylist()}

        def qids(id_: int) -> list[str]:
            return [
                x["catalogue_id"]
                for x in meta[id_]["cross_ids"]
                if x["catalogue"] == "wikidata"
            ]

        assert (qids(hip_10), qids(hip_20), qids(hip_30)) == (["Q4"], ["Q1"], [])
        assert (meta[hip_10]["name"], meta[hip_30]["name"]) == ("Bellatrix", "HD 300")
        assert not meta[hip_30]["object"]
        summary = stars.summary(registry, [], 3)
        assert "Wikidata items: 2 placed of 3 with a claim" in summary
        found = sorted((star.qid, star.id) for star in read_star_objects(root))
        assert found == [("Q1", hip_20), ("Q4", hip_10)]

    def test_a_partial_ingest_refuses_a_complete_registry(self, tmp_path):
        root = tmp_path / "root"
        names_path = write_names(tmp_path / "names.json", [])
        self.run(root, names_path)
        with pytest.raises(RegistryError, match="complete ingest"):
            stars.ingest(root, root / "backup", limit=10)

    def test_a_partial_ingest_refuses_the_default_root(self, tmp_path, monkeypatch):
        default = tmp_path / "registry"
        link = tmp_path / "link"
        link.symlink_to(default, target_is_directory=True)
        monkeypatch.setattr(stars, "REGISTRY_ROOT", default)
        # The refusal comes before the ingest reads its input.
        monkeypatch.setattr(BestNeighbours, "read", lambda: pytest.fail("read"))
        for root in (default, link):
            with pytest.raises(RegistryError, match="default registry"):
                stars.ingest(root, tmp_path / "backup", limit=10)


class TestIngestTarget:
    """The extrasolar and skycultures targets of space-map-ingest."""

    @pytest.fixture
    def calls(self, monkeypatch):
        found: dict[str, list] = {"db": [], "stars": [], "skycultures": [], "order": []}
        monkeypatch.setattr(
            ingest_cli, "ingest_db", lambda *args: found["db"].append(args)
        )

        def fake_ingest(root, backup, limit):
            found["stars"].append((root, backup, limit))
            found["order"].append("extrasolar")
            return IngestResult(1, {}, "the report\n"), "the summary\n"

        def fake_match(root, out):
            found["skycultures"].append((root, out))
            found["order"].append("skycultures")
            return "the cultures\n"

        monkeypatch.setattr(ingest_cli.stars, "ingest", fake_ingest)
        monkeypatch.setattr(ingest_cli.skycultures, "ingest", fake_match)
        return found

    def cli(self, monkeypatch, *args: str) -> None:
        monkeypatch.setattr(sys, "argv", ["space-map-ingest", *args])
        ingest_cli.cli()

    def test_extrasolar_alone_leaves_the_db_alone(
        self, monkeypatch, calls, capsys, tmp_path
    ):
        root = tmp_path / "root"
        self.cli(
            monkeypatch,
            "--targets",
            "extrasolar",
            "--limit",
            "5",
            "--registry-root",
            str(root),
        )
        assert calls["db"] == []
        assert calls["stars"] == [(root, root / "backup", 5)]
        out = capsys.readouterr().out
        assert "the report" in out and "the summary" in out

    def test_the_default_root_backs_up_to_the_nas(self, monkeypatch, calls):
        self.cli(monkeypatch, "--targets", "extrasolar")
        assert calls["stars"] == [(REGISTRY_ROOT, REGISTRY_BACKUP_DIR, None)]

    def test_extrasolar_matches_the_sky_cultures_after_it(
        self, monkeypatch, calls, capsys
    ):
        self.cli(monkeypatch, "--targets", "extrasolar")
        assert calls["order"] == ["extrasolar", "skycultures"]
        assert calls["skycultures"] == [(REGISTRY_ROOT, DERIVED_SKYCULTURES_DIR)]
        assert "the cultures" in capsys.readouterr().out

    def test_another_root_keeps_its_matched_cultures(
        self, monkeypatch, calls, tmp_path
    ):
        root = tmp_path / "root"
        self.cli(monkeypatch, "--targets", "extrasolar", "--registry-root", str(root))
        assert calls["skycultures"] == [(root, root / "skycultures")]

    def test_skycultures_alone_reads_the_registry_only(self, monkeypatch, calls):
        self.cli(monkeypatch, "--targets", "skycultures")
        assert calls["order"] == ["skycultures"]
        assert calls["db"] == []

    def test_naming_both_matches_once(self, monkeypatch, calls):
        self.cli(monkeypatch, "--targets", "skycultures", "extrasolar")
        assert calls["order"] == ["extrasolar", "skycultures"]

    def test_a_named_backup_root(self, monkeypatch, calls, tmp_path):
        root, backup = tmp_path / "root", tmp_path / "elsewhere"
        self.cli(
            monkeypatch,
            "--targets",
            "extrasolar",
            "--registry-root",
            str(root),
            "--backup-root",
            str(backup),
        )
        assert calls["stars"] == [(root, backup, None)]

    def test_all_leaves_extrasolar_out(self, monkeypatch, calls):
        self.cli(monkeypatch, "--targets", "all")
        assert calls["stars"] == []
        assert calls["skycultures"] == []
        ((selected, full_rebuild, _),) = calls["db"]
        assert "extrasolar" not in selected and "tiles" not in selected
        assert full_rebuild

    def test_both_kinds_of_target(self, monkeypatch, calls, tmp_path):
        self.cli(
            monkeypatch,
            "--targets",
            "models",
            "extrasolar",
            "--registry-root",
            str(tmp_path),
        )
        assert [args[0] for args in calls["db"]] == [["models"]]
        assert len(calls["stars"]) == 1
