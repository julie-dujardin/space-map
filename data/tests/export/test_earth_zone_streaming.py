"""Tests for the streaming Earth exporter's skip-before-parse + disk scan."""

from types import SimpleNamespace

from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.pipeline import zone as zone_mod
from space_map_data.export.pipeline.zone import _scan_date_snapshots, export_earth_zone
from space_map_data.export.position.layout import position_zone_dir


class TestScanDateSnapshots:
    """The manifest reads date-segmented part counts straight off disk so
    archive years skipped without parsing still ship."""

    def test_counts_parts_per_date_dir(self, tmp_path):
        # earth is flat — date dirs sit directly under position/earth/ (no zoom).
        zdir = position_zone_dir(tmp_path, "earth", 0)
        for date, n in [("2024-01-01", 2), ("2024-01-08", 1), ("2026-06-02", 3)]:
            d = zdir / date
            d.mkdir(parents=True)
            for i in range(n):
                (d / f"{i}.bin.gz").write_bytes(b"x")
        # A non-date dir and a date dir with no parts are both ignored.
        (zdir / "groups").mkdir()
        (zdir / "2024-02-02").mkdir()
        snaps = _scan_date_snapshots(tmp_path, "earth", 0)
        assert [(s.time, s.num_parts) for s in snaps] == [
            ("2024-01-01", 2),
            ("2024-01-08", 1),
            ("2026-06-02", 3),
        ]

    def test_missing_zone_dir_is_empty(self, tmp_path):
        assert _scan_date_snapshots(tmp_path, "earth", 0) == []


class TestSkipBeforeParse:
    """An archive year whose zip fingerprints match its on-disk marker is
    skipped without re-parsing on the next run; a dirty year is parsed once."""

    def _patch(self, monkeypatch):
        calls = SimpleNamespace(parse_count=0, written_sources=[])

        def fake_load_archive_weeks(years):
            calls.parse_count += 1
            return {"2024-01-01": {25544: {}}}

        def fake_write_parts(objects, out_dir, zone, zoom, *a, time, **k):
            # Mirror the real writer's dir output so the disk scan sees the week.
            d = position_zone_dir(out_dir, zone, zoom) / time
            d.mkdir(parents=True, exist_ok=True)
            (d / "0.bin.gz").write_bytes(b"x")
            calls.written_sources.append(objects[0]._source_override)
            return 1

        monkeypatch.setattr(zone_mod, "load_archive_weeks", fake_load_archive_weeks)
        monkeypatch.setattr(
            zone_mod, "archive_zip_fingerprints", lambda years: [{"y": list(years)}]
        )
        monkeypatch.setattr(
            zone_mod, "build_zone_object_data", lambda objs, ctx: ChunkObjectData()
        )
        monkeypatch.setattr(
            zone_mod, "_derive_parent_id_type", lambda z, o: "norad_satcat"
        )
        monkeypatch.setattr(
            zone_mod, "_overlay_celestrak_elements", lambda base, els, **k: list(base)
        )
        monkeypatch.setattr(zone_mod, "_write_element_parts", fake_write_parts)
        return calls

    def _base(self):
        # SimpleNamespace stands in for Object: the overlay/metadata are stubbed,
        # but it must accept the transient `_source_override` the writer reads.
        return [SimpleNamespace()]

    def test_dirty_year_parsed_once(self, tmp_path, monkeypatch):
        calls = self._patch(monkeypatch)
        ctx = SimpleNamespace(wikidata_entities=None, units=None)
        result = export_earth_zone(self._base(), {}, [2024], tmp_path, ctx=ctx)  # type: ignore[arg-type]
        assert calls.parse_count == 1
        # The week shipped, stamped Space-Track.
        assert [(s.time, s.num_parts) for s in result.snapshots] == [("2024-01-01", 1)]
        assert all(str(s) == "spacetrack" for s in calls.written_sources)

    def test_second_run_skips_parse(self, tmp_path, monkeypatch):
        calls = self._patch(monkeypatch)
        ctx = SimpleNamespace(wikidata_entities=None, units=None)
        export_earth_zone(self._base(), {}, [2024], tmp_path, ctx=ctx)  # type: ignore[arg-type]
        assert calls.parse_count == 1
        # Markers now match the stable fingerprint → no parse, week still ships.
        r2 = export_earth_zone(self._base(), {}, [2024], tmp_path, ctx=ctx)  # type: ignore[arg-type]
        assert calls.parse_count == 1  # unchanged — not parsed again
        assert [(s.time, s.num_parts) for s in r2.snapshots] == [("2024-01-01", 1)]

    def test_changed_fingerprint_reparses(self, tmp_path, monkeypatch):
        calls = self._patch(monkeypatch)
        ctx = SimpleNamespace(wikidata_entities=None, units=None)
        export_earth_zone(self._base(), {}, [2024], tmp_path, ctx=ctx)  # type: ignore[arg-type]
        assert calls.parse_count == 1
        # Fingerprint changes (e.g. re-downloaded zip) → marker mismatch → reparse.
        monkeypatch.setattr(
            zone_mod, "archive_zip_fingerprints", lambda years: [{"changed": True}]
        )
        export_earth_zone(self._base(), {}, [2024], tmp_path, ctx=ctx)  # type: ignore[arg-type]
        assert calls.parse_count == 2


class TestGlobalOrbitOverlay:
    """The per-object global bundle's orbit block is built from the transient
    `_daily_kepler`, so the most recent daily must be overlaid onto the base
    *before* metadata is built — without it Earth sats ship with no orbit block
    and URL navigation hides them (redirecting to the Sun)."""

    def _patch(self, monkeypatch, captured):
        # Spy on the metadata build to record what `_daily_kepler` each object
        # carries at build time; the overlay itself runs for real.
        def fake_build(objs, ctx):
            captured.extend(getattr(o, "_daily_kepler", None) for o in objs)
            return ChunkObjectData()

        def fake_write_parts(objects, out_dir, zone, zoom, *a, time, **k):
            d = position_zone_dir(out_dir, zone, zoom) / time
            d.mkdir(parents=True, exist_ok=True)
            (d / "0.bin.gz").write_bytes(b"x")
            return 1

        monkeypatch.setattr(zone_mod, "build_zone_object_data", fake_build)
        monkeypatch.setattr(
            zone_mod, "_derive_parent_id_type", lambda z, o: "norad_satcat"
        )
        monkeypatch.setattr(zone_mod, "_write_element_parts", fake_write_parts)

    def test_latest_daily_overlaid_before_metadata(self, tmp_path, monkeypatch):
        captured: list = []
        self._patch(monkeypatch, captured)
        ctx = SimpleNamespace(wikidata_entities=None, units=None)
        sat = SimpleNamespace(norad_cat_id=25544)
        old = {25544: {"epoch_jd": 1.0, "n": 15.0}}
        new = {25544: {"epoch_jd": 2.0, "n": 15.5}}
        export_earth_zone(
            [sat],  # type: ignore[arg-type]
            {"2026-06-02": old, "2026-06-18": new},  # type: ignore[arg-type]
            [],
            tmp_path,
            ctx=ctx,  # type: ignore[arg-type]
        )
        # Metadata was built with the most recent daily's elements attached.
        assert captured == [new[25544]]

    def test_sat_missing_from_latest_day_keeps_earlier_elements(
        self, tmp_path, monkeypatch
    ):
        captured: list = []
        self._patch(monkeypatch, captured)
        ctx = SimpleNamespace(wikidata_entities=None, units=None)
        sat = SimpleNamespace(norad_cat_id=25544)
        only_old = {25544: {"epoch_jd": 1.0, "n": 15.0}}
        # The latest day has other sats but not this one.
        latest = {99999: {"epoch_jd": 2.0, "n": 16.0}}
        export_earth_zone(
            [sat],  # type: ignore[arg-type]
            {"2026-06-01": only_old, "2026-06-02": latest},  # type: ignore[arg-type]
            [],
            tmp_path,
            ctx=ctx,  # type: ignore[arg-type]
        )
        # Absent from the newest day → falls back to the earlier day's elements.
        assert captured == [only_old[25544]]

    def test_no_daily_elements_warns_and_skips_overlay(
        self, tmp_path, monkeypatch, caplog
    ):
        captured: list = []
        self._patch(monkeypatch, captured)
        ctx = SimpleNamespace(wikidata_entities=None, units=None)
        sat = SimpleNamespace(norad_cat_id=25544)
        with caplog.at_level("WARNING"):
            export_earth_zone([sat], {}, [], tmp_path, ctx=ctx)  # type: ignore[arg-type]
        assert captured == [None]
        assert "no daily elements" in caplog.text
