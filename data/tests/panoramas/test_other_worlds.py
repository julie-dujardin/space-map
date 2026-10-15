import json

import numpy as np
from PIL import Image
import pytest

from space_map_data.panoramas import other_worlds


def test_mercator_top_horizon_leaves_sky_empty():
    source = Image.new("RGB", (360, 180), (180, 100, 30))
    sphere, percent = other_worlds.project_mercator(source, width=360)
    pixels = np.asarray(sphere)
    assert sphere.size == (360, 180)
    assert not pixels[:90, :, 3].any()
    assert pixels[90, :, 3].all()
    assert not pixels[-1, :, 3].any()
    assert percent == pytest.approx(50 * np.tanh(np.pi), abs=0.1)


def test_mercator_retains_dark_terrain():
    sphere, _ = other_worlds.project_mercator(Image.new("RGB", (360, 180)), width=360)
    assert np.asarray(sphere)[90, :, 3].all()


def test_mercator_rejects_invalid_width():
    with pytest.raises(ValueError):
        other_worlds.project_mercator(Image.new("RGB", (360, 180)), width=257)


def test_offline_pipeline_metadata_and_idempotence(tmp_path, monkeypatch):
    product = next(p for p in other_worlds.PRODUCTS if p["id"] == "apollo16-station1")
    monkeypatch.setattr(other_worlds, "PRODUCTS", [product])
    source, output = tmp_path / "sources", tmp_path / "output"
    source.mkdir()
    Image.new("RGB", (360, 80), (140, 120, 100)).save(source / (product["id"] + ".jpg"))
    other_worlds.process(source, output, offline=True)
    other_worlds.process(source, output, offline=True)
    catalog = json.loads((output / "moon/catalog.json").read_text())
    assert len(catalog["panoramas"]) == 1
    entry = catalog["panoramas"][0]
    assert entry["sphere_ready"] and not entry["map_ready"]
    metadata = json.loads((output / entry["metadata"]).read_text())
    assert metadata["body"] == "moon"
    assert metadata["coverage"]["sphere_percent"] is None
    assert metadata["coverage"]["horizontal_degrees"] is None
    assert len(metadata["source_sha256"]) == 64


def test_offline_missing_source_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        other_worlds.process(tmp_path, tmp_path / "output", offline=True)


@pytest.mark.parametrize("tilt", [0, 50, -50])
def test_tilted_scan_preserves_solid_angle(tilt):
    sphere, percent, horizontal = other_worlds.project_tilted_scan(
        Image.new("RGB", (180, 40), (120, 120, 120)), width=720, tilt_deg=tilt
    )
    assert percent == pytest.approx(50 * np.sin(np.deg2rad(18.5)), abs=0.05)
    assert sphere.size == (720, 360)
    assert 175 < horizontal < 250
    assert not np.asarray(sphere)[0, :, 3].any()


def test_tilted_scan_center_looks_down_and_keeps_shadows():
    sphere, _, _ = other_worlds.project_tilted_scan(
        Image.new("RGB", (180, 40)), width=720
    )
    alpha = np.asarray(sphere)[:, :, 3]
    assert alpha[280, 0] == 255  # Nominal center is 50° below the horizon.
    assert not alpha[180, 0]
    assert not alpha[:, 360].any()


def test_perspective_camera_footprint_and_dark_shadows():
    sphere, percent = other_worlds.project_perspective(
        Image.new("RGB", (1024, 1024)),
        width=720,
    )
    alpha = np.asarray(sphere)[:, :, 3]
    assert alpha[180, 0] == 255
    assert alpha[180, -1] == 255
    assert not alpha[:, 60:660].any()
    assert not alpha[:120].any()
    assert not alpha[240:].any()
    assert not alpha[:, 360].any()
    half = np.tan(np.deg2rad(30))
    solid_angle = 4 * np.arctan(half**2 / np.sqrt(1 + 2 * half**2))
    assert percent == pytest.approx(solid_angle / (4 * np.pi) * 100, abs=0.1)


@pytest.mark.parametrize("angle", [0, 180, float("nan")])
def test_perspective_rejects_invalid_angle(angle):
    with pytest.raises(ValueError):
        other_worlds.project_perspective(Image.new("RGB", (100, 100)), angle)


def test_philae_is_a_dated_ring_of_cameras(tmp_path, monkeypatch):
    product = next(p for p in other_worlds.PRODUCTS if p["id"] == "philae-civa")
    monkeypatch.setattr(other_worlds, "PRODUCTS", [product])
    source = tmp_path / "source"
    (source / "philae-civa").mkdir(parents=True)
    for frame in product["frames"]:
        suffix = frame["url"].rsplit(".", 1)[1]
        Image.new("RGB", (64, 64), (30, 30, 30)).save(
            source / "philae-civa" / f"camera-{frame['camera']}.{suffix}"
        )
    output = tmp_path / "derived"
    other_worlds.process(source, output, offline=True)
    metadata = json.loads((output / "67p/philae-civa/metadata.json").read_text())
    assert metadata["capture_time"] == "2014-11-13T06:13:53Z"
    assert metadata["orientation_status"] == "unknown"
    assert metadata["coverage"]["estimated_horizontal_degrees"] == 360
    assert [f["azimuth_deg"] for f in metadata["frames"]] == [180, 240, 300, 0, 60, 120]
    assert all(len(f["sha256"]) == 64 for f in metadata["frames"])
    assert metadata["position"]["longitude"] == pytest.approx(358.4)
    assert metadata["reuse"]["status"] == "educational-editorial-informational-only"


def test_ring_draws_each_direction_from_the_camera_facing_it():
    dark, light = (
        Image.new("RGB", (64, 64), (40, 40, 40)),
        Image.new("RGB", (64, 64), (200, 200, 200)),
    )
    sphere, percent = other_worlds.project_ring(
        [(0, dark), (60, light)], horizontal=70, width=720
    )
    pixels = np.asarray(sphere)
    # 29° is nearer camera 1's axis, 31° camera 2's, though both see them.
    assert tuple(pixels[180, 58, :3]) == (40, 40, 40)
    assert tuple(pixels[180, 62, :3]) == (200, 200, 200)
    assert not pixels[180, 360, 3]
    assert 0 < percent < 2 * 70 / 360 * 100


def test_mercator_start_azimuth_puts_north_at_the_left_edge():
    pixels = np.zeros((180, 360, 3), dtype=np.uint8)
    pixels[:, 180] = (255, 0, 0)
    sphere, _ = other_worlds.project_mercator(
        Image.fromarray(pixels), width=360, start_azimuth=180
    )
    row = np.asarray(sphere)[95]
    assert row[0, 0] == 255 and row[180, 0] == 0


def test_only_black_reaching_the_edge_counts_as_empty():
    pixels = np.full((40, 40, 3), 120, dtype=np.uint8)
    pixels[:5] = 0
    pixels[20:25, 20:25] = 0
    empty = other_worlds.border_black(Image.fromarray(pixels))
    assert empty[:5].all()
    assert not empty[20:25, 20:25].any()


def test_poster_panels_share_one_downloaded_poster():
    panels = [p for p in other_worlds.PRODUCTS if p.get("source_file")]
    assert {p["id"] for p in panels} == {"huygens-15km", "huygens-2km", "huygens-400m"}
    assert {p["source_file"] for p in panels} == {"huygens-poster-b.jpg"}
    assert all(p["start_azimuth_deg"] == 180 for p in panels)


def test_every_new_lander_has_a_published_site():
    for identity in ("venera14-lpi", "philae-civa", "surveyor1-stooke", "huygens-2km"):
        assert other_worlds.site_position(identity) is not None


def test_apollo_records_have_capture_evidence():
    products = [
        p
        for p in other_worlds.PRODUCTS
        if p["collection"] == "moon" and p["mission"].startswith("apollo")
    ]
    assert {p["mission"] for p in products} == {
        "apollo11",
        "apollo12",
        "apollo14",
        "apollo15",
        "apollo16",
        "apollo17",
    }
    assert all(
        p["capture_time"] and p["source_frames"] and p["capture_activity_met"]
        for p in products
    )
    assert all("apollojournals.org" in p["capture_date_source_url"] for p in products)


def test_single_turn_crop_removes_duplicate_columns():
    pixels = np.tile(np.arange(100, dtype=np.uint8), (30, 1))
    source = Image.fromarray(np.concatenate((pixels, pixels[:, :20]), axis=1))
    spec = {
        "source_size": [120, 30],
        "source_sha256": "reviewed",
        "bounds_px": [10, 0, 110, 30],
    }
    cropped = other_worlds.crop_single_turn(source, spec, "reviewed")
    assert cropped.size == (100, 30)
    assert len(np.unique(np.asarray(cropped)[15])) == 100
    assert source.size == (120, 30)
    with pytest.raises(ValueError, match="changed source"):
        other_worlds.crop_single_turn(source, spec, "replacement")
    with pytest.raises(ValueError, match="bounds"):
        other_worlds.crop_single_turn(
            source, {**spec, "bounds_px": [10, 0, 130, 30]}, "reviewed"
        )


def test_pipeline_crops_before_resizing_and_preserves_master_size(
    tmp_path, monkeypatch
):
    from space_map_data.panoramas.pipeline import sha256

    source, output = tmp_path / "source", tmp_path / "derived"
    source.mkdir()
    path = source / "test.jpg"
    Image.new("RGB", (400, 60), (140, 120, 100)).save(path)
    product = next(p for p in other_worlds.PRODUCTS if p["id"] == "apollo11-landing")
    spec = {
        "source_size": [400, 60],
        "source_sha256": sha256(path),
        "bounds_px": [20, 0, 380, 60],
    }
    monkeypatch.setattr(
        other_worlds, "PRODUCTS", [{**product, "id": "test", "sweep_crop": spec}]
    )
    other_worlds.process(source, output, offline=True, collections=["moon"])
    metadata = json.loads((output / "moon/test/metadata.json").read_text())
    assert metadata["source_width"] == 400
    assert metadata["rendition_source_width"] == 360
    assert metadata["sweep_crop"] == spec
    with Image.open(output / "moon/test/preview.webp") as preview:
        assert preview.size == (360, 60)
    assert sha256(path) == spec["source_sha256"]


def test_only_mappings_that_turn_may_claim_a_north(tmp_path, monkeypatch):
    product = {
        **next(p for p in other_worlds.PRODUCTS if p["id"] == "venera14-lpi"),
        "start_azimuth_deg": 90,
    }
    monkeypatch.setattr(other_worlds, "PRODUCTS", [product])
    with pytest.raises(ValueError, match="cannot be turned"):
        other_worlds.process(tmp_path, tmp_path / "derived", offline=True)


def test_the_ring_preview_is_a_grid_in_azimuth_order():
    frames = [
        (azimuth, Image.new("RGB", (8, 8), (shade, shade, shade)))
        for azimuth, shade in (
            (120, 30),
            (0, 10),
            (60, 20),
            (300, 60),
            (180, 40),
            (240, 50),
        )
    ]
    preview = np.asarray(other_worlds.ring_preview(frames))
    assert preview.shape == (1024, 1536, 3)
    assert [
        preview[256 + 512 * (i // 3), 256 + 512 * (i % 3), 0] for i in range(6)
    ] == [
        10,
        20,
        30,
        40,
        50,
        60,
    ]
