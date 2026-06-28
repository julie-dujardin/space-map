"""Tests for export output-directory cleanup helpers."""

from pathlib import Path

from space_map_data.export.pipeline.cleanup import prune_nomenclature


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")


class TestPruneNomenclature:
    """`prune_nomenclature` drops marker files for bodies no longer exported."""

    def test_drops_orphan_positions_and_labels(self, tmp_path: Path) -> None:
        nomen = tmp_path / "nomenclature"
        for body in ("naif-301", "spkid-20000052"):
            _touch(nomen / "positions" / f"{body}.bin.gz")
            for lang in ("en", "fr"):
                _touch(nomen / "labels" / lang / f"{body}.txt.gz")

        prune_nomenclature(tmp_path, ["naif-301"])

        assert (nomen / "positions" / "naif-301.bin.gz").exists()
        assert not (nomen / "positions" / "spkid-20000052.bin.gz").exists()
        for lang in ("en", "fr"):
            assert (nomen / "labels" / lang / "naif-301.txt.gz").exists()
            assert not (nomen / "labels" / lang / "spkid-20000052.txt.gz").exists()

    def test_no_nomenclature_dir_is_noop(self, tmp_path: Path) -> None:
        prune_nomenclature(tmp_path, ["naif-301"])  # must not raise
