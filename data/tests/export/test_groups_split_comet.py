"""Tests for split-comet family group helpers."""

import space_map_data.export.groups as groups_mod
from space_map_data.export.groups import _designation_qids


def _write_matches(tmp_path, pid, rows):
    d = tmp_path / "wikidata" / "ids" / "matches"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pid}.csv").write_text("".join(f"{term},{qids}\n" for term, qids in rows))


def test_designation_qids_reads_and_merges(tmp_path, monkeypatch):
    # P490 holds hand-set prefixed designations; P5736 holds numbered ones.
    _write_matches(tmp_path, "P490", [("C/1860 D1", "Q9826864"), ("C/1956 F1", "Q1")])
    _write_matches(tmp_path, "P5736", [("483P", "Q60977726")])
    monkeypatch.setattr(groups_mod, "SOURCES_METADATA_DIR", tmp_path)

    out = _designation_qids()
    assert out["C/1860 D1"] == ["Q9826864"]
    assert out["C/1956 F1"] == ["Q1"]
    assert out["483P"] == ["Q60977726"]


def test_designation_qids_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(groups_mod, "SOURCES_METADATA_DIR", tmp_path)
    assert _designation_qids() == {}
