"""Set of Object.ids covered by the chebyshev export — used to filter elements zones."""

import logging
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from space_map_data.export.position.chebyshev.writer import (
    _object_for_naif_id,
    should_export,
)

logger = logging.getLogger(__name__)


def chebyshev_coverage(session: Session, download_dir: Path) -> set[str]:
    """Object IDs covered by the chebyshev export.

    Filters cheb-covered bodies out of the elements zones — the frontend can
    derive Kepler elements from chebyshev positions, so a duplicate row is
    just dead bytes.
    """
    cheb_dir = download_dir / "derived" / "position" / "chebyshev"
    if not cheb_dir.exists():
        return set()
    ids: set[str] = set()
    for path in sorted(cheb_dir.glob("*.npz")):
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
