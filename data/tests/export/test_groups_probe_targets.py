"""Tests for the probes read as groups: the Probes category page's
per-target bar chart, and each small-body collection's probe list."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.export.groups.probe_targets import (
    build_group_probes,
    build_probe_target_chart,
)
from space_map_data.export.objects import probe_targets
from space_map_data.models.object import Object, ObjectType
from space_map_data.models.object.base import Base
from space_map_data.models.object.sbdb import SBDB, OrbitClass


@pytest.fixture
def session() -> Iterator[Session]:
    """Fresh in-memory SQLite with the full schema, scoped to one test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        sess.add_all(
            [
                Object(
                    id="naif-499",
                    name="Mars",
                    object_type=ObjectType.planet,
                    wikidata_qid="Q111",
                    sitelinks_count=200,
                ),
                Object(
                    id="naif-301",
                    name="Moon",
                    object_type=ObjectType.moon,
                    sitelinks_count=300,
                ),
                Object(
                    id="spkid-120065803",
                    name="Dimorphos",
                    object_type=ObjectType.moon,
                ),
                Object(
                    id="naif-3",
                    name="Earth-Moon Barycenter",
                    object_type=ObjectType.barycenter,
                ),
            ]
        )
        sess.commit()
        yield sess


@pytest.fixture
def events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def probe(probe_id: int, *targets: dict) -> dict:
        # Undated events are skipped by the index, so each flyby gets a day.
        return {
            "probe_id": probe_id,
            "name": f"Probe {probe_id}",
            "events": [
                {"type": "flyby", "date": f"2000-01-{i + 1:02d}", "target": t}
                for i, t in enumerate(targets)
            ],
        }

    (tmp_path / "events.json").write_text(
        json.dumps(
            {
                "probes": [
                    probe(
                        1,
                        {"naif": 499, "name": "Mars"},
                        {"naif": 301, "name": "Moon"},
                        {"naif": 3, "name": "Earth-Moon L2"},
                        {"naif": 399, "name": "Earth"},
                    ),
                    probe(
                        2,
                        {"naif": 499, "name": "Mars"},
                        {"naif": 499, "name": "Mars"},
                        {"naif": 392, "name": "Sun-Earth L2"},
                        {"naif": 120065803, "name": "Dimorphos"},
                    ),
                    probe(3, {"naif": 301, "name": "Moon"}),
                ]
            }
        )
    )
    monkeypatch.setattr(probe_targets, "EVENTS_DIR", tmp_path)


def test_rows_rank_by_probes_then_sitelinks(session: Session, events: None) -> None:
    rows = build_probe_target_chart(session).rows
    # Moon and Mars tie at two probes; the Moon's sitelinks break it. The
    # single-visit tail has none, so it falls back to the name.
    assert [(r["name"], r["n"]) for r in rows] == [
        ("Moon", 2),
        ("Mars", 2),
        ("Dimorphos", 1),
        ("Earth-Moon L2", 1),
        ("Sun-Earth L2", 1),
    ]
    assert rows[1]["primary_id"] == "naif-499"


def test_libration_points_link_to_their_collection(
    session: Session, events: None
) -> None:
    rows = {r["name"]: r for r in build_probe_target_chart(session).rows}
    assert rows["Sun-Earth L2"]["primary_type"] == "group"
    assert rows["Sun-Earth L2"]["primary_id"] == "class-EL2"
    # NAIF 3 resolves to the Earth-Moon barycenter, which is not where the
    # probe went, and that pair's L2 has no collection of its own.
    assert "primary_id" not in rows["Earth-Moon L2"]


def test_qids_cover_the_linked_rows(session: Session, events: None) -> None:
    assert build_probe_target_chart(session).qids == {"naif-499": "Q111"}


@pytest.fixture
def small_bodies(session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """Two visited asteroids and a comet, with the registry the probe rows
    denormalize their names from."""
    session.add_all(
        [
            Object(
                id="spkid-20000004",
                name="4 Vesta",
                object_type=ObjectType.asteroid_main_belt,
                wikidata_qid="Q3030",
            ),
            Object(
                id="spkid-20000001",
                name="1 Ceres",
                object_type=ObjectType.dwarf_planet,
            ),
            Object(
                id="spkid-1000093",
                name="9P/Tempel 1",
                object_type=ObjectType.comet,
            ),
            SBDB(
                spkid="20000004",
                object_id="spkid-20000004",
                class_=OrbitClass.MBA,
            ),
            SBDB(
                spkid="20000001",
                object_id="spkid-20000001",
                class_=OrbitClass.MBA,
                neo=True,
                pha=True,
            ),
            SBDB(
                spkid="1000093",
                object_id="spkid-1000093",
                class_=OrbitClass.JFc,
            ),
        ]
    )
    session.commit()
    monkeypatch.setattr(
        probe_targets,
        "load_registry",
        lambda: [
            {"probe_id": 1, "name": "Probe 1", "wikidata_qid": "Q1"},
            {"probe_id": 2, "name": "Probe 2"},
        ],
    )
    return session


@pytest.fixture
def small_body_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Probe 1 orbits both main-belt bodies in turn; probe 2 flies past the
    comet."""
    (tmp_path / "events.json").write_text(
        json.dumps(
            {
                "probes": [
                    {
                        "probe_id": 1,
                        "name": "Probe 1",
                        "status": {"alive": False},
                        "events": [
                            {
                                "type": "orbit_insertion",
                                "date": "2011-07-16",
                                "target": {"naif": 2000004, "name": "Vesta"},
                            },
                            {
                                "type": "orbit_departure",
                                "date": "2012-09-05",
                                "target": {"naif": 2000004, "name": "Vesta"},
                            },
                            {
                                "type": "orbit_insertion",
                                "date": "2015-03-06",
                                "target": {"naif": 2000001, "name": "Ceres"},
                            },
                        ],
                    },
                    {
                        "probe_id": 2,
                        "name": "Probe 2",
                        "events": [
                            {
                                "type": "flyby",
                                "date": "2005-07-04",
                                "target": {"naif": 1000093, "name": "Tempel 1"},
                            }
                        ],
                    },
                ]
            }
        )
    )
    monkeypatch.setattr(probe_targets, "EVENTS_DIR", tmp_path)


def test_collections_list_the_probes_sent_to_their_members(
    small_bodies: Session, small_body_events: None
) -> None:
    probes = build_group_probes(small_bodies).probes
    assert {slug: [p.fallback_name for p in rows] for slug, rows in probes.items()} == {
        "class-MBA": ["Probe 1"],
        "class-JFc": ["Probe 2"],
        "cat-asteroids": ["Probe 1"],
        "cat-comets": ["Probe 2"],
        "flag-neo": ["Probe 1"],
        "flag-pha": ["Probe 1"],
    }


def test_a_probe_carries_every_member_it_reached_latest_first(
    small_bodies: Session, small_body_events: None
) -> None:
    (dawn,) = build_group_probes(small_bodies).probes["class-MBA"]
    assert dawn.visits == [
        # The probe is not alive, so its last event at Ceres closes the visit.
        {
            "id": "spkid-20000001",
            "name": "1 Ceres",
            "arrival": "2015-03-06",
            "end": "2015-03-06",
        },
        {
            "id": "spkid-20000004",
            "name": "4 Vesta",
            "arrival": "2011-07-16",
            "end": "2012-09-05",
        },
    ]
    # The per-body `visit` says what the probe did there; over a collection the
    # bodies replace it.
    assert dawn.visit is None


def test_a_split_comet_family_lists_its_fragments_probes(
    small_bodies: Session, small_body_events: None
) -> None:
    probes = build_group_probes(
        small_bodies, {"spkid-1000093": "comet-family-1993-f2"}
    ).probes
    assert [p.fallback_name for p in probes["comet-family-1993-f2"]] == ["Probe 2"]


def test_target_qids_localize_the_bodies_a_row_names(
    small_bodies: Session, small_body_events: None
) -> None:
    # Only Vesta has a Wikidata entity to localize from.
    assert build_group_probes(small_bodies).qids["class-MBA"] == {
        "spkid-20000004": "Q3030"
    }
