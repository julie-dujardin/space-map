"""Tests for sitemap URL construction.

A path here must byte-match the canonical link its page states, built by
``frontend/src/lib/state/page-href.ts`` from the name of ``page-name.ts`` — a
mismatch makes the indexed URL point at another one.
"""

import gzip
from pathlib import Path
from unittest.mock import MagicMock

import orjson
import pytest
from sqlalchemy.orm import Session

from space_map_data.constants.providers import BASE_LOCALE
from space_map_data.export import sitemap
from space_map_data.export.groups.registry import GROUPS, GroupType
from space_map_data.export.localization import MESSAGES_DIR
from space_map_data.export.objects.writer import hash_bucket
from space_map_data.export.sitemap import (
    SITELINKS_THRESHOLD,
    _bundle_names,
    _feature_paths,
    _group_name,
    _group_paths,
    _named,
    _notable_paths,
    _object_names,
    _object_path,
)
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object, ObjectType, OrbitalSource
from tests.conftest import make_object


def _entities(sitelinks: dict[str, int]) -> MagicMock:
    """Cache stub returning a sitelink count per feature QID."""

    def get_feature_entity(qid: str | None):
        if qid is None or qid not in sitelinks:
            return None
        return {"sitelinks": {f"w{i}": "" for i in range(sitelinks[qid])}}

    cache = MagicMock()
    cache.get_feature_entity.side_effect = get_feature_entity
    return cache


def _feature(session: Session, feature_id: int, **kwargs) -> None:
    defaults = {
        "feature_id": feature_id,
        "object_id": "naif-301",
        "name": f"Feature {feature_id}",
        "target": "moon",
        "wikidata_qid": f"Q{feature_id}",
        "center_lat": 0.0,
        "center_lon": 0.0,
        "feature_type_code": "AA",
    }
    defaults.update(kwargs)
    session.add(Feature(**defaults))


def _asteroid(obj_id: str, **kwargs) -> Object:
    return make_object(
        id=obj_id,
        object_type=ObjectType.asteroid,
        orbital_source=OrbitalSource.sbdb,
        **kwargs,
    )


def _write_bundles(bundle_dir: Path, n_buckets: int, entries: dict[str, dict]) -> None:
    """Write *entries* as the export does: one file per bucket that has one."""
    buckets: dict[int, dict[str, dict]] = {}
    for key, entry in entries.items():
        buckets.setdefault(hash_bucket(key, n_buckets), {})[key] = entry
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for bucket, bucket_entries in buckets.items():
        (bundle_dir / f"{bucket}.json.gz").write_bytes(
            gzip.compress(orjson.dumps(bucket_entries))
        )


class TestObjectPath:
    """Id scheme → URL type segment."""

    def test_maps_each_known_prefix(self):
        assert _object_path("naif-499") == "/b/499"
        assert _object_path("spkid-2000001") == "/s/2000001"
        assert _object_path("norad_satcat-25544") == "/e/25544"

    def test_rejects_an_unknown_scheme(self):
        assert _object_path("bogus-1") is None
        assert _object_path("naif-") is None


class TestNamed:
    """The name segment of a path."""

    def test_encodes_the_name_as_encode_uri_component_does(self):
        assert _named("/b/599", "Jupiter I") == "/b/599/Jupiter%20I"
        assert _named("/s/1", "(1) Ceres / A&B") == "/s/1/(1)%20Ceres%20%2F%20A%26B"

    def test_leaves_a_nameless_page_without_the_segment(self):
        assert _named("/b/599", None) == "/b/599"
        assert _named("/b/599", "") == "/b/599"


class TestBundleNames:
    """Names read back from hash-bucketed bundles."""

    def test_reads_the_name_of_each_key(self, tmp_path: Path):
        _write_bundles(tmp_path, 3, {f"naif-{i}": {"name": f"N{i}"} for i in range(9)})

        names = _bundle_names(tmp_path, 3, ["naif-2", "naif-7"])
        assert names == {"naif-2": "N2", "naif-7": "N7"}

    def test_tells_an_entry_with_no_name_from_no_entry(self, tmp_path: Path):
        _write_bundles(tmp_path, 1, {"a": {"description": "x"}, "b": {"name": ""}})

        names = _bundle_names(tmp_path, 1, ["a", "b", "absent"])
        assert names == {"a": None, "b": None}

    def test_ignores_a_bucket_file_of_an_earlier_layout(self, tmp_path: Path):
        """A run with fewer buckets leaves the high-numbered files in place."""
        _write_bundles(tmp_path, 1, {"naif-399": {"name": "Earth"}})
        (tmp_path / "7.json.gz").write_bytes(
            gzip.compress(orjson.dumps({"naif-399": {"name": "Stale"}}))
        )

        assert _bundle_names(tmp_path, 1, ["naif-399"]) == {"naif-399": "Earth"}

    def test_reads_nothing_from_a_tier_with_no_bucket(self, tmp_path: Path):
        assert _bundle_names(tmp_path / "absent", 0, ["naif-399"]) == {}

    def test_skips_a_bucket_that_has_no_file(self, tmp_path: Path):
        assert _bundle_names(tmp_path, 4, ["naif-399"]) == {}


class TestObjectNames:
    """The page name of an object, as ``objectPageName`` gives it."""

    BUCKETS = {BASE_LOCALE: 1, "global": 2}

    def _export(self, out_dir: Path) -> None:
        objects = out_dir / "objects"
        _write_bundles(
            objects / BASE_LOCALE,
            1,
            {"spkid-1": {"name": "Ceres"}, "spkid-2": {"description": "asteroid"}},
        )
        _write_bundles(
            objects / "__global__",
            2,
            {
                "spkid-1": {"name": "1 Ceres"},
                "spkid-2": {"name": "2 Pallas"},
                "spkid-3": {},
            },
        )

    def test_prefers_the_localized_name(self, tmp_path: Path):
        self._export(tmp_path)

        names = _object_names(tmp_path, self.BUCKETS, ["spkid-1"])
        assert names == {"spkid-1": "Ceres"}

    def test_falls_back_to_the_catalogue_name(self, tmp_path: Path):
        self._export(tmp_path)

        names = _object_names(tmp_path, self.BUCKETS, ["spkid-2"])
        assert names == {"spkid-2": "2 Pallas"}

    def test_keeps_an_exported_object_that_has_no_name(self, tmp_path: Path):
        self._export(tmp_path)

        assert _object_names(tmp_path, self.BUCKETS, ["spkid-3"]) == {"spkid-3": None}

    def test_leaves_out_an_object_the_export_does_not_have(self, tmp_path: Path):
        self._export(tmp_path)

        assert _object_names(tmp_path, self.BUCKETS, ["spkid-4"]) == {}


class TestNotablePaths:
    """Which objects are listed, and under which name."""

    def test_names_each_notable_object_from_the_bundles(
        self, session: Session, tmp_path: Path
    ):
        session.add(make_object(id="naif-399", naif_id=399, name="EARTH"))
        session.add(_asteroid("spkid-20000001", sitelinks_count=SITELINKS_THRESHOLD))
        session.add(_asteroid("spkid-29999999"))
        session.flush()
        _write_bundles(
            tmp_path / "objects" / BASE_LOCALE, 1, {"naif-399": {"name": "Earth"}}
        )
        _write_bundles(
            tmp_path / "objects" / "__global__",
            1,
            {"spkid-20000001": {"name": "1 Ceres"}, "spkid-29999999": {"name": "X"}},
        )

        paths = _notable_paths(session, tmp_path, {BASE_LOCALE: 1, "global": 1})
        assert paths == {
            "naif-399": "/b/399/Earth",
            "spkid-20000001": "/s/20000001/1%20Ceres",
        }

    def test_skips_a_notable_object_the_export_does_not_have(
        self, session: Session, tmp_path: Path
    ):
        """It has no page: a lost comet stays in the catalogue."""
        session.add(_asteroid("spkid-1000004", sitelinks_count=SITELINKS_THRESHOLD))
        session.add(_asteroid("spkid-1000005", sitelinks_count=SITELINKS_THRESHOLD))
        session.flush()
        _write_bundles(tmp_path / "objects" / "__global__", 1, {"spkid-1000005": {}})

        paths = _notable_paths(session, tmp_path, {BASE_LOCALE: 0, "global": 1})
        assert paths == {"spkid-1000005": "/s/1000005"}

    def test_never_lists_a_barycenter(self, session: Session, tmp_path: Path):
        """Its page is named by an app label, which no bundle carries."""
        session.add(
            make_object(
                id="naif-5",
                naif_id=5,
                object_type=ObjectType.barycenter,
                sitelinks_count=SITELINKS_THRESHOLD,
            )
        )
        session.flush()

        assert _notable_paths(session, tmp_path, {BASE_LOCALE: 0, "global": 0}) == {}


class TestFeaturePaths:
    """Feature URLs and the notability floor gating them."""

    def test_builds_the_route_shape_the_app_resolves(self, session: Session):
        _feature(session, 7, name="Tycho")
        session.flush()

        paths = _feature_paths(session, _entities({"Q7": SITELINKS_THRESHOLD}))
        assert [path for _, path in paths] == ["/b/301/f/7/Tycho"]

    def test_drops_features_under_the_sitelink_floor(self, session: Session):
        _feature(session, 1, name="Famous")
        _feature(session, 2, name="Obscure")
        session.flush()

        paths = _feature_paths(
            session,
            _entities({"Q1": SITELINKS_THRESHOLD, "Q2": SITELINKS_THRESHOLD - 1}),
        )
        assert [path for _, path in paths] == ["/b/301/f/1/Famous"]

    def test_drops_features_with_no_wikidata_entity(self, session: Session):
        _feature(session, 1, name="Ghost")
        session.flush()

        assert _feature_paths(session, _entities({})) == []

    def test_takes_the_name_of_the_label_file(self, session: Session):
        """The page reads its name there, and that is the IAU ``name``."""
        _feature(session, 3, name="Plante", unicode_name="Planté")
        session.flush()

        paths = _feature_paths(session, _entities({"Q3": SITELINKS_THRESHOLD}))
        assert [path for _, path in paths] == ["/b/301/f/3/Plante"]

    def test_skips_features_with_no_host_body(self, session: Session):
        _feature(session, 4, object_id=None)
        session.flush()

        assert _feature_paths(session, _entities({"Q4": SITELINKS_THRESHOLD})) == []

    @pytest.mark.parametrize(
        "missing",
        [{"center_lat": None}, {"center_lon": None}, {"feature_type_code": None}],
    )
    def test_skips_a_feature_the_gazetteer_leaves_out(
        self, session: Session, missing: dict
    ):
        """Such a feature has no page: the app reads its name from the gazetteer."""
        _feature(session, 5, **missing)
        session.flush()

        assert _feature_paths(session, _entities({"Q5": SITELINKS_THRESHOLD})) == []


class TestGroupName:
    """The page name of a group, as ``groupPageName`` gives it."""

    LABELS = {
        "category_name_dwarf_planets": "Dwarf Planets",
        "orbit_class_APO": "Apollo",
    }

    def test_takes_the_exported_name(self):
        assert _group_name("const-starlink", "Starlink", self.LABELS) == "Starlink"

    def test_takes_the_app_label_of_a_category_over_the_exported_name(self):
        name = _group_name("cat-dwarf-planets", "dwarf planet", self.LABELS)
        assert name == "Dwarf Planets"

    def test_takes_the_app_label_of_an_orbit_class_the_export_does_not_name(self):
        assert _group_name("class-APO", None, self.LABELS) == "Apollo"

    def test_keeps_the_exported_name_of_an_orbit_class(self):
        name = _group_name("class-APO", "Low Earth orbit", self.LABELS)
        assert name == "Low Earth orbit"

    def test_gives_no_name_when_there_is_none(self):
        assert _group_name("const-unknown", None, self.LABELS) is None
        assert _group_name("class-XYZ", None, self.LABELS) is None

    def test_the_app_labels_every_category_and_orbit_class(self):
        """The label keys are the app's own: a renamed one must fail here."""
        app_labels = orjson.loads((MESSAGES_DIR / f"{BASE_LOCALE}.json").read_bytes())
        app_named = [
            g.slug
            for g in GROUPS
            if g.type
            in (
                GroupType.CATEGORY,
                GroupType.ORBIT_CLASS,
                GroupType.EARTH_ORBIT_CLASS,
            )
        ]

        unnamed = [s for s in app_named if not _group_name(s, None, app_labels)]
        assert app_named and unnamed == []


class TestGroupPaths:
    """Group URLs from the group index and bundles."""

    def test_names_each_group_of_the_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        messages = tmp_path / "messages"
        messages.mkdir()
        (messages / f"{BASE_LOCALE}.json").write_bytes(
            orjson.dumps({"category_name_planets": "Planets"})
        )
        monkeypatch.setattr(sitemap, "MESSAGES_DIR", messages)
        groups = tmp_path / "groups"
        _write_bundles(
            groups / BASE_LOCALE,
            1,
            {"const-oneweb": {"name": "OneWeb"}, "cat-planets": {"name": "planet"}},
        )
        (groups / "__index__.json").write_bytes(
            orjson.dumps({"const-oneweb": {}, "cat-planets": {}, "const-bare": {}})
        )

        assert _group_paths(tmp_path, 1) == {
            "const-oneweb": "/g/const-oneweb/OneWeb",
            "cat-planets": "/g/cat-planets/Planets",
            "const-bare": "/g/const-bare",
        }

    def test_lists_no_group_without_the_index(self, tmp_path: Path):
        assert _group_paths(tmp_path, 1) == {}
