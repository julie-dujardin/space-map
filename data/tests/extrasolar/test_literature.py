"""The literature table and its ingest pass."""

import numpy as np
import pytest

from space_map_data.constants.stars.literature import DISTANCES, REFERENCES, Distance
from space_map_data.download.providers.stars.wikidata_stars import (
    GAIA_PIXEL_LEVEL,
    GAIA_PIXEL_SHIFT,
)
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import IngestRun
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources import distances, gaia, literature
from space_map_data.extrasolar.sources.distances import REYLE_2021
from space_map_data.extrasolar.sources.gaia import GAIA_DR3
from space_map_data.extrasolar.sources.literature import LITERATURE
from space_map_data.extrasolar.tables import POINT_SOURCE
from tests.extrasolar.conftest import table_rows
from tests.extrasolar.test_simbad import NO_BEST
from tests.extrasolar.test_stars import at, fidelity, gaia_star, gaia_stars

METHODS = {"parallax", "photometric", "cluster", "galaxy", "geometric", "expansion"}


def gaia_id(ra: float, dec: float, n: int) -> int:
    """A Gaia source id whose pixel holds the position, as Gaia's do."""
    pixel = int(sky.cells(np.array([ra]), np.array([dec]), GAIA_PIXEL_LEVEL)[0])
    return (pixel << GAIA_PIXEL_SHIFT) + n


class TestTable:
    """The entries of the literature table."""

    def test_entries(self):
        for key, distance in DISTANCES.items():
            assert key[:2] in {("gaia", "dr3"), ("hip", "2007"), ("hd", "1949")}
            assert distance.lower <= distance.value <= distance.upper
            assert distance.method in METHODS
            assert distance.reference in REFERENCES

    def test_references(self):
        for reference in REFERENCES.values():
            assert reference.url.startswith("https://doi.org/")
            assert reference.short and reference.title

    def test_eta_car(self):
        eta_car = DISTANCES[("gaia", "dr3", "5350358584482202880")]
        assert eta_car == Distance(2350, 2300, 2400, "expansion", "smith_2006")


class TestRows:
    """The pass rows of the table."""

    def test_ids(self):
        key = ("gaia", "dr3", "5350358584482202880")
        assert literature.catalogue_id(key) == "gaia/dr3/5350358584482202880"
        assert literature.key_of(literature.catalogue_id(key)) == key

    def test_positions(self):
        ra, dec = at(0)
        source = gaia_id(ra, dec, 7)
        table = {
            ("gaia", "dr3", str(source)): Distance(10, 9, 11, "parallax", "smith_2006"),
            ("hip", "2007", "5"): Distance(20, 19, 21, "parallax", "smith_2006"),
            ("hd", "1949", "6"): Distance(30, 29, 31, "parallax", "smith_2006"),
        }
        rows = literature.engine_rows({"5": (1.0, 2.0)}, {"6": (3.0, 4.0)}, table)
        assert rows["catalogue_id"].to_pylist() == [
            f"gaia/dr3/{source}",
            "hip/2007/5",
            "hd/1949/6",
        ]
        assert not any(rows["mint"].to_pylist())
        # The centre of the Gaia pixel, within a pixel of level 12 (52″).
        assert (
            sky.separation(
                np.array([rows["match_ra"][0].as_py()]),
                np.array([rows["match_dec"][0].as_py()]),
                ra,
                dec,
            )[0]
            < 52
        )
        assert rows["match_ra"].to_pylist()[1:] == [1.0, 3.0]
        assert rows["distance"].to_pylist() == [10, 20, 30]
        assert [c[0]["catalogue_id"] for c in rows["claims"].to_pylist()] == [
            str(source),
            "5",
            "6",
        ]

    def test_unknown_star(self):
        table = {("hip", "2007", "5"): Distance(20, 19, 21, "parallax", "smith_2006")}
        with pytest.raises(ValueError, match="no star has hip/2007/5"):
            literature.engine_rows({}, {}, table)
        table = {("tyc", "2", "5"): Distance(20, 19, 21, "parallax", "smith_2006")}
        with pytest.raises(ValueError, match="not a Gaia, HIP or HD id"):
            literature.engine_rows({}, {}, table)


class TestPass:
    """The literature pass through the engine."""

    def test_ingest(self, tmp_path):
        root = tmp_path / "root"
        p1, p2 = at(0), at(120)
        source = gaia_id(*p1, 1)
        stored = gaia.engine_rows(
            gaia.join_fidelity(
                gaia_stars([gaia_star(source, *p1, 5.0), gaia_star(2, *p2, 6.0)]),
                fidelity([]),
            ),
            NO_BEST,
        )
        key = ("gaia", "dr3", str(source))
        rows = literature.engine_rows(
            {}, {}, {key: Distance(2350, 2300, 2400, "expansion", "smith_2006")}
        )
        # A catalogue distance of the same star ranks below the paper.
        reyle = distances.rows(
            np.array([p1[0]]),
            np.array([p1[1]]),
            [key],
            np.array([100.0]),
            np.array([99.0]),
            np.array([101.0]),
            ["parallax"],
        )
        with IngestRun.start(root, root / "backup") as run:
            run.add(GAIA_DR3, [stored])
            run.add(REYLE_2021, [reyle])
            run.add(LITERATURE, [rows])
            result = run.commit()
        assert result.entry["counts"]["minted"] == 2
        star = int(Registry(root).lookup("gaia", "dr3", [str(source)])[0])
        point = {r["id"]: r for r in table_rows(root, POINT_SOURCE.slug).to_pylist()}
        row = point[star]
        assert (row["distance_source"], row["distance_method"]) == (
            "literature",
            "expansion",
        )
        assert (row["distance"], row["distance_lower"], row["distance_upper"]) == (
            2350,
            2300,
            2400,
        )
        meta = {r["id"]: r for r in table_rows(root, "metadata").to_pylist()}
        assert {
            "catalogue": "literature",
            "release": "star",
            "catalogue_id": f"gaia/dr3/{source}",
        } in meta[star]["cross_ids"]
        # The literature id gives the star an object entry.
        assert meta[star]["object"]
        assert [r["object"] for i, r in meta.items() if i != star] == [False]
