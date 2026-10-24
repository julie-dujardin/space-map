"""Synthetic sources, tables and sky positions for the extrasolar tests."""

from collections.abc import Iterator
from pathlib import Path

import astropy.units as u
import numpy as np
import pyarrow as pa
import pytest
from cdshealpix import nested

from space_map_data.export.extrasolar import skycultures
from space_map_data.extrasolar import engine, sky
from space_map_data.extrasolar.engine import IngestResult, IngestRun, Source
from space_map_data.extrasolar.match import PositionMatcher
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.tables import CROSS_ID, METADATA, ColumnGroup, TableDef

GAIA = Source("gaia", "gaia", "dr3", home=1, kind="star")
HIP = Source("hip", "hip", "2007", home=1, matcher=PositionMatcher(), kind="star")
NAMES = Source("names", "iau", "wgsn", home=1)

POINT = TableDef(
    number=1,
    slug="point",
    groups=(
        ColumnGroup(
            "astrometry",
            (
                pa.field("ra", pa.float64()),
                pa.field("dec", pa.float64()),
                pa.field("parallax", pa.float32()),
            ),
            ("gaia", "hip"),
        ),
        ColumnGroup("photometry", (pa.field("g", pa.float32()),), ("gaia",)),
        ColumnGroup("hip_photometry", (pa.field("hp", pa.float32()),), ("hip",)),
    ),
)
META = TableDef(
    number=None,
    slug="metadata",
    groups=(
        ColumnGroup("name", (pa.field("name", pa.string()),), ("names",)),
        ColumnGroup("class", (pa.field("class", pa.string()),), ("gaia", "hip")),
    ),
    computed=METADATA.computed,
)
CLAIMS = pa.list_(CROSS_ID)


def offset(ra: float, dec: float, arcsec: float, angle: float) -> tuple[float, float]:
    """The point `arcsec` away from (ra, dec) at position angle `angle` (deg)."""
    d, pa_ = np.radians(arcsec / 3600), np.radians(angle)
    ra1, dec1 = np.radians(ra), np.radians(dec)
    dec2 = np.arcsin(np.sin(dec1) * np.cos(d) + np.cos(dec1) * np.sin(d) * np.cos(pa_))
    ra2 = ra1 + np.arctan2(
        np.sin(pa_) * np.sin(d) * np.cos(dec1), np.cos(d) - np.sin(dec1) * np.sin(dec2)
    )
    return float(np.degrees(ra2) % 360), float(np.degrees(dec2))


def centre(cell: int) -> tuple[float, float]:
    lon, lat = nested.healpix_to_lonlat(np.array([cell], np.uint64), 10)
    return float(lon.to_value(u.deg)[0]), float(lat.to_value(u.deg)[0])


def straddle(region: int, gap: float = 0.2) -> tuple[tuple, tuple]:
    """Two points under `gap` arcsec apart, in `region` and in a neighbour."""
    low, high = sky.region_cells(region)
    cells = np.arange(low, high, dtype=np.uint64)
    block = nested.neighbours(cells, 10)
    outside = (block >= 0) & ((block >> sky.REGION_SHIFT) != region)
    at = int(np.flatnonzero(outside.any(axis=1))[0])
    a = np.array(centre(int(cells[at])))
    b = np.array(centre(int(block[at][outside[at]][0])))
    while sky.separation(*a, *b) > gap:
        mid = (a + b) / 2
        if sky.region_of(int(sky.cells(mid[:1], mid[1:])[0])) == region:
            a = mid
        else:
            b = mid
    return (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))


def gaia_rows(rows: list[dict]) -> pa.Table:
    """Gaia rows: id, ra, dec, mag; optional mint, claims, parallax, class."""
    return pa.table(
        {
            "catalogue_id": [str(r["id"]) for r in rows],
            "mint": [r.get("mint", True) for r in rows],
            "match_ra": [r["ra"] for r in rows],
            "match_dec": [r["dec"] for r in rows],
            "match_mag": pa.array([r.get("mag") for r in rows], pa.float32()),
            "match_error": pa.array([r.get("error", 0.01) for r in rows], pa.float32()),
            "claims": pa.array([r.get("claims") for r in rows], CLAIMS),
            "ra": [r["ra"] for r in rows],
            "dec": [r["dec"] for r in rows],
            "parallax": pa.array([r.get("parallax", 10.0) for r in rows], pa.float32()),
            "g": pa.array([r.get("mag") for r in rows], pa.float32()),
            "class": [r.get("class", "star") for r in rows],
        }
    )


def hip_rows(rows: list[dict]) -> pa.Table:
    """Hipparcos rows: id, ra, dec, mag; optional claims and error."""
    return pa.table(
        {
            "catalogue_id": [str(r["id"]) for r in rows],
            "mint": [r.get("mint", True) for r in rows],
            "match_ra": [r["ra"] for r in rows],
            "match_dec": [r["dec"] for r in rows],
            "match_mag": pa.array([r.get("mag") for r in rows], pa.float32()),
            "match_error": pa.array([r.get("error", 0.5) for r in rows], pa.float32()),
            "claims": pa.array([r.get("claims") for r in rows], CLAIMS),
            "ra": [r["ra"] for r in rows],
            "dec": [r["dec"] for r in rows],
            "parallax": pa.array([r.get("parallax", 11.0) for r in rows], pa.float32()),
            "hp": pa.array([r.get("mag") for r in rows], pa.float32()),
            "class": [r.get("class", "star") for r in rows],
        }
    )


def name_rows(rows: list[dict]) -> pa.Table:
    """Name rows: id (the name), ra, dec; optional claims. Names never mint."""
    return pa.table(
        {
            "catalogue_id": [r["id"] for r in rows],
            "mint": [False] * len(rows),
            "match_ra": [r["ra"] for r in rows],
            "match_dec": [r["dec"] for r in rows],
            "claims": pa.array([r.get("claims") for r in rows], CLAIMS),
            "name": [r["id"] for r in rows],
        }
    )


def claim(catalogue: str, release: str, id_: object) -> dict:
    return {"catalogue": catalogue, "release": release, "catalogue_id": str(id_)}


@pytest.fixture(autouse=True)
def _no_git(monkeypatch):
    monkeypatch.setattr(engine, "code_version", lambda: ("test-commit", False))


@pytest.fixture(autouse=True)
def _no_sky_cultures(monkeypatch, tmp_path):
    """An export reads no matched sky cultures unless a test gives some."""
    monkeypatch.setattr(skycultures, "CULTURES_DIR", tmp_path / "no-skycultures")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "registry-root"


@pytest.fixture
def backup(tmp_path: Path) -> Path:
    return tmp_path / "backup"


@pytest.fixture
def ingest(root: Path, backup: Path):
    """Run one ingest of (source, table or batches) passes and commit it."""

    def run(
        passes: list[tuple[Source, pa.Table]], max_retired: int | None = None
    ) -> IngestResult:
        with IngestRun.start(root, backup, (POINT,), META) as current:
            for source, table in passes:
                current.add(source, [table])
            return current.commit(max_retired)

    return run


@pytest.fixture
def registry(root: Path) -> Iterator[Registry]:
    yield Registry(root)


def table_rows(root: Path, slug: str) -> pa.Table:
    """Every region of a current table, concatenated."""
    current = Registry(root)
    parts = [current.read_table(slug, r) for r in current.table_regions(slug)]
    tables = [p for p in parts if p is not None]
    return (
        pa.concat_tables(tables)
        if tables
        else pa.table({"id": pa.array([], pa.int64())})
    )


def id_of(root: Path, source: Source, catalogue_id: object) -> int:
    return int(
        Registry(root).lookup(source.catalogue, source.release, [str(catalogue_id)])[0]
    )
