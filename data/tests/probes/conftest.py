"""Shared fixtures for the probes tests."""

from pathlib import Path

import pytest

from space_map_data.probes import attachments, landing_events


@pytest.fixture
def events_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the loaders at a temp dir so each test owns its event JSONs.

    Both import ``EVENTS_DIR`` by value, so each module's binding is patched.
    """
    root = tmp_path / "events"
    root.mkdir()
    for module in (attachments, landing_events):
        monkeypatch.setattr(module, "EVENTS_DIR", root)
    return root
