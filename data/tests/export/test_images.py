"""Tests for space_map_data.export.images.

Discovery and best-of-tree selection live in
:mod:`space_map_data.ingest.providers.image_selection` and have their own
tests; here we only exercise the bundle/render side: given a pre-selected
``object_images.json`` entry, does the export produce the right thumbnails
and metadata?
"""

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
    derived_from: list[str] | None = None,
    other_versions: list[str] | None = None,
    sdc_statements: dict | None = None,
) -> None:
    """Populate a fake ``IMAGES_DIR/<filename>/`` entry."""
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
    payload: dict = {
        "filename": filename,
        "fetched_at": "2026-04-24T00:00:00+00:00",
        "imageinfo": {"extmetadata": em},
        "license_servable": license_servable,
    }
    if derived_from is not None:
        payload["derived_from"] = derived_from
    if other_versions is not None:
        payload["other_versions"] = other_versions
    if sdc_statements is not None:
        payload["sdc"] = {"statements": sdc_statements}
    (d / "metadata.json").write_bytes(orjson.dumps(payload))


def _p571(time_str: str, precision: int, *, rank: str = "normal") -> dict:
    """Build a fake SDC P571 (inception) statement."""
    return {
        "mainsnak": {
            "snaktype": "value",
            "property": "P571",
            "datavalue": {
                "value": {"time": time_str, "precision": precision},
                "type": "time",
            },
        },
        "type": "statement",
        "rank": rank,
    }


def _p180(qid: str, *, rank: str = "normal") -> dict:
    """Build a fake SDC P180 (depicts) statement."""
    return {
        "mainsnak": {
            "snaktype": "value",
            "property": "P180",
            "datavalue": {
                "value": {"entity-type": "item", "id": qid},
                "type": "wikibase-entityid",
            },
        },
        "type": "statement",
        "rank": rank,
    }


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


def _collect(entries: list[dict] | str, kind: str = "photo") -> list[dict] | None:
    """Seed the object-images cache and call :func:`collect_object_images`.

    Pass a single filename for the common one-image case, or a list of
    ``{"file", "kind"}`` dicts for the multi-image cases.
    """
    if isinstance(entries, str):
        entries = [{"file": entries, "kind": kind}]
    images_mod._OBJECT_IMAGES_CACHE = {"test-obj": entries}
    return images_mod.collect_object_images("test-obj")


class TestCollectObjectImages:
    """collect_object_images — bundle assembly given a cached selection.

    Selection-side concerns (canonicalization, dedup across sources, kind
    assignment from P18/P154/pageimages) are tested in the image_selection
    ingest module; this class only checks render-time filtering.
    """

    def test_drops_when_source_missing(self, tmp_path, layout):
        _stage_download(tmp_path, "A.jpg", missing_source=True)
        assert _collect("A.jpg") is None

    def test_drops_when_download_metadata_missing(self, tmp_path, layout):
        # Stage only source.jpg, no metadata.json.
        d = layout["downloads"] / "A.jpg"
        d.mkdir(parents=True)
        (d / "source.jpg").write_bytes(_make_source_jpg(4, 4))
        assert _collect("A.jpg") is None

    def test_drops_non_servable(self, tmp_path, layout):
        _stage_download(tmp_path, "A.jpg", license_servable=False)
        assert _collect("A.jpg") is None

    def test_keeps_servable_drops_non_servable_in_same_call(self, tmp_path, layout):
        _stage_download(tmp_path, "bad.jpg", license_servable=False)
        _stage_download(tmp_path, "good.jpg", license_servable=True)
        result = _collect(
            [
                {"file": "bad.jpg", "kind": "photo"},
                {"file": "good.jpg", "kind": "photo"},
            ]
        )
        assert result is not None
        assert [e["file"] for e in result] == ["good.jpg"]

    def test_encodes_source_url(self, tmp_path, layout):
        _stage_download(tmp_path, "A_(crop).jpg")
        result = _collect("A_(crop).jpg")
        assert result is not None
        assert (
            result[0]["source_url"]
            == "https://commons.wikimedia.org/wiki/File:A_%28crop%29.jpg"
        )

    def test_kind_passes_through_from_cache_entry(self, tmp_path, layout):
        _stage_download(tmp_path, "Logo.png")
        result = _collect("Logo.png", kind="logo")
        assert result is not None and result[0]["kind"] == "logo"

    def test_entry_has_expected_keys(self, tmp_path, layout):
        _stage_download(tmp_path, "A.jpg")
        result = _collect("A.jpg")
        assert result is not None
        assert set(result[0].keys()) == {
            "file",
            "source_url",
            "kind",
            "variants",
            "width",
            "height",
        }
        assert result[0]["width"] == 4
        assert result[0]["height"] == 4

    def test_excluded_prefix_silently_dropped(self, tmp_path, layout, caplog):
        # Defensive: even if an excluded-prefix filename leaks into the cache,
        # the render side filters it out without noisy logging.
        caplog.set_level("INFO", logger="space_map_data.export.images")
        result = _collect(
            [
                {"file": "Орбита_астероида_1234.png", "kind": "photo"},
                {"file": "Орбита_кометы_175P.jpg", "kind": "photo"},
            ]
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
        result = _collect(filename)
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
        result = _collect("icon.svg")
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
        result = _collect("clip.webm")
        assert result is not None
        assert result[0]["variants"] == {"xl": "webm"}
        assert (layout["export"] / "clip.webm" / "xl.webm").read_bytes() == webm_bytes

    def test_webm_over_size_cap_dropped(self, tmp_path, monkeypatch, layout):
        # Oversize passthrough sources are dropped rather than breaking the
        # Cloudflare Pages deploy.
        monkeypatch.setattr(images_mod, "_PASSTHROUGH_MAX_BYTES", 16)
        _stage_download(tmp_path, "big.webm", bytes_=b"x" * 128)
        result = _collect("big.webm")
        assert result is None
        assert not (layout["export"] / "big.webm" / "xl.webm").exists()

    def test_pdf_source_skipped(self, tmp_path, layout):
        _stage_download(tmp_path, "paper.pdf", bytes_=b"%PDF-1.5\n%stub\n")
        result = _collect("paper.pdf")
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
        result = _collect("a.jpg")
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

        result = _collect("stale.png")
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
                        "nl": "Dutch desc",  # not in LANGUAGES — should drop
                    }
                },
                "DateTime": {"value": "2024-01-01"},  # frontend doesn't use — dropped
            },
        )
        _collect("img.jpg")
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
        _collect("solo.jpg")
        assert not (layout["export"] / "solo.jpg" / "variants.json").exists()


class TestTreeMetadataAggregation:
    """Aggregation of artist/description across the chosen file's tree.

    The chosen file's metadata is the default; tree members reachable via
    ``derived_from``/``other_versions`` provide fallbacks (per-locale for
    multilang dicts). License stays tied to the chosen file because it
    describes the bytes we serve.
    """

    def _read_metadata(self, layout, filename: str) -> dict:
        path = layout["export"] / filename / "metadata.json.gz"
        return orjson.loads(gzip.decompress(path.read_bytes()))

    def test_description_per_locale_fallback(self, tmp_path, layout):
        # Chosen image has English; derivative has French. Both should land
        # in the merged description.
        _stage_download(
            tmp_path,
            "Original.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "ImageDescription": {"value": {"_type": "lang", "en": "English desc"}},
            },
            derived_from=["Crop.jpg"],
        )
        _stage_download(
            tmp_path,
            "Crop.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "ImageDescription": {
                    "value": {"_type": "lang", "fr": "Description française"}
                },
            },
        )
        _collect("Original.jpg")
        meta = self._read_metadata(layout, "Original.jpg")
        assert meta["description"] == {
            "en": "English desc",
            "fr": "Description française",
        }

    def test_chosen_file_wins_per_locale(self, tmp_path, layout):
        # Both have an English description — the chosen file's value wins.
        _stage_download(
            tmp_path,
            "Original.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "ImageDescription": {"value": {"_type": "lang", "en": "Chosen desc"}},
            },
            derived_from=["Crop.jpg"],
        )
        _stage_download(
            tmp_path,
            "Crop.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "ImageDescription": {
                    "value": {"_type": "lang", "en": "Crop desc", "fr": "Crop fr"}
                },
            },
        )
        _collect("Original.jpg")
        meta = self._read_metadata(layout, "Original.jpg")
        assert meta["description"] == {"en": "Chosen desc", "fr": "Crop fr"}

    def test_artist_falls_back_when_chosen_missing(self, tmp_path, layout):
        # Chosen file has no Artist/Credit; derivative does — use the derivative.
        _stage_download(
            tmp_path,
            "Original.jpg",
            extmetadata={"LicenseShortName": {"value": "CC BY-SA 4.0"}},
            derived_from=["Crop.jpg"],
        )
        _stage_download(
            tmp_path,
            "Crop.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "Artist": {"value": "Jane Doe"},
            },
        )
        _collect("Original.jpg")
        meta = self._read_metadata(layout, "Original.jpg")
        assert meta["artist"] == "Jane Doe"

    def test_chosen_artist_wins_over_fallback(self, tmp_path, layout):
        _stage_download(
            tmp_path,
            "Original.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "Artist": {"value": "Jane Doe"},
            },
            derived_from=["Crop.jpg"],
        )
        _stage_download(
            tmp_path,
            "Crop.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "Artist": {"value": "John Smith"},
            },
        )
        _collect("Original.jpg")
        meta = self._read_metadata(layout, "Original.jpg")
        assert meta["artist"] == "Jane Doe"

    def test_license_does_not_aggregate(self, tmp_path, layout):
        # License describes the bytes we serve; a derivative's license must
        # not bleed onto the chosen file.
        _stage_download(
            tmp_path,
            "Original.jpg",
            extmetadata={"LicenseShortName": {"value": "CC BY-SA 4.0"}},
            derived_from=["Crop.jpg"],
        )
        _stage_download(
            tmp_path,
            "Crop.jpg",
            extmetadata={
                "LicenseShortName": {"value": "Public domain"},
                "Artist": {"value": "Someone"},
            },
        )
        _collect("Original.jpg")
        meta = self._read_metadata(layout, "Original.jpg")
        assert meta["license"]["name"] == "CC BY-SA 4.0"

    def test_walks_via_other_versions(self, tmp_path, layout):
        # Sibling reached via other_versions (not derived_from) still
        # contributes its description.
        _stage_download(
            tmp_path,
            "Original.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "ImageDescription": {"value": {"_type": "lang", "en": "Eng"}},
            },
            other_versions=["Sibling.jpg"],
        )
        _stage_download(
            tmp_path,
            "Sibling.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "ImageDescription": {"value": {"_type": "lang", "fr": "Fra"}},
            },
        )
        _collect("Original.jpg")
        meta = self._read_metadata(layout, "Original.jpg")
        assert meta["description"] == {"en": "Eng", "fr": "Fra"}

    def test_closer_derivative_wins_over_distant(self, tmp_path, layout):
        # BFS order: Original -> Near (depth 1) -> Far (depth 2). When both
        # Near and Far have a French description that the chosen file lacks,
        # Near should win.
        _stage_download(
            tmp_path,
            "Original.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "ImageDescription": {"value": {"_type": "lang", "en": "Eng"}},
            },
            derived_from=["Near.jpg"],
        )
        _stage_download(
            tmp_path,
            "Near.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "ImageDescription": {"value": {"_type": "lang", "fr": "Near fr"}},
            },
            derived_from=["Far.jpg"],
        )
        _stage_download(
            tmp_path,
            "Far.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "ImageDescription": {"value": {"_type": "lang", "fr": "Far fr"}},
            },
        )
        _collect("Original.jpg")
        meta = self._read_metadata(layout, "Original.jpg")
        assert meta["description"] == {"en": "Eng", "fr": "Near fr"}

    def test_missing_tree_member_metadata_skipped(self, tmp_path, layout):
        # Tree references a file we never downloaded. Don't crash; just
        # use what we have.
        _stage_download(
            tmp_path,
            "Original.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "ImageDescription": {"value": {"_type": "lang", "en": "Eng"}},
            },
            derived_from=["NeverDownloaded.jpg"],
        )
        _collect("Original.jpg")
        meta = self._read_metadata(layout, "Original.jpg")
        assert meta["description"] == {"en": "Eng"}


class TestDateExtraction:
    """Date is sourced from SDC P571 (precision-aware) with extmetadata fallback."""

    def _read_metadata(self, layout, filename: str) -> dict:
        path = layout["export"] / filename / "metadata.json.gz"
        return orjson.loads(gzip.decompress(path.read_bytes()))

    def test_p571_day_precision(self, tmp_path, layout):
        _stage_download(
            tmp_path,
            "img.jpg",
            sdc_statements={"P571": [_p571("+2009-10-05T00:00:00Z", 11)]},
        )
        _collect("img.jpg")
        assert self._read_metadata(layout, "img.jpg")["date"] == "2009-10-05"

    def test_p571_month_precision_truncates(self, tmp_path, layout):
        _stage_download(
            tmp_path,
            "img.jpg",
            sdc_statements={"P571": [_p571("+2009-10-05T00:00:00Z", 10)]},
        )
        _collect("img.jpg")
        assert self._read_metadata(layout, "img.jpg")["date"] == "2009-10"

    def test_p571_year_precision_truncates(self, tmp_path, layout):
        _stage_download(
            tmp_path,
            "img.jpg",
            sdc_statements={"P571": [_p571("+2009-10-05T00:00:00Z", 9)]},
        )
        _collect("img.jpg")
        assert self._read_metadata(layout, "img.jpg")["date"] == "2009"

    def test_p571_decade_precision_falls_back_to_datetime_original(
        self, tmp_path, layout
    ):
        # P571 at decade precision isn't useful as a date string, so we
        # treat it as absent and let the more granular DateTimeOriginal
        # win — EXIF dates are typically far more precise than a hand-
        # tagged "1960s"-ish SDC entry.
        _stage_download(
            tmp_path,
            "img.jpg",
            sdc_statements={"P571": [_p571("+2000-01-01T00:00:00Z", 8)]},
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "DateTimeOriginal": {"value": "2009-10-05"},
            },
        )
        _collect("img.jpg")
        assert self._read_metadata(layout, "img.jpg")["date"] == "2009-10-05"

    def test_p571_decade_precision_alone_drops_date(self, tmp_path, layout):
        # P571 too coarse and no DateTimeOriginal fallback: emit no date.
        _stage_download(
            tmp_path,
            "img.jpg",
            sdc_statements={"P571": [_p571("+2000-01-01T00:00:00Z", 8)]},
        )
        _collect("img.jpg")
        assert "date" not in self._read_metadata(layout, "img.jpg")

    def test_falls_back_to_datetime_original(self, tmp_path, layout):
        _stage_download(
            tmp_path,
            "img.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "DateTimeOriginal": {"value": "2012-09-23 16:26:36"},
            },
        )
        _collect("img.jpg")
        assert self._read_metadata(layout, "img.jpg")["date"] == "2012-09-23"

    def test_datetime_original_year_only(self, tmp_path, layout):
        _stage_download(
            tmp_path,
            "img.jpg",
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "DateTimeOriginal": {"value": "1999"},
            },
        )
        _collect("img.jpg")
        assert self._read_metadata(layout, "img.jpg")["date"] == "1999"

    def test_no_date_when_neither_source_available(self, tmp_path, layout):
        _stage_download(tmp_path, "img.jpg")
        _collect("img.jpg")
        assert "date" not in self._read_metadata(layout, "img.jpg")

    def test_tree_fallback_when_chosen_lacks_date(self, tmp_path, layout):
        _stage_download(tmp_path, "Original.jpg", derived_from=["Crop.jpg"])
        _stage_download(
            tmp_path,
            "Crop.jpg",
            sdc_statements={"P571": [_p571("+2008-01-30T00:00:00Z", 11)]},
        )
        _collect("Original.jpg")
        assert self._read_metadata(layout, "Original.jpg")["date"] == "2008-01-30"

    def test_chosen_date_wins_over_tree(self, tmp_path, layout):
        _stage_download(
            tmp_path,
            "Original.jpg",
            sdc_statements={"P571": [_p571("+2008-01-30T00:00:00Z", 11)]},
            derived_from=["Crop.jpg"],
        )
        _stage_download(
            tmp_path,
            "Crop.jpg",
            sdc_statements={"P571": [_p571("+2020-06-01T00:00:00Z", 11)]},
        )
        _collect("Original.jpg")
        assert self._read_metadata(layout, "Original.jpg")["date"] == "2008-01-30"


class TestDepictsExtraction:
    """Depicts is a list of QIDs from SDC P180."""

    def _read_metadata(self, layout, filename: str) -> dict:
        path = layout["export"] / filename / "metadata.json.gz"
        return orjson.loads(gzip.decompress(path.read_bytes()))

    def test_depicts_qids_extracted(self, tmp_path, layout):
        _stage_download(
            tmp_path,
            "img.jpg",
            sdc_statements={"P180": [_p180("Q405"), _p180("Q111")]},
        )
        _collect("img.jpg")
        assert self._read_metadata(layout, "img.jpg")["depicts"] == ["Q405", "Q111"]

    def test_depicts_dedupes(self, tmp_path, layout):
        _stage_download(
            tmp_path,
            "img.jpg",
            sdc_statements={"P180": [_p180("Q405"), _p180("Q405")]},
        )
        _collect("img.jpg")
        assert self._read_metadata(layout, "img.jpg")["depicts"] == ["Q405"]

    def test_depicts_skips_deprecated(self, tmp_path, layout):
        _stage_download(
            tmp_path,
            "img.jpg",
            sdc_statements={"P180": [_p180("Q405", rank="deprecated"), _p180("Q111")]},
        )
        _collect("img.jpg")
        assert self._read_metadata(layout, "img.jpg")["depicts"] == ["Q111"]

    def test_no_depicts_when_absent(self, tmp_path, layout):
        _stage_download(tmp_path, "img.jpg")
        _collect("img.jpg")
        assert "depicts" not in self._read_metadata(layout, "img.jpg")

    def test_chosen_depicts_wins_over_tree(self, tmp_path, layout):
        # A crop may have its own framing; once the chosen file declares
        # depicts at all, we don't merge in the derivative's list.
        _stage_download(
            tmp_path,
            "Original.jpg",
            sdc_statements={"P180": [_p180("Q405")]},
            derived_from=["Crop.jpg"],
        )
        _stage_download(
            tmp_path,
            "Crop.jpg",
            sdc_statements={"P180": [_p180("Q111"), _p180("Q525")]},
        )
        _collect("Original.jpg")
        assert self._read_metadata(layout, "Original.jpg")["depicts"] == ["Q405"]

    def test_tree_depicts_fills_when_chosen_empty(self, tmp_path, layout):
        _stage_download(tmp_path, "Original.jpg", derived_from=["Crop.jpg"])
        _stage_download(
            tmp_path,
            "Crop.jpg",
            sdc_statements={"P180": [_p180("Q111")]},
        )
        _collect("Original.jpg")
        assert self._read_metadata(layout, "Original.jpg")["depicts"] == ["Q111"]
