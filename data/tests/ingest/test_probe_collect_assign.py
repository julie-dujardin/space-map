from pathlib import Path
from unittest.mock import patch

from space_map_data.ingest.providers.objects import probes
from space_map_data.probes.probe_id import ProbeIdRecord


def _record(mission: str, naif_id: int) -> dict:
    return {
        "mission": mission,
        "naif_id": naif_id,
        "inception_mjd": 43000,
        "name_hint": None,
        "cospar_hint": None,
    }


def _assigned(records: list[dict]) -> dict[tuple[str, int], ProbeIdRecord]:
    # Every -32 kernel belongs to Voyager 2, as the registry attaches it.
    return {
        (r["mission"], r["naif_id"]): ProbeIdRecord(
            probe_id=49000448,
            naif_id=r["naif_id"],
            inception_mjd=43000,
            dedupe=0,
            kernel_sources=(("VOYAGER", -32), ("HORIZONS-SYNTH", -32)),
            name="Voyager 2",
        )
        for r in records
    }


class TestCollectAndAssign:
    """A synthesised kernel attached on first sight yields one probe record, not two."""

    def test_a_new_attachment_is_collected_into_its_probe(self):
        first = [_record("VOYAGER", -32), _record("HORIZONS-SYNTH", -32)]
        again = [_record("VOYAGER", -32)]
        with (
            patch.object(probes, "_collect_probes", side_effect=[first, again]),
            patch.object(probes, "_assign", side_effect=_assigned),
        ):
            records, assignments = probes._collect_and_assign(Path(), Path())
        assert records == again
        assert list(assignments) == [("VOYAGER", -32)]

    def test_records_with_their_own_ids_are_collected_once(self):
        records = [_record("VOYAGER", -32)]
        with (
            patch.object(probes, "_collect_probes", return_value=records) as collect,
            patch.object(probes, "_assign", side_effect=_assigned),
        ):
            probes._collect_and_assign(Path(), Path())
        assert collect.call_count == 1
