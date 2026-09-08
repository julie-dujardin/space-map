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
    assert percent == pytest.approx(50 * np.sin(np.deg2rad(20)), abs=0.05)
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
