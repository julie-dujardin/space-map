"""Tests for the metallicity sources: PASTEL, APOGEE, LAMOST, GSP-Spec, XHIP."""

import csv
import gzip
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from astropy.io import fits

from space_map_data.download.cds import README
from space_map_data.download.providers.stars import gaia_source
from space_map_data.extrasolar.engine import IngestRun
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources import apogee, gaia, hipparcos, lamost, pastel
from space_map_data.extrasolar.sources.gaia import (
    GAIA_DR3,
    BestNeighbours,
    SourceTable,
)
from space_map_data.extrasolar.sources.hipparcos import HIPPARCOS
from space_map_data.extrasolar.sources.pastel import SimbadObject
from space_map_data.extrasolar.tables import POINT_SOURCE
from tests.extrasolar.conftest import offset, table_rows
from tests.extrasolar.test_stars import (
    NO_ORBITS,
    astrophysical,
    at,
    fidelity,
    flame_spec,
    gaia_star,
    gaia_stars,
    hip_stars,
    xgboost,
)

# A chunk name that covers every level-8 pixel.
ALL_SKY = "GaiaSource_000000-786431.parquet"


def no_neighbours() -> BestNeighbours:
    return BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64))


def determinations(rows: list[tuple[str, float]]) -> pa.Table:
    """PASTEL determinations: designation and [Fe/H]; a bibcode each."""
    return pa.table(
        {
            "designation": [r[0] for r in rows],
            "feh": [r[1] for r in rows],
            "bibcode": [f"2020Test...{i:03d}" for i in range(len(rows))],
        }
    )


# Byte ranges of the PASTEL fields that the source reads (its ReadMe).
PASTEL_FIELDS = (
    ("ID", 1, 33, "A33"),
    ("RAdeg", 35, 49, "F15.11"),
    ("DEdeg", 51, 65, "F15.11"),
    ("Vmag", 83, 88, "F6.3"),
    ("[Fe/H]", 167, 172, "F6.3"),
    ("bibcode", 205, 223, "A19"),
)


def write_pastel(directory: Path, rows: list[tuple]) -> Path:
    """A PASTEL ReadMe and data file with these determinations."""
    directory.mkdir()
    readme = [
        "Byte-by-byte Description of file: pastel.dat",
        "-" * 80,
        "Bytes",
        "-" * 80,
    ]
    for label, start, end, kind in PASTEL_FIELDS:
        readme.append(f"{start:4d}-{end:3d}  {kind:6s} ---  {label}  x")
    readme.append("-" * 80)
    (directory / README).write_text("\n".join(readme) + "\n")
    lines = []
    for values in rows:
        line = [" "] * 223
        for (label, start, end, _), value in zip(PASTEL_FIELDS, values):
            if value is None:
                continue
            text = str(value)
            width = end - start + 1
            text = (
                text.ljust(width) if label in ("ID", "bibcode") else text.rjust(width)
            )
            line[start - 1 : end] = list(text[:width])
        lines.append("".join(line))
    (directory / pastel.PASTEL_FILE).write_bytes(
        gzip.compress(("\n".join(lines) + "\n").encode("latin-1"))
    )
    return directory


def write_simbad(path: Path, names: dict[str, SimbadObject | None]) -> Path:
    """A names.csv; None is a name that SIMBAD does not resolve."""
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "oid", "ra", "dec", "gaia_dr3"])
        for name, found in names.items():
            if found is None:
                writer.writerow([name, "", "", "", ""])
            else:
                gaia_id = found.gaia or ""
                writer.writerow([name, found.oid, found.ra, found.dec, gaia_id])
    return path


def placed(
    rows: list[tuple[str, float | None]],
    found: list[tuple[int, int, int, float, float]] | None = None,
    simbad: dict[str, SimbadObject] | None = None,
    hips: list[dict] | None = None,
    best: BestNeighbours | None = None,
) -> list[tuple[int, int, str]]:
    """(source_id, hip, route) of each designation.

    `rows` are (designation, V); `found` are the candidates as (row,
    source_id, hip, separation, expected V).
    """
    stars = pa.table(
        {
            "designation": [r[0] for r in rows],
            "v_mag": pa.array([r[1] for r in rows], pa.float64()),
        }
    )
    columns = list(zip(*found)) if found else [()] * 5
    candidates = pastel.Candidates(
        *(np.array(c, np.int64) for c in columns[:3]),
        *(np.array(c, np.float64) for c in columns[3:]),
    )
    out = pastel.place(
        stars,
        candidates,
        simbad or {},
        hip_stars(hips or []),
        best or no_neighbours(),
    )
    return list(zip(out.source_id.tolist(), out.hip.tolist(), out.route))


class TestPastelSummary:
    """One row per star from the determinations of its designations."""

    def test_median_range_count_and_bibcodes(self):
        rows = determinations(
            [
                ("HD 4", 0.1),
                ("HD 4", -0.3),
                ("BD+01 2", 0.0),
                ("HD 4", 0.2),
                ("BD+05 9", -1.0),
                ("Lost", 0.5),
            ]
        )
        one = SimbadObject(1, 0.0, 0.0, 7)
        stars = pastel.by_star(
            rows,
            {"HD 4": (7, 4), "BD+01 2": (7, 0), "BD+05 9": (0, 9)},
            {"HD 4": one, "BD+01 2": one},
        ).to_pylist()
        # A designation that reaches no star has no row.
        assert [s["pastel_designation"] for s in stars] == ["BD+05 9", "HD 4"]
        assert (stars[0]["source_id"], stars[0]["hip"]) == (0, 9)
        hd = stars[1]
        # One SIMBAD object gives one row, named by its HD number.
        assert (hd["source_id"], hd["hip"], hd["designations"]) == (7, 4, 2)
        assert hd["feh_pastel"] == pytest.approx(0.05)
        assert (hd["feh_pastel_min"], hd["feh_pastel_max"]) == pytest.approx(
            (-0.3, 0.2)
        )
        assert hd["feh_pastel_count"] == 4
        assert sorted(hd["pastel_bibcodes"].split()) == [
            f"2020Test...{i:03d}" for i in range(4)
        ]

    def test_designations_that_simbad_keeps_apart(self):
        rows = determinations(
            [(name, 0.0) for name in ("HD 5", "BD+02 3", "HD 6", "BD+03 4")]
            + [("HIP 13", 0.0), ("Twin", 0.0)]
        )
        simbad = {
            "HD 5": SimbadObject(1, 0.0, 0.0, 8),
            "BD+02 3": SimbadObject(2, 0.0, 0.0, 0),
            "HD 6": SimbadObject(3, 0.0, 0.0, 99),
            "BD+03 4": SimbadObject(4, 0.0, 0.0, 98),
            "HIP 13": SimbadObject(5, 0.0, 0.0, 0),
            "Twin": SimbadObject(6, 0.0, 0.0, 0),
        }
        stars = pastel.by_star(
            rows,
            {
                "HD 5": (8, 0),
                "BD+02 3": (8, 0),
                "HD 6": (9, 0),
                "BD+03 4": (9, 0),
                "HIP 13": (0, 13),
                "Twin": (0, 13),
            },
            simbad,
        ).to_pylist()
        # Only HD 5 has its SIMBAD object on its source. No member of source 9
        # or of HIP 13 has, so these stars have no row.
        assert [(s["pastel_designation"], s["designations"]) for s in stars] == [
            ("HD 5", 1)
        ]


class TestPastelPlace:
    """The routes from a designation to its star."""

    def test_v_must_agree(self):
        assert placed(
            [("A", 10.0), ("B", 10.0), ("C", 10.0)],
            [
                (0, 5, 0, 0.5, 10.29),
                (1, 6, 0, 0.5, 10.31),
                # Outside the colour range of the G - V fit.
                (2, 7, 0, 0.5, np.nan),
            ],
        ) == [(5, 0, "position"), (0, 0, "none"), (0, 0, "none")]

    def test_without_v_a_single_candidate_within_1_arcsec(self):
        assert placed(
            [("A", None), ("B", None), ("C", None)],
            [
                (0, 5, 0, 0.8, 12.0),
                (1, 6, 0, 1.5, 12.0),
                (2, 7, 0, 0.2, 12.0),
                (2, 8, 0, 2.5, 12.0),
            ],
        ) == [(5, 0, "position"), (0, 0, "none"), (0, 0, "none")]

    def test_beyond_1_arcsec_fails_when_simbad_names_another_source(self):
        far = SimbadObject(1, 0.0, 0.0, 99)
        assert placed(
            [("A", 10.0), ("B", 10.0)],
            [(0, 5, 0, 2.0, 10.0), (1, 6, 0, 0.5, 10.0)],
            {"A": far, "B": far},
        ) == [(99, 0, "simbad"), (6, 0, "position")]

    def test_simbad_source_wins_else_the_nearest(self):
        found = [
            (0, 5, 0, 0.3, 10.0),
            (0, 6, 0, 1.2, 10.1),
            (1, 5, 0, 0.3, 10.0),
            (1, 6, 0, 1.2, 10.1),
        ]
        assert placed(
            [("A", 10.0), ("B", 10.0)], found, {"A": SimbadObject(1, 0.0, 0.0, 6)}
        ) == [(6, 0, "position"), (5, 0, "position")]

    def test_a_hipparcos_candidate_keeps_its_hip_number(self):
        assert placed([("A", 4.0)], [(0, 0, 7, 0.4, 4.1)]) == [(0, 7, "position")]

    def test_without_a_candidate_simbad_gives_the_source(self):
        assert placed(
            [("A", 10.0), ("B", 10.0), ("C", 10.0)],
            simbad={
                "A": SimbadObject(1, 0.0, 0.0, 42),
                "B": SimbadObject(2, 0.0, 0.0, 0),
            },
        ) == [(42, 0, "simbad"), (0, 0, "none"), (0, 0, "none")]

    def test_hd_component_rule(self):
        hips = [
            {"hip": 10, "ra": 40.0, "dec": 10.0, "hd": 100},
            {"hip": 20, "ra": 50.0, "dec": 10.0},
            {"hip": 30, "ra": 60.0, "dec": 10.0},
            # Two HIP stars share one HD number, so that number names neither.
            {"hip": 40, "ra": 70.0, "dec": 10.0, "hd": 400},
            {"hip": 41, "ra": 70.1, "dec": 10.0, "hd": 400},
        ]
        best = BestNeighbours(np.array([1000, 3000]), np.array([10, 20]))
        simbad = {
            "HD 100": SimbadObject(1, *offset(40.0, 10.0, 5, 0), 2000),
            "HIP 10": SimbadObject(1, *offset(40.0, 10.0, 5, 0), 1000),
            "HIP 20": SimbadObject(2, *offset(50.0, 10.0, 30, 0), 4000),
            "HIP 30": SimbadObject(3, *offset(60.0, 10.0, 2, 0), 5000),
            "HD 400": SimbadObject(4, 70.0, 10.0, 6000),
        }
        # Each source is a Gaia candidate of its row.
        found = [(1, 1000, 0, 0.1, 9.0), (2, 3000, 0, 0.1, 9.0), (3, 5000, 0, 0.1, 9.0)]
        assert placed(
            [(name, None) for name in simbad],
            found,
            simbad=simbad,
            hips=hips,
            best=best,
        ) == [
            # Within 10″, SIMBAD's source is another component of the system.
            (2000, 0, "name, component from SIMBAD"),
            (1000, 10, "name"),
            # Beyond 10″ it is another star, and the best neighbour stays.
            (3000, 20, "name"),
            # Without a best neighbour, SIMBAD's source keeps the HIP number.
            (5000, 30, "name"),
            (6000, 0, "simbad"),
        ]

    def test_a_source_that_is_no_candidate_leaves_the_hip_number(self):
        # The best neighbours of HIP 10 and of HIP 20, which A reaches by
        # position, are not among the stars read: those rows join the
        # Hipparcos star. The source of HIP 30 is a candidate, so it stays.
        hips = [
            {"hip": 10, "ra": 40.0, "dec": 10.0},
            {"hip": 20, "ra": 50.0, "dec": 10.0},
            {"hip": 30, "ra": 60.0, "dec": 10.0},
        ]
        best = BestNeighbours(np.array([1000, 2000, 3000]), np.array([10, 20, 30]))
        assert placed(
            [("HIP 10", None), ("A", 9.0), ("HIP 30", None)],
            [(1, 2000, 20, 0.2, 9.0), (2, 3000, 0, 0.1, 9.0)],
            hips=hips,
            best=best,
        ) == [(0, 10, "name"), (0, 20, "position"), (3000, 30, "name")]

    def test_the_designations_of_one_star_join_alike(self):
        # HIP 100's source is a candidate of one designation, HIP 300's of none.
        hips = [
            {"hip": 100, "ra": 40.0, "dec": 10.0, "hd": 200},
            {"hip": 300, "ra": 60.0, "dec": 10.0},
        ]
        best = BestNeighbours(np.array([1000, 3000]), np.array([100, 300]))
        assert placed(
            [("BD+01 1", None), ("HD 200", None), ("HIP 100", None), ("HIP 300", None)],
            [(2, 1000, 0, 0.1, 9.0)],
            simbad={"BD+01 1": SimbadObject(7, 60.0, 10.0, 3000)},
            hips=hips,
            best=best,
        ) == [
            (0, 300, "simbad"),
            (1000, 100, "name"),
            (1000, 100, "name"),
            (0, 300, "name"),
        ]

    def test_a_name_without_a_gaia_id_in_simbad_takes_the_nearest(self):
        # The farther candidate is a Hipparcos star without a best neighbour.
        assert placed(
            [("A", 10.0)],
            [(0, 0, 7, 0.4, 10.0), (0, 5, 0, 0.2, 10.0)],
            {"A": SimbadObject(1, 0.0, 0.0, 0)},
        ) == [(5, 0, "position")]


class TestPastelRead:
    """From the PASTEL and SIMBAD files to one row per star."""

    def test_positions_at_j2000_and_the_routes(self, tmp_path):
        ra, dec = 40.0, 10.0
        # It moves 1″/yr east, so it is 16″ from its J2000 position at J2016.0.
        moved_ra = ra + 16 / 3600 / np.cos(np.radians(dec))
        chunk = tmp_path / ALL_SKY
        pq.write_table(
            pa.table(
                {
                    "source_id": pa.array([5], pa.int64()),
                    "ra": [moved_ra],
                    "dec": [dec],
                    "pmra": pa.array([1000.0], pa.float32()),
                    "pmdec": pa.array([0.0], pa.float32()),
                    "phot_g_mean_mag": pa.array([12.0], pa.float32()),
                    "phot_bp_mean_mag": pa.array([12.4], pa.float32()),
                    "phot_rp_mean_mag": pa.array([11.5], pa.float32()),
                }
            ),
            chunk,
        )
        hip = hip_stars([{"hip": 7, "ra": 80.0, "dec": -5.0, "v_mag": 4.0}])
        directory = write_pastel(
            tmp_path / "pastel",
            [
                ("G   1-1", f"{ra:.11f}", f"{dec:.11f}", "12.200", "-0.500", "2001A"),
                ("BD+10    1", f"{ra:.11f}", f"{dec:.11f}", None, "-0.300", "2002A"),
                ("Faint", f"{ra + 0.1:.11f}", f"{dec:.11f}", "20.000", "-0.5", None),
                (
                    "*  lam Tst",
                    "80.00000000000",
                    "-5.00000000000",
                    "4.100",
                    "0.1",
                    None,
                ),
                ("HD      1", "0.00000000000", "0.00000000000", "9.000", "0.0", None),
            ],
        )
        simbad = write_simbad(
            tmp_path / "names.csv",
            {"Faint": None, "HD 1": SimbadObject(3, 0.0, 0.0, 77)},
        )
        stars = pastel.read_stars(
            [chunk],
            hip,
            BestNeighbours(np.array([5]), np.array([8])),
            workers=1,
            directory=directory,
            simbad_file=simbad,
        ).to_pylist()
        keys = {s["pastel_designation"]: (s["source_id"], s["hip"]) for s in stars}
        # G 1-1 agrees in V. Source 5 is the only star within 1″ of BD+10 1.
        # The two make one star. HIP 7 has no Gaia source.
        assert keys == {"* lam Tst": (0, 7), "BD+10 1": (5, 0), "HD 1": (77, 0)}
        merged = next(s for s in stars if s["pastel_designation"] == "BD+10 1")
        assert (merged["designations"], merged["feh_pastel_count"]) == (2, 2)
        assert merged["feh_pastel"] == pytest.approx(-0.4)


# Plain values of the allStarLite columns that the source reads.
ALLSTAR = dict.fromkeys(apogee.VALUES.values(), 0.1) | {
    "APOGEE_ID": "2M0",
    "GAIAEDR3_SOURCE_ID": 0,
    "EXTRATARG": 0,
    "GAIAEDR3_PHOT_G_MEAN_MAG": 14.0,
    "GAIAEDR3_PHOT_BP_MEAN_MAG": 14.5,
    "GAIAEDR3_PHOT_RP_MEAN_MAG": 13.5,
    "H": 12.0,
    "TEFF": 5000.0,
    "SNR": 100.0,
}
ALLSTAR_FORMATS = {"APOGEE_ID": "20A", "GAIAEDR3_SOURCE_ID": "K", "EXTRATARG": "J"}


def write_allstar(path: Path, rows: list[dict]) -> Path:
    """An allStarLite file; a column that a row does not give is plain."""
    columns = [
        fits.Column(
            name=name,
            format=ALLSTAR_FORMATS.get(name, "E"),
            array=np.array([row.get(name, value) for row in rows]),
        )
        for name, value in ALLSTAR.items()
    ]
    fits.BinTableHDU.from_columns(columns).writeto(path)
    return path


def allstar_row(apogee_id: str, source_id: int, bp_rp: float, **more) -> dict:
    """A dwarf of this colour, with the Teff and G - H of its colour."""
    teff = np.interp(bp_rp, apogee.DWARF_BP_RP[::-1], apogee.DWARF_TEFF[::-1])
    excess = more.pop("excess", 0.0)
    g = 14.0
    return {
        "APOGEE_ID": apogee_id,
        "GAIAEDR3_SOURCE_ID": source_id,
        "GAIAEDR3_PHOT_BP_MEAN_MAG": g + bp_rp / 2,
        "GAIAEDR3_PHOT_RP_MEAN_MAG": g - bp_rp / 2,
        "H": g - (1.5 * bp_rp + 0.2) - excess,
        "TEFF": teff,
        **more,
    }


class TestApogee:
    """Duplicates, blanks and the cut of wrong Gaia ids."""

    def test_best_row_of_each_star_with_a_named_value(self, tmp_path):
        path = write_allstar(
            tmp_path / "allStar.fits",
            [
                {"APOGEE_ID": "2M1", "GAIAEDR3_SOURCE_ID": 7, "SNR": 50.0},
                {"APOGEE_ID": "2M2", "GAIAEDR3_SOURCE_ID": 7, "M_H": -0.2},
                {"APOGEE_ID": "2M3", "GAIAEDR3_SOURCE_ID": 8, "EXTRATARG": 16},
                {
                    "APOGEE_ID": "2M4",
                    "GAIAEDR3_SOURCE_ID": 9,
                    "M_H": -9999.99,
                    "FE_H": np.nan,
                },
                {"APOGEE_ID": "2M5", "GAIAEDR3_SOURCE_ID": 0},
            ],
        )
        stars = apogee.read_stars(path)
        # Source 7 keeps the row with the best S/N. 2M3 is a duplicate row,
        # 2M4 has no named value and 2M5 has no Gaia id.
        assert stars["apogee_id"].to_pylist() == ["2M2"]
        assert stars["source_id"].to_pylist() == [7]
        assert stars["mh_apogee"].to_pylist() == pytest.approx([-0.2])

    def test_a_gaia_source_too_faint_for_its_h_is_another_star(self, tmp_path):
        field = [
            allstar_row(f"2M{k}", 1000 + k, bp_rp)
            for k, bp_rp in enumerate(np.linspace(0.5, 2.5, 600))
        ]
        # BP - RP 0.6 is far too blue for a Teff of 4000 K.
        path = write_allstar(
            tmp_path / "allStar.fits",
            [
                *field,
                allstar_row("2Mfaint", 1, 1.0, excess=2.5),
                allstar_row("2Mfaintblue", 2, 0.6, excess=1.5, TEFF=4000.0),
                allstar_row("2Mblue", 3, 0.6, TEFF=4000.0),
                allstar_row("2Mfaintonly", 4, 1.5, excess=1.5),
            ],
        )
        kept = set(apogee.read_stars(path)["apogee_id"].to_pylist())
        assert kept == {row["APOGEE_ID"] for row in field} | {"2Mblue", "2Mfaintonly"}


LAMOST_HEADER = (
    "ID,obsid,RA,Dec,SNRr,SNRi,Gmag,BPmag,RPmag,Plx,Teff,e_Teff,Logg,e_Logg,"
    "[M/H],e_[M/H],Activity,VBFlag"
)


def lamost_line(name: str, obsid: int, snr: str, mh: str = "-0.1", **flags) -> str:
    activity, vbflag = flags.get("activity", 0), flags.get("vbflag", 0)
    g = flags.get("g", "15.1")
    return (
        f"{name},{obsid},10.0,20.0,5,{snr},{g},16.0,14.0,5.0,3500,50,4.8,0.1,"
        f"{mh},0.1,{activity},{vbflag}"
    )


def write_mstellar(
    path: Path, gaia_ids: dict[int, str], g: dict[int, float] | None = None
) -> Path:
    """An M-star catalogue: the Gaia DR3 id of each obsid, as text, and the G
    of that source, the G of `lamost_line` unless `g` gives another."""
    fits.BinTableHDU.from_columns(
        [
            fits.Column(name="obsid", format="J", array=np.array(list(gaia_ids))),
            fits.Column(
                name="gaia_source_id",
                format="25A",
                array=np.array(list(gaia_ids.values())),
            ),
            fits.Column(
                name="gaia_g_mean_mag",
                format="E",
                array=np.array([(g or {}).get(obsid, 15.1) for obsid in gaia_ids]),
            ),
        ]
    ).writeto(path)
    return path


class TestLamost:
    """One spectrum per Gaia source, by the Gaia id of the M-star catalogue."""

    def test_one_per_source(self):
        source_id = np.array([5, 5, 6, 6, 7, 7, 8, 8])
        snr = np.array([20.0, 60.0, 30.0, 30.0, np.nan, 10.0, np.nan, np.nan])
        obsid = np.array([1, 2, 4, 3, 5, 6, 12, 11])
        # The best S/N wins, then the lowest obsid. A NaN S/N comes last.
        assert lamost.one_per_source(source_id, snr, obsid).tolist() == [1, 3, 5, 7]

    def test_read_stars(self, tmp_path):
        lines = [
            lamost_line("J1", 1, "20"),
            lamost_line("J1b", 2, "60", "-0.2", activity=1, vbflag=2),
            lamost_line("J2a", 4, "30"),
            lamost_line("J2b", 3, "30"),
            lamost_line("J3a", 5, ""),
            lamost_line("J3b", 6, "10"),
            # J4 to J7: a Gaia id of -9999, a blank id, no M-star row, no [M/H].
            lamost_line("J4", 7, "50"),
            lamost_line("J5", 8, "50"),
            lamost_line("J6", 9, "50"),
            lamost_line("J7", 10, "50", ""),
            lamost_line("J8a", 11, ""),
            lamost_line("J8b", 12, ""),
            # The G of the M-star source is not the row's: another star.
            lamost_line("J9a", 13, "80"),
            lamost_line("J9b", 14, "20"),
            # A G missing on either side fails the check.
            lamost_line("J10a", 15, "80", g=""),
            lamost_line("J10b", 16, "20"),
            lamost_line("J11", 17, "50"),
        ]
        mstellar = write_mstellar(
            tmp_path / "mstellar.fits",
            {1: "2001", 2: "2001", 3: "2002", 4: "2002", 5: "2003", 6: " 2003 "}
            | {7: "-9999", 8: "", 10: "2005", 11: "2004", 12: "2004"}
            | {13: "2006", 14: "2006", 15: "2007", 16: "2007", 17: "2008"},
            {13: 16.3, 17: np.nan},
        )

        def read(order: list[str]) -> list[dict]:
            path = tmp_path / "m.csv"
            path.write_text("\n".join([LAMOST_HEADER, *order]) + "\n")
            stars = lamost.read_stars(path, mstellar).to_pylist()
            return sorted(stars, key=lambda star: star["source_id"])

        stars = read(lines)
        assert [(s["source_id"], s["lamost_id"]) for s in stars] == [
            (2001, "J1b"),
            (2002, "J2b"),
            (2003, "J3b"),
            (2004, "J8a"),
            (2006, "J9b"),
            (2007, "J10b"),
        ]
        assert stars[0]["mh_lamost"] == pytest.approx(-0.2)
        assert (stars[0]["activity_lamost"], stars[0]["vbflag_lamost"]) == (True, 2)
        assert (stars[1]["activity_lamost"], stars[1]["vbflag_lamost"]) == (False, 0)
        # The choice does not depend on the order of the file.
        assert read(lines[::-1]) == stars


class TestGspspec:
    """The calibrations of Recio-Blanco et al. 2023 and where [Fe/H] holds."""

    def test_calibrated_values(self):
        good = "0" * 41
        stars = pa.table(
            {
                "logg_gspspec": pa.array([4.4, 2.0, 5.0, 4.0, None], pa.float32()),
                "mh_gspspec": pa.array([-0.1, -0.5, 0.0, 0.0, None], pa.float32()),
                "fem_gspspec": pa.array([0.05, 0.02, 0.1, 0.1, None], pa.float32()),
                "flags_gspspec": [good, good[:28] + "2" + good[29:], good, None, None],
            }
        )
        out = gaia.calibrate_gspspec(stars)
        mh = out["mh_gspspec_calibrated"].to_pylist()
        feh = out["feh_gspspec_calibrated"].to_pylist()
        assert mh[0] == pytest.approx(
            -0.1 + 0.274 - 0.1373 * 4.4 - 0.0050 * 4.4**2 + 0.0048 * 4.4**3, abs=1e-6
        )
        assert feh[0] == pytest.approx(
            -0.05 + 0.3699 - 0.0680 * 4.4 + 0.0028 * 4.4**2 - 0.0004 * 4.4**3,
            abs=1e-6,
        )
        # A poor [Fe/M], a log g past the range, or no flags: no [Fe/H].
        assert feh[1:] == [None, None, None, None]
        assert mh[4] is None


def catalogue_rows(
    ids: list[int], columns: tuple[str, ...], **values: list
) -> pa.Table:
    """Rows of a joined catalogue; the columns not given are null."""
    table = {"source_id": pa.array(ids, pa.int64())}
    for name in columns:
        kind = POINT_SOURCE.schema.field(name).type
        table[name] = pa.array(values.get(name, [None] * len(ids)), kind)
    return pa.table(table)


class TestJoins:
    """The catalogues join the Gaia rows by source_id, PASTEL also by HIP."""

    def test_a_chunk_takes_the_rows_of_its_own_pixels(self):
        low = 1 << gaia_source.PIXEL_SHIFT
        table = SourceTable.of(
            catalogue_rows(
                [3 * low + 1, low + 5, low + 2],
                apogee.COLUMNS,
                apogee_id=["c", "b", "a"],
            ),
            apogee.COLUMNS,
        )

        def ids(name: str) -> list[str]:
            return table.part(Path(name))["apogee_id"].to_pylist()

        assert ids("GaiaSource_000001-000002.parquet") == ["a", "b"]
        assert ids("GaiaSource_000003-000003.parquet") == ["c"]
        assert ids("GaiaSource_000004-000009.parquet") == []

    def test_a_source_with_two_rows_fails(self):
        with pytest.raises(ValueError, match="two rows"):
            SourceTable.of(catalogue_rows([4, 4], apogee.COLUMNS), apogee.COLUMNS)

    def test_the_values_reach_known_stars_and_mint_nothing(self, tmp_path):
        p = {k: at(60 * k) for k in range(1, 5)}
        best = BestNeighbours(np.array([1]), np.array([10]))
        joined = (
            SourceTable.of(
                catalogue_rows(
                    [1, 999],
                    pastel.COLUMNS,
                    pastel_designation=["HD 100", "Elsewhere"],
                    feh_pastel=[-0.3, 0.0],
                ),
                pastel.COLUMNS,
            ),
            SourceTable.of(
                catalogue_rows(
                    [3, 999],
                    apogee.COLUMNS,
                    apogee_id=["2M3", "2M999"],
                    mh_apogee=[0.5, 0.0],
                ),
                apogee.COLUMNS,
            ),
            SourceTable.of(
                catalogue_rows([2], lamost.COLUMNS, lamost_id=["J2"], mh_lamost=[0.2]),
                lamost.COLUMNS,
            ),
        )
        reader = gaia.GaiaReader(
            best,
            source_dir=tmp_path,
            fidelity_dir=tmp_path,
            astrophysical_dir=tmp_path,
            flame_spec_dir=tmp_path,
            xgboost_dir=tmp_path,
            joined=joined,
            orbits=NO_ORBITS,
        )
        path = tmp_path / ALL_SKY
        stars = gaia_stars([gaia_star(k, *p[k], 5.0 + k) for k in (1, 2, 3)])
        pq.write_table(stars.select(gaia.COLUMNS), path)
        pq.write_table(
            fidelity([(1, 0.9), (2, 0.9), (3, 0.9)]), reader.fidelity_path(path)
        )
        pq.write_table(astrophysical([]), reader.astrophysical_path(path))
        pq.write_table(flame_spec([]), reader.flame_spec_path(path))
        pq.write_table(xgboost([]), reader.xgboost_path(path))
        gaia_rows = list(reader.batches([path]))
        assert {k: reader.counts[k] for k in ("pastel_designation", "apogee_id")} == {
            "pastel_designation": 1,
            "apogee_id": 1,
        }
        # HIP 40 has no Gaia source, so its PASTEL row joins by HIP number.
        by_hip = catalogue_rows(
            [0], pastel.COLUMNS, pastel_designation=["HD 400"], feh_pastel=[-0.7]
        ).append_column("hip", pa.array([40], pa.int64()))
        hip, _ = hipparcos.engine_rows(
            hip_stars(
                [
                    {
                        "hip": 10,
                        "ra": p[1][0],
                        "dec": p[1][1],
                        "v_mag": 6.0,
                        "b_v": 0.6,
                        "hd": 100,
                        "feh_xhip": -0.4,
                        "feh_xhip_quality": "A",
                    },
                    {"hip": 40, "ra": p[4][0], "dec": p[4][1], "v_mag": 7.0},
                ]
            ),
            best,
            by_hip,
        )
        root = tmp_path / "root"
        with IngestRun.start(root, root / "backup") as run:
            run.add(GAIA_DR3, gaia_rows)
            run.add(HIPPARCOS, [hip])
            result = run.commit()
        assert result.entry["counts"]["minted"] == 4
        registry = Registry(root)

        def id_of(catalogue: str, release: str, value: object) -> int:
            return int(registry.lookup(catalogue, release, [str(value)])[0])

        first, second, third = (id_of("gaia", "dr3", k) for k in (1, 2, 3))
        fourth = id_of("hip", "2007", 40)
        assert id_of("apogee", "dr17", "2M3") == 0
        point = {r["id"]: r for r in table_rows(root, "point-source").to_pylist()}
        assert len(point) == 4
        assert point[first]["pastel_designation"] == "HD 100"
        assert point[first]["feh_pastel"] == pytest.approx(-0.3)
        assert point[first]["pastel_source"] == GAIA_DR3.name
        assert point[first]["feh_xhip"] == pytest.approx(-0.4)
        assert point[first]["xhip_metallicity_source"] == HIPPARCOS.name
        assert point[second]["lamost_id"] == "J2"
        assert point[second]["mh_lamost"] == pytest.approx(0.2)
        assert point[second]["lamost_source"] == GAIA_DR3.name
        assert point[second]["apogee_id"] is None
        assert point[third]["apogee_id"] == "2M3"
        assert point[third]["mh_apogee"] == pytest.approx(0.5)
        assert point[third]["apogee_source"] == GAIA_DR3.name
        assert point[fourth]["pastel_designation"] == "HD 400"
        assert point[fourth]["feh_pastel"] == pytest.approx(-0.7)
        assert point[fourth]["pastel_source"] == HIPPARCOS.name
