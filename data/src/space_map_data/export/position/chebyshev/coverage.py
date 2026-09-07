"""Set of Object.ids covered by the chebyshev export — used to filter elements zones."""

import logging
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from space_map_data.export.position.chebyshev.writer import (
    _object_for_naif_id,
    should_export,
)
from space_map_data.export.position.layout import chebyshev_npz_paths

logger = logging.getLogger(__name__)


def chebyshev_coverage(session: Session, download_dir: Path) -> set[str]:
    """Object IDs the chebyshev export positions over the whole timeline.

    Filters cheb-covered bodies out of the elements zones — the frontend can
    derive Kepler elements from chebyshev positions, so a duplicate row is
    just dead bytes. Probe-target fits are left out: they cover a flyby, not
    the export range, so those bodies keep the element row that carries them
    the rest of the time.
    """
    return _ids_for(session, chebyshev_npz_paths(download_dir, full_range_only=True))


def chebyshev_written_ids(session: Session, download_dir: Path) -> set[str]:
    """Object IDs the chebyshev export writes segments for, overlays included."""
    return _ids_for(session, chebyshev_npz_paths(download_dir))


def _ids_for(session: Session, paths: list[Path]) -> set[str]:
    ids: set[str] = set()
    for path in paths:
        try:
            data = np.load(path)
            naif_id = int(data["meta"][0])
        except Exception as exc:
            logger.warning("Couldn't read cheb npz %s: %s", path, exc)
            continue
        obj = _object_for_naif_id(session, naif_id)
        if obj is not None and should_export(obj, naif_id):
            ids.add(obj.id)
    return ids
