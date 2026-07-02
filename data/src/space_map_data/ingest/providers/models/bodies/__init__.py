"""Natural-body shape-model ingest (missions/radar meshes + DAMIT lightcurve)."""

from space_map_data.ingest.providers.models.bodies.damit import DamitProcessor
from space_map_data.ingest.providers.models.bodies.processor import BodyModelProcessor

__all__ = ["BodyModelProcessor", "DamitProcessor"]
