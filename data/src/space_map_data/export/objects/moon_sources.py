"""Per-provider panel blocks for asteroid and TNO moons.

More than one source describes these bodies and they disagree about them:
SBDB says a companion exists and rarely more, Johnston compiles the sizes,
masses and discovery record from the literature. They stay in separate blocks
so the panel can attribute every number, rather than merging into one view
that hides which source a figure came from.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from space_map_data.export.objects.johnston import (
    load_johnston_moons,
    load_johnston_systems,
)
from space_map_data.export.quantities import UnitConverter


@dataclass(frozen=True)
class MoonSourceBlocks:
    """Blocks keyed by Object.id — the moon's, except systems, keyed by parent."""

    johnston_systems: dict[str, dict]
    johnston_moons: dict[str, dict]

    def blocks_for(self, object_id: str) -> dict[str, dict]:
        """Block name -> block, for whichever of these this object has."""
        out: dict[str, dict] = {}
        # A body is a system or a companion, never both, so one key serves.
        johnston = self.johnston_systems.get(object_id) or self.johnston_moons.get(
            object_id
        )
        if johnston is not None:
            out["johnston"] = johnston
        return out


def load_moon_sources(session: Session, units: UnitConverter) -> MoonSourceBlocks:
    return MoonSourceBlocks(
        johnston_systems=load_johnston_systems(session, units),
        johnston_moons=load_johnston_moons(session),
    )
