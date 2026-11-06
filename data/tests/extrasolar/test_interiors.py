"""Stellar interiors: the grid tables, the fit, the tiers and the Interior table."""

import io
import json
import tarfile
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.export.extrasolar import container
from space_map_data.export.extrasolar.build import export_extrasolar
from space_map_data.extrasolar import placement
from space_map_data.extrasolar.interiors import (
    grid,
    inputs,
    metallicity,
    photometry,
    table,
)
from space_map_data.extrasolar.interiors.fit import fit
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.tables import POINT_SOURCE
from tests.extrasolar.export_registry import star, write_registry

# `grid.ready` before the autouse fixture of conftest replaces it.
READY = grid.ready
EEPS = grid.TPAGB - grid.ZAMS + 1
MS_EEPS = grid.TAMS - grid.ZAMS


def _tracks(feh: float, envelope: float = 0.72, dex: float = 0.0) -> grid.Tracks:
    """Main-sequence tracks of 0.8 to 1.2 M☉ with simple laws. `share` runs
    from 0 at the ZAMS to 1 at the TAMS. `dex` shifts every Teff."""
    masses = np.round(np.arange(0.80, 1.201, 0.02), 2)
    values = np.full((masses.size, EEPS, len(grid.TRACK_COLUMNS)), np.nan)
    share = np.linspace(0.0, 1.0, MS_EEPS)
    for k, mass in enumerate(masses):
        log_l = 4.0 * np.log10(mass) + 0.3 * share
        log_teff = 3.7612 + 0.6 * np.log10(mass) - 0.01 * share + dex
        log_r = 0.5 * log_l - 2.0 * (log_teff - np.log10(5772.0))
        column = {
            "star_age": np.log10(1e7 + share * 1e10 / mass**2.5),
            "star_mass": np.full(MS_EEPS, mass),
            "log_L": log_l,
            "log_Teff": log_teff,
            "log_R": log_r,
            "he_core_mass": np.zeros(MS_EEPS),
            "mass_conv_core": np.full(MS_EEPS, 0.1 * max(mass - 1.0, 0.0)),
            "center_h1": 0.7 * (1 - share),
            "center_he4": 0.28 + 0.7 * share,
            "log_center_T": 7.2 + 0.1 * np.log10(mass) + 0.05 * share,
            "log_center_Rho": 2.0 + 0.2 * share,
            "conv_env_bot_mass": np.full(MS_EEPS, 0.98 * mass),
            "conv_env_bot_radius": envelope * 10**log_r,
            "conv_env_top_radius": 10**log_r,
        }
        for i, name in enumerate(grid.TRACK_COLUMNS):
            values[k, :MS_EEPS, i] = column[name]
    return grid.Tracks(feh, masses, values)


@pytest.fixture(scope="module")
def tables() -> grid.Tables:
    return grid.build_tables([_tracks(-0.25, 0.70), _tracks(0.25, 0.74)])


# A star on the 1 M☉ track halfway along the main sequence.
SUN_LIKE = (3.7562, 0.15)


def _fit_one(tables, log_teff, log_l, feh=0.0, sigma_feh=0.05):
    return fit(
        tables,
        np.array([log_teff]),
        np.array([0.0]),
        np.array([log_l]),
        np.array([0.0]),
        np.array([feh]),
        np.array([sigma_feh]),
    )


def _q(name: str) -> int:
    return grid.QUANTITIES.index(name)


class TestGrid:
    """The posterior tables over the HR diagram."""

    def test_a_star_on_a_track_gets_its_values(self, tables):
        found = _fit_one(tables, *SUN_LIKE, feh=-0.25, sigma_feh=0.0)
        assert found.inside[0]
        assert found.value[0, _q("mass")] == pytest.approx(1.0, abs=0.03)
        assert found.value[0, _q("envelope_base_radius")] == pytest.approx(
            0.70, abs=0.005
        )
        assert grid.STAGES[found.stage[0]] == "main_sequence"

    def test_the_range_holds_the_age_spread(self, tables):
        found = _fit_one(tables, *SUN_LIKE)
        k = _q("centre_x")
        assert found.lower[0, k] < 0.35 < found.upper[0, k]
        assert found.upper[0, k] - found.lower[0, k] > 0.05

    def test_metallicity_between_two_nodes_mixes_them(self, tables):
        found = _fit_one(tables, *SUN_LIKE, feh=0.0, sigma_feh=0.0)
        k = _q("envelope_base_radius")
        assert found.value[0, k] == pytest.approx(0.72, abs=0.005)

    def test_the_metallicity_width_widens_the_range(self, tables):
        narrow = _fit_one(tables, *SUN_LIKE, feh=-0.2, sigma_feh=0.0)
        wide = _fit_one(tables, *SUN_LIKE, feh=-0.2, sigma_feh=0.25)
        k = _q("envelope_base_radius")
        assert wide.upper[0, k] - wide.lower[0, k] > (
            narrow.upper[0, k] - narrow.lower[0, k]
        )

    def test_a_star_far_from_every_track_is_outside(self, tables):
        assert not _fit_one(tables, 3.7562, -2.0).inside[0]

    def test_a_metallicity_off_the_grid_is_outside(self, tables):
        found = _fit_one(tables, *SUN_LIKE, feh=0.5)
        assert not found.inside[0]
        assert not found.feh_inside[0]

    def test_a_metallicity_within_its_widths_of_the_grid_is_inside(self, tables):
        assert _fit_one(tables, *SUN_LIKE, feh=0.35, sigma_feh=0.05).inside[0]

    def test_the_stars_own_widths_reach_the_tracks(self, tables):
        """0.4 dex over the end of the main sequence, beyond the grid's
        resolution but within 3 widths of the star's L."""
        above = (SUN_LIKE[0], 0.75)
        assert not _fit_one(tables, *above).inside[0]
        found = fit(
            tables,
            *(np.array([v]) for v in (above[0], 0.0, above[1], 0.15, 0.0, 0.05)),
        )
        assert found.inside[0]
        assert grid.STAGES[found.stage[0]] == "main_sequence"
        k = _q("centre_x")
        assert found.lower[0, k] < found.value[0, k] < found.upper[0, k]

    def test_a_width_must_be_finite(self, tables):
        with pytest.raises(ValueError):
            fit(tables, *(np.array([v]) for v in (3.75, np.nan, 0.1, 0.0, 0.0, 0.1)))

    def test_one_metallicity_is_no_grid(self):
        with pytest.raises(ValueError):
            grid.build_tables([_tracks(0.0)])

    def test_points_older_than_the_universe_weigh_nothing(self):
        whole = _tracks(0.0)
        values = whole.values[:2].copy()
        values[:, :MS_EEPS, 0] = np.log10(1e7 + np.linspace(0, 2e10, MS_EEPS))
        tracks = grid.Tracks(0.0, whole.masses[:2], values)
        young = int((10 ** values[0, :, 0] <= grid.AGE_LIMIT).sum())
        assert young < MS_EEPS
        # One interval of MASS_STEPS tracks, then the last mass. The last young
        # point of a track has no age step past it.
        tracks_count = grid.MASS_STEPS + 1
        found = grid.points(tracks).weight.size
        assert tracks_count * (young - 1) <= found <= tracks_count * young

    def test_the_radius_is_that_of_the_track(self, tables):
        found = _fit_one(tables, *SUN_LIKE, feh=-0.25, sigma_feh=0.0)
        k = _q("log_radius")
        log_r = 0.5 * SUN_LIKE[1] - 2.0 * (SUN_LIKE[0] - np.log10(5772.0))
        assert found.value[0, k] == pytest.approx(log_r, abs=0.02)
        assert found.lower[0, k] < found.value[0, k] < found.upper[0, k]


def _with_columns(tracks: grid.Tracks, rows: slice, **values: float) -> grid.Tracks:
    """`tracks` with TRACK_COLUMNS set to `values` on the tracks `rows`."""
    out = tracks.values.copy()
    for name, value in values.items():
        column = grid.TRACK_COLUMNS.index(name)
        out[rows, :MS_EEPS, column] = value
    return grid.Tracks(tracks.feh, tracks.masses, out)


class TestEnvelope:
    """The envelope base: no surface zone, full convection and two modes."""

    @pytest.mark.parametrize("top", [0.0, 0.3])
    def test_no_surface_zone_puts_the_base_at_the_surface(self, tmp_path, top):
        """MIST writes 0 when there is no outer zone, and on some EEPs its
        outer zone is a thin zone deep inside."""
        text = _track_text(3.0, 0.0, top=top)
        path = tmp_path / "MIST_v2.5_feh_p000_afe_p0_vvcrit0.4_EEPS.txz"
        with tarfile.open(path, "w:xz") as tar:
            info = tarfile.TarInfo("x/eeps/00300M.track.eep")
            info.size = len(text.encode())
            tar.addfile(info, io.BytesIO(text.encode()))
        first = dict(zip(grid.TRACK_COLUMNS, grid.read_tarball(path).values[0, 0]))
        assert first["conv_env_bot_mass"] == 3.0
        assert first["conv_env_bot_radius"] == pytest.approx(10 ** first["log_R"])

    def test_interpolation_does_not_cross_full_convection(self):
        """The tracks below 1 M☉ are fully convective. The tracks between
        them and a track with an envelope take the nearer one's base."""
        whole = _tracks(0.0)
        below = slice(0, 10)
        tracks = _with_columns(
            whole, below, conv_env_bot_mass=0.0, conv_env_bot_radius=0.0
        )
        found = grid.points(tracks)
        base = found.quantities[:, _q("envelope_base_radius")]
        assert ((base == 0.0) | (np.abs(base - 0.72) < 0.002)).all()
        assert (base == 0.0).any()

    def test_a_star_on_the_full_convection_boundary_takes_one_mode(self):
        """Fully convective tracks below 1 M☉: a star on the boundary has
        both, and its value is one of the two, never the mean."""
        tracks = [
            _with_columns(
                _tracks(feh),
                slice(0, 10),
                conv_env_bot_mass=0.0,
                conv_env_bot_radius=0.0,
            )
            for feh in (-0.25, 0.25)
        ]
        tables_ = grid.build_tables(tracks)
        k = _q("envelope_base_radius")
        values = []
        for log_mass in np.linspace(-0.02, 0.02, 9):
            log_teff = 3.7612 + 0.6 * log_mass - 0.005
            log_l = 4.0 * log_mass + 0.15
            found = fit(
                tables_,
                *(np.array([v]) for v in (log_teff, 0.01, log_l, 0.04, 0.0, 0.05)),
            )
            assert found.lower[0, k] <= found.value[0, k] <= found.upper[0, k]
            values.append(found.value[0, k])
        assert values[0] == 0.0
        assert values[-1] == pytest.approx(0.72, abs=0.01)
        assert all(v == 0.0 or v > 0.7 for v in values)
        assert any(v == 0.0 for v in values) and any(v > 0.7 for v in values)


def _track_text(mass: float, feh: float, top: float = 1.0) -> str:
    """A `.track.eep` file in the MIST layout with three EEPs from the ZAMS,
    a radius of 1 R☉ and the top of the outer convection zone at `top`."""
    names = ["star_age", *grid.TRACK_COLUMNS[1:], "extra", "phase"]
    rows = [
        [
            1e7 * (k + 1),
            mass,
            0.1 * k,
            3.76,
            0.0,
            0,
            0,
            0.7,
            0.28,
            7.2,
            2.0,
            min(0.98, top),
            min(0.7, top),
            top,
            9,
            0,
        ]
        for k in range(3)
    ]
    return "\n".join(
        [
            "# MIST version number  = 2.5",
            "# ---",
            "#  Yinit        Zinit   [Fe/H]   [a/Fe]  v/vcrit",
            f"# 0.2703  1.63577E-02  {feh:7.2f}     0.00     0.40",
            "# ---",
            "#     initial_mass   N_pts   N_EEP   N_col   phase        type",
            f"# {mass:.10E}       3       1     {len(names)}     YES    low-mass",
            f"# EEPs:      {grid.ZAMS}",
            "# ---",
            "#   " + "   ".join(str(i + 1) for i in range(len(names))),
            "#   " + "   ".join(names),
            *("  ".join(f"{v:.6E}" for v in row) for row in rows),
        ]
    )


class TestTarball:
    """The tracks as MIST publishes them."""

    def test_reads_the_columns_by_name_from_the_zams(self, tmp_path):
        path = tmp_path / "MIST_v2.5_feh_p000_afe_p0_vvcrit0.4_EEPS.txz"
        with tarfile.open(path, "w:xz") as tar:
            for mass in (1.0, 0.8):
                data = _track_text(mass, 0.0).encode()
                info = tarfile.TarInfo(f"x/eeps/{round(mass * 100):05d}M.track.eep")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        tracks = grid.read_tarball(path)
        assert tracks.feh == 0.0
        assert tracks.masses.tolist() == [0.8, 1.0]
        assert tracks.values.shape == (2, EEPS, len(grid.TRACK_COLUMNS))
        first = dict(zip(grid.TRACK_COLUMNS, tracks.values[1, 0]))
        assert first["star_age"] == pytest.approx(7.0)
        assert first["conv_env_bot_radius"] == pytest.approx(0.7)
        assert np.isnan(tracks.values[1, 3]).all()


NO_ROW: dict = {}


def _point_rows(*stars: dict, binary: tuple[int, ...] = ()) -> pa.Table:
    """Point source rows with what `inputs.read` reads, and no orbits. The
    IDs run from 100; `binary` holds the IDs of the points of two stars."""
    schema = POINT_SOURCE.schema
    fields = [schema.field(name) for name in inputs.COLUMNS]
    rows = [{"id": 100 + k} | star_ for k, star_ in enumerate(stars)]
    table_ = pa.Table.from_pylist(rows, schema=pa.schema(fields))
    systems = pa.table(
        {
            "id": pa.array(binary, pa.int64()),
            "point": pa.array([True] * len(binary), pa.bool_()),
        }
    )
    return inputs.with_binary_points(
        placement.with_orbit_parallax(table_, None), systems
    )


def _dwarf(**more) -> dict:
    """A single FGK dwarf at 10 pc: BP − RP 0.8, absolute G 5, parallax 1%."""
    return {
        "parallax": 100.0,
        "parallax_error": 1.0,
        "astrometry_source": "gaia-dr3",
        "fidelity_v2": 1.0,
        "phot_g_mean_mag": 5.0,
        "phot_bp_mean_mag": 5.4,
        "phot_rp_mean_mag": 4.6,
        "ruwe": 1.0,
        "non_single_star": 0,
        "in_oba_golden_sample": False,
        "teff_gspphot": 5704.0,
        "teff_gspphot_lower": 5650.0,
        "teff_gspphot_upper": 5760.0,
        "lum_flame": 1.413,
        "lum_flame_lower": 1.38,
        "lum_flame_upper": 1.45,
    } | more


class TestTiers:
    """The tier rules of the research count, over the panel's metallicity."""

    def _read(self, *stars: dict) -> inputs.Inputs:
        return inputs.read(_point_rows(*stars))

    def test_the_four_tiers(self):
        found = self._read(
            _dwarf(feh_pastel=0.1),
            _dwarf(mh_xgboost=0.1),
            _dwarf(feh_pastel=0.1, ruwe=2.0),
            _dwarf(),
        )
        assert found.tier.tolist() == [1, 2, 3, 3]
        assert found.feh_source.tolist() == [
            metallicity.PASTEL,
            metallicity.XP,
            metallicity.PASTEL,
            inputs.ASSUMED_SOLAR,
        ]
        assert found.feh[3] == 0.0
        assert found.sigma_feh[3] == inputs.SOLAR_SIGMA

    def test_unknown_multiplicity_keeps_tier_2_only(self):
        found = self._read(_dwarf(feh_pastel=0.1, ruwe=None, non_single_star=None))
        assert found.tier.tolist() == [2]

    def test_a_point_of_two_stars_has_no_tier(self):
        found = inputs.read(
            _point_rows(
                _dwarf(feh_pastel=0.1),
                _dwarf(feh_pastel=0.1),
                _dwarf(feh_pastel=0.1, non_single_star=1),
                binary=(101,),
            )
        )
        assert found.tier.tolist() == [1, inputs.NO_TIER, 3]
        assert found.out.tolist() == ["", "binary point", ""]

    def test_a_fair_distance_keeps_tier_2_only(self):
        found = self._read(_dwarf(feh_pastel=0.1, parallax_error=15.0))
        assert found.tier.tolist() == [2]

    def test_a_suspect_parallax_keeps_tier_3_only(self):
        """Placement step 6: a Gaia row of low fidelity that Hipparcos saw."""
        suspect = {"fidelity_v2": 0.2, "hipparcos_photometry_source": "hipparcos-2007"}
        found = self._read(
            _dwarf(feh_pastel=0.1, **suspect),
            _dwarf(feh_pastel=0.1, fidelity_v2=0.2),
        )
        assert placement.placement(_point_rows(_dwarf(**suspect))).by_suspect[0]
        assert found.tier.tolist() == [3, inputs.NO_TIER]

    def test_gspphot_metallicity_counts_as_none(self):
        found = self._read(_dwarf(mh_gspphot=-0.3))
        assert found.tier.tolist() == [3]
        assert found.feh_source.tolist() == [inputs.ASSUMED_SOLAR]

    def test_stars_with_no_tier(self):
        found = self._read(
            _dwarf(classprob_dsc_combmod_whitedwarf=0.9, phot_g_mean_mag=12.0),
            _dwarf(spicy_id=5),
            _dwarf(simbad_otype="TT*"),
            _dwarf(
                distance=10.0,
                distance_lower=4.0,
                distance_upper=16.0,
                distance_source="literature",
            ),
            _dwarf(phot_bp_mean_mag=None, phot_rp_mean_mag=None, teff_gspphot=None),
        )
        assert (found.tier == inputs.NO_TIER).all()
        assert found.out.tolist() == [
            "white dwarf",
            "young stellar object",
            "young stellar object",
            "distance",
            "no kind",
        ]

    def test_a_white_dwarf_lies_below_the_main_sequence(self):
        found = self._read(
            _dwarf(classprob_dsc_combmod_whitedwarf=0.9),
            _dwarf(simbad_otype="WD*"),
        )
        assert found.out.tolist() == ["", "white dwarf"]

    def test_the_distance_error_is_that_of_the_render_distance(self):
        rows = _point_rows(
            _dwarf(),
            _dwarf(
                parallax=None,
                parallax_error=None,
                host_distance=20.0,
                host_distance_error=1.0,
            ),
            _dwarf(
                parallax=None,
                parallax_error=None,
                distance=10.0,
                distance_lower=9.0,
                distance_upper=11.0,
                distance_source="literature",
            ),
        )
        error = placement.distance_error(rows, placement.placement(rows))
        assert error == pytest.approx([0.01, 0.05, 0.1])

    def test_inputs_are_the_panels(self):
        found = self._read(
            _dwarf(teff_gspphot_lower=5600.0, teff_gspphot_upper=5800.0),
            _dwarf(
                lum_flame=None,
                lum_flame_spec=2.0,
                lum_flame_spec_lower=1.9,
                lum_flame_spec_upper=2.1,
                teff_gspphot=None,
                host_teff=6000.0,
            ),
            _dwarf(teff_gspphot_lower=None, teff_gspphot_upper=None),
        )
        assert found.log_teff[0] == pytest.approx(np.log10(5704.0))
        assert found.sigma_log_teff[0] == pytest.approx(
            (np.log10(5800.0) - np.log10(5600.0)) / 2
        )
        assert found.log_l[1] == pytest.approx(np.log10(2.0))
        assert found.log_teff[1] == pytest.approx(np.log10(6000.0))
        assert found.teff_source[2] is None


class TestReady:
    """The grid tables of the stellar-models download."""

    @pytest.fixture(autouse=True)
    def leases(self, monkeypatch):
        """The leases of the test, closed at its end."""
        held: dict = {}
        monkeypatch.setattr(grid, "_LEASES", held)
        yield held
        for handle in held.values():
            handle.close()

    @pytest.fixture
    def download(self, tmp_path):
        """The manifest's tarballs, with their download record."""
        tracks_dir = tmp_path / "stellar-models" / grid.MIST.key
        tracks_dir.mkdir(parents=True)
        files = {}
        for k, remote in enumerate(grid.MIST.urls):
            (tracks_dir / remote.name).write_bytes(b"x" * (k + 1))
            files[remote.name] = {"url": remote.url, "bytes": k + 1}
        record = {grid.MIST.key: {"fetched_at": "2026-11-05", "files": files}}
        (tracks_dir.parent / grid.DOWNLOAD_RECORD).write_text(
            json.dumps({"catalogues": record})
        )
        return tracks_dir

    @pytest.fixture
    def builds(self, monkeypatch, tables):
        made = []

        def build(tracks_dir, out):
            made.append(out)
            grid.save(tables, out)

        monkeypatch.setattr(grid, "build", build)
        return made

    def test_builds_once_into_a_directory_of_its_inputs(
        self, download, builds, tables, tmp_path
    ):
        root = tmp_path / "cache"
        out = READY(download, root)
        assert READY(download, root) == out
        assert len(builds) == 1 and builds[0] != out
        assert out.parent == root and out.name.startswith(grid.MIST.key)
        assert grid.load(out).sums.shape == tables.sums.shape
        assert [path.name for path in root.iterdir() if path.is_dir()] == [out.name]

    def _download_again(self, download, content: bytes) -> None:
        """Every tarball written again with `content`, and a new record."""
        record_path = download.parent / grid.DOWNLOAD_RECORD
        record = json.loads(record_path.read_text())
        entry = record["catalogues"][grid.MIST.key]
        entry["fetched_at"] = "2026-12-01"
        for name, file in entry["files"].items():
            (download / name).write_bytes(content or b"x" * file["bytes"])
            file["bytes"] = (download / name).stat().st_size
        record_path.write_text(json.dumps(record))

    def test_the_same_bytes_again_keep_the_tables(self, download, builds, tmp_path):
        root = tmp_path / "cache"
        first = READY(download, root)
        self._download_again(download, b"")
        assert READY(download, root) == first and len(builds) == 1

    def test_new_bytes_build_new_tables_and_prune_the_old(
        self, download, builds, tmp_path, leases
    ):
        root = tmp_path / "cache"
        first = READY(download, root)
        leases.pop(first).close()
        self._download_again(download, b"new")
        second = READY(download, root)
        assert second != first and len(builds) == 2
        assert not first.exists() and second.exists()

    def test_tables_that_a_process_holds_stay(self, download, builds, tmp_path):
        """The test's own lease on the first tables stands for another
        process."""
        root = tmp_path / "cache"
        first = READY(download, root)
        self._download_again(download, b"new")
        second = READY(download, root)
        assert second != first and first.exists()

    def test_a_checksum_is_taken_once(self, download, builds, tmp_path, monkeypatch):
        root = tmp_path / "cache"
        READY(download, root)
        monkeypatch.setattr(grid, "_sha256", lambda path: pytest.fail(str(path)))
        READY(download, root)

    def test_a_missing_tarball_stops(self, download, builds, tmp_path):
        missing = grid.MIST.urls[3].name
        (download / missing).unlink()
        with pytest.raises(grid.GridError, match=missing):
            READY(download, tmp_path / "cache")
        assert not builds

    def test_a_tarball_of_another_size_stops(self, download, builds, tmp_path):
        (download / grid.MIST.urls[0].name).write_bytes(b"truncated")
        with pytest.raises(grid.GridError, match="size"):
            READY(download, tmp_path / "cache")

    def test_no_download_record_stops(self, download, builds, tmp_path):
        (download.parent / grid.DOWNLOAD_RECORD).unlink()
        with pytest.raises(grid.GridError):
            READY(download, tmp_path / "cache")


def _bright(**more) -> dict:
    """A saturated Hipparcos-only dwarf at 10 pc: B − V 0.665 gives 5704 K by
    Casagrande 2010, and V 4.435 gives log L 0.156 by Flower's BC."""
    return {
        "parallax": 100.0,
        "parallax_error": 0.5,
        "astrometry_source": "hipparcos-2007",
        "hipparcos_photometry_source": "hipparcos-2007",
        "v_mag": 4.435,
        "b_v": 0.665,
        "b_v_error": 0.005,
        "v_i": 0.72,
        "feh_pastel": 0.0,
    } | more


class TestRelations:
    """The published relations, against their own tables."""

    def test_casagrande_gives_the_sun_its_teff(self):
        teff = 10 ** photometry.casagrande_log_teff(np.array([0.641]), np.zeros(1))
        assert teff[0] == pytest.approx(5777, abs=5)

    def test_flower_matches_its_table_3(self):
        log_teff = photometry.flower_log_teff(np.array([0.0, 0.65, 1.0]))
        assert log_teff == pytest.approx([3.9791, 3.7572, 3.6852], abs=2e-4)
        assert photometry.flower_bc(np.array([3.7572]))[0] == pytest.approx(
            -0.091, abs=0.002
        )

    def test_the_slope_holds_at_the_ends_of_the_range(self):
        for log_teff_of, colours, more in (
            (photometry.flower_log_teff, photometry.FLOWER_COLOURS, ()),
            (photometry.casagrande_log_teff, photometry.CASAGRANDE_COLOURS, (0.0,)),
        ):
            ends = np.array(colours)
            found = photometry.slope(log_teff_of, ends, *(np.full(2, m) for m in more))
            assert np.isfinite(found).all() and (found > 0).all()

    def test_outside_their_ranges_they_give_nothing(self):
        assert np.isnan(photometry.flower_log_teff(np.array([2.0]))[0])
        assert np.isnan(photometry.casagrande_log_teff(np.array([0.1]), np.zeros(1))[0])


class TestFallbacks:
    """The Teff and L of the stars that Gaia gives none."""

    def _read(self, *stars: dict) -> inputs.Inputs:
        return inputs.read(_point_rows(*stars))

    def test_the_teff_order(self):
        no_gaia = {"teff_gspphot": None}
        found = self._read(
            _dwarf(
                teff_xgboost=5600.0,
                teff_apogee=5650.0,
                teff_apogee_error=50.0,
                **no_gaia,
            ),
            _dwarf(teff_xgboost=5600.0, **no_gaia),
            _dwarf(**no_gaia, b_v=0.665, b_v_error=0.005),
            _dwarf(teff_xgboost=5600.0, host_teff=5900.0),
        )
        assert found.teff_source.tolist() == [
            inputs.APOGEE,
            inputs.XP,
            photometry.CASAGRANDE_2010,
            inputs.GSPPHOT,
        ]
        assert 10 ** found.log_teff[0] == pytest.approx(5650.0)

    def test_each_teff_holds_for_its_kind_only(self):
        hot = {
            "teff_gspphot": None,
            "phot_bp_mean_mag": 5.0,
            "phot_rp_mean_mag": 5.0,
            "phot_g_mean_mag": 1.0,
        }
        found = self._read(
            _dwarf(teff_apogee=9000.0, teff_esphs=9500.0, **hot),
            _dwarf(teff_esphs=9500.0, teff_gspphot=None),
            _dwarf(teff_lamost=5600.0, teff_gspphot=None),
        )
        assert found.teff_source.tolist() == [inputs.ESPHS, None, None]

    def test_the_luminosity_order(self):
        no_flame = {"lum_flame": None}
        found = self._read(
            _dwarf(
                lum_flame_spec=1.2,
                lum_flame_spec_lower=1.1,
                lum_flame_spec_upper=1.3,
                radius_literature=1.0,
                **no_flame,
            ),
            _dwarf(radius_literature=1.0, **no_flame),
            _dwarf(v_mag=4.435, **no_flame),
            _dwarf(**no_flame),
        )
        assert found.luminosity_source.tolist() == [
            inputs.FLAME_SPEC,
            inputs.RADIUS,
            inputs.BOLOMETRIC,
            None,
        ]
        assert found.log_l[1] == pytest.approx(4 * np.log10(5704.0 / 5772.0))

    def test_a_derived_input_keeps_a_star_out_of_tier_1(self):
        found = self._read(
            _dwarf(feh_pastel=0.1),
            _dwarf(feh_pastel=0.1, teff_gspphot=None, b_v=0.665),
            _dwarf(feh_pastel=0.1, lum_flame=None, v_mag=4.435),
            _dwarf(feh_pastel=0.1, lum_flame=None, radius_literature=1.0),
        )
        assert found.tier.tolist() == [1, 2, 2, 1]

    def test_an_unknown_extinction_sends_a_derived_star_to_tier_3(self):
        far = {"parallax": 5.0, "parallax_error": 0.1, "phot_g_mean_mag": 11.5}
        far |= {"phot_bp_mean_mag": 11.9, "phot_rp_mean_mag": 11.1}
        found = self._read(
            _dwarf(feh_pastel=0.1, lum_flame=None, v_mag=11.0, **far),
            _dwarf(
                feh_pastel=0.1, lum_flame=None, v_mag=11.0, azero_gspphot=0.1, **far
            ),
            _dwarf(feh_pastel=0.1, **far),
        )
        assert found.tier.tolist() == [3, 2, 1]
        assert found.log_l[1] - found.log_l[0] == pytest.approx(0.04)


class TestMetallicity:
    """The port of the panel's metallicity order."""

    def _choose(self, kind: str, **values) -> tuple[float, str | None]:
        rows = _point_rows(_dwarf(**values))
        value, _, source = metallicity.choose(rows, np.array([kind]))
        return float(value[0]), source[0]

    def test_an_m_dwarf_takes_no_pastel(self):
        assert self._choose(metallicity.M_DWARF, feh_pastel=0.2)[1] is None
        assert self._choose(metallicity.FGK_DWARF, feh_pastel=0.2) == (
            pytest.approx(0.2),
            metallicity.PASTEL,
        )

    def test_an_oba_star_takes_spectra_of_hot_stars_only(self):
        assert self._choose(metallicity.OBA, mh_xgboost=0.1)[1] is None
        assert self._choose(metallicity.OBA, feh_xhip=0.1, feh_xhip_quality="B")[1] == (
            metallicity.XHIP
        )

    def test_lamost_needs_a_quiet_m_dwarf(self):
        quiet = self._choose(metallicity.M_DWARF, mh_lamost=-0.2, activity_lamost=False)
        active = self._choose(metallicity.M_DWARF, mh_lamost=-0.2, activity_lamost=True)
        assert quiet[1] == metallicity.LAMOST
        assert active[1] is None

    def test_gspspec_holds_on_the_medium_cut(self):
        good = "0" * 6 + "3" + "0" * 34
        bad = "0" * 12 + "1" + "0" * 28
        values = {
            "mh_gspspec": 0.0,
            "mh_gspspec_calibrated": 0.05,
            "fem_gspspec": 0.0,
            "feh_gspspec_calibrated": 0.08,
        }
        assert self._choose(metallicity.GIANT, flags_gspspec=good, **values) == (
            pytest.approx(0.08),
            metallicity.GSPSPEC,
        )
        assert self._choose(metallicity.GIANT, flags_gspspec=bad, **values)[1] is None


# The stars of the panel's rules, which metallicity.test.ts reads too.
PANEL_STARS = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "star_metallicity.json").read_text()
)["stars"]


@pytest.mark.parametrize("star_", PANEL_STARS, ids=lambda star_: star_["name"])
def test_the_port_matches_the_panel(star_):
    rows = _point_rows(star_["row"])
    for name, value in star_["row"].items():
        column = rows.schema.field(name).type
        if isinstance(value, str):
            assert column == pa.string(), name
        elif isinstance(value, bool):
            assert column == pa.bool_(), name
        elif value is not None:
            assert column == pa.float32(), name
    distance = placement.star_distance(rows, placement.placement(rows))[0]
    colour, abs_g = inputs.colour(rows), inputs.absolute_g(rows, distance)
    kind = metallicity.star_kind(colour, abs_g)
    value, _, source = metallicity.choose(rows, kind)
    expected = star_["expected"]
    assert (kind[0] or None, source[0]) == (expected["kind"], expected["source"])
    for found, wanted in (
        (value[0], expected["value"]),
        (colour[0], expected["colour"]),
        (abs_g[0], expected["absolute_g"]),
    ):
        if wanted is None:
            assert np.isnan(found)
        else:
            assert found == pytest.approx(wanted, abs=1e-4)


class TestTable:
    """The Interior rows."""

    def test_fitted_rows(self, tables):
        rows, counts = table.rows(
            _point_rows(
                _dwarf(feh_pastel=0.0),
                _dwarf(),
                _dwarf(lum_flame=0.01),
                _dwarf(teff_gspphot=None),
            ),
            tables,
        )
        assert rows.schema == table.INTERIOR.schema
        assert rows["tier"].to_pylist() == [1, 3]
        assert counts["outside the grid: HR diagram"] == 1
        assert counts["no Teff"] == 1
        first, assumed = rows.to_pylist()
        assert first["stage"] == "main_sequence"
        assert first["teff"] == 5704.0
        assert first["feh_source"] == metallicity.PASTEL
        assert first["envelope_base_radius"] == pytest.approx(0.72, abs=0.01)
        assert first["radius_lower"] < first["radius"] < first["radius_upper"]
        assert first["radius"] == pytest.approx(1.2, rel=0.1)
        assert first["centre_temperature"] == pytest.approx(
            10 ** (7.2 + 0.025), rel=0.05
        )
        assert first["centre_x_lower"] < first["centre_x_upper"]
        assert "centre_x" not in first and "convective_core_mass" not in first
        assert assumed["feh_source"] == inputs.ASSUMED_SOLAR
        assert assumed["envelope_base_radius"] is not None
        for name in table.CENTRE_COLUMNS:
            for suffix in ("_lower", "_upper"):
                assert assumed[f"{name}{suffix}"] is None

    def test_a_bright_hipparcos_star_gets_an_interior(self, tables):
        rows, counts = table.rows(_point_rows(_bright()), tables)
        assert counts["tier 2"] == 1
        (row,) = rows.to_pylist()
        assert row["teff_source"] == photometry.CASAGRANDE_2010
        assert row["luminosity_source"] == inputs.BOLOMETRIC
        assert row["stage"] == "main_sequence"
        assert row["mass"] == pytest.approx(1.0, abs=0.05)

    def test_inputs_too_wide_to_place_the_star_give_no_row(self, tables):
        """Rigel's B − V Teff has a width of 0.47 dex."""
        rows, counts = table.rows(
            _point_rows(
                _dwarf(feh_pastel=0.0),
                _dwarf(teff_gspphot_lower=4000.0, teff_gspphot_upper=8500.0),
                _dwarf(lum_flame_lower=0.2, lum_flame_upper=10.0),
            ),
            tables,
        )
        assert rows["id"].to_pylist() == [100]
        assert counts["inputs too uncertain"] == 2

    def test_a_base_above_0_never_rounds_to_0(self):
        values = np.array([0.0, 0.0004, 0.0006, 0.5])
        assert table._rounded("envelope_base_radius", values).tolist() == [
            0.0,
            0.001,
            0.001,
            0.5,
        ]
        assert table._rounded("centre_x", values)[1] == 0.0

    def test_values_are_rounded_to_their_precision(self, tables):
        rows, _ = table.rows(_point_rows(_dwarf(feh_pastel=0.0)), tables)
        (row,) = rows.to_pylist()
        for name in ("mass", "envelope_base_radius", "convective_core_mass_upper"):
            assert row[name] == pytest.approx(round(row[name], 3), abs=1e-7)
        for name in ("radius", "centre_temperature"):
            assert row[name] == pytest.approx(float(f"{row[name]:.3g}"), rel=1e-6)

    def test_a_curated_star_takes_the_place_of_its_fit(self, tables):
        points = _point_rows(_dwarf(), _dwarf(), _dwarf(teff_gspphot=None))
        rows, _ = table.rows(points, tables)
        assert rows["id"].to_pylist() == [100, 101]
        stars = {
            101: table.Curated("hip/2007/1", '{"layers": []}'),
            102: table.Curated("hip/2007/2", "{}"),
        }
        out = table.with_curated(rows, points, 0, stars)
        assert out["id"].to_pylist() == [100, 101, 102]
        assert out["tier"].to_pylist() == [3, table.CURATED_TIER, table.CURATED_TIER]
        assert out["curated"].to_pylist() == [None, '{"layers": []}', "{}"]
        assert out["mass"].to_pylist()[1] is None
        assert out["teff"].to_pylist() == [5704.0, None, None]
        assert out["teff_source"].to_pylist()[1:] == [None, None]

    @pytest.mark.parametrize(
        "point, why",
        [
            (
                _dwarf(classprob_dsc_combmod_whitedwarf=0.9, phot_g_mean_mag=12.0),
                "white dwarf",
            ),
            (_dwarf(simbad_otype="TT*"), "young stellar object"),
            (NO_ROW, "no Point source row"),
        ],
    )
    def test_a_curated_star_must_be_a_star_the_frontend_shows(self, tables, point, why):
        points = _point_rows(_dwarf(), *([point] if point else []))
        stars = {101: table.Curated("hip/2007/7", "{}")}
        with pytest.raises(ValueError, match=f"hip/2007/7 .*{why}"):
            table.with_curated(table.rows(points, tables)[0], points, 0, stars)

    def test_a_curated_point_of_two_stars_is_an_error(self, tables):
        points = _point_rows(_dwarf(), _dwarf(), binary=(101,))
        stars = {101: table.Curated("hip/2007/7", "{}")}
        with pytest.raises(ValueError, match="binary point"):
            table.with_curated(table.rows(points, tables)[0], points, 0, stars)

    def test_curated_stars_resolve_by_their_key(self, monkeypatch, tmp_path):
        sirius = ("hip", "2007", "32349")
        facts = table.STAR_INTERIORS[sirius]
        monkeypatch.setattr(
            table, "STAR_INTERIORS", {sirius: facts, ("hip", "2007", "1"): facts}
        )
        registry = Registry(tmp_path)

        def lookup(catalogue, release, numbers):
            return np.array([77 if n == "32349" else 0 for n in numbers], np.int64)

        monkeypatch.setattr(registry, "lookup", lookup)
        found = table.curated(registry)
        assert list(found) == [77]
        assert found[77].name == "hip/2007/32349"
        monkeypatch.setattr(
            registry, "lookup", lambda c, r, numbers: np.array([77, 77])
        )
        with pytest.raises(ValueError, match="32349"):
            table.curated(registry)
        block = json.loads(found[77].block)
        assert [layer["role"] for layer in block["layers"]] == [
            "convective_zone",
            "radiative_zone",
        ]
        assert block["centre_temperature_k"] == pytest.approx(22.46e6)
        assert block["sources"][0]["url"].endswith("10.1051/0004-6361:20030994")

    def test_credits_follow_the_rows(self):
        assert table.credits(Counter({"curated": 2})) == []
        found = table.credits(Counter({"tier 2": 1, "teff_source: flower-1996": 1}))
        assert [credit["organisation"] for credit in found] == [
            table.MIST_CREDIT["organisation"],
            "Flower 1996",
            "Torres 2010",
        ]
        assert found[1]["source"].startswith("https://doi.org/")


class TestExport:
    """The Interior table in the extrasolar export."""

    def test_the_table_is_served_site_only(self, tmp_path, tables, monkeypatch):
        tables_dir = tmp_path / "tables"
        tables_dir.mkdir()
        grid.save(tables, tables_dir)
        monkeypatch.setattr(grid, "ready", lambda tracks, out: tables_dir)
        fitted = {
            "teff_gspphot": 5704.0,
            "teff_gspphot_lower": 5650.0,
            "teff_gspphot_upper": 5760.0,
            "lum_flame": 1.413,
            "lum_flame_lower": 1.38,
            "lum_flame_upper": 1.45,
            "feh_pastel": 0.0,
            "ruwe": 1.0,
            "non_single_star": 0,
        }
        built = write_registry(
            tmp_path / "reg", [star(10.0, 5.0) | fitted, star(11.0, 5.0)]
        )
        curated_id = int(built.ids[1])
        monkeypatch.setattr(
            table,
            "curated",
            lambda registry: {
                curated_id: table.Curated("hip/2007/1", '{"layers": []}')
            },
        )
        out = tmp_path / "x"
        export_extrasolar(built.root, out, workers=1)

        root = out / "v1" / "x"
        metadata = json.loads((root / "metadata.json").read_text())
        assert table.MIST_CREDIT in metadata["credits"]
        entry = metadata["tables"]["interior"]
        assert entry["number"] is None
        assert entry["distribution"] == "site-only"
        assert entry["rows"] == 2
        assert {"name": "stage", "type": "dict"} in entry["columns"]
        rows = pa.concat_tables(
            container.read(path).table()
            for path in sorted((root / "interior").glob("*/*.bin.gz"))
        ).to_pylist()
        by_id = {row["id"]: row for row in rows}
        assert by_id[built.ids[0]]["tier"] == 1
        assert by_id[built.ids[0]]["stage"] == "main_sequence"
        assert by_id[curated_id]["tier"] == table.CURATED_TIER
        assert by_id[curated_id]["curated"] == '{"layers": []}'
