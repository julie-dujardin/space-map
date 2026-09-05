"""Per-provider panel blocks for asteroid and TNO moons.

Three sources describe the same bodies and disagree about them: SBDB says a
companion exists and rarely more, AsterSat fits the mutual orbit, Johnston
compiles the sizes, masses and discovery record. They stay in separate blocks
so the panel can attribute every number, rather than merging into one view
that hides which source a figure came from.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from space_map_data.export.objects.astersat import load_astersat
from space_map_data.export.objects.johnston import (
    load_johnston_moons,
    load_johnston_systems,
)
from space_map_data.export.quantities import UnitConverter


@dataclass(frozen=True)
class MoonSourceBlocks:
    """Blocks keyed by Object.id — the moon's, except systems, keyed by parent."""

    astersat: dict[str, dict]
    johnston_systems: dict[str, dict]
    johnston_moons: dict[str, dict]

    def blocks_for(self, object_id: str) -> dict[str, dict]:
        """Block name -> block, for whichever of the three this object has."""
        out: dict[str, dict] = {}
        if (astersat := self.astersat.get(object_id)) is not None:
            out["astersat"] = astersat
        # A body is a system or a companion, never both, so one key serves.
        johnston = self.johnston_systems.get(object_id) or self.johnston_moons.get(
            object_id
        )
        if johnston is not None:
            out["johnston"] = johnston
        return out


def load_moon_sources(session: Session, units: UnitConverter) -> MoonSourceBlocks:
    return MoonSourceBlocks(
        astersat=load_astersat(session, units),
        johnston_systems=load_johnston_systems(session, units),
        johnston_moons=load_johnston_moons(session),
    )
