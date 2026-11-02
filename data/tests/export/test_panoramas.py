"""Which cached panorama products reach the export, and in what shape."""

import errno
import gzip
import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np
import orjson
import pytest
from PIL import Image

from space_map_data.export import panoramas
from space_map_data.export.objects.writer import hash_bucket

MARS = "naif-499"


def _product(**overrides) -> dict:
    base = {
        "id": "perseverance-sol2",
        "body_id": MARS,
        "mission": "perseverance",
        "instrument": "Navcam",
        "sol": 2,
        "start_time": "2021-02-20T21:48:15.029Z",
        "stop_time": "2021-02-20T22:06:31.743Z",
        "position": {"latitude": 18.44, "longitude": 77.45, "elevation_m": -2569.9},
        "image": "panorama.webp",
        "preview": "preview.webp",
        "north_azimuth_offset_deg": 0,
        "source_coverage": {"azimuth_start_deg": 67.2},
        "coverage": {"horizontal_degrees": 352.9, "sphere_percent": 15.7},
        "color": "rgb",
        "credit": "Courtesy NASA/JPL-Caltech",
        "reuse_policy_url": "https://www.jpl.nasa.gov/jpl-image-use-policy/",
        "sources": {"label_url": "https://example.test/label.xml"},
    }
    return {**base, **overrides}


def _write_cache(root: Path, collection: str, products: list[dict]) -> None:
    items = []
    for product in products:
        folder = root / collection / product["id"]
        folder.mkdir(parents=True)
        (folder / "metadata.json").write_text(json.dumps(product))
        # A product may name the sphere it carries, so two of them can be given
        # the same bytes the way the archive delivers one mosaic twice.
        sphere = product.get("sphere", product["id"])
        shade = tuple(hashlib.sha256(sphere.encode()).digest()[:3])
        Image.new("RGB", (64, 32), shade).save(folder / "panorama.webp", lossless=True)
        Image.new("RGBA", (1536, 396)).save(folder / "preview.webp")
        items.append(
            {
                "id": product["id"],
                "metadata": f"{collection}/{product['id']}/metadata.json",
            }
        )
    (root / collection / "catalog.json").write_text(json.dumps({"panoramas": items}))


class TestSelection:
    """A product exports once it can be placed and dated; how well its
    geometry and north are known travels with it."""

    def test_complete_product_exports(self, tmp_path: Path):
        _write_cache(tmp_path, "perseverance", [_product()])
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry == {
            "id": "perseverance-sol2",
            "mission": "perseverance",
            "instrument": "Navcam",
            "sol": 2,
            "time": "2021-02-20T21:48:15Z",
            "time_end": "2021-02-20T22:06:31Z",
            "lat": 18.44,
            "lon": 77.45,
            "elevation_m": -2569.9,
            "north_offset_deg": 0,
            "azimuth_start_deg": 67.2,
            "hfov_deg": 352.9,
            "sphere_percent": 15.7,
            "horizon_deg": 360.0,
            "color": "rgb",
            "credit": "Courtesy NASA/JPL-Caltech",
            "credit_url": "https://www.jpl.nasa.gov/jpl-image-use-policy/",
            "source_url": "https://example.test/label.xml",
        }
        folder = tmp_path / "perseverance" / "perseverance-sol2"
        assert product.image == folder / "panorama.webp"
        assert product.preview == folder / "preview.webp"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"body_id": None},
            {"position": None},
            {"image": None},
            {"start_time": "", "capture_time": None},
        ],
        ids=[
            "no body",
            "no position",
            "flat only",
            "undated",
        ],
    )
    def test_unplaceable_product_stays_local(self, tmp_path: Path, overrides: dict):
        _write_cache(tmp_path, "perseverance", [_product(**overrides)])
        assert panoramas.load_panoramas(tmp_path) == {}

    def test_a_texture_keeping_its_coordinate_grid_is_exported_and_marked(
        self, tmp_path: Path
    ):
        """Lower quality is worth having on the map, but must stay tellable."""
        _write_cache(
            tmp_path,
            "perseverance",
            [_product(coverage={"includes_source_grid": True})],
        )
        (entry,) = panoramas.load_panoramas(tmp_path)["naif-499"]

        assert entry.entry["source_grid"] is True

    def test_a_source_awaiting_reuse_permission_stays_local(self, tmp_path: Path):
        """Processed and kept, but never published until the terms are settled:
        a stop with no sphere to open would be a traverse nobody can enter."""
        _write_cache(
            tmp_path,
            "perseverance",
            [_product(reuse={"status": panoramas.REUSE_WITHHELD})],
        )
        assert panoramas.load_panoramas(tmp_path) == {}

    def test_an_editorial_only_release_exports_its_sphere_marked(self, tmp_path: Path):
        """ESA's standard terms allow the sphere on an educational page and not
        a commercial one, so it publishes with the tier a reader can gate on."""
        _write_cache(
            tmp_path,
            "huygens",
            [_product(reuse={"status": "educational-editorial-informational-only"})],
        )
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["distribution"] == "non-commercial"
        assert product.image is not None

    def test_a_product_stating_nothing_about_reuse_is_unaffected(self, tmp_path: Path):
        _write_cache(tmp_path, "perseverance", [_product(reuse=None)])
        assert panoramas.load_panoramas(tmp_path)["naif-499"]

    def test_a_withheld_release_stays_local_without_a_reuse_field(self, tmp_path: Path):
        """Reuse belongs to the release, so a product written before the terms
        were recorded must not publish on its own silence."""
        _write_cache(
            tmp_path,
            "yutu-2",
            [_product(id="yutu-2-sol1", mission="yutu-2", reuse=None)],
        )
        assert panoramas.load_panoramas(tmp_path) == {}

    def test_a_clean_texture_is_not_marked(self, tmp_path: Path):
        _write_cache(tmp_path, "perseverance", [_product()])
        (entry,) = panoramas.load_panoramas(tmp_path)["naif-499"]

        assert "source_grid" not in entry.entry

    @pytest.mark.parametrize(
        "overrides",
        [{"grid_geometry_status": "estimated"}, {"geometry_status": "estimated"}],
        ids=["grid fit", "strip fit"],
    )
    def test_fitted_geometry_exports_marked(self, tmp_path: Path, overrides: dict):
        _write_cache(tmp_path, "perseverance", [_product(**overrides)])
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["geometry"] == "estimated"

    def test_unknown_north_exports_without_a_heading(self, tmp_path: Path):
        _write_cache(
            tmp_path,
            "perseverance",
            [_product(north_azimuth_offset_deg=None, orientation_status="unknown")],
        )
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["orientation"] == "unknown"
        assert product.entry["north_offset_deg"] == 0

    def test_established_north_records_how(self, tmp_path: Path):
        _write_cache(
            tmp_path,
            "perseverance",
            [_product(orientation_status="matched to an archival sphere")],
        )
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["orientation"] == "matched to an archival sphere"

    def test_a_view_from_the_air_reports_its_altitude(self, tmp_path: Path):
        _write_cache(tmp_path, "perseverance", [_product(observer_altitude_m=10000)])
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["altitude_m"] == 10000

    def test_archival_geometry_and_north_say_nothing(self, tmp_path: Path):
        _write_cache(tmp_path, "perseverance", [_product()])
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert "orientation" not in product.entry
        assert "geometry" not in product.entry
        assert "altitude_m" not in product.entry

    def test_capture_time_stands_in_for_start_time(self, tmp_path: Path):
        _write_cache(
            tmp_path,
            "moon",
            [_product(start_time=None, stop_time=None, capture_time="1969-07-21")],
        )
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["time"] == "1969-07-21"
        assert "time_end" not in product.entry

    def test_a_missing_cache_refuses_rather_than_publishing_none(self, tmp_path: Path):
        """The cache lives on a mount, so absence means unmounted far more often
        than emptied on purpose, and publishing none deletes every panorama."""
        with pytest.raises(FileNotFoundError, match="would delete"):
            panoramas.load_panoramas(tmp_path / "absent")

    def test_an_empty_cache_still_publishes_none(self, tmp_path: Path):
        """Deleting every panorama stays possible, but has to be asked for."""
        (tmp_path / "empty").mkdir()
        assert panoramas.load_panoramas(tmp_path / "empty") == {}


def _sphere(root: Path, collection: str) -> Path:
    return root / collection / "perseverance-sol2" / "panorama.webp"


def _half_turn() -> bytes:
    """A whole-frame WebP that holds half a turn of opaque pixels."""
    rgba = np.zeros((360, 720, 4), dtype=np.uint8)
    rgba[60:250, :360] = 255
    out = io.BytesIO()
    Image.fromarray(rgba).save(out, "WEBP", lossless=True)
    return out.getvalue()


def _mask(top: float, bottom: float, turn: float = 1.0) -> np.ndarray:
    """A sphere showing `top` to `bottom` degrees of elevation over `turn` of
    the azimuths, at the texel size the export reads."""
    shown = np.zeros((720, 1440), dtype=bool)
    shown[int((90 - top) * 4) : int((90 - bottom) * 4), : int(1440 * turn)] = True
    return shown


class TestHorizon:
    """How much of the horizon a sphere's pixels show, whatever its frame."""

    def test_a_full_turn_reads_360(self):
        assert panoramas.horizon_degrees(_mask(10, -40)) == 360

    def test_a_partial_turn_reads_its_width(self):
        assert panoramas.horizon_degrees(_mask(10, -40, 0.5)) == 180

    @pytest.mark.parametrize(
        ("top", "bottom"), [(20, -6), (8, -7), (1, -15)], ids=["high", "thin", "low"]
    )
    def test_a_strip_across_the_horizon_counts(self, top: float, bottom: float):
        assert panoramas.horizon_degrees(_mask(top, bottom)) == 360

    @pytest.mark.parametrize(
        ("top", "bottom"), [(-25, -74), (-5, -40), (30, 10)], ids=["low", "near", "sky"]
    )
    def test_a_ring_off_the_horizon_reads_zero(self, top: float, bottom: float):
        assert panoramas.horizon_degrees(_mask(top, bottom)) == 0

    def test_a_view_stopping_at_its_horizon_counts(self):
        """Many masks take the sky away, and leave the edge a hair under it."""
        assert panoramas.horizon_degrees(_mask(-0.25, -40)) == 360

    def test_a_small_step_is_not_a_tilt(self):
        """A step fits a sine well in degrees, and poorly for its size."""
        shown = _mask(10, -40, 0.5) | (_mask(-5, -40) & ~_mask(90, -90, 0.5))
        assert panoramas.horizon_degrees(shown) == 180

    def test_only_azimuths_that_reach_the_horizon_count(self):
        """Half a view and half a ring of ground is half a horizon."""
        shown = _mask(10, -40, 0.5) | (_mask(-25, -70) & ~_mask(90, -90, 0.5))
        assert panoramas.horizon_degrees(shown) == 180

    def test_a_little_view_over_a_ring_counts_for_what_it_shows(self):
        shown = _mask(10, -40, 0.25) | (_mask(-25, -70) & ~_mask(90, -90, 0.25))
        assert panoramas.horizon_degrees(shown) == 90

    def test_a_gap_at_the_horizon_is_no_view_of_it(self):
        assert panoramas.horizon_degrees(_mask(60, 40) | _mask(-40, -60)) == 0

    def test_a_tilted_horizon_counts_all_the_way_round(self):
        """A rover on a slope sees the level far outside the view at the
        crests of its horizon's wave."""
        shown = np.zeros((720, 1440), dtype=bool)
        for x in range(1440):
            top = 360 - 20 * 4 * np.sin((x + 0.5) / 1440 * 2 * np.pi)
            shown[int(top) - 40 : int(top) + 200, x] = True
        assert panoramas.horizon_degrees(shown) == 360

    def test_stray_frames_are_not_a_view(self):
        shown = _mask(10, -40, 0.5)
        shown[360:368, 1000:1100] = True
        assert panoramas.horizon_degrees(shown) == 180

    def test_a_grid_line_is_not_a_view(self):
        shown = _mask(10, -40, 0.5)
        shown[360, :] = True
        assert panoramas.horizon_degrees(shown) == 180

    def test_a_hole_under_the_horizon_takes_nothing_from_it(self):
        """A notch of the mosaic leaves the view above it a short run."""
        shown = _mask(10, -60)
        shown[400:420, 600:700] = False
        assert panoramas.horizon_degrees(shown) == 360

    def test_an_empty_mask_reads_zero(self):
        assert panoramas.horizon_degrees(np.zeros((720, 1440), dtype=bool)) == 0

    def test_transparent_pixels_of_a_texture_do_not_count(self, tmp_path: Path):
        """The frame is whole, as InSight's is: only alpha tells."""
        _write_cache(tmp_path, "insight", [_product()])
        _sphere(tmp_path, "insight").write_bytes(_half_turn())
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["horizon_deg"] == 180

    @pytest.mark.parametrize("keep", [0, 0.01, 0.5], ids=["empty", "header", "cut"])
    def test_a_sphere_with_no_image_is_not_exported(self, tmp_path: Path, keep: float):
        _write_cache(
            tmp_path, "perseverance", [_product(), _product(id="whole", sol=3)]
        )
        path = _sphere(tmp_path, "perseverance")
        sphere = _half_turn()
        path.write_bytes(sphere[: int(len(sphere) * keep)])
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["id"] == "whole"

    def test_a_body_left_with_no_image_is_left_out(self, tmp_path: Path):
        _write_cache(tmp_path, "perseverance", [_product()])
        _sphere(tmp_path, "perseverance").write_bytes(b"")
        assert panoramas.load_panoramas(tmp_path) == {}

    def test_a_measure_is_kept_for_the_same_sphere(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        _write_cache(tmp_path, "perseverance", [_product()])
        panoramas.load_panoramas(tmp_path)

        def fail(_: Path) -> float:
            raise AssertionError("measured twice")

        monkeypatch.setattr(panoramas, "_sphere_horizon", fail)
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["horizon_deg"] == 360

    def test_a_changed_sphere_is_measured_again(self, tmp_path: Path):
        _write_cache(tmp_path, "perseverance", [_product()])
        panoramas.load_panoramas(tmp_path)
        _sphere(tmp_path, "perseverance").write_bytes(_half_turn())
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["horizon_deg"] == 180

    def test_a_failed_read_stops_the_run_and_is_not_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A passing mount error must not mark a good sphere as no image."""
        _write_cache(tmp_path, "perseverance", [_product()])

        def fail(*_: object) -> None:
            raise OSError(errno.EIO, "Input/output error")

        with monkeypatch.context() as patch:
            patch.setattr(panoramas.Image, "open", fail)
            with pytest.raises(OSError, match="Input/output"):
                panoramas.load_panoramas(tmp_path)
        assert panoramas._load_horizons() == {}

    def test_a_sphere_gone_from_disk_is_named(self, tmp_path: Path):
        _write_cache(tmp_path, "perseverance", [_product()])
        _sphere(tmp_path, "perseverance").unlink()
        with pytest.raises(FileNotFoundError, match="panorama.webp"):
            panoramas.load_panoramas(tmp_path)

    @pytest.mark.parametrize("content", [b"[]", b"null", b"not json"])
    def test_a_bad_memo_is_an_empty_one(self, content: bytes):
        panoramas._HORIZON_CACHE_PATH.write_bytes(content)
        assert panoramas._load_horizons() == {}

    def test_a_write_keeps_what_another_checkout_measured(self):
        panoramas._write_horizons({"theirs": 360.0})
        panoramas._write_horizons({"ours": 0.0})
        assert panoramas._load_horizons() == {"theirs": 360.0, "ours": 0.0}


class TestDedupe:
    """One mosaic delivered under two product names ships once."""

    def test_the_same_sphere_twice_is_kept_once(self, tmp_path: Path):
        _write_cache(
            tmp_path,
            "p",
            [_product(id="left", sphere="one"), _product(id="right", sphere="one")],
        )
        [product] = panoramas.load_panoramas(tmp_path)[MARS]
        assert product.entry["id"] == "left"


class TestOrder:
    """Entries are grouped by mission and follow the traverse in time."""

    def test_sorted_by_mission_then_time(self, tmp_path: Path):
        _write_cache(
            tmp_path,
            "mixed",
            [
                _product(id="p-late", start_time="2021-03-01T00:00:00Z"),
                _product(
                    id="c-any", mission="curiosity", start_time="2012-09-01T00:00:00Z"
                ),
                _product(id="p-early", start_time="2021-02-20T00:00:00Z"),
            ],
        )
        entries = panoramas.load_panoramas(tmp_path)[MARS]
        assert [p.entry["id"] for p in entries] == ["c-any", "p-early", "p-late"]

    def test_no_mission_sorts_first(self, tmp_path: Path):
        _write_cache(
            tmp_path,
            "loose",
            [
                _product(id="p"),
                _product(id="lone", mission=None, start_time="2021-03-01T00:00:00Z"),
            ],
        )
        entries = panoramas.load_panoramas(tmp_path)[MARS]
        assert [p.entry["id"] for p in entries] == ["lone", "p"]
        assert "mission" not in entries[0].entry


class TestAdditiveRun:
    """`--only panoramas` copies textures and patches the body's bundle in place."""

    def test_assets_and_bundle(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        cache = tmp_path / "derived"
        _write_cache(cache, "perseverance", [_product()])
        monkeypatch.setattr(
            panoramas, "_cached", lambda: panoramas.load_panoramas(cache)
        )

        out_dir = tmp_path / "v1"
        bucket = hash_bucket(MARS, 3)
        bundle_path = out_dir / "objects" / "__global__" / f"{bucket}.json.gz"
        bundle_path.parent.mkdir(parents=True)
        bundle_path.write_bytes(
            gzip.compress(orjson.dumps({MARS: {"id": MARS, "name": "Mars"}}))
        )
        (out_dir / "metadata.json").write_bytes(
            orjson.dumps(
                {"object_bundles": {"global": 3}, "versions": {"objects": "0"}}
            )
        )

        (out_dir / "panoramas").mkdir()
        (out_dir / "panoramas" / "gone.webp").write_bytes(b"old")
        panoramas.write_panorama_assets(out_dir)
        panoramas._patch_global_bundles(out_dir)

        assert not (out_dir / "panoramas" / "gone.webp").exists()

        assert (out_dir / "panoramas" / "perseverance-sol2.webp").read_bytes() == (
            _sphere(cache, "perseverance").read_bytes()
        )
        with Image.open(out_dir / "panoramas" / "perseverance-sol2-preview.webp") as im:
            assert im.size == (512, 132)
        bundle = orjson.loads(gzip.decompress(bundle_path.read_bytes()))
        assert bundle[MARS]["name"] == "Mars"
        assert [p["id"] for p in bundle[MARS]["panoramas"]] == ["perseverance-sol2"]

    def test_regenerated_preview_replaces_thumbnail(self, tmp_path: Path, monkeypatch):
        cache = tmp_path / "derived"
        _write_cache(cache, "perseverance", [_product()])
        monkeypatch.setattr(
            panoramas, "_cached", lambda: panoramas.load_panoramas(cache)
        )
        out_dir = tmp_path / "v1"
        panoramas.write_panorama_assets(out_dir)
        thumb = out_dir / "panoramas" / "perseverance-sol2-preview.webp"
        before = thumb.stat().st_mtime

        source = cache / "perseverance" / "perseverance-sol2" / "preview.webp"
        Image.new("RGBA", (1024, 396)).save(source)
        os.utime(source, (before + 60, before + 60))
        panoramas.write_panorama_assets(out_dir)
        with Image.open(thumb) as im:
            assert im.size == (512, 198)

    def test_body_that_lost_its_panoramas_is_cleared(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(panoramas, "_cached", dict)
        out_dir = tmp_path / "v1"
        bundle_path = out_dir / "objects" / "__global__" / "0.json.gz"
        bundle_path.parent.mkdir(parents=True)
        bundle_path.write_bytes(
            gzip.compress(
                orjson.dumps({MARS: {"id": MARS, "panoramas": [{"id": "x"}]}})
            )
        )
        panoramas._patch_global_bundles(out_dir)
        bundle = orjson.loads(gzip.decompress(bundle_path.read_bytes()))
        assert "panoramas" not in bundle[MARS]


class TestIndex:
    """`v1/panoramas.json`, which the gallery reads to know what exists."""

    def test_missions_carry_their_span(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        cache = tmp_path / "derived"
        _write_cache(
            cache,
            "mars",
            [
                _product(id="early", start_time="2021-02-20T21:48:15Z"),
                _product(
                    id="late",
                    start_time="2022-12-26T20:56:23Z",
                    position={"latitude": 18.5, "longitude": 77.5},
                ),
                _product(
                    id="other",
                    mission="curiosity",
                    start_time="2012-08-16T09:20:32Z",
                    position={"latitude": -4.5, "longitude": 137.4},
                ),
            ],
        )
        monkeypatch.setattr(
            panoramas, "_cached", lambda: panoramas.load_panoramas(cache)
        )
        out_dir = tmp_path / "v1"
        panoramas.write_panorama_index(out_dir)

        index = orjson.loads((out_dir / "panoramas.json").read_bytes())
        [body] = index["bodies"]
        assert body["id"] == MARS
        assert body["missions"] == [
            {
                "mission": "curiosity",
                "probe": "probe-100265984",
                "count": 1,
                "first_time": "2012-08-16T09:20:32Z",
                "last_time": "2012-08-16T09:20:32Z",
            },
            {
                "mission": "perseverance",
                "probe": "probe-113246208",
                "count": 2,
                "first_time": "2021-02-20T21:48:15Z",
                "last_time": "2022-12-26T20:56:23Z",
            },
        ]

    def test_no_coverage_writes_an_empty_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(panoramas, "_cached", dict)
        out_dir = tmp_path / "v1"
        panoramas.write_panorama_index(out_dir)
        assert orjson.loads((out_dir / "panoramas.json").read_bytes()) == {"bodies": []}


class TestDeduplication:
    """One mosaic delivered twice is dropped; two different views of one stop
    both export, though the archive gives them the same time and place."""

    def test_a_repeated_sphere_is_exported_once(self, tmp_path: Path):
        _write_cache(
            tmp_path,
            "curiosity-navcam",
            [
                _product(id="first", sphere="same"),
                _product(id="second", sphere="same"),
            ],
        )

        [product] = panoramas.load_panoramas(tmp_path)[MARS]

        assert product.entry["id"] == "first"

    def test_two_views_of_one_stop_both_export(self, tmp_path: Path):
        """A stop held for days leaves mosaics the archive dates from the first
        frame of the campaign, so the time and place they share name several
        genuinely different spheres."""
        _write_cache(
            tmp_path,
            "curiosity-navcam",
            [
                _product(id="sol59", coverage={"sphere_percent": 36.4}),
                _product(id="sol93", coverage={"sphere_percent": 74.0}),
            ],
        )

        exported = panoramas.load_panoramas(tmp_path)[MARS]

        assert [product.entry["id"] for product in exported] == ["sol59", "sol93"]

    def test_a_repeat_at_a_different_place_is_kept(self, tmp_path: Path):
        """Two stops can be photographed identically; they are still two
        places, and dropping one would lose a point on the traverse."""
        _write_cache(
            tmp_path,
            "curiosity-navcam",
            [
                _product(id="here", sphere="same"),
                _product(
                    id="there",
                    sphere="same",
                    position={"latitude": 18.45, "longitude": 77.45},
                ),
            ],
        )

        assert len(panoramas.load_panoramas(tmp_path)[MARS]) == 2

    def test_survivors_keep_mission_then_time_order(self, tmp_path: Path):
        """Neighbours in the exported list are neighbours on the traverse."""
        _write_cache(
            tmp_path,
            "curiosity-navcam",
            [
                _product(id="late", start_time="2021-03-01T00:00:00.000Z"),
                _product(id="early"),
            ],
        )

        exported = panoramas.load_panoramas(tmp_path)[MARS]

        assert [product.entry["id"] for product in exported] == ["early", "late"]


class TestApproximatePositions:
    """A panorama placed only within a range carries that range, so the viewer
    can say how well the marker is known rather than imply it is exact."""

    def _entries(self, tmp_path, position):
        _write_cache(tmp_path, "perseverance", [_product(position=position)])
        return panoramas.load_panoramas(tmp_path)[MARS][0].entry

    def test_a_bounded_position_states_how_far_off_it_can_be(self, tmp_path):
        entry = self._entries(
            tmp_path,
            {
                "latitude": 18.44,
                "longitude": 77.45,
                "elevation_m": -2569.9,
                "uncertainty_m": 8.4,
            },
        )

        assert entry["position_uncertainty_m"] == 8.4

    def test_an_exact_position_states_no_range(self, tmp_path):
        """Most positions come straight from the archive, and an uncertainty
        of nothing would read as a measured zero."""
        entry = self._entries(
            tmp_path,
            {"latitude": 18.44, "longitude": 77.45, "elevation_m": -2569.9},
        )

        assert "position_uncertainty_m" not in entry
