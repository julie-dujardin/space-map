"""Extrap kernels must reach the exporter even when absent from the index.

The propagation synthesiser writes `<naif>-extrap.bsp` and records it in the
mission `_index.json`, but a re-download regenerates that index from the
downloaded files only — dropping the synthetic entry. Discovery therefore
falls back to disk presence; these tests pin that down.
"""

import json
from pathlib import Path

from space_map_data.download.providers.spice.probes.downloader import (
    _existing_extrap_records,
)
from space_map_data.export.position.probes.kernels import kernels_from_index


def _write_index(mdir: Path, files: list[dict], targets: dict) -> None:
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "_index.json").write_text(json.dumps({"files": files, "targets": targets}))


def test_extrap_picked_up_when_missing_from_index(tmp_path: Path) -> None:
    mdir = tmp_path / "PIONEER10"
    _write_index(mdir, files=[{"name": "p10-a.bsp"}], targets={"-23": ["p10-a.bsp"]})
    (mdir / "p10-a.bsp").touch()
    (mdir / "-23-extrap.bsp").touch()  # on disk, NOT in the index

    names = [p.name for p in kernels_from_index(mdir)]
    assert names == ["-23-extrap.bsp", "p10-a.bsp"]  # extrap (predict) furnshed first


def test_extrap_not_double_counted_when_in_index(tmp_path: Path) -> None:
    mdir = tmp_path / "M2"
    _write_index(
        mdir,
        files=[{"name": "m2.bsp"}, {"name": "-2-extrap.bsp"}],
        targets={"-2": ["m2.bsp", "-2-extrap.bsp"]},
    )
    (mdir / "m2.bsp").touch()
    (mdir / "-2-extrap.bsp").touch()

    names = [p.name for p in kernels_from_index(mdir)]
    assert names.count("-2-extrap.bsp") == 1


def test_downloader_preserves_existing_extrap_records(tmp_path: Path) -> None:
    mdir = tmp_path / "HELIOS"
    _write_index(
        mdir,
        files=[
            {"name": "helios.bsp", "targets": [-301]},
            {"name": "-301-extrap.bsp", "targets": [-301], "propagation": {}},
        ],
        targets={"-301": ["helios.bsp", "-301-extrap.bsp"]},
    )
    (mdir / "-301-extrap.bsp").touch()

    records = _existing_extrap_records(mdir)
    assert [r["name"] for r in records] == ["-301-extrap.bsp"]


def test_downloader_drops_extrap_record_when_file_gone(tmp_path: Path) -> None:
    mdir = tmp_path / "HELIOS"
    _write_index(
        mdir,
        files=[{"name": "-301-extrap.bsp", "targets": [-301]}],
        targets={"-301": ["-301-extrap.bsp"]},
    )
    # File deleted (verdict flipped PROPAGATE → SKIP) but index lagging.
    assert _existing_extrap_records(mdir) == []
