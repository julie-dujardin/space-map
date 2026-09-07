"""The probe-visited small bodies in the chebyshev export.

They are fit into their own `.npz` pool (so they stay out of
`fit_centers.load_candidates`) but ship as ordinary `major_asteroids` bodies,
and each has to be listed in `PROMOTED_EXTRA_IDS` — chebyshev coverage no
longer promotes on its own, and a covered body drops out of the elements zones
that would otherwise carry its point-cloud dot.
"""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.constants.promoted import PROMOTED_EXTRA_IDS, PROMOTED_TYPES
from space_map_data.export.labels import _promoted_ids
from space_map_data.export.position.chebyshev.coverage import (
    chebyshev_coverage,
    chebyshev_written_ids,
)
from space_map_data.export.position.chebyshev.writer import (
    _determine_zone,
    write_chebyshev,
)
from space_map_data.export.position.layout import chebyshev_npz_paths
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.base import Base
from space_map_data.probes.small_bodies import SMALL_BODY_TARGET_NAIF_IDS
from space_map_data.utils.naif import (
    CHEBYSHEV_ASTEROID_WHITELIST,
    spk_id_from_naif,
)

RYUGU_NAIF = 2162173
HALLEY_NAIF = 1000036
VESTA_NAIF = 2000004

BODIES = [
    ("spkid-20162173", "Ryugu", ObjectType.asteroid_inner, RYUGU_NAIF),
    ("spkid-1000036", "1P/Halley", ObjectType.comet, HALLEY_NAIF),
    ("spkid-20000004", "4 Vesta", ObjectType.asteroid_main_belt, VESTA_NAIF),
]


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        sess.add_all(
            [
                Object(
                    id=oid,
                    name=name,
                    object_type=t,
                    parent_id="naif-0",
                    naif_id=naif,
                    spkid=int(oid.split("-")[1]),
                )
                for oid, name, t, naif in BODIES
            ]
        )
        sess.commit()
        yield sess


def _write_npz(path: Path, naif_id: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        start_jds=np.array([2451545.0]),
        end_jds=np.array([2455197.0]),
        coeffs=np.zeros((1, 3, 8), dtype=np.float64),
        meta=np.array([naif_id, 0, 7], dtype=np.int64),
        params=np.array([2451545.0, 2455197.0, 86400.0], dtype=np.float64),
    )


@pytest.fixture
def download_dir(tmp_path: Path) -> Path:
    """Vesta in the perturber pool and in the target pool (it is both), Ryugu
    and Halley in the target pool only."""
    derived = tmp_path / "derived" / "position"
    (derived / "tables").mkdir(parents=True)
    (derived / "tables" / "metadata.json").write_bytes(
        b'{"chebyshev_start_year": 2000, "chebyshev_end_year": 2010,'
        b' "chebyshev_chunk_years": 5}'
    )
    _write_npz(derived / "chebyshev" / f"{VESTA_NAIF}.npz", VESTA_NAIF)
    targets = derived / "chebyshev-small-bodies"
    for naif in (VESTA_NAIF, RYUGU_NAIF, HALLEY_NAIF):
        _write_npz(targets / f"{naif}.npz", naif)
    return tmp_path


class TestTargetPool:
    def test_targets_ship_alongside_the_perturbers(
        self, session, download_dir, tmp_path
    ):
        manifest = write_chebyshev(session, download_dir, tmp_path / "out", {}, {})
        assert set(manifest) == {"major_asteroids"}

    def test_a_body_in_both_pools_is_read_once(self, download_dir):
        """Vesta is both an sb441 perturber and a Dawn target; the export must
        see one file for it — the perturber fit, which spans the whole export
        range rather than one mission."""
        paths = chebyshev_npz_paths(download_dir)
        assert [p.name for p in paths] == [
            f"{VESTA_NAIF}.npz",
            f"{HALLEY_NAIF}.npz",
            f"{RYUGU_NAIF}.npz",
        ]
        assert paths[0].parent.name == "chebyshev"

    def test_only_full_range_fits_drop_the_element_row(self, session, download_dir):
        """A target fit covers a flyby, so the body still needs the element row
        that carries it the rest of the timeline; only Vesta's perturber fit
        spans the export range and replaces one."""
        assert chebyshev_coverage(session, download_dir) == {"spkid-20000004"}

    def test_every_written_body_counts_as_written(self, session, download_dir):
        assert chebyshev_written_ids(session, download_dir) == {
            "spkid-20000004",
            "spkid-20162173",
            "spkid-1000036",
        }

    def test_comets_never_land_in_the_major_zone(self):
        """`major` is the Sun/planet/dwarf tier — nothing comet-sized belongs
        in it, whatever route brought it into the export."""
        assert _determine_zone(ObjectType.comet, 0) == "major_asteroids"

    def test_ceres_stays_in_the_major_zone(self):
        """Ceres is a Dawn target *and* a dwarf planet; being on the target
        list must not pull it out of the tier its type puts it in."""
        assert _determine_zone(ObjectType.dwarf_planet, 0) == "major"


class TestPromotion:
    def test_coverage_alone_does_not_promote(self):
        """The whole point of the explicit list: a covered body that nobody
        listed stays off the map."""
        assert (
            _promoted_ids(
                {"spkid-20000200": {"type": ObjectType.asteroid_main_belt}},
                {"spkid-20000200"},
                set(),
                set(),
                {},
            )
            == set()
        )

    def test_every_covered_small_body_is_listed(self):
        """The invariant `write_global_labels` warns about, checked here where
        it is decidable: both covered sets are frozen constants, so a body
        added to either without a promotion entry fails at commit time rather
        than as a line in a multi-hour export log."""
        covered = set(SMALL_BODY_TARGET_NAIF_IDS) | CHEBYSHEV_ASTEROID_WHITELIST
        missing = sorted(
            naif
            for naif in covered
            if f"spkid-{spk_id_from_naif(naif) or naif}" not in PROMOTED_EXTRA_IDS
        )
        # Ceres alone, and only because it is a dwarf planet — promoted by type,
        # and carried by `major` rather than `major_asteroids`.
        assert missing == [2000001]
        assert ObjectType.dwarf_planet in PROMOTED_TYPES
