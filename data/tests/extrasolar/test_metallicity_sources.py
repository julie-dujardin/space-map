"""Tests for the metallicity sources: APOGEE, LAMOST, GSP-Spec, XHIP."""

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from astropy.io import fits

from space_map_data.download.providers.stars import gaia_source
from space_map_data.extrasolar.engine import IngestRun
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources import apogee, gaia, hipparcos, lamost
from space_map_data.extrasolar.sources.gaia import (
    GAIA_DR3,
    BestNeighbours,
    SourceTable,
)
from space_map_data.extrasolar.sources.hipparcos import HIPPARCOS
from space_map_data.extrasolar.tables import POINT_SOURCE
from tests.extrasolar.conftest import table_rows
from tests.extrasolar.test_stars import (
    astrophysical,
    at,
    fidelity,
    gaia_star,
    gaia_stars,
    hip_stars,
    xgboost,
)

# A chunk name that covers every level-8 pixel.
ALL_SKY = "GaiaSource_000000-786431.parquet"


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
    """The catalogues join the Gaia rows by source_id."""

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
        p = {k: at(60 * k) for k in range(1, 4)}
        best = BestNeighbours(np.array([1]), np.array([10]))
        joined = (
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
            xgboost_dir=tmp_path,
            joined=joined,
        )
        path = tmp_path / ALL_SKY
        stars = gaia_stars([gaia_star(k, *p[k], 5.0 + k) for k in (1, 2, 3)])
        pq.write_table(stars.select(gaia.COLUMNS), path)
        pq.write_table(
            fidelity([(1, 0.9), (2, 0.9), (3, 0.9)]), reader.fidelity_path(path)
        )
        pq.write_table(astrophysical([]), reader.astrophysical_path(path))
        pq.write_table(xgboost([]), reader.xgboost_path(path))
        gaia_rows = list(reader.batches([path]))
        assert reader.counts["apogee_id"] == 1
        hip = hipparcos.engine_rows(
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
                ]
            ),
            best,
        )
        root = tmp_path / "root"
        with IngestRun.start(root, root / "backup") as run:
            run.add(GAIA_DR3, gaia_rows)
            run.add(HIPPARCOS, [hip])
            result = run.commit()
        assert result.entry["counts"]["minted"] == 3
        registry = Registry(root)

        def id_of(catalogue: str, release: str, value: object) -> int:
            return int(registry.lookup(catalogue, release, [str(value)])[0])

        first, second, third = (id_of("gaia", "dr3", k) for k in (1, 2, 3))
        assert id_of("apogee", "dr17", "2M3") == 0
        point = {r["id"]: r for r in table_rows(root, "point-source").to_pylist()}
        assert len(point) == 3
        assert point[first]["feh_xhip"] == pytest.approx(-0.4)
        assert point[first]["xhip_metallicity_source"] == HIPPARCOS.name
        assert point[second]["lamost_id"] == "J2"
        assert point[second]["mh_lamost"] == pytest.approx(0.2)
        assert point[second]["lamost_source"] == GAIA_DR3.name
        assert point[second]["apogee_id"] is None
        assert point[third]["apogee_id"] == "2M3"
        assert point[third]["mh_apogee"] == pytest.approx(0.5)
        assert point[third]["apogee_source"] == GAIA_DR3.name
