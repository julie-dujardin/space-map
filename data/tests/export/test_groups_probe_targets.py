"""Tests for the probes-per-target bar chart on the Probes category page."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.export.groups.probe_targets import build_probe_target_chart
from space_map_data.export.objects import probe_targets
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
