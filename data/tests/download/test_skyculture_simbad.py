"""Tests for the SIMBAD crosswalk of Bucur's identifiers."""

import csv
import json

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.skycultures import bucur, simbad
from space_map_data.download.providers.skycultures.simbad import (
    SkycultureSimbadDownloader,
    simbad_identifiers,
)

CULTURE = {
    "id": "Test",
    "constellations": [
        {
            "id": "CON Test 001",
            "lines": [["* alf UMa", "* bet UMa"]],
            "group": ["* gam UMa"],
        }
    ],
    "common_names": {"* alf UMa": [{"english": "Pointer"}], "NAME Venus": []},
}
# What the fake SIMBAD knows: identifier → oid, and each oid's rows.
OIDS = {"* alf UMa": "1", "* bet UMa": "2"}
BASIC = {"1": ["1", "* alf UMa", "SB*", "165.9", "61.7", "K0III"]}
BASIC["2"] = ["2", "* bet UMa", "PM*", "165.4", "56.4", "A1IV"]
BASIC["9"] = ["9", "* sys UMa", "**", "165.4", "56.4", ""]
IDS = {"1": "HIP 54061|* alf UMa", "2": "* bet UMa", "9": "HIP 53910|* sys UMa"}
LINKS = [["2", "9", ""]]


def fake_join(client, url, query, column, datatype, values, chunk):
    if "join ident" in query:
        return ["name", "oidref"], [[v, OIDS[v]] for v in values if v in OIDS]
    if "h_link" in query:
        rows = [link for link in LINKS if int(link[0]) in values]
        return ["child", "parent", "membership"], rows
    if "basic" in query:
        header = ["oid", "main_id", "otype", "ra", "dec", "sp_type"]
        return header, [BASIC[str(v)] for v in values]
    return ["oidref", "ids"], [[str(v), IDS[str(v)]] for v in values]


@pytest.fixture
def downloader(tmp_path, monkeypatch):
    source = tmp_path / "bucur"
    (source / "json").mkdir(parents=True)
    (source / "json" / "Test.json").write_text(json.dumps(CULTURE))
    (source / "metadata.json").write_text("{}")
    monkeypatch.setattr(bucur, "OUT_DIR", source)
    monkeypatch.setattr(bucur, "CULTURES_DIR", source / "json")
    monkeypatch.setattr(simbad, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(simbad, "tap_join", fake_join)
    monkeypatch.setattr(simbad, "tap_sync", lambda *a, **k: "otype,path\nSB*,* > **\n")
    return SkycultureSimbadDownloader(httpx.Client())


def _rows(path):
    with path.open(newline="") as handle:
        return list(csv.reader(handle))


class TestIdentifiers:
    """Every SIMBAD identifier of the lines, groups and names, once."""

    def test_collects_lines_groups_and_names_without_planets(self, downloader):
        assert simbad_identifiers(bucur.CULTURES_DIR) == [
            "* alf UMa",
            "* bet UMa",
            "* gam UMa",
        ]


class TestDownload:
    """The crosswalk files hold the matched objects and their parents."""

    def test_writes_names_with_empty_oid_for_unknown(self, downloader):
        downloader.download()
        out = simbad.OUT_DIR
        assert _rows(out / "names.csv") == [
            ["name", "oid"],
            ["* alf UMa", "1"],
            ["* bet UMa", "2"],
            ["* gam UMa", ""],
        ]
        assert [row[0] for row in _rows(out / "basic.csv")[1:]] == ["1", "2", "9"]
        assert _rows(out / "h_link.csv")[1:] == LINKS
        meta = json.loads((out / "metadata.json").read_text())
        assert meta["names_resolved"] == 2
        assert meta["parents"] == 1
        assert meta["bucur_commit"] == bucur.COMMIT

    def test_missing_input_fails(self, downloader):
        (bucur.OUT_DIR / "metadata.json").unlink()
        with pytest.raises(DownloadError, match="run its provider first"):
            downloader.download()
