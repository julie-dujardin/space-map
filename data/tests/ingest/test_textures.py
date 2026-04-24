"""Tests for space_map_data.ingest.providers.textures."""

import json

import numpy as np
from PIL import Image

from space_map_data.ingest.providers import textures
from space_map_data.ingest.providers.textures import (
    MAX_FILE_BYTES,
    MIN_QUALITY,
    _any_export_over_cap,
    _save_webp,
)


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
    """_save_webp enforces MAX_FILE_BYTES by reducing quality, then dims."""

    def test_small_image_saves_at_default_quality(self, tmp_path):
        """Trivially small images fit under the cap with no degradation."""
        img = Image.new("RGB", (64, 32), color="red")
        rec = _save_webp(img, tmp_path / "out.webp", lossless=False)
        assert rec["width"] == 64
        assert rec["height"] == 32
        assert rec["size_bytes"] < MAX_FILE_BYTES
        assert "quality" not in rec  # default quality, no annotation

    def test_lossless_skips_cap_but_warns(self, tmp_path, caplog):
        """Lossless path preserves the image even if oversized — but warns."""
        caplog.set_level("WARNING", logger="space_map_data.ingest.providers.textures")
        img = _make_noise(512, 512)
        # Use an impossibly tight cap to force the warning branch.
        rec = _save_webp(img, tmp_path / "out.webp", lossless=True, max_bytes=1024)
        assert rec["lossless"] is True
        assert rec["width"] == 512
        assert any("exceeds cap" in r.message for r in caplog.records)

    def test_quality_drops_to_fit_cap(self, tmp_path, caplog):
        """A gradient image (compresses well at lower quality) lands under a
        mid-range cap after one or two quality steps, without resizing."""
        caplog.set_level("INFO", logger="space_map_data.ingest.providers.textures")
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
        rec = _save_webp(img, tmp_path / "out.webp", lossless=False, max_bytes=cap)
        assert rec["width"] == 1024  # no resize
        assert rec["size_bytes"] <= cap
        assert rec.get("quality") is not None
        assert MIN_QUALITY <= rec["quality"] < 80

    def test_shrinks_when_quality_floor_hit(self, tmp_path, caplog, monkeypatch):
        """Cap too small for any q≥MIN_QUALITY: must downscale.

        Uses a noise image (uncompressible) and a permissive MIN_DIM floor so
        the test runs fast without actually shrinking below a reasonable size.
        """
        caplog.set_level("INFO", logger="space_map_data.ingest.providers.textures")
        monkeypatch.setattr(textures, "MIN_DIM_AFTER_SHRINK", 256)
        img = _make_noise(1024, 1024)

        # Probe at MIN_QUALITY — noise compresses poorly, natural floor is
        # several hundred KiB at 1024px; a 50 KiB cap forces a shrink.
        img.save(tmp_path / "probe.webp", "webp", quality=MIN_QUALITY)
        min_q_size = (tmp_path / "probe.webp").stat().st_size
        cap = min_q_size // 5

        rec = _save_webp(img, tmp_path / "out.webp", lossless=False, max_bytes=cap)
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
        caplog.set_level("ERROR", logger="space_map_data.ingest.providers.textures")
        img = _make_noise(1024, 1024)  # first shrink → 870 < 4096 floor
        rec = _save_webp(img, tmp_path / "out.webp", lossless=False, max_bytes=1)
        assert (tmp_path / "out.webp").exists()
        assert rec["size_bytes"] > 1
        assert any("cannot fit" in r.message for r in caplog.records)


class TestAnyExportOverCap:
    """_any_export_over_cap triggers auto-reprocess when a bundle is stale."""

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
        assert _any_export_over_cap(tmp_path) is True

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
        assert _any_export_over_cap(tmp_path) is False

    def test_missing_metadata_returns_false(self, tmp_path):
        assert _any_export_over_cap(tmp_path) is False

    def test_corrupt_metadata_returns_false(self, tmp_path):
        (tmp_path / "metadata.json").write_text("{not json")
        assert _any_export_over_cap(tmp_path) is False
