"""Streaming a zone in CHUNK_SIZE-aligned batches must land the same part files
as a one-shot write.

This guards the SBDB batching path: a giant combo is loaded and written in
`_SBDB_BATCH_ROWS` batches, each shifted by `part_offset` so the parts form a
contiguous `0..N-1` run. The on-disk result must be byte-identical to writing
the whole combo at once.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.export.pipeline import orchestrator, zone
from space_map_data.export.pipeline.orchestrator import (
    _Aggregators,
    _iter_sbdb_zone_snapshots,
)
from space_map_data.export.pipeline.zone import _write_element_parts
from space_map_data.models.object import Object, ObjectType, OrbitalSource
from space_map_data.models.object.base import Base
from space_map_data.models.object.sbdb import SBDB, OrbitClass
from tests.conftest import make_object


def _bodies(n: int) -> list:
    return [
        make_object(
            id=f"naif-{1000 + i}",
            naif_id=1000 + i,
            name=f"body-{i}",
            object_type=ObjectType.moon,
            orbital_source=OrbitalSource.spice,
        )
        for i in range(n)
    ]


def _write(objs, out_dir, part_offset, monkeypatch, chunk_size=10) -> int:
    # Shrink the chunk size so a handful of objects spans several parts.
    monkeypatch.setattr(zone, "CHUNK_SIZE", chunk_size)
    return _write_element_parts(
        objs,
        out_dir,
        "moons",
        0,
        has_localized={},
        wikidata_entities=MagicMock(),
        units=MagicMock(),
        time=None,
        part_offset=part_offset,
    )


def test_batched_offset_parts_match_one_shot(tmp_path, monkeypatch):
    objs = _bodies(25)  # 3 parts at chunk size 10: [0:10], [10:20], [20:25]

    one = tmp_path / "one"
    assert _write(objs, one, 0, monkeypatch) == 3

    # Two CHUNK-aligned batches: 20 rows then 5, the second offset by 20/10 = 2.
    batched = tmp_path / "batched"
    assert _write(objs[:20], batched, 0, monkeypatch) == 2
    assert _write(objs[20:], batched, 2, monkeypatch) == 1

    rel = "position/moons"  # flat single-zoom zone — no zoom segment
    one_files = sorted(p.name for p in (one / rel).iterdir())
    batched_files = sorted(p.name for p in (batched / rel).iterdir())
    assert one_files == batched_files == ["0.bin.gz", "1.bin.gz", "2.bin.gz"]
    for name in one_files:
        assert (one / rel / name).read_bytes() == (batched / rel / name).read_bytes()


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def test_sbdb_streaming_spans_batches_without_killing_session(
    session, tmp_path, monkeypatch
):
    """Streaming a combo across a batch boundary must not invalidate the
    identity map mid-cursor (regression: `expunge_all()` killed the map the
    live `yield_per` cursor was still feeding rows into)."""
    monkeypatch.setattr(orchestrator, "CHUNK_SIZE", 10)
    monkeypatch.setattr(orchestrator, "_SBDB_BATCH_ROWS", 20)
    # sbdb_zone_signature reads DOWNLOAD_DIR; stub it out for the unit test.
    monkeypatch.setattr(
        orchestrator.incremental, "sbdb_zone_signature", lambda *a, **k: {}
    )

    n = 25  # one unnamed MBA combo → batches of 20 then 5
    for i in range(n):
        obj = Object(
            id=f"spkid-{i}",
            name=None,
            object_type=ObjectType.asteroid,
            orbital_source=OrbitalSource.sbdb,
            spkid=i,
            random_int=i,
        )
        obj.sbdb = SBDB(spkid=str(i), object_id=f"spkid-{i}", class_=OrbitClass.MBA)
        session.add(obj)
    session.flush()

    batches = list(
        _iter_sbdb_zone_snapshots(session, set(), tmp_path, _Aggregators(), False)
    )

    # Two batches, offsets 0 then 20/10 = 2, covering every row once in order.
    assert [(z, zoom, off) for z, zoom, _, off in batches] == [
        ("small_bodies/MBA", 1, 0),
        ("small_bodies/MBA", 1, 2),
    ]
    seen = [o.id for _, _, snaps, _ in batches for o in snaps.base]
    assert seen == [f"spkid-{i}" for i in range(n)]
