import json
import pickle

import pytest

from space_map_data.extrasolar import registry as registry_module
from space_map_data.extrasolar.engine import IngestRun
from space_map_data.extrasolar.registry import (
    Registry,
    RegistryBusy,
    RegistryError,
    WrongHost,
)
from tests.extrasolar.conftest import (
    GAIA,
    HIP,
    META,
    POINT,
    centre,
    gaia_rows,
    hip_rows,
)

RA, DEC = centre(6_000_000)


def _rows():
    return gaia_rows([{"id": 11, "ra": RA, "dec": DEC, "mag": 5.0}])


class TestWriters:
    """The minting lock and the minting host."""

    def test_second_writer_is_refused(self, root, backup):
        with IngestRun.start(root, backup, (POINT,), META) as run:
            with pytest.raises(RegistryBusy):
                IngestRun.start(root, backup, (POINT,), META)
            run.add(GAIA, [_rows()])
            run.commit()
        with IngestRun.start(root, backup, (POINT,), META) as run:
            run.add(GAIA, [_rows()])
            run.commit()
        assert Registry(root).last_ingest == 2

    def test_other_host_is_refused(self, root, backup, monkeypatch):
        with IngestRun.start(root, backup, (POINT,), META) as run:
            run.add(GAIA, [_rows()])
            run.commit()
        monkeypatch.setattr(registry_module.socket, "gethostname", lambda: "elsewhere")
        with pytest.raises(WrongHost):
            IngestRun.start(root, backup, (POINT,), META)
        # A read-only copy still answers lookups.
        assert Registry(root).lookup("gaia", "dr3", ["11"])[0] > 0


class TestReaders:
    """Readers share the lock with each other, and never with an ingest."""

    def test_a_reader_blocks_a_writer(self, root, ingest, backup):
        ingest([(GAIA, _rows())])
        with Registry(root).reader():
            with pytest.raises(RegistryBusy, match="locked by an ingest or an export"):
                IngestRun.start(root, backup, (POINT,), META)
            with pytest.raises(RegistryBusy), Registry(root).writer():
                pass
        with Registry(root).writer():
            pass

    def test_a_writer_blocks_a_reader(self, root, ingest, backup):
        ingest([(GAIA, _rows())])
        with IngestRun.start(root, backup, (POINT,), META) as run:
            with (
                pytest.raises(RegistryBusy, match="locked by an ingest;"),
                Registry(root).reader(),
            ):
                pass
            run.add(GAIA, [_rows()])
            run.commit()
        with Registry(root).reader() as registry:
            assert registry.last_ingest == 2

    def test_readers_share_the_lock_on_any_host(self, root, ingest, monkeypatch):
        current = Registry(root)
        ingest([(GAIA, _rows())])
        monkeypatch.setattr(registry_module.socket, "gethostname", lambda: "elsewhere")
        with current.reader() as first, Registry(root).reader() as second:
            # The manifest is read again under the lock.
            assert first.last_ingest == second.last_ingest == 1

    def test_no_registry(self, tmp_path, root, backup):
        with (
            pytest.raises(RegistryError, match="no registry"),
            Registry(tmp_path / "nothing").reader(),
        ):
            pass
        # A lock with no committed ingest is no registry either.
        with IngestRun.start(root, backup, (POINT,), META):
            pass
        with pytest.raises(RegistryError, match="no registry"), Registry(root).reader():
            pass

    def test_a_registry_pickles_inside_a_reader(self, root, ingest):
        ingest([(GAIA, _rows())])
        with Registry(root).reader() as registry:
            copy = pickle.loads(pickle.dumps(registry))
            assert copy.manifest == registry.manifest
            (region,) = copy.table_regions("point")
            table = copy.read_table("point", region, ["id"])
            assert table is not None and table.num_rows == 1


class TestLookup:
    """(catalogue, release, catalogue id) → ID."""

    def test_lookup(self, root, ingest):
        ingest(
            [
                (GAIA, _rows()),
                (HIP, hip_rows([{"id": 3, "ra": RA + 1, "dec": DEC, "mag": 1.0}])),
            ]
        )
        registry = Registry(root)
        found = registry.lookup("gaia", "dr3", ["11", "12"])
        assert found[0] > 0 and found[1] == 0
        assert registry.lookup("gaia", "dr2", ["11"])[0] == 0
        hip_id = registry.lookup("hip", "2007", ["3"])[0]
        assert hip_id > 0 and hip_id != found[0]
        region = int(registry_module.region_of(registry_module.cell_of(int(found[0]))))
        assert registry.lookup("gaia", "dr3", ["11"], regions=[region])[0] == found[0]
        assert (
            registry.lookup("gaia", "dr3", ["11"], regions=[(region + 5) % 768])[0] == 0
        )


class TestTables:
    """The current version of each table, by region."""

    def test_read_table_columns(self, root, ingest):
        ingest([(GAIA, _rows())])
        registry = Registry(root)
        (region,) = registry.table_regions("point")
        full = registry.read_table("point", region)
        assert full is not None and full.column_names == POINT.schema.names
        narrow = registry.read_table("point", region, columns=["id", "g"])
        assert narrow is not None and narrow.column_names == ["id", "g"]
        assert registry.read_table("point", (region + 5) % 768, ["id"]) is None


class TestBackup:
    """Each commit copies its segment and the manifest beside the NAS path."""

    def test_backup_copy(self, root, backup, ingest):
        ingest([(GAIA, _rows())])
        ingest([(GAIA, _rows())])
        registry = Registry(root)
        target = backup / registry.manifest["host"]
        assert json.loads((target / "manifest.json").read_text()) == registry.manifest
        for entry in registry.ingests:
            source = registry.segment_dir(entry["ingest"])
            copied = target / "segments" / source.name
            files = sorted(
                p.relative_to(source) for p in source.rglob("*") if p.is_file()
            )
            assert files and files == sorted(
                p.relative_to(copied) for p in copied.rglob("*") if p.is_file()
            )
            for name in files:
                assert (source / name).read_bytes() == (copied / name).read_bytes()
        assert not list(target.rglob("*.part"))
