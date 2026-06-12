"""Tests for notable-member selection and shared bundle-entry building."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.export import notable
from space_map_data.export.groups.small_body import (
    NOTABLE_MEMBER_COUNT,
    _notable_members,
)
from space_map_data.export.notable import NotableObject
from space_map_data.models.object import Object, ObjectType, OrbitalSource
from space_map_data.models.object.base import Base
from space_map_data.models.object.sbdb import SBDB, CometPrefix, OrbitClass


@pytest.fixture
def session() -> Iterator[Session]:
    """Fresh in-memory SQLite with the full schema, scoped to one test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess


def _add_member(
    session: Session,
    spkid: int,
    *,
    name: str | None = None,
    qid: str | None = None,
    image: bool = False,
    sitelinks: int = 0,
    diameter: float | None = None,
    h_mag: float | None = None,
    first_obs: str | None = None,
    cls: OrbitClass = OrbitClass.MBA,
    prefix: CometPrefix | None = None,
    neo: bool = False,
    pha: bool = False,
    orbital_source: OrbitalSource | None = OrbitalSource.sbdb,
) -> None:
    obj = Object(
        id=f"spkid-{spkid}",
        name=name or f"Body {spkid}",
        object_type=ObjectType.asteroid,
        wikidata_qid=qid,
        image_available=image,
        sitelinks_count=sitelinks,
        orbital_source=orbital_source,
    )
    session.add(obj)
    session.add(
        SBDB(
            spkid=str(spkid),
            object_id=obj.id,
            class_=cls,
            prefix=prefix,
            diameter=diameter,
            H=h_mag,
            first_obs=first_obs,
            neo=neo,
            pha=pha,
        )
    )
    session.commit()


class TestNotableMembers:
    """Selection ordering and filters of ``_notable_members``."""

    def test_ranking_order(self, session: Session) -> None:
        # Deliberately inserted out of expected order.
        _add_member(session, 1, sitelinks=50)  # high sitelinks, no image
        _add_member(session, 2, image=True, sitelinks=5)  # image wins outright
        _add_member(session, 3, diameter=400.0)  # no wikidata: diameter tier
        _add_member(session, 4, h_mag=8.0)  # no diameter: H tier
        _add_member(session, 5, h_mag=10.0)  # dimmer than 4

        members = _notable_members(session, SBDB.class_ == OrbitClass.MBA)
        assert [m.object_id for m in members] == [
            "spkid-2",
            "spkid-1",
            "spkid-3",
            "spkid-4",
            "spkid-5",
        ]

    def test_spkid_tiebreak_is_deterministic(self, session: Session) -> None:
        for spkid in (12, 10, 11):
            _add_member(session, spkid)
        members = _notable_members(session, SBDB.class_ == OrbitClass.MBA)
        assert [m.object_id for m in members] == ["spkid-10", "spkid-11", "spkid-12"]

    def test_includes_spice_routed_dwarf_planets(self, session: Session) -> None:
        _add_member(session, 2000001, sitelinks=200, orbital_source=OrbitalSource.spice)
        members = _notable_members(session, SBDB.class_ == OrbitClass.MBA)
        assert [m.object_id for m in members] == ["spkid-2000001"]

    def test_excludes_defunct_comets(self, session: Session) -> None:
        _add_member(session, 1, sitelinks=100, prefix=CometPrefix.D)
        _add_member(session, 2)
        members = _notable_members(session, SBDB.class_ == OrbitClass.MBA)
        assert [m.object_id for m in members] == ["spkid-2"]

    def test_limits_to_notable_member_count(self, session: Session) -> None:
        for spkid in range(100, 100 + NOTABLE_MEMBER_COUNT + 5):
            _add_member(session, spkid)
        members = _notable_members(session, SBDB.class_ == OrbitClass.MBA)
        assert len(members) == NOTABLE_MEMBER_COUNT

    def test_flag_filter(self, session: Session) -> None:
        _add_member(session, 1, neo=True)
        _add_member(session, 2)
        members = _notable_members(session, SBDB.neo.is_(True))
        assert [m.object_id for m in members] == ["spkid-1"]

    def test_carries_display_fields(self, session: Session) -> None:
        _add_member(
            session,
            7,
            name="Iris",
            qid="Q149012",
            diameter=199.8,
            first_obs="1847-08-13",
        )
        (member,) = _notable_members(session, SBDB.class_ == OrbitClass.MBA)
        assert member == NotableObject(
            object_id="spkid-7",
            wikidata_qid="Q149012",
            fallback_name="Iris",
            diameter_km=199.8,
            first_obs="1847-08-13",
        )


class _StubEntityCache:
    """Minimal WikidataEntityCache stand-in: ``get_entity`` from a dict."""

    def __init__(self, labels_by_qid: dict[str, dict[str, str]]) -> None:
        self._labels = labels_by_qid

    def get_entity(self, qid: str | None) -> dict | None:
        if qid is None or qid not in self._labels:
            return None
        return {"labels": self._labels[qid]}


def _obj(object_id: str, qid: str | None, fallback: str) -> NotableObject:
    return NotableObject(
        object_id=object_id,
        wikidata_qid=qid,
        fallback_name=fallback,
        diameter_km=None,
        first_obs=None,
    )


class TestNotableEntries:
    """Shared bundle-entry shape and localized name overrides."""

    def test_entries_resolve_en_label_and_thumbnail(self, monkeypatch) -> None:
        cache = _StubEntityCache({"Q1": {"en": "Ceres", "ru": "Церера"}})
        monkeypatch.setattr(
            notable,
            "collect_object_images",
            lambda object_id: (
                [{"file": "Ceres.jpg", "kind": "photo", "variants": {"s": "webp"}}]
                if object_id == "spkid-1"
                else None
            ),
        )
        entries = notable.notable_entries(
            [_obj("spkid-1", "Q1", "1 Ceres"), _obj("spkid-2", None, "Vesta fallback")],
            cache,  # type: ignore[arg-type]
        )
        assert entries[0] == {
            "name": "Ceres",
            "id": "spkid-1",
            "thumbnail": {"file": "Ceres.jpg", "label": "s", "ext": "webp"},
        }
        assert entries[1] == {"name": "Vesta fallback", "id": "spkid-2"}

    def test_entries_include_optional_stats(self, monkeypatch) -> None:
        monkeypatch.setattr(notable, "collect_object_images", lambda object_id: None)
        member = NotableObject(
            object_id="spkid-3",
            wikidata_qid=None,
            fallback_name="Juno",
            diameter_km=246.6,
            first_obs="1804-09-01",
        )
        (entry,) = notable.notable_entries(
            [member],
            _StubEntityCache({}),  # type: ignore[arg-type]
        )
        assert entry["diameter_km"] == 246.6
        assert entry["first_obs"] == "1804-09-01"

    def test_localized_names_only_when_differing(self, monkeypatch) -> None:
        monkeypatch.setattr(notable, "collect_object_images", lambda object_id: None)
        cache = _StubEntityCache(
            {
                "Q1": {"en": "Ceres", "ru": "Церера"},
                "Q2": {"en": "Vesta", "ru": "Vesta"},
            }
        )
        members = [_obj("spkid-1", "Q1", "1 Ceres"), _obj("spkid-2", "Q2", "4 Vesta")]
        entries = notable.notable_entries(members, cache)  # type: ignore[arg-type]
        names = notable.notable_names(members, entries, "ru", cache)  # type: ignore[arg-type]
        assert names == {"spkid-1": "Церера"}
