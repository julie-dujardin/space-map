"""Tests for notable-member selection and shared bundle-entry building."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from space_map_data.constants.atmosphere.facts import ATMOSPHERE_FACTS
from space_map_data.constants.atmosphere.structure import (
    ATMOSPHERE_STRUCTURE,
    CAPPED_ROLES,
)
from space_map_data.constants.activity.magnetism import MAGNETIC_FIELDS
from space_map_data.constants.activity.tidal import TIDAL_HEATING
from space_map_data.constants.activity.volcanism import GEOLOGIC_ACTIVITY
from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.rings.catalog import RING_CATALOGS, catalog_span_km
from space_map_data.export import notable
from space_map_data.export.groups.categories import (
    _atmosphere_stats,
    _magnetic_stats,
    _ocean_stats,
    _radiation_stats,
    _tidal_stats,
    _volcanism_stats,
    _probe_members,
    _ring_system_stats,
)
from space_map_data.constants.radiation.environments import RADIATION_ENVIRONMENTS
from space_map_data.export.objects.activity import collection_row
from space_map_data.export.objects.radiation import (
    Place,
    radiation_block,
)
from space_map_data.export.objects.radiation import (
    collection_row as radiation_collection_row,
)
from space_map_data.export.objects.atmosphere import atmosphere_block, pressure_block
from space_map_data.export.objects.interior import ocean_block
from space_map_data.export.objects.rings import (
    ring_mass_block,
    ring_sources_block,
    ring_stats_block,
)
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
        # A PCK dwarf (Ceres in MBA) gets the same tilt as on its dwarf-planet page.
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
        # Explicit false (not omission) distinguishes "no texture" from a
        # pre-flag bundle; omitted when no set is supplied.
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
        # A constellation resolves to a group entry (no object id), thumbnail
        # from the group's images.
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


class TestRingSystemStats:
    """The Ring Systems page's three stat cards."""

    def _member(self, object_id: str, name: str) -> NotableObject:
        return NotableObject(
            object_id=object_id,
            wikidata_qid=None,
            fallback_name=name,
            diameter_km=None,
            first_obs=None,
        )

    def test_counts_every_catalogue_row_not_just_the_rings(self) -> None:
        """The tiles count top-level rings; this card is what's inside them."""
        stats = _ring_system_stats([self._member("naif-699", "Saturn")])
        top_level = sum(
            1 for c in RING_CATALOGS.values() for f in c.features if not f.parent
        )
        every_row = sum(len(c.features) for c in RING_CATALOGS.values())
        assert stats.ring_feature_count == every_row
        assert every_row > top_level

    def test_widest_is_the_system_reaching_furthest(self) -> None:
        members = [self._member(body, body) for body in RING_CATALOGS]
        stats = _ring_system_stats(members)
        expected = max(
            RING_CATALOGS, key=lambda b: catalog_span_km(RING_CATALOGS[b]) or 0
        )
        assert stats.widest_rings is not None
        assert stats.widest_rings["primary_id"] == expected
        assert stats.widest_rings["span_km"] == catalog_span_km(RING_CATALOGS[expected])

    def test_widest_skips_a_system_with_no_member_to_link(self) -> None:
        """A body missing from the object table has no tile and no card link."""
        stats = _ring_system_stats([self._member("naif-799", "Uranus")])
        assert stats.widest_rings is not None
        assert stats.widest_rings["primary_id"] == "naif-799"

    def test_sources_cover_every_listed_system_once(self) -> None:
        """The page's credit line: every table it reads, each credited once."""
        members = [self._member(body, body) for body in RING_CATALOGS]
        stats = _ring_system_stats(members)
        assert stats.ring_sources is not None
        urls = [source["url"] for source in stats.ring_sources]
        assert len(urls) == len(set(urls))
        assert set(urls) == {
            source.url for c in RING_CATALOGS.values() for source in c.sources
        }

    def test_sources_skip_a_system_with_no_member(self) -> None:
        """A body with no tile contributes no citation either."""
        stats = _ring_system_stats([self._member("naif-699", "Saturn")])
        assert stats.ring_sources == ring_sources_block("naif-699")

    def test_discovery_year_is_the_earliest_system(self) -> None:
        stats = _ring_system_stats([self._member("naif-699", "Saturn")])
        assert stats.discovery_year == min(
            c.discovery_year
            for c in RING_CATALOGS.values()
            if c.discovery_year is not None
        )


class TestOceanBlock:
    """The row the Oceans collection chart ranks a body by."""

    def test_only_water_oceans_qualify(self) -> None:
        """`sea` is its own role: Titan's are liquid methane, not water — mixing
        them into the water total would be a category error, not a rounding one."""
        with_ocean = {body for body in INTERIOR_FACTS if ocean_block(body)}
        sea_only = {
            body
            for body, facts in INTERIOR_FACTS.items()
            if any(layer.role == "sea" for layer in facts.layers)
            and not any(layer.role == "ocean" for layer in facts.layers)
        }
        assert with_ocean
        assert not (with_ocean & sea_only)

    def test_volume_reproduces_earths_published_figure(self) -> None:
        """Charette & Smith 2010's 1.33238e9 km³ — source of Earth's layer radii —
        comes back out to within 0.4%, not tighter since radii round to 0.1 km."""
        block = ocean_block("naif-399")
        assert block is not None
        assert block["volume_km3"] == pytest.approx(1.33238e9, rel=4e-3)
        assert block["subsurface"] is False

    def test_a_shell_is_floored_by_the_layer_under_it(self) -> None:
        """Europa's ocean carries no `base_radius_km`, so its floor is the top
        of the mantle — 74.1 km down, not the whole radius."""
        block = ocean_block("naif-502")
        assert block is not None
        assert block["thickness_km"] == pytest.approx(74.1, abs=0.1)
        assert block["subsurface"] is True

    def test_no_block_for_a_body_with_no_ocean(self) -> None:
        assert ocean_block("naif-599") is None
        assert ocean_block("spkid-99999999") is None


class TestStructureActivityStats:
    """Stat cards on the two property pages."""

    def _member(self, object_id: str, name: str, **extra) -> NotableObject:
        return NotableObject(
            object_id=object_id,
            wikidata_qid=None,
            fallback_name=name,
            diameter_km=None,
            first_obs=None,
            **extra,
        )

    def test_ocean_total_is_every_listed_ocean(self) -> None:
        blocks = {
            body: block
            for body in INTERIOR_FACTS
            if (block := ocean_block(body)) is not None
        }
        members = [
            self._member(body, body, ocean=block) for body, block in blocks.items()
        ]
        stats = _ocean_stats(members)
        assert stats.ocean_volume_km3 == pytest.approx(
            sum(block["volume_km3"] for block in blocks.values())
        )
        # They add up to tens of Earth's own, and Earth's isn't even the largest.
        earth = ocean_block("naif-399")
        assert earth is not None
        assert stats.ocean_volume_km3 > 10 * earth["volume_km3"]

    def test_deepest_is_thickness_not_volume(self) -> None:
        """The chart already plots volume, so the card ranks on something else."""
        thick = self._member(
            "naif-1", "Thick", ocean={"volume_km3": 1.0, "thickness_km": 500.0}
        )
        big = self._member(
            "naif-2", "Big", ocean={"volume_km3": 1e12, "thickness_km": 10.0}
        )
        stats = _ocean_stats([big, thick])
        assert stats.deepest_ocean is not None
        assert stats.deepest_ocean["primary_id"] == "naif-1"

    def test_tallest_atmosphere_ignores_the_capped_layers(self) -> None:
        """Ranking on exosphere tops makes Earth the tallest atmosphere in the
        solar system, at a density the cross-section refuses to draw."""
        members = [self._member(body, body) for body in ATMOSPHERE_FACTS]
        stats = _atmosphere_stats(members)
        assert stats.tallest_atmosphere is not None
        assert stats.tallest_atmosphere["primary_id"] != "naif-399"
        winner = stats.tallest_atmosphere["primary_id"]
        assert stats.tallest_atmosphere["km"] == max(
            layer.top_km
            for layer in ATMOSPHERE_STRUCTURE[winner].layers
            if layer.top_km is not None and layer.role not in CAPPED_ROLES
        )

    def test_tallest_atmosphere_needs_a_member_to_link(self) -> None:
        """A body with no tile on the page can't take the card."""
        stats = _atmosphere_stats([self._member("naif-799", "Uranus")])
        assert stats.tallest_atmosphere is not None
        assert stats.tallest_atmosphere["primary_id"] == "naif-799"

    def test_type_count_is_the_vocabulary_in_use(self) -> None:
        members = [self._member(body, body) for body in ATMOSPHERE_FACTS]
        stats = _atmosphere_stats(members)
        assert stats.atmosphere_type_count == len(
            {facts.atmosphere_type for facts in ATMOSPHERE_FACTS.values()}
        )


class TestPressureBlockSharing:
    """The collection chart and the body's own panel read one formatting."""

    def test_body_panel_and_collection_row_agree(self) -> None:
        for body, facts in ATMOSPHERE_FACTS.items():
            block = atmosphere_block(body)
            assert block is not None
            if facts.pressure is None:
                assert "pressure" not in block
            else:
                assert block["pressure"] == pressure_block(facts.pressure)


class TestActivityCollectionRow:
    """The trimmed row the three heat pages share."""

    def test_covers_every_body_any_activity_table_holds(self) -> None:
        bodies = set(GEOLOGIC_ACTIVITY) | set(MAGNETIC_FIELDS) | set(TIDAL_HEATING)
        assert bodies
        assert all(collection_row(body) is not None for body in bodies)
        assert collection_row("spkid-99999999") is None

    def test_carries_headline_values_not_measurements(self) -> None:
        """A collection row has no room for a published width — the body's own
        panel already has that."""
        row = collection_row("naif-501")
        assert row is not None
        assert row["volcanism"]["endogenic_power_w"] == pytest.approx(1.05e14)
        assert row["tidal"]["power_w"] == pytest.approx(1.05e14)

    def test_a_bound_is_flagged_rather_than_dropped(self) -> None:
        """Titan's field is how tightly nobody found one. The value ships so the
        row can print "< 0.78 nT"; the flag stops the chart plotting it."""
        row = collection_row("naif-606")
        assert row is not None
        assert row["magnetism"]["surface_field_t"] == pytest.approx(7.8e-10)


class TestMagneticMembership:
    """Which bodies the Magnetic Fields page lists at all."""

    def test_only_bodies_with_a_surface_field(self) -> None:
        """A member with no figure printed the kind of field instead, so the
        page led with "None detected" on a page about fields."""
        measured = {b for b, f in MAGNETIC_FIELDS.items() if f.surface_field_t}
        dropped = set(MAGNETIC_FIELDS) - measured
        # Venus's only figure is an upper bound on its dipole; the three Jovian
        # moons carry a field induced in them, of no published strength.
        assert dropped == {"naif-299", "naif-501", "naif-502", "naif-504"}

    def test_a_published_bound_still_counts(self) -> None:
        """Titan's 0.78 nT is a real result — the row prints "< 0.78 nT"."""
        field = MAGNETIC_FIELDS["naif-606"].surface_field_t
        assert field is not None and field.upper_limit


class TestHeatPageStats:
    """Stat cards on volcanism, magnetic fields and tidal heating."""

    def _members(self, table, builder) -> list[NotableObject]:
        return [
            NotableObject(
                object_id=body,
                wikidata_qid=None,
                fallback_name=body,
                diameter_km=None,
                first_obs=None,
                activity=collection_row(body),
            )
            for body in table
        ]

    def test_erupting_now_names_them(self) -> None:
        """The card's tooltip is the list — four is few enough to invite the
        question."""
        stats = _volcanism_stats(self._members(GEOLOGIC_ACTIVITY, None))
        active = {
            body
            for body, activity in GEOLOGIC_ACTIVITY.items()
            if activity.volcanism.status == "active"
        }
        assert stats.erupting_now is not None
        assert set(stats.erupting_now) == active
        assert stats.erupting_now == sorted(stats.erupting_now)

    def test_vents_sum_every_survey(self) -> None:
        stats = _volcanism_stats(self._members(GEOLOGIC_ACTIVITY, None))
        assert stats.known_centres == sum(
            int(a.volcanism.known_centres.value)
            for a in GEOLOGIC_ACTIVITY.values()
            if a.volcanism.known_centres is not None
        )

    def test_strongest_field_ignores_a_non_detection(self) -> None:
        """A bound isn't a measurement — the one card where that distinction
        would vanish."""
        titan = NotableObject(
            object_id="naif-606",
            wikidata_qid=None,
            fallback_name="Titan",
            diameter_km=None,
            first_obs=None,
            activity={
                "magnetism": {
                    "kind": "none",
                    "surface_field_t": 1.0,
                    "surface_field_t_upper_limit": True,
                }
            },
        )
        assert _magnetic_stats([titan]).strongest_field is None

    def test_strongest_and_most_tilted_are_different_bodies(self) -> None:
        stats = _magnetic_stats(self._members(MAGNETIC_FIELDS, None))
        assert stats.strongest_field is not None
        assert stats.most_tilted_field is not None
        assert stats.dynamo_count == sum(
            1 for f in MAGNETIC_FIELDS.values() if f.kind == "dynamo"
        )
        # Jupiter's field is strongest, Uranus's the most askew — a bug reading
        # one for both would collapse them onto one body.
        assert (
            stats.strongest_field["primary_id"] != stats.most_tilted_field["primary_id"]
        )

    def test_tidal_hottest_is_the_published_wattage(self) -> None:
        stats = _tidal_stats(self._members(TIDAL_HEATING, None))
        assert stats.hottest_body is not None
        assert stats.hottest_body["watts"] == max(
            t.power_w.value for t in TIDAL_HEATING.values() if t.power_w is not None
        )


class TestRadiationCollection:
    """The Radiation page: its rows, its cards, and the note vocabulary the
    frontend has to keep up with."""

    PLACES = {
        body: Place(parent_id=f"naif-{body.removeprefix('naif-')[0]}", distance_au=au)
        for body, au in {
            "naif-199": 0.387,
            "naif-299": 0.723,
            "naif-301": 1.0,
            "naif-399": 1.0,
            "naif-499": 1.524,
            "naif-501": 5.203,
            "naif-502": 5.203,
            "naif-503": 5.203,
            "naif-504": 5.203,
            "naif-599": 5.203,
            "naif-606": 9.537,
            "naif-699": 9.537,
            "naif-799": 19.191,
            "naif-899": 30.069,
        }.items()
    }

    def _rows(self) -> dict[str, dict]:
        """The members: the places carrying a figure, which is seven of the
        fourteen environments on record."""
        rows = {
            body: radiation_collection_row(body, place)
            for body, place in self.PLACES.items()
        }
        return {body: row for body, row in rows.items() if row is not None}

    def _members(self) -> list[NotableObject]:
        return [
            NotableObject(
                object_id=body,
                wikidata_qid=None,
                fallback_name=body,
                diameter_km=None,
                first_obs=None,
                radiation=row,
            )
            for body, row in self._rows().items()
        ]

    def test_the_places_are_every_environment_on_record(self) -> None:
        assert set(self.PLACES) == set(RADIATION_ENVIRONMENTS)

    def test_a_figure_is_what_makes_a_body_a_member(self) -> None:
        """A row reading only "worst in the solar system" beside six numbers is
        a caption, not a member — the rule the pressure and field pages follow.
        The seven dropped are classified but unquoted."""
        assert set(self.PLACES) - set(self._rows()) == {
            "naif-503",
            "naif-504",
            "naif-599",
            "naif-606",
            "naif-699",
            "naif-799",
            "naif-899",
        }

    def test_a_row_is_the_body_panel_minus_what_a_row_cannot_draw(self) -> None:
        place = self.PLACES["naif-399"]
        row = radiation_collection_row("naif-399", place)
        block = radiation_block(
            "naif-399", parent_id=place.parent_id, distance_au=place.distance_au
        )
        assert row is not None and block is not None
        assert row["surface_dose"] == block["surface_dose"]
        # A row is a figure and which chart it draws on. Everything else the
        # block carries is prose or geometry, one click away on the body itself.
        assert set(row) == {"kind", "surface_dose"}

    def test_the_two_charts_split_on_kind_and_both_have_members(self) -> None:
        """Trapped electrons and cosmic rays are not one quantity, and sharing
        an axis would draw every cosmic ray surface as nothing."""
        plotted = [
            row
            for row in self._rows().values()
            if row.get("surface_dose") or row.get("modelled_surface_dose")
        ]
        assert plotted == list(self._rows().values())
        trapped = [row for row in plotted if row["kind"] == "trapped"]
        assert len(trapped) == 2
        assert len(plotted) - len(trapped) == 5

    def test_the_measured_card_counts_instruments_not_models(self) -> None:
        """Three of seven, which is the page's first fact. Venus, Io and Europa
        carry published figures that are somebody's transport code."""
        stats = _radiation_stats(self._members(), self.PLACES)
        assert stats.radiation_measured == ["naif-301", "naif-399", "naif-499"]

    def test_the_quietest_card_carries_what_the_chart_cannot(self) -> None:
        """Venus's bar is zero pixels wide against the Moon's."""
        stats = _radiation_stats(self._members(), self.PLACES)
        assert stats.quietest_surface is not None
        assert stats.quietest_surface["primary_id"] == "naif-299"

    def test_the_page_cites_every_work_behind_it(self) -> None:
        """Scoped to the members: the seven places that lost their row took
        their citations with them."""
        stats = _radiation_stats(self._members(), self.PLACES)
        assert stats.radiation_sources
        titles = " ".join(row["title"] for row in stats.radiation_sources)
        assert "Neptune Radiation Model" not in titles
        assert all(row["title"] and row["url"] for row in stats.radiation_sources)
        urls = [row["url"] for row in stats.radiation_sources]
        assert len(urls) == len(set(urls))
