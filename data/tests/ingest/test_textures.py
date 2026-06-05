"""Tests for space_map_data.ingest.providers.textures."""

import json

import numpy as np
from PIL import Image

from space_map_data.ingest.providers.textures import (
    EARTH_CLOUDS_OBJECT_ID,
    MAX_FILE_BYTES,
    MIN_QUALITY,
    TextureProcessor,
    any_export_over_cap,
    expand_entry_files,
    save_webp,
)
from space_map_data.ingest.providers.textures import config


def _make_noise(width: int, height: int) -> Image.Image:
    """Random RGB noise: nearly incompressible, great for forcing the cap path."""
    rng = np.random.default_rng(seed=42)
    arr = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    return Image.fromarray(arr, mode="RGB")


def _make_gradient(width: int, height: int) -> Image.Image:
    """Smooth RGB gradient — compresses drastically between quality steps."""
    y, x = np.mgrid[0:height, 0:width]
    r = (x * 255 // max(1, width - 1)).astype(np.uint8)
    g = (y * 255 // max(1, height - 1)).astype(np.uint8)
    b = np.full_like(r, 128)
    return Image.fromarray(np.stack([r, g, b], axis=-1), mode="RGB")


class TestSaveWebpCap:
    """save_webp enforces MAX_FILE_BYTES by reducing quality, then dims."""

    def test_small_image_saves_at_default_quality(self, tmp_path):
        """Trivially small images fit under the cap with no degradation."""
        img = Image.new("RGB", (64, 32), color="red")
        rec = save_webp(img, tmp_path / "out.webp", lossless=False)
        assert rec["width"] == 64
        assert rec["height"] == 32
        assert rec["size_bytes"] < MAX_FILE_BYTES
        assert "quality" not in rec  # default quality, no annotation

    def test_lossless_skips_cap_but_warns(self, tmp_path, caplog):
        """Lossless path preserves the image even if oversized — but warns."""
        caplog.set_level("WARNING")
        img = _make_noise(512, 512)
        # Use an impossibly tight cap to force the warning branch.
        rec = save_webp(img, tmp_path / "out.webp", lossless=True, max_bytes=1024)
        assert rec["lossless"] is True
        assert rec["width"] == 512
        assert any("exceeds cap" in r.message for r in caplog.records)

    def test_quality_drops_to_fit_cap(self, tmp_path):
        """A gradient image (compresses well at lower quality) lands under a
        mid-range cap after one or two quality steps, without resizing."""
        img = _make_gradient(1024, 1024)

        # Encode at q=80 and MIN_QUALITY to bracket the achievable size range.
        (tmp_path / "probe80.webp").write_bytes(b"")  # placate fs
        img.save(tmp_path / "probe80.webp", "webp", quality=80)
        q80 = (tmp_path / "probe80.webp").stat().st_size
        img.save(tmp_path / "probe_min.webp", "webp", quality=MIN_QUALITY)
        q_min = (tmp_path / "probe_min.webp").stat().st_size
        assert q_min < q80  # sanity

        # Cap midway between the two so exactly one quality step should be
        # enough — the test exercises the "q down, no resize" path.
        cap = (q_min + q80) // 2
        rec = save_webp(img, tmp_path / "out.webp", lossless=False, max_bytes=cap)
        assert rec["width"] == 1024  # no resize
        assert rec["size_bytes"] <= cap
        assert rec.get("quality") is not None
        assert MIN_QUALITY <= rec["quality"] < 80

    def test_shrinks_when_quality_floor_hit(self, tmp_path, caplog, monkeypatch):
        """Cap too small for any q≥MIN_QUALITY: must downscale.

        Uses a noise image (uncompressible) and a permissive MIN_DIM floor so
        the test runs fast without actually shrinking below a reasonable size.
        """
        caplog.set_level("INFO")
        monkeypatch.setattr(config, "MIN_DIM_AFTER_SHRINK", 256)
        img = _make_noise(1024, 1024)

        # Probe at MIN_QUALITY — noise compresses poorly, natural floor is
        # several hundred KiB at 1024px; a 50 KiB cap forces a shrink.
        img.save(tmp_path / "probe.webp", "webp", quality=MIN_QUALITY)
        min_q_size = (tmp_path / "probe.webp").stat().st_size
        cap = min_q_size // 5

        rec = save_webp(img, tmp_path / "out.webp", lossless=False, max_bytes=cap)
        assert rec["size_bytes"] <= cap
        # Must have shrunk below the original 1024 longest side.
        assert max(rec["width"], rec["height"]) < 1024
        assert max(rec["width"], rec["height"]) >= 256
        assert any("shrinking" in r.message for r in caplog.records)

    def test_gives_up_at_min_dim_but_still_writes_file(self, tmp_path, caplog):
        """Cap so tight even MIN_DIM_AFTER_SHRINK can't fit: best-effort
        output stays on disk and an error is logged. Uses a small noise image
        so the shrink loop terminates quickly (first shrink already undershoots
        the default MIN_DIM_AFTER_SHRINK=4096)."""
        caplog.set_level("ERROR")
        img = _make_noise(1024, 1024)  # first shrink → 870 < 4096 floor
        rec = save_webp(img, tmp_path / "out.webp", lossless=False, max_bytes=1)
        assert (tmp_path / "out.webp").exists()
        assert rec["size_bytes"] > 1
        assert any("cannot fit" in r.message for r in caplog.records)


class TestAnyExportOverCap:
    """any_export_over_cap triggers auto-reprocess when a bundle is stale."""

    def test_returns_true_when_any_export_exceeds(self, tmp_path):
        (tmp_path / "metadata.json").write_text(
            json.dumps(
                {
                    "exports": {
                        "low": {"size_bytes": 1000},
                        "high": {"size_bytes": MAX_FILE_BYTES + 1},
                    }
                }
            )
        )
        assert any_export_over_cap(tmp_path) is True

    def test_returns_false_when_all_under_cap(self, tmp_path):
        (tmp_path / "metadata.json").write_text(
            json.dumps(
                {
                    "exports": {
                        "low": {"size_bytes": 1000},
                        "high": {"size_bytes": MAX_FILE_BYTES - 1},
                    }
                }
            )
        )
        assert any_export_over_cap(tmp_path) is False

    def test_missing_metadata_returns_false(self, tmp_path):
        assert any_export_over_cap(tmp_path) is False

    def test_corrupt_metadata_returns_false(self, tmp_path):
        (tmp_path / "metadata.json").write_text("{not json")
        assert any_export_over_cap(tmp_path) is False

    def test_nested_monthly_exports_detected_over_cap(self, tmp_path):
        """Monthly metadata nests records one level deeper (frame → tier → rec).

        The recursive walk must spot a single over-cap record anywhere in the
        tree, otherwise stale monthly bundles never trigger auto-reprocess.
        """
        (tmp_path / "metadata.json").write_text(
            json.dumps(
                {
                    "type": "cylindrical_monthly",
                    "exports": {
                        "01": {
                            "low": {"size_bytes": 1000},
                            "high": {"size_bytes": 1000},
                        },
                        "07": {
                            "low": {"size_bytes": 1000},
                            "high": {"size_bytes": MAX_FILE_BYTES + 1},
                        },
                    },
                }
            )
        )
        assert any_export_over_cap(tmp_path) is True


class TestExpandEntryFiles:
    """expand_entry_files turns a yaml entry into concrete raw filenames."""

    def test_single_frame_identity(self):
        entry = {"file": "mars.tif", "type": "cylindrical"}
        assert expand_entry_files(entry) == ["mars.tif"]

    def test_monthly_template_expands(self):
        entry = {
            "file": "world.2004{month:02d}.tif",
            "type": "cylindrical_monthly",
            "months": 12,
        }
        result = expand_entry_files(entry)
        assert len(result) == 12
        assert result[0] == "world.200401.tif"
        assert result[5] == "world.200406.tif"
        assert result[11] == "world.200412.tif"

    def test_monthly_default_months_is_twelve(self):
        """`months` defaults to 12 when omitted — matches the Blue Marble cycle."""
        entry = {
            "file": "x.{month}.tif",
            "type": "cylindrical_monthly",
        }
        assert len(expand_entry_files(entry)) == 12


class TestProcessMonthly:
    """End-to-end ingest of a small synthetic monthly series.

    Uses a tmp DOWNLOAD/EXPORT layout via monkeypatch; bypasses the DB-touching
    helpers so the test doesn't need a session.
    """

    @staticmethod
    def _make_processor(monkeypatch, tmp_path, entry: dict) -> TextureProcessor:
        raw = tmp_path / "raw"
        processed = tmp_path / "processed"
        raw.mkdir()
        processed.mkdir()
        monkeypatch.setattr(config, "RAW_DIR", raw)
        monkeypatch.setattr(config, "PROCESSED_DIR", processed)
        proc = TextureProcessor.__new__(TextureProcessor)
        proc._raw_meta = [entry]
        # Skip the DB writes; the texture-availability flag is exercised by the
        # full ingest harness, not this unit test.
        proc._mark_texture_available = lambda object_id: None  # noqa: ARG005
        proc._reset_texture_available = lambda: None
        return proc

    def _seed_frames(self, raw_dir, template: str, months: int) -> None:
        for m in range(1, months + 1):
            img = Image.new("RGB", (256, 128), color=(20 * m, 100, 200))
            img.save(raw_dir / template.format(month=m))

    def test_emits_per_frame_tier_files_and_nested_metadata(
        self, tmp_path, monkeypatch
    ):
        entry = {
            "body": "naif-399",
            "body_name": "earth",
            "source": "https://example.com",
            "organisation": "NASA",
            "attribution": "Test attribution",
            "file": "world.{month:02d}.tif",
            "type": "cylindrical_monthly",
            "months": 3,
        }
        proc = self._make_processor(monkeypatch, tmp_path, entry)
        self._seed_frames(config.RAW_DIR, entry["file"], entry["months"])

        proc._process_monthly(entry)

        body_dir = config.PROCESSED_DIR / "naif-399"
        meta = json.loads((body_dir / "metadata.json").read_text())
        assert meta["type"] == "cylindrical_monthly"
        assert meta["frames"] == 3
        assert meta["source_file"] == entry["file"]
        assert sorted(meta["exports"].keys()) == ["01", "02", "03"]
        for frame, tier_recs in meta["exports"].items():
            for tier, rec in tier_recs.items():
                assert rec["file"] == f"{tier}_{frame}.webp"
                assert (body_dir / rec["file"]).exists()

    def test_strips_stale_single_frame_outputs(self, tmp_path, monkeypatch):
        """Bodies migrating from `cylindrical` to `cylindrical_monthly` shouldn't
        ship the old flat-layout webps alongside the new per-month ones."""
        entry = {
            "body": "naif-399",
            "body_name": "earth",
            "source": "https://example.com",
            "organisation": "NASA",
            "file": "w.{month:02d}.tif",
            "type": "cylindrical_monthly",
            "months": 2,
        }
        proc = self._make_processor(monkeypatch, tmp_path, entry)
        self._seed_frames(config.RAW_DIR, entry["file"], entry["months"])
        body_dir = config.PROCESSED_DIR / "naif-399"
        body_dir.mkdir()
        for stale in ("low.webp", "medium.webp", "high.webp"):
            (body_dir / stale).write_bytes(b"stale")

        proc._process_monthly(entry)

        for stale in ("low.webp", "medium.webp", "high.webp"):
            assert not (body_dir / stale).exists()

    def test_missing_source_logs_warning_and_skips_frame(
        self, tmp_path, monkeypatch, caplog
    ):
        caplog.set_level("WARNING")
        entry = {
            "body": "naif-399",
            "body_name": "earth",
            "source": "https://example.com",
            "organisation": "NASA",
            "file": "m.{month:02d}.tif",
            "type": "cylindrical_monthly",
            "months": 3,
        }
        proc = self._make_processor(monkeypatch, tmp_path, entry)
        # Seed only months 1 and 3; 2 is missing.
        for m in (1, 3):
            img = Image.new("RGB", (128, 64), color="blue")
            img.save(config.RAW_DIR / entry["file"].format(month=m))

        proc._process_monthly(entry)

        meta = json.loads(
            (config.PROCESSED_DIR / "naif-399" / "metadata.json").read_text()
        )
        assert sorted(meta["exports"].keys()) == ["01", "03"]
        assert any("monthly source missing" in r.message for r in caplog.records)
        assert any("m.02.tif" in r.message for r in caplog.records)

    def test_reprocess_when_yaml_shape_changes(self, tmp_path, monkeypatch):
        """If the yaml entry switches `months` or template, the body must
        reprocess even without force — otherwise stale frame files linger."""
        entry = {
            "body": "naif-399",
            "body_name": "earth",
            "source": "https://example.com",
            "organisation": "NASA",
            "file": "m.{month:02d}.tif",
            "type": "cylindrical_monthly",
            "months": 2,
        }
        proc = self._make_processor(monkeypatch, tmp_path, entry)
        self._seed_frames(config.RAW_DIR, entry["file"], entry["months"])
        proc._process_monthly(entry)

        body_dir = config.PROCESSED_DIR / "naif-399"
        # Mutate yaml to claim 3 frames; add a 3rd source so the processor can
        # produce it.
        img = Image.new("RGB", (128, 64), color="green")
        img.save(config.RAW_DIR / entry["file"].format(month=3))
        new_entry = {**entry, "months": 3}

        proc._process_monthly(new_entry)
        meta = json.loads((body_dir / "metadata.json").read_text())
        assert meta["frames"] == 3
        assert sorted(meta["exports"].keys()) == ["01", "02", "03"]


class TestProcessClouds:
    """End-to-end ingest of a synthetic earth_clouds snapshot tree.

    Uses a tmp DOWNLOAD/EXPORT layout via monkeypatch; bypasses the DB-touching
    helpers so the test doesn't need a session.
    """

    @staticmethod
    def _make_processor(monkeypatch, tmp_path) -> TextureProcessor:
        clouds = tmp_path / "earth_clouds"
        processed = tmp_path / "processed"
        clouds.mkdir()
        processed.mkdir()
        monkeypatch.setattr(config, "EARTH_CLOUDS_DIR", clouds)
        monkeypatch.setattr(config, "PROCESSED_DIR", processed)
        proc = TextureProcessor.__new__(TextureProcessor)
        proc._raw_meta = []
        proc._mark_texture_available = lambda _object_id: None
        proc._reset_texture_available = lambda: None
        return proc

    @staticmethod
    def _seed_snapshot(clouds_dir, when: tuple[int, int, int, int]) -> str:
        year, month, day, hour = when
        path = (
            clouds_dir
            / f"{year:04d}"
            / f"{month:02d}"
            / f"{day:02d}"
            / f"{hour:02d}.png"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (256, 128), color=(255, 255, 255, 128)).save(path)
        return path.relative_to(clouds_dir).as_posix()

    @staticmethod
    def _seed_metadata(clouds_dir) -> None:
        (clouds_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "source_url": "https://example.com/clouds.png",
                    "attribution": "Contains modified EUMETSAT data",
                }
            )
        )

    def test_exports_every_snapshot_and_writes_metadata(self, tmp_path, monkeypatch):
        proc = self._make_processor(monkeypatch, tmp_path)
        self._seed_metadata(config.EARTH_CLOUDS_DIR)
        self._seed_snapshot(config.EARTH_CLOUDS_DIR, (2026, 5, 5, 0))
        self._seed_snapshot(config.EARTH_CLOUDS_DIR, (2026, 5, 5, 18))

        proc._process_clouds()

        out_dir = config.PROCESSED_DIR / EARTH_CLOUDS_OBJECT_ID
        meta = json.loads((out_dir / "metadata.json").read_text())
        assert meta["id"] == EARTH_CLOUDS_OBJECT_ID
        assert meta["type"] == "clouds_overlay"
        assert meta["attribution"] == "Contains modified EUMETSAT data"
        assert meta["source"] == "https://example.com/clouds.png"
        assert meta["frames"] == ["2026050500", "2026050518"]
        assert meta["tiers"] == sorted(meta["tiers"])
        assert meta["tiers"]
        # Per-frame size_bytes / source_file are intentionally dropped.
        assert "source_file" not in meta
        # Each frame has at least the low tier on disk.
        for fid in meta["frames"]:
            assert (out_dir / f"low_{fid}.webp").exists()

    def test_incrementally_adds_new_snapshot(self, tmp_path, monkeypatch):
        proc = self._make_processor(monkeypatch, tmp_path)
        self._seed_metadata(config.EARTH_CLOUDS_DIR)
        self._seed_snapshot(config.EARTH_CLOUDS_DIR, (2026, 5, 5, 0))
        proc._process_clouds()

        out_dir = config.PROCESSED_DIR / EARTH_CLOUDS_OBJECT_ID
        assert json.loads((out_dir / "metadata.json").read_text())["frames"] == [
            "2026050500"
        ]

        self._seed_snapshot(config.EARTH_CLOUDS_DIR, (2026, 5, 5, 18))
        proc._process_clouds()
        meta = json.loads((out_dir / "metadata.json").read_text())
        assert meta["frames"] == ["2026050500", "2026050518"]
        # Both the pre-existing and the newly added frame are on disk.
        assert (out_dir / "low_2026050500.webp").exists()
        assert (out_dir / "low_2026050518.webp").exists()

    def test_purges_outputs_for_vanished_snapshots(self, tmp_path, monkeypatch):
        proc = self._make_processor(monkeypatch, tmp_path)
        self._seed_metadata(config.EARTH_CLOUDS_DIR)
        self._seed_snapshot(config.EARTH_CLOUDS_DIR, (2026, 5, 5, 0))
        self._seed_snapshot(config.EARTH_CLOUDS_DIR, (2026, 5, 5, 18))
        proc._process_clouds()

        out_dir = config.PROCESSED_DIR / EARTH_CLOUDS_OBJECT_ID
        assert (out_dir / "low_2026050500.webp").exists()

        # Delete the older snapshot and reprocess; its outputs must go too.
        (config.EARTH_CLOUDS_DIR / "2026" / "05" / "05" / "00.png").unlink()
        proc._process_clouds()
        meta = json.loads((out_dir / "metadata.json").read_text())
        assert meta["frames"] == ["2026050518"]
        assert not (out_dir / "low_2026050500.webp").exists()

    def test_skips_when_frame_inventory_unchanged(self, tmp_path, monkeypatch):
        proc = self._make_processor(monkeypatch, tmp_path)
        self._seed_metadata(config.EARTH_CLOUDS_DIR)
        self._seed_snapshot(config.EARTH_CLOUDS_DIR, (2026, 5, 5, 0))
        proc._process_clouds()

        out_dir = config.PROCESSED_DIR / EARTH_CLOUDS_OBJECT_ID
        first_ts = json.loads((out_dir / "metadata.json").read_text())["processed_at"]

        proc._process_clouds()
        second_ts = json.loads((out_dir / "metadata.json").read_text())["processed_at"]
        assert first_ts == second_ts

    def test_no_snapshots_warns_and_skips(self, tmp_path, monkeypatch, caplog):
        caplog.set_level("WARNING")
        proc = self._make_processor(monkeypatch, tmp_path)
        self._seed_metadata(config.EARTH_CLOUDS_DIR)

        result = proc._process_clouds()
        assert result == config.PROCESSED_DIR
        assert any("no earth_clouds snapshots" in r.message for r in caplog.records)

    def test_missing_clouds_dir_is_silent_noop(self, tmp_path, monkeypatch, caplog):
        caplog.set_level("WARNING")
        proc = self._make_processor(monkeypatch, tmp_path)
        # Remove the dir created by _make_processor.
        config.EARTH_CLOUDS_DIR.rmdir()

        result = proc._process_clouds()
        assert result == config.PROCESSED_DIR
        assert not caplog.records
