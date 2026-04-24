"""Tests for space_map_data.export.images."""

import gzip
import io
from pathlib import Path

import orjson
import pytest
from PIL import Image, ImageDraw

from space_map_data.export import images as images_mod
from space_map_data.utils import commons_images as ci


def _make_source_jpg(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _make_source_png(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color="blue")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _make_source_animated_gif(width: int, height: int, n_frames: int = 3) -> bytes:
    # Draw a moving rectangle so Pillow doesn't dedupe identical frames down
    # to a single-frame GIF.
    frames = []
    step_x = max(1, width // (n_frames + 1))
    step_y = max(1, height // (n_frames + 1))
    for i in range(n_frames):
        im = Image.new("RGB", (width, height), color="white")
        draw = ImageDraw.Draw(im)
        x, y = i * step_x, i * step_y
        draw.rectangle(
            [x, y, min(x + step_x, width - 1), min(y + step_y, height - 1)],
            fill="red",
        )
        frames.append(im.convert("P"))
    buf = io.BytesIO()
    frames[0].save(
        buf,
        "GIF",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    return buf.getvalue()


def _make_source_mpo(width: int, height: int) -> bytes:
    # MPO is a JPEG container with embedded secondary frames (stereoscopic
    # pairs, camera exposure stacks). Pillow reports is_animated=True and
    # n_frames>1 but frames aren't real animation.
    primary = Image.new("RGB", (width, height), color="red")
    secondary = Image.new("RGB", (width, height), color="blue")
    buf = io.BytesIO()
    primary.save(buf, "MPO", save_all=True, append_images=[secondary])
    return buf.getvalue()


def _make_source_static_gif(width: int, height: int) -> bytes:
    img = Image.new("P", (width, height), color=5)
    buf = io.BytesIO()
    img.save(buf, "GIF")
    return buf.getvalue()


def _stage_download(
    tmp_path: Path,
    filename: str,
    *,
    bytes_: bytes | None = None,
    width: int = 4,
    height: int = 4,
    license_servable: bool = True,
    extmetadata: dict | None = None,
    missing_source: bool = False,
) -> None:
    """Populate a fake DOWNLOAD_DIR/images/<filename>/ entry."""
    ext = Path(filename).suffix.lower()
    d = tmp_path / "downloads" / "images" / filename
    d.mkdir(parents=True, exist_ok=True)
    if not missing_source:
        if bytes_ is None:
            if ext == ".png":
                bytes_ = _make_source_png(width, height)
            elif ext == ".gif":
                bytes_ = _make_source_animated_gif(width, height)
            else:
                bytes_ = _make_source_jpg(width, height)
        (d / f"source{ext}").write_bytes(bytes_)
    em = (
        extmetadata
        if extmetadata is not None
        else {
            "LicenseShortName": {"value": "CC BY-SA 4.0"},
            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
        }
    )
    payload = {
        "filename": filename,
        "fetched_at": "2026-04-24T00:00:00+00:00",
        "imageinfo": {"extmetadata": em},
        "license_servable": license_servable,
    }
    (d / "metadata.json").write_bytes(orjson.dumps(payload))


@pytest.fixture
def layout(tmp_path, monkeypatch):
    """Point both the shared-util and export-side paths at tmp_path."""
    downloads_images = tmp_path / "downloads" / "images"
    export_images = tmp_path / "export" / "v1" / "images"
    downloads_images.mkdir(parents=True, exist_ok=True)
    export_images.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ci, "IMAGES_DIR", downloads_images)
    monkeypatch.setattr(images_mod, "DOWNLOADS_IMAGES_DIR", downloads_images)
    monkeypatch.setattr(images_mod, "_EXPORT_IMAGES_DIR", export_images)
    images_mod.clear_export_cache()
    return {"downloads": downloads_images, "export": export_images}


class TestCollectObjectImages:
    """collect_object_images — dedup, kind assignment, license gating."""

    def test_canonicalizes_wikidata_space_form_to_underscore(self, tmp_path, layout):
        _stage_download(tmp_path, "Foo_bar.jpg")
        result = images_mod.collect_object_images({"image": ["Foo bar.jpg"]}, [])
        assert result is not None and result[0]["file"] == "Foo_bar.jpg"

    def test_dedupes_across_p18_and_wikipedia_sources(self, tmp_path, layout):
        _stage_download(tmp_path, "A.jpg")
        result = images_mod.collect_object_images({"image": ["A.jpg"]}, ["A.jpg"])
        assert result is not None and len(result) == 1

    def test_dedupes_space_and_underscore_variants(self, tmp_path, layout):
        _stage_download(tmp_path, "A_b.jpg")
        result = images_mod.collect_object_images({"image": ["A b.jpg", "A_b.jpg"]}, [])
        assert result is not None and len(result) == 1

    def test_drops_when_source_missing(self, tmp_path, layout):
        _stage_download(tmp_path, "A.jpg", missing_source=True)
        assert images_mod.collect_object_images({"image": ["A.jpg"]}, []) is None

    def test_drops_when_download_metadata_missing(self, tmp_path, layout):
        # Stage only source.jpg, no metadata.json.
        d = layout["downloads"] / "A.jpg"
        d.mkdir(parents=True)
        (d / "source.jpg").write_bytes(_make_source_jpg(4, 4))
        assert images_mod.collect_object_images({"image": ["A.jpg"]}, []) is None

    def test_drops_non_servable(self, tmp_path, layout):
        _stage_download(tmp_path, "A.jpg", license_servable=False)
        assert images_mod.collect_object_images({"image": ["A.jpg"]}, []) is None

    def test_logo_kind_assigned_to_p154(self, tmp_path, layout):
        _stage_download(tmp_path, "Logo.png")
        result = images_mod.collect_object_images({"logo_image": ["Logo.png"]}, [])
        assert result is not None and result[0]["kind"] == "logo"

    def test_photo_kind_assigned_to_p18_and_pageimage(self, tmp_path, layout):
        _stage_download(tmp_path, "A.jpg")
        _stage_download(tmp_path, "B.jpg")
        result = images_mod.collect_object_images({"image": ["A.jpg"]}, ["B.jpg"])
        assert result is not None
        assert {e["file"]: e["kind"] for e in result} == {
            "A.jpg": "photo",
            "B.jpg": "photo",
        }

    def test_keeps_acceptable_and_drops_rest_in_same_call(self, tmp_path, layout):
        _stage_download(tmp_path, "bad.jpg", license_servable=False)
        _stage_download(tmp_path, "good.jpg", license_servable=True)
        result = images_mod.collect_object_images(
            {"image": ["bad.jpg", "good.jpg"]}, []
        )
        assert result is not None
        assert [e["file"] for e in result] == ["good.jpg"]

    def test_encodes_source_url(self, tmp_path, layout):
        _stage_download(tmp_path, "A_(crop).jpg")
        result = images_mod.collect_object_images({"image": ["A_(crop).jpg"]}, [])
        assert result is not None
        assert (
            result[0]["source_url"]
            == "https://commons.wikimedia.org/wiki/File:A_%28crop%29.jpg"
        )

    def test_entry_has_expected_keys(self, tmp_path, layout):
        _stage_download(tmp_path, "A.jpg")
        result = images_mod.collect_object_images({"image": ["A.jpg"]}, [])
        assert result is not None
        assert set(result[0].keys()) == {"file", "source_url", "kind", "variants"}

    def test_excluded_prefix_silently_dropped(self, tmp_path, layout, caplog):
        caplog.set_level("INFO", logger="space_map_data.export.images")
        result = images_mod.collect_object_images(
            {"image": ["Орбита_астероида_1234.png", "Орбита_кометы_175P.jpg"]}, []
        )
        assert result is None
        assert caplog.records == []


class TestVariantRules:
    """Bucket-selection + conversion rules in _generate_variants.

    Uses real Pillow round-trips because the logic depends on opening the
    source file and checking dimensions / format.
    """

    def _variants(self, tmp_path, filename, width, height, *, bytes_=None):
        if bytes_ is None:
            ext = Path(filename).suffix.lower()
            if ext == ".png":
                bytes_ = _make_source_png(width, height)
            elif ext == ".gif":
                bytes_ = _make_source_animated_gif(width, height)
            else:
                bytes_ = _make_source_jpg(width, height)
        _stage_download(tmp_path, filename, bytes_=bytes_)
        result = images_mod.collect_object_images({"image": [filename]}, [])
        assert result is not None
        return result[0]["variants"]

    def test_source_5000_jpg_yields_three_webp_variants(self, tmp_path, layout):
        # Source > xl: all three buckets are downscaled webp.
        variants = self._variants(tmp_path, "big.jpg", 5000, 2500)
        assert variants == {"s": "webp", "m": "webp", "xl": "webp"}
        bundle = layout["export"] / "big.jpg"
        for label in ("s", "m", "xl"):
            assert (bundle / f"{label}.webp").exists()

    def test_source_2000_jpg_yields_xl_verbatim(self, tmp_path, layout):
        # s and m downscaled; xl keeps source format (no upscale).
        variants = self._variants(tmp_path, "med.jpg", 2000, 1000)
        assert variants == {"s": "webp", "m": "webp", "xl": "jpg"}
        bundle = layout["export"] / "med.jpg"
        assert (bundle / "s.webp").exists()
        assert (bundle / "m.webp").exists()
        assert (bundle / "xl.jpg").exists()
        with Image.open(bundle / "xl.jpg") as xl:
            assert max(xl.size) == 2000

    def test_source_1000_jpg_yields_m_verbatim_no_xl(self, tmp_path, layout):
        variants = self._variants(tmp_path, "small.jpg", 1000, 500)
        assert variants == {"s": "webp", "m": "jpg"}
        bundle = layout["export"] / "small.jpg"
        assert not (bundle / "xl.jpg").exists()
        assert not (bundle / "xl.webp").exists()

    def test_source_400_jpg_yields_only_s_verbatim(self, tmp_path, layout):
        variants = self._variants(tmp_path, "tiny.jpg", 400, 400)
        assert variants == {"s": "jpg"}
        bundle = layout["export"] / "tiny.jpg"
        assert (bundle / "s.jpg").exists()
        assert not (bundle / "m.jpg").exists()
        assert not (bundle / "xl.jpg").exists()

    def test_source_exactly_1024_jpg_stays_verbatim(self, tmp_path, layout):
        # Edge case (a) for lossy sources: stay verbatim even when dim matches
        # the bucket exactly — re-encoding JPEG to webp has no quality win.
        variants = self._variants(tmp_path, "edge.jpg", 1024, 512)
        assert variants == {"s": "webp", "m": "jpg"}

    def test_source_exactly_1024_png_converts_to_webp(self, tmp_path, layout):
        # Lossless sources always go to (lossy) webp — no lossless-webp special
        # case anymore. One lossless→lossy re-encode is equivalent to encoding
        # from the original.
        variants = self._variants(tmp_path, "edge.png", 1024, 512)
        assert variants == {"s": "webp", "m": "webp"}

    def test_source_5000_png_yields_three_webp_variants(self, tmp_path, layout):
        variants = self._variants(tmp_path, "big.png", 5000, 2500)
        assert variants == {"s": "webp", "m": "webp", "xl": "webp"}
        bundle = layout["export"] / "big.png"
        for label in ("s", "m", "xl"):
            assert (bundle / f"{label}.webp").exists()

    def test_source_2000_png_yields_xl_lossy_webp(self, tmp_path, layout):
        # Regression: PNG under the xl bucket used to be copied verbatim,
        # shipping 36 MiB Ganymede PNGs. Now re-encoded to lossy webp.
        variants = self._variants(tmp_path, "med.png", 2000, 1000)
        assert variants == {"s": "webp", "m": "webp", "xl": "webp"}
        bundle = layout["export"] / "med.png"
        assert not (bundle / "xl.png").exists()
        with Image.open(bundle / "xl.webp") as xl:
            assert max(xl.size) == 2000

    def test_source_1000_png_yields_m_lossy_webp_no_xl(self, tmp_path, layout):
        variants = self._variants(tmp_path, "small.png", 1000, 500)
        assert variants == {"s": "webp", "m": "webp"}
        bundle = layout["export"] / "small.png"
        assert not (bundle / "xl.webp").exists()
        assert not (bundle / "xl.png").exists()

    def test_source_400_png_yields_only_s_webp(self, tmp_path, layout):
        variants = self._variants(tmp_path, "tiny.png", 400, 400)
        assert variants == {"s": "webp"}
        bundle = layout["export"] / "tiny.png"
        assert (bundle / "s.webp").exists()
        assert not (bundle / "m.webp").exists()
        assert not (bundle / "s.png").exists()

    def test_animated_gif_2000_yields_avif_variants(self, tmp_path, layout):
        variants = self._variants(tmp_path, "anim.gif", 2000, 1000)
        assert variants == {"s": "avif", "m": "avif", "xl": "avif"}
        bundle = layout["export"] / "anim.gif"
        assert not (bundle / "xl.gif").exists()
        with Image.open(bundle / "xl.avif") as xl:
            assert getattr(xl, "is_animated", False)
            assert getattr(xl, "n_frames", 0) == 3
            assert max(xl.size) == 2000

    def test_animated_gif_400_yields_only_s_avif(self, tmp_path, layout):
        variants = self._variants(
            tmp_path,
            "tiny.gif",
            400,
            400,
            bytes_=_make_source_animated_gif(400, 400, n_frames=2),
        )
        assert variants == {"s": "avif"}
        bundle = layout["export"] / "tiny.gif"
        with Image.open(bundle / "s.avif") as s:
            assert getattr(s, "is_animated", False)
            assert getattr(s, "n_frames", 0) == 2

    def test_svg_served_verbatim_at_xl(self, tmp_path, layout):
        # SVGs are vectors — PIL can't open them and we don't want to. Copy
        # the source to xl.svg and let the frontend's fallback pick it up.
        svg_bytes = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            b'<rect width="10" height="10" fill="red"/></svg>'
        )
        _stage_download(tmp_path, "icon.svg", bytes_=svg_bytes)
        result = images_mod.collect_object_images({"image": ["icon.svg"]}, [])
        assert result is not None
        assert result[0]["variants"] == {"xl": "svg"}
        bundle = layout["export"] / "icon.svg"
        assert (bundle / "xl.svg").read_bytes() == svg_bytes
        assert not (bundle / "s.webp").exists()
        assert not (bundle / "m.webp").exists()

    def test_webm_served_verbatim_at_xl(self, tmp_path, layout):
        # WebM is a video. Browsers don't render it in <img>, but we ship it
        # verbatim so the frontend can pick it up when video support lands.
        webm_bytes = b"\x1aE\xdf\xa3stub-webm-bytes-for-test-purposes-only"
        _stage_download(tmp_path, "clip.webm", bytes_=webm_bytes)
        result = images_mod.collect_object_images({"image": ["clip.webm"]}, [])
        assert result is not None
        assert result[0]["variants"] == {"xl": "webm"}
        assert (layout["export"] / "clip.webm" / "xl.webm").read_bytes() == webm_bytes

    def test_webm_over_size_cap_dropped(self, tmp_path, monkeypatch, layout):
        # Oversize passthrough sources are dropped rather than breaking the
        # Cloudflare Pages deploy.
        monkeypatch.setattr(images_mod, "_PASSTHROUGH_MAX_BYTES", 16)
        _stage_download(tmp_path, "big.webm", bytes_=b"x" * 128)
        result = images_mod.collect_object_images({"image": ["big.webm"]}, [])
        assert result is None
        assert not (layout["export"] / "big.webm" / "xl.webm").exists()

    def test_pdf_source_skipped(self, tmp_path, layout):
        _stage_download(tmp_path, "paper.pdf", bytes_=b"%PDF-1.5\n%stub\n")
        result = images_mod.collect_object_images({"image": ["paper.pdf"]}, [])
        assert result is None
        bundle = layout["export"] / "paper.pdf"
        # No variants written and no metadata committed.
        assert not bundle.exists() or not any(bundle.iterdir())

    def test_truncated_jpeg_still_exported(self, tmp_path, layout):
        # Trim the JPEG's trailing EOI marker so Pillow flags it as truncated.
        # LOAD_TRUNCATED_IMAGES=True at module load must let the decode
        # succeed anyway.
        full = _make_source_jpg(2000, 1000)
        truncated = full[:-2]
        variants = self._variants(tmp_path, "chopped.jpg", 2000, 1000, bytes_=truncated)
        assert variants == {"s": "webp", "m": "webp", "xl": "jpg"}

    def test_mpo_jpeg_treated_as_static(self, tmp_path, layout):
        # Regression: some cameras (and some Commons JPGs like
        # Pléiades_(satellite).jpg) are actually MPO — multi-frame JPEGs.
        # Pillow flags them is_animated=True but iterating frames raises
        # "No data found for frame". They must go through the normal JPG
        # path, not the animated-AVIF path.
        variants = self._variants(
            tmp_path, "stereo.jpg", 2000, 1000, bytes_=_make_source_mpo(2000, 1000)
        )
        assert variants == {"s": "webp", "m": "webp", "xl": "jpg"}
        bundle = layout["export"] / "stereo.jpg"
        assert (bundle / "xl.jpg").exists()
        assert not (bundle / "xl.avif").exists()

    def test_static_gif_falls_through_to_webp(self, tmp_path, layout):
        # Single-frame GIF: the is_animated check drives AVIF, not the .gif
        # extension. A static GIF should be treated like any lossless source.
        variants = self._variants(
            tmp_path,
            "still.gif",
            800,
            600,
            bytes_=_make_source_static_gif(800, 600),
        )
        assert variants == {"s": "webp", "m": "webp"}
        bundle = layout["export"] / "still.gif"
        assert not (bundle / "m.avif").exists()
        assert not (bundle / "m.gif").exists()

    def test_idempotent_on_rerun(self, tmp_path, layout):
        self._variants(tmp_path, "a.jpg", 2000, 1000)
        # metadata.json.gz is the skip marker: second call reads variants from it.
        images_mod.clear_export_cache()
        result = images_mod.collect_object_images({"image": ["a.jpg"]}, [])
        assert result is not None
        assert result[0]["variants"] == {"s": "webp", "m": "webp", "xl": "jpg"}

    def test_stale_bundle_schema_triggers_regeneration(self, tmp_path, layout):
        # Seed a bundle that looks like an old-schema export: stale files and a
        # metadata.json.gz without a `schema` field (pre-v2 layout: PNGs could
        # ship as xl.png).
        bundle = layout["export"] / "stale.png"
        bundle.mkdir(parents=True)
        (bundle / "xl.png").write_bytes(b"stale png bytes")
        (bundle / "metadata.json.gz").write_bytes(
            gzip.compress(orjson.dumps({"variants": {"xl": "png"}}))
        )
        # Stage a current source so regeneration has something to work with.
        _stage_download(tmp_path, "stale.png", width=2000, height=1000)

        result = images_mod.collect_object_images({"image": ["stale.png"]}, [])
        assert result is not None
        assert result[0]["variants"] == {"s": "webp", "m": "webp", "xl": "webp"}
        assert not (bundle / "xl.png").exists()
        assert (bundle / "xl.webp").exists()


class TestMetadataTrimming:
    """Shape of metadata.json.gz written alongside the thumbnails."""

    @pytest.fixture
    def metadata(self, tmp_path, layout):
        _stage_download(
            tmp_path,
            "img.jpg",
            width=800,
            height=400,
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "LicenseUrl": {
                    "value": "https://creativecommons.org/licenses/by-sa/4.0"
                },
                "Artist": {"value": "Jane Doe"},
                "ImageDescription": {
                    "value": {
                        "_type": "lang",
                        "en": "English desc",
                        "fr": "French desc",
                        "pt": "Portuguese desc",  # not in LANGUAGES — should drop
                    }
                },
                "DateTime": {"value": "2024-01-01"},  # frontend doesn't use — dropped
            },
        )
        images_mod.collect_object_images({"image": ["img.jpg"]}, [])
        meta_path = layout["export"] / "img.jpg" / "metadata.json.gz"
        assert meta_path.exists()
        return orjson.loads(gzip.decompress(meta_path.read_bytes()))

    def test_license_block(self, metadata):
        assert metadata["license"] == {
            "name": "CC BY-SA 4.0",
            "url": "https://creativecommons.org/licenses/by-sa/4.0",
        }

    def test_artist_bare_string_passthrough(self, metadata):
        assert metadata["artist"] == "Jane Doe"

    def test_description_trimmed_to_supported_locales(self, metadata):
        assert metadata["description"] == {"en": "English desc", "fr": "French desc"}

    def test_source_url_present(self, metadata):
        assert (
            metadata["source_url"] == "https://commons.wikimedia.org/wiki/File:img.jpg"
        )

    def test_unknown_fields_dropped(self, metadata):
        assert "DateTime" not in metadata
        assert "imageinfo" not in metadata

    def test_variants_embedded(self, metadata):
        # variants.json used to live alongside — now it's in the same blob.
        assert metadata["variants"] == {"s": "webp", "m": "jpg"}

    def test_no_separate_variants_file(self, tmp_path, layout):
        _stage_download(tmp_path, "solo.jpg")
        images_mod.collect_object_images({"image": ["solo.jpg"]}, [])
        assert not (layout["export"] / "solo.jpg" / "variants.json").exists()
