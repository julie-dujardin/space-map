"""Tests for the streaming Earth exporter's skip-before-parse + disk scan."""

from types import SimpleNamespace

from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.pipeline import zone as zone_mod
from space_map_data.export.pipeline.zone import _scan_date_snapshots, export_earth_zones


class TestScanDateSnapshots:
    """The manifest reads date-segmented part counts straight off disk so
    archive years skipped without parsing still ship."""

    def test_counts_parts_per_date_dir(self, tmp_path):
        zdir = tmp_path / "position" / "earth" / "0"
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
    skipped without re-parsing on the next run, and a dirty year is parsed once
    across all zooms."""

    def _patch(self, monkeypatch):
        calls = SimpleNamespace(parse_count=0, written_sources=[])

        def fake_load_archive_weeks(years):
            calls.parse_count += 1
            return {"2024-01-01": {25544: {}}}

        def fake_write_parts(objects, out_dir, zone, zoom, *a, time, **k):
            # Mirror the real writer's dir output so the disk scan sees the week.
            d = out_dir / "position" / zone / str(zoom) / time
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

    def _zoom_bases(self):
        # SimpleNamespace stands in for Object: the overlay/metadata are stubbed,
        # but it must accept the transient `_source_override` the writer reads.
        return [(0, [SimpleNamespace()]), (1, [SimpleNamespace()])]

    def test_one_parse_drives_both_zooms(self, tmp_path, monkeypatch):
        calls = self._patch(monkeypatch)
        ctx = SimpleNamespace(wikidata_entities=None, units=None)
        results = export_earth_zones(self._zoom_bases(), {}, [2024], tmp_path, ctx=ctx)  # type: ignore[arg-type]
        # The dirty year is parsed once, not once per zoom.
        assert calls.parse_count == 1
        # Both zooms shipped the week, stamped Space-Track.
        assert [(s.time, s.num_parts) for s in results[0].snapshots] == [
            ("2024-01-01", 1)
        ]
        assert [(s.time, s.num_parts) for s in results[1].snapshots] == [
            ("2024-01-01", 1)
        ]
        assert all(str(s) == "spacetrack" for s in calls.written_sources)

    def test_second_run_skips_parse(self, tmp_path, monkeypatch):
        calls = self._patch(monkeypatch)
        ctx = SimpleNamespace(wikidata_entities=None, units=None)
        export_earth_zones(self._zoom_bases(), {}, [2024], tmp_path, ctx=ctx)  # type: ignore[arg-type]
        assert calls.parse_count == 1
        # Markers now match the stable fingerprint → no parse, week still ships.
        r2 = export_earth_zones(self._zoom_bases(), {}, [2024], tmp_path, ctx=ctx)  # type: ignore[arg-type]
        assert calls.parse_count == 1  # unchanged — not parsed again
        assert [(s.time, s.num_parts) for s in r2[0].snapshots] == [("2024-01-01", 1)]

    def test_changed_fingerprint_reparses(self, tmp_path, monkeypatch):
        calls = self._patch(monkeypatch)
        ctx = SimpleNamespace(wikidata_entities=None, units=None)
        export_earth_zones(self._zoom_bases(), {}, [2024], tmp_path, ctx=ctx)  # type: ignore[arg-type]
        assert calls.parse_count == 1
        # Fingerprint changes (e.g. re-downloaded zip) → marker mismatch → reparse.
        monkeypatch.setattr(
            zone_mod, "archive_zip_fingerprints", lambda years: [{"changed": True}]
        )
        export_earth_zones(self._zoom_bases(), {}, [2024], tmp_path, ctx=ctx)  # type: ignore[arg-type]
        assert calls.parse_count == 2
