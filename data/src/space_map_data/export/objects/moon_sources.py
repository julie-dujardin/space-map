"""Per-provider panel blocks for asteroid and TNO moons.

Three sources describe the same bodies and disagree about them: SBDB says a
companion exists and rarely more, AsterSat fits the mutual orbit, Johnston
compiles the sizes, masses and discovery record. They stay in separate blocks
so the panel can attribute every number, rather than merging into one view
that hides which source a figure came from.

Keyed by Object.id — the moon's, except Johnston's system blocks, which are
keyed by the host. A body is a system or a companion, never both, so the two
Johnston loaders share one key.
"""

from sqlalchemy.orm import Session

from space_map_data.export.objects.astersat import load_astersat
from space_map_data.export.objects.johnston import (
    load_johnston_moons,
    load_johnston_systems,
)
from space_map_data.export.quantities import UnitConverter

MoonSourceBlocks = dict[str, dict[str, dict]]


def load_moon_sources(session: Session, units: UnitConverter) -> MoonSourceBlocks:
    """Object.id -> {block name: block}, merged once for the whole export."""
    out: MoonSourceBlocks = {}
    sources = (
        ("astersat", load_astersat(session, units)),
        ("johnston", load_johnston_systems(session, units)),
        ("johnston", load_johnston_moons(session)),
    )
    for name, blocks in sources:
        for object_id, block in blocks.items():
            out.setdefault(object_id, {})[name] = block
    return out
