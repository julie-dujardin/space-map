"""Set of Object.ids covered by the chebyshev export — used to filter elements zones."""

import logging
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from space_map_data.constants.providers import PROVIDERS
from space_map_data.export.position.chebyshev.writer import (
    _object_for_naif_id,
    should_export,
)

logger = logging.getLogger(__name__)


def chebyshev_coverage(session: Session, download_dir: Path) -> set[str]:
    """Object IDs covered by the chebyshev export.

    Used to filter cheb-covered bodies out of the elements zones so the same
    body's positions don't ship in two formats. The frontend can derive
    osculating Kepler elements from chebyshev positions when needed, so a
    duplicated kepler row is just dead bytes.

    Walks `download_dir/spice/chebyshev/*.npz` and resolves each file's
    `naif_id` against the DB (with the SPK-ID fallback used by the cheb
    writer). Returns a set of `Object.id` strings (e.g. `naif-499`,
    `spkid-20134340`) so callers can filter on the prefixed form.
    """
    cheb_dir = download_dir / PROVIDERS.SPICE / "chebyshev"
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
