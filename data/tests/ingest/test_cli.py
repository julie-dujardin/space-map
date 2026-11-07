"""Tests for the order of the ingest CLI's targets."""

import sys
from types import SimpleNamespace

from space_map_data.ingest import __main__ as ingest_cli


class TestTargetOrder:
    """The DB's image step reads the registry's planets, so the extrasolar
    ingest that writes them runs first."""

    def test_extrasolar_before_db(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(
            ingest_cli.stars,
            "ingest",
            lambda *_: calls.append("extrasolar") or (SimpleNamespace(report=""), ""),
        )
        monkeypatch.setattr(
            ingest_cli.skycultures, "ingest", lambda *_: calls.append("skycultures")
        )
        monkeypatch.setattr(
            ingest_cli, "ingest_db", lambda targets, *_: calls.append(targets)
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["space-map-ingest", "--targets", "all", "extrasolar"],
        )
        ingest_cli.cli()
        assert calls[:2] == ["extrasolar", "skycultures"]
        assert "images" in calls[2]
