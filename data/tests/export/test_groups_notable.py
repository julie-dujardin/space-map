"""Tests for notable-member selection and shared bundle-entry building."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.constants.rings.catalog import RING_CATALOGS
from space_map_data.export import notable
from space_map_data.export.groups.categories import _probe_members
from space_map_data.export.objects.rings import ring_mass_block, ring_stats_block
from space_map_data.export.groups.registry import CLASS_SLUG_PREFIX
from space_map_data.export.groups.small_body import (
    NOTABLE_MEMBER_COUNT,
    _notable_members,
    build_small_body_group_stats,
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
    naif_id: int | None = None,
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
    sbdb_name: str | None = None,
    albedo: float | None = None,
    spec_b: str | None = None,
    spec_t: str | None = None,
) -> None:
    obj = Object(
        id=f"spkid-{spkid}",
        name=name or f"Body {spkid}",
        object_type=ObjectType.asteroid,
        wikidata_qid=qid,
        naif_id=naif_id,
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
            name=sbdb_name,
            diameter=diameter,
            H=h_mag,
            first_obs=first_obs,
            neo=neo,
            pha=pha,
            albedo=albedo,
            spec_B=spec_b,
            spec_T=spec_t,
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

    def test_carries_albedo_and_prefers_smass_spec(self, session: Session) -> None:
        _add_member(session, 7, albedo=0.09, spec_b="C", spec_t="G")
        (member,) = _notable_members(session, SBDB.class_ == OrbitClass.MBA)
        assert member.albedo == 0.09
        assert member.spec == "C"  # SMASS (spec_B) wins over Tholen (spec_T)

    def test_spec_falls_back_to_tholen(self, session: Session) -> None:
        _add_member(session, 8, spec_t="S")
        (member,) = _notable_members(session, SBDB.class_ == OrbitClass.MBA)
        assert member.spec == "S"

    def test_pole_from_orientation_for_pck_dwarf(self, session: Session) -> None:
        # A PCK dwarf in its orbit-class zone (Ceres in MBA) gets the same tilt
        # it has on the dwarf-planet page.
        _add_member(session, 2000001, naif_id=2000001)
        orientation = {2000001: {"pole_ra_0": 291.418, "pole_dec_0": 66.764}}
        (member,) = _notable_members(
            session, SBDB.class_ == OrbitClass.MBA, orientation=orientation
        )
        assert member.pole == {"ra": 291.418, "dec": 66.764}

    def test_no_pole_without_orientation(self, session: Session) -> None:
        _add_member(session, 2000001, naif_id=2000001)
        (member,) = _notable_members(session, SBDB.class_ == OrbitClass.MBA)
        assert member.pole is None

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


class TestRenderSize:
    """`render_size` render-radius priority (mirrors the position pipeline)."""

    def test_prefers_pck_triaxial_radii(self) -> None:
        pluto = {"a": 1188.3, "b": 1188.3, "c": 1188.3}
        triaxial, radius_km = notable.render_size(999, "Q339", {999: pluto}, None, None)
        assert triaxial == pluto
        assert radius_km is None

    def test_none_without_radii_or_wikidata(self) -> None:
        assert notable.render_size(None, None, {}, None, None) == (None, None)


class TestNamedCounts:
    """Named (IAU-named) member counts in build_small_body_group_stats."""

    def test_counts_named_asteroids_per_class(self, session: Session) -> None:
        _add_member(session, 1, cls=OrbitClass.MBA, sbdb_name="Ceres")
        _add_member(session, 2, cls=OrbitClass.MBA)  # designation-only
        _add_member(session, 3, cls=OrbitClass.TNO, sbdb_name="Eris")
        stats = build_small_body_group_stats(session)
        assert stats.named_counts == {
            f"{CLASS_SLUG_PREFIX}MBA": 1,
            f"{CLASS_SLUG_PREFIX}TNO": 1,
        }
        assert stats.member_counts[f"{CLASS_SLUG_PREFIX}MBA"] == 2

    def test_excludes_comets(self, session: Session) -> None:
        _add_member(
            session, 1, cls=OrbitClass.COM, prefix=CometPrefix.C, sbdb_name="Halley"
        )
        stats = build_small_body_group_stats(session)
        assert f"{CLASS_SLUG_PREFIX}COM" not in stats.named_counts


def _add_spacecraft(
    session: Session,
    object_id: str,
    *,
    orbital_source: OrbitalSource,
    name: str | None = None,
    qid: str | None = None,
    image: bool = False,
    sitelinks: int = 0,
) -> None:
    session.add(
        Object(
            id=object_id,
            name=name or object_id,
            object_type=ObjectType.spacecraft,
            wikidata_qid=qid,
            image_available=image,
            sitelinks_count=sitelinks,
            orbital_source=orbital_source,
        )
    )
    session.commit()


class TestProbeMembers:
    """``_probe_members``: spice-probe-only count + most-linked ordering."""

    def test_counts_and_ranks_probes_only(self, session: Session) -> None:
        sp = OrbitalSource.spice_probe
        _add_spacecraft(session, "probe-1", orbital_source=sp, sitelinks=50)
        _add_spacecraft(session, "probe-2", orbital_source=sp, image=True, sitelinks=5)
        _add_spacecraft(session, "probe-3", orbital_source=sp)
        # An Earth satellite — also spacecraft-typed, but not a probe.
        _add_spacecraft(
            session,
            "norad_satcat-25544",
            orbital_source=OrbitalSource.celestrak,
            sitelinks=999,
        )
        _add_member(session, 99)  # an asteroid — must be excluded too

        members, total = _probe_members(session, {}, {}, {})
        assert total == 3
        assert [m.object_id for m in members] == ["probe-2", "probe-1", "probe-3"]


class _StubEntityCache:
    """Minimal WikidataEntityCache stand-in: ``get_entity`` from a dict."""

    def __init__(
        self,
        labels_by_qid: dict[str, dict[str, str]],
        descriptions_by_qid: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self._labels = labels_by_qid
        self._descriptions = descriptions_by_qid or {}

    def get_entity(self, qid: str | None) -> dict | None:
        if qid is None or qid not in self._labels:
            return None
        return {
            "labels": self._labels[qid],
            "descriptions": self._descriptions.get(qid, {}),
        }

    # Group members (constellations) resolve their entity via get_referenced.
    get_referenced = get_entity


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

    def test_entries_include_albedo_and_spec(self, monkeypatch) -> None:
        monkeypatch.setattr(notable, "collect_object_images", lambda object_id: None)
        member = NotableObject(
            object_id="spkid-4",
            wikidata_qid=None,
            fallback_name="Vesta",
            diameter_km=525.4,
            first_obs=None,
            albedo=0.42,
            spec="V",
        )
        (entry,) = notable.notable_entries(
            [member],
            _StubEntityCache({}),  # type: ignore[arg-type]
        )
        assert entry["albedo"] == 0.42
        assert entry["spec"] == "V"

    def test_texture_flag_explicit_true_false(self, monkeypatch) -> None:
        # Explicit false (not omission) so the frontend can tell "no texture"
        # from a pre-flag bundle; omitted entirely when no set is supplied.
        monkeypatch.setattr(notable, "collect_object_images", lambda object_id: None)
        cache = _StubEntityCache({})
        members = [_obj("spkid-1", None, "Ceres"), _obj("spkid-2", None, "Pallas")]
        entries = notable.notable_entries(
            members,
            cache,  # type: ignore[arg-type]
            textured_ids={"spkid-1"},
        )
        assert entries[0]["texture"] is True
        assert entries[1]["texture"] is False
        entries = notable.notable_entries(members, cache)  # type: ignore[arg-type]
        assert "texture" not in entries[0]

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

    def test_group_member_routes_to_group_page(self, monkeypatch) -> None:
        # A constellation listed in its orbit zone resolves a group entry (no
        # object id), with a thumbnail from the group's images.
        monkeypatch.setattr(
            notable,
            "collect_group_images",
            lambda slug: (
                [{"file": "Starlink.jpg", "kind": "photo", "variants": {"s": "webp"}}]
                if slug == "const-starlink"
                else None
            ),
        )
        cache = _StubEntityCache({"Q1": {"en": "Starlink", "ru": "Старлинк"}})
        member = NotableObject(
            object_id="",
            wikidata_qid="Q1",
            fallback_name="STARLINK",
            diameter_km=None,
            first_obs=None,
            group_slug="const-starlink",
            sitelinks_count=42,
        )
        entries = notable.notable_entries([member], cache)  # type: ignore[arg-type]
        assert entries[0] == {
            "name": "Starlink",
            "group": "const-starlink",
            "thumbnail": {"file": "Starlink.jpg", "label": "s", "ext": "webp"},
        }
        # Localized overrides key by the group slug (frontend uses id ?? group).
        names = notable.notable_names(
            [member],
            entries,
            "ru",
            cache,  # type: ignore[arg-type]
        )
        assert names == {"const-starlink": "Старлинк"}

    def test_localized_descriptions_omit_members_without_one(self) -> None:
        cache = _StubEntityCache(
            {"Q1": {"en": "Ceres"}, "Q2": {"en": "Vesta"}, "Q3": {"en": "Pallas"}},
            {"Q1": {"en": "dwarf planet", "ru": "карликовая планета"}, "Q2": {}},
        )
        members = [
            _obj("spkid-1", "Q1", "1 Ceres"),
            _obj("spkid-2", "Q2", "4 Vesta"),
            _obj("spkid-3", None, "no qid"),
        ]
        descs = notable.notable_descriptions(members, "en", cache)  # type: ignore[arg-type]
        assert descs == {"spkid-1": "dwarf planet"}


class TestMemberPoleProvenance:
    """A member's tilt names its publisher when it isn't the PCK — the footer
    credits the IAU only for poles the IAU actually tabulated."""

    def test_pck_pole_carries_no_source(self, session: Session) -> None:
        _add_member(session, 2000001, naif_id=2000001)
        orientation = {
            2000001: {"pole_ra_0": 291.418, "pole_dec_0": 66.764, "source": "pck"}
        }
        (member,) = _notable_members(
            session, SBDB.class_ == OrbitClass.MBA, orientation=orientation
        )
        assert member.pole == {"ra": 291.418, "dec": 66.764}

    def test_lightcurve_pole_is_labelled(self, session: Session) -> None:
        _add_member(session, 2000021, naif_id=2000021)
        orientation = {
            2000021: {"pole_ra_0": 130.0, "pole_dec_0": -59.0, "source": "lightcurve"}
        }
        (member,) = _notable_members(
            session, SBDB.class_ == OrbitClass.MBA, orientation=orientation
        )
        assert member.pole == {"ra": 130.0, "dec": -59.0, "source": "lightcurve"}


class TestRingSystemMembers:
    """The Ring Systems page's members carry their rings' mass."""

    def test_ring_mass_rides_the_member_entry(self, monkeypatch) -> None:
        monkeypatch.setattr(notable, "collect_object_images", lambda object_id: None)
        member = NotableObject(
            object_id="naif-699",
            wikidata_qid=None,
            fallback_name="Saturn",
            diameter_km=None,
            first_obs=None,
            ring_mass={"low_kg": 1.54e19, "uncertainty_kg": 4.9e18},
        )
        (entry,) = notable.notable_entries(
            [member],
            _StubEntityCache({}),  # type: ignore[arg-type]
        )
        assert entry["ring_mass"] == {"low_kg": 1.54e19, "uncertainty_kg": 4.9e18}

    def test_a_body_without_one_omits_the_field(self, monkeypatch) -> None:
        """Neptune's rings have no published mass, and no empty block either."""
        monkeypatch.setattr(notable, "collect_object_images", lambda object_id: None)
        member = NotableObject(
            object_id="naif-899",
            wikidata_qid=None,
            fallback_name="Neptune",
            diameter_km=None,
            first_obs=None,
        )
        (entry,) = notable.notable_entries(
            [member],
            _StubEntityCache({}),  # type: ignore[arg-type]
        )
        assert "ring_mass" not in entry

    def test_the_collection_reads_the_same_figure_as_the_body(self) -> None:
        """One source for both: the chart on the collection page and the stat
        card on the body's own Rings tab cannot drift apart."""
        for body_id in RING_CATALOGS:
            stats = ring_stats_block(body_id) or {}
            assert ring_mass_block(body_id) == stats.get("mass")
