"""Unit tests for the hand-edited per-spacecraft pointing config loader."""

import textwrap
from pathlib import Path

from space_map_data.export.position.spacecraft_orientation import (
    apply_orientation_config,
    load_orientation_config,
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "spacecraft-orientation.yaml"
    path.write_text(textwrap.dedent(body))
    return path


class TestLoadOrientationConfig:
    """Parsing, validation, and graceful degradation of the YAML."""

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_orientation_config(tmp_path / "nope.yaml") == {}

    def test_primary_and_secondary(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
            norad_satcat-25544:
              primary:   { axis: "-y", target: parent }
              secondary: { axis: "+x", target: velocity }
            """,
        )
        assert load_orientation_config(path) == {
            "norad_satcat-25544": {
                "primary": {"axis": "-y", "target": "parent"},
                "secondary": {"axis": "+x", "target": "velocity"},
            }
        }

    def test_primary_only(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
            probe-22904832:
              primary: { axis: "+z", target: sun }
            """,
        )
        spec = load_orientation_config(path)["probe-22904832"]
        assert spec == {"primary": {"axis": "+z", "target": "sun"}}
        assert "secondary" not in spec

    def test_invalid_axis_drops_constraint(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
            probe-1:
              primary:   { axis: "+w", target: sun }
            probe-2:
              primary:   { axis: "+x", target: parent }
              secondary: { axis: "sideways", target: sun }
            """,
        )
        config = load_orientation_config(path)
        # probe-1's only constraint is invalid → whole entry dropped.
        assert "probe-1" not in config
        # probe-2 keeps its valid primary, drops the bad secondary.
        assert config["probe-2"] == {"primary": {"axis": "+x", "target": "parent"}}

    def test_invalid_target_dropped(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
            probe-3:
              primary: { axis: "+x", target: moon }
            """,
        )
        assert load_orientation_config(path) == {}

    def test_non_mapping_top_level_ignored(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "- just\n- a\n- list\n")
        assert load_orientation_config(path) == {}

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "")
        assert load_orientation_config(path) == {}


class TestApplyOrientationConfig:
    """Injecting `pointing` into per-object global entries."""

    def test_applies_to_matching_objects_only(self, tmp_path: Path) -> None:
        config = {
            "norad_satcat-25544": {"primary": {"axis": "-y", "target": "parent"}},
            "probe-404": {"primary": {"axis": "+x", "target": "sun"}},
        }
        global_data: dict[str, dict] = {"norad_satcat-25544": {}, "naif-399": {}}
        applied = apply_orientation_config(global_data, config)
        assert applied == 1
        assert (
            global_data["norad_satcat-25544"]["pointing"]
            == config["norad_satcat-25544"]
        )
        # Unmatched config id leaves nothing behind; unrelated object untouched.
        assert "pointing" not in global_data["naif-399"]
