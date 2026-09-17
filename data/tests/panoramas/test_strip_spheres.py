import numpy as np
import pytest
from PIL import Image

from space_map_data.panoramas.strip_spheres import project_strip


def test_partial_strip_leaves_gap_and_poles_empty():
    source = Image.new("RGB", (580, 100), (140, 90, 40))
    sphere, percent = project_strip(source, 290, 0.5, width=360)
    alpha = np.asarray(sphere)[:, :, 3]
    assert not alpha[:, 290:].any()
    assert not alpha[0].any()
    assert not alpha[-1].any()
    assert alpha[90, :290].all()
    assert 0 < percent < 290 / 360 * 100


def test_black_holes_are_not_filled():
    sphere, percent = project_strip(Image.new("RGB", (360, 100)), 360, 0.5, width=360)
    assert percent == 0
    assert not np.asarray(sphere)[:, :, 3].any()


def test_invalid_sweep_rejected():
    with pytest.raises(ValueError):
        project_strip(Image.new("RGB", (100, 100)), 400, 0.5)


def test_heading_wraps_partial_strip_across_north():
    source = Image.new("RGB", (120, 60), (140, 90, 40))
    sphere, _ = project_strip(source, 120, 0.5, width=360, start_azimuth=300)
    alpha = np.asarray(sphere)[90, :, 3]
    assert alpha[:60].all() and alpha[300:].all()
    assert not alpha[60:300].any()


def test_north_at_source_center_is_rotated_to_seam():
    pixels = np.zeros((60, 360, 3), dtype=np.uint8)
    pixels[:, :180] = (200, 50, 20)
    pixels[:, 180:] = (20, 50, 200)
    sphere, _ = project_strip(
        Image.fromarray(pixels), 360, 0.5, width=360, start_azimuth=180
    )
    assert tuple(np.asarray(sphere)[90, 0, :3]) == (20, 50, 200)
    assert tuple(np.asarray(sphere)[90, 180, :3]) == (200, 50, 20)


def test_curated_processing_is_dated_idempotent_and_ignores_inactive(tmp_path):
    import json
    from space_map_data.panoramas.strip_spheres import STRIPS, process

    spec = next(s for s in STRIPS if "santorini" in s["id"])
    target = tmp_path / spec["collection"] / spec["id"]
    target.mkdir(parents=True)
    Image.new("RGB", (360, 60), (140, 90, 40)).save(target / "preview.webp")
    metadata = {
        "id": spec["id"],
        "preview": "preview.webp",
        "source_sha256": spec["source_sha256"],
    }
    path = target / "metadata.json"
    path.write_text(json.dumps(metadata))
    catalog = target.parent / "catalog.json"
    catalog.write_text(json.dumps({"panoramas": []}))
    assert process(tmp_path, width=360) == 0
    catalog.write_text(
        json.dumps(
            {
                "panoramas": [
                    {"id": spec["id"], "metadata": str(path.relative_to(tmp_path))}
                ]
            }
        )
    )
    assert process(tmp_path, width=360) == 1
    first = path.read_text()
    assert process(tmp_path, width=360) == 1
    assert path.read_text() == first
    result = json.loads(first)
    assert result["capture_time"] == "2008-11-21"
    assert result["capture_stop_time"] == "2008-11-24"
    assert result["north_azimuth_offset_deg"] == 0
    assert result["coverage"]["sphere_percent"] is None
    entry = json.loads(catalog.read_text())["panoramas"][0]
    assert entry["sphere_ready"] and not entry["map_ready"]
    result["source_sha256"] = "changed"
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="changed source"):
        process(tmp_path, width=360)


class TestHowAStripSaysItsGeometryWasFound:
    """A horizon solved against an archive must not read as one eyeballed."""

    def render(self, tmp_path, spec):
        from space_map_data.panoramas.strip_spheres import render_curated

        target = tmp_path / spec["id"]
        target.mkdir(parents=True)
        Image.new("RGB", (360, 60), (140, 90, 40)).save(target / "preview.webp")
        metadata = {
            "id": spec["id"],
            "preview": "preview.webp",
            "source_sha256": spec["source_sha256"],
        }
        return render_curated(target, metadata, spec, width=360)

    def solved(self):
        from space_map_data.panoramas.strip_spheres import STRIPS

        return next(s for s in STRIPS if s.get("horizon_evidence"))

    def test_a_solved_horizon_states_what_it_was_solved_against(self, tmp_path):
        spec = self.solved()

        result = self.render(tmp_path, spec)

        evidence = result["geometry_evidence"]
        assert evidence["vertical"] == spec["horizon_basis"]
        assert evidence["horizon_evidence"]["matched_products"]
        assert "solved against archival spheres" in result["geometry_note"]

    def test_an_eyeballed_horizon_still_says_so(self, tmp_path):
        from space_map_data.panoramas.strip_spheres import STRIPS

        spec = next(s for s in STRIPS if not s.get("horizon_evidence"))

        result = self.render(tmp_path, spec)

        assert "visually estimated horizon" in result["geometry_evidence"]["vertical"]
        assert result["geometry_evidence"]["horizon_evidence"] is None
        assert "Visually estimated horizon" in result["geometry_note"]

    def test_a_sol_the_gallery_states_is_not_credited_to_the_raw_archive(
        self, tmp_path
    ):
        from space_map_data.panoramas.strip_spheres import STRIPS

        spec = next(s for s in STRIPS if s.get("capture_sol_basis"))

        result = self.render(tmp_path, spec)

        assert result["sol"] == spec["capture_sol"]
        assert result["sol_basis"] == spec["capture_sol_basis"]
        assert "raw-image archive" not in result["sol_basis"]
