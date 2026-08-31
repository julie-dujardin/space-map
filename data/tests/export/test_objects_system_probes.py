"""Tests for the planetary system roll-up: a barycenter's probes list."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.export.objects import probe_targets
from space_map_data.export.objects.probe_targets import attach_system_probes
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.base import Base


@pytest.fixture
def session() -> Iterator[Session]:
    """Fresh in-memory SQLite with the full schema, scoped to one test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        sess.add_all(
            [
                Object(
                    id="naif-4",
                    name="Mars Barycenter",
                    object_type=ObjectType.barycenter,
                ),
                Object(
                    id="naif-499",
                    name="Mars",
                    object_type=ObjectType.planet,
                    parent_id="naif-4",
                ),
                Object(
                    id="naif-401",
                    name="Phobos",
                    object_type=ObjectType.moon,
                    parent_id="naif-4",
                ),
                # Hung off the planet rather than the barycenter, as a few are.
                Object(
                    id="naif-402",
                    name="Deimos",
                    object_type=ObjectType.moon,
                    parent_id="naif-499",
                ),
                Object(
                    id="naif-3",
                    name="Earth-Moon Barycenter",
                    object_type=ObjectType.barycenter,
                ),
                Object(
                    id="naif-399",
                    name="Earth",
                    object_type=ObjectType.planet,
                    parent_id="naif-3",
                ),
            ]
        )
        sess.commit()
        yield sess


@pytest.fixture
def events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "mars.json").write_text(
        json.dumps(
            {
                "probes": [
                    {
                        "probe_id": 1,
                        "name": "Both",
                        "events": [
                            {
                                "type": "orbit_insertion",
                                "date": "1976-06-19",
                                "target": {"naif": 499, "name": "Mars"},
                            },
                            {
                                "type": "flyby",
                                "date": "1977-02-18",
                                "target": {"naif": 401, "name": "Phobos"},
                            },
                        ],
                    },
                    {
                        "probe_id": 2,
                        "name": "Moon only",
                        "events": [
                            {
                                "type": "flyby",
                                "date": "1988-08-25",
                                "target": {"naif": 402, "name": "Deimos"},
                            }
                        ],
                    },
                    {
                        "probe_id": 3,
                        "name": "Libration",
                        "events": [
                            {
                                "type": "orbit_insertion",
                                "date": "2018-06-14",
                                "target": {"naif": 3, "name": "Earth-Moon L2"},
                            }
                        ],
                    },
                ]
            }
        )
    )
    monkeypatch.setattr(probe_targets, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(
        probe_targets,
        "load_registry",
        lambda: [
            {"probe_id": 1, "name": "Both"},
            {"probe_id": 2, "name": "Moon only"},
            {"probe_id": 3, "name": "Libration"},
        ],
    )


@pytest.fixture
def chunk() -> ChunkObjectData:
    out = ChunkObjectData()
    for object_id in (
        "naif-3",
        "naif-4",
        "naif-399",
        "naif-499",
        "naif-401",
        "naif-402",
    ):
        out.global_data[object_id] = {"id": object_id}
    return out


def test_system_lists_every_members_probes(
    session: Session, events: None, chunk: ChunkObjectData
) -> None:
    attach_system_probes(session, chunk, WikidataEntityCache())
    mars = chunk.global_data["naif-4"]
    assert mars["probe_count"] == 2
    # Latest arrival first, as the per-body lists are.
    assert [p["id"] for p in mars["probes"]] == ["probe-2", "probe-1"]


def test_row_names_the_bodies_it_reached(
    session: Session, events: None, chunk: ChunkObjectData
) -> None:
    attach_system_probes(session, chunk, WikidataEntityCache())
    both = chunk.global_data["naif-4"]["probes"][1]
    assert both["visits"] == [
        {
            "id": "naif-401",
            "name": "Phobos",
            "arrival": "1977-02-18",
            "end": "1977-02-18",
        },
        {
            "id": "naif-499",
            "name": "Mars",
            "arrival": "1976-06-19",
            "end": "1976-06-19",
        },
    ]
    # The kind of call is dropped: the bodies are what the row has room to say.
    assert "visit" not in both


def test_barycenter_keeps_the_probes_that_target_it(
    session: Session, events: None, chunk: ChunkObjectData
) -> None:
    """Earth-Moon L2 craft name NAIF 3, which is the system, not a body in it."""
    attach_system_probes(session, chunk, WikidataEntityCache())
    earth_moon = chunk.global_data["naif-3"]
    assert [p["id"] for p in earth_moon["probes"]] == ["probe-3"]
    assert earth_moon["probes"][0]["visits"][0]["id"] == "naif-3"


def test_a_system_nothing_reached_gets_no_list(
    session: Session, events: None, chunk: ChunkObjectData
) -> None:
    attach_system_probes(session, chunk, WikidataEntityCache())
    assert "probes" not in chunk.global_data["naif-499"]
