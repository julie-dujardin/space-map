"""The works a probe's panel credits for the traverse that places it."""

from space_map_data.constants.traverses.references import TRAVERSE_SOURCES
from space_map_data.export.objects.sources import source_row
from space_map_data.probes.traverses import load_traverses


def load_probe_position_sources() -> dict[int, list[dict]]:
    """`{probe_id → cited works}` for the probes a traverse places on their
    body."""
    return {
        probe_id: [source_row(TRAVERSE_SOURCES[key]) for key in traverse.sources]
        for probe_id, traverse in load_traverses().items()
    }
