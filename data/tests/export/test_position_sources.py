"""The works a probe's panel credits for the traverse that places it."""

from pathlib import Path

import pytest

from space_map_data.export.objects.position_sources import (
    load_probe_position_sources,
)
from space_map_data.probes import traverses


@pytest.fixture
def traverse_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(traverses, "TRAVERSES_DIR", tmp_path)
    return tmp_path


class TestLoadProbePositionSources:
    """Each traverse's source keys become the panel's cited works."""

    def test_a_traverse_credits_its_paper(self, traverse_dir: Path):
        traverses.write_traverse(
            traverse_dir,
            probe_id=42098689,
            body_naif=301,
            sources=("karachevtseva_2017",),
            landing_point=(25.9991, 30.40754),
            waypoints=[("1973-05-10", 25.83233, 30.92211)],
        )
        assert load_probe_position_sources() == {
            42098689: [
                {
                    "title": "Karachevtseva et al. 2017 (Icarus 283)",
                    "url": "https://doi.org/10.1016/j.icarus.2016.05.021",
                    "note": "Lunokhod 2 route",
                }
            ]
        }

    def test_a_probe_without_a_traverse_credits_nothing(self, traverse_dir: Path):
        assert load_probe_position_sources() == {}
