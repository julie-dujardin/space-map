"""Set Object.discovery_year on natural moons from the JPL discovery table.

Runs after SPICE so every natural-moon Object exists. Matches each table row to
a moon by IAU name, falling back to a normalized provisional designation
(`S/2005 S6` ↔ our `S2005_S06`); the match sets `Object.discovery_year`. Earth's
Moon and ~2 designation-less moons don't match — they stay always-visible.
"""

import json
import logging
import re
from pathlib import Path

from sqlalchemy import select, update

from space_map_data.models.object import Object, ObjectType, OrbitalSource
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


def _norm_name(s: str | None) -> str:
    return re.sub(r"\s+", "", (s or "").strip().lower())


def _desig(s: str | None) -> str:
    """Designation key: alnum only, drop a leading `S` and the satellite
    number's leading zeros so `S/2005 S6`, `S2005_S06`, `2005 S6` all collapse."""
    c = re.sub(r"[^a-z0-9]", "", (s or "").lower())
    c = re.sub(r"^s", "", c)
    return re.sub(r"([a-z])0+(\d)", r"\1\2", c)


def _first_year(s: str | None) -> int | None:
    """Earliest 4-digit year in the cell (some list discovery + recovery)."""
    m = re.search(r"\d{4}", s or "")
    return int(m.group()) if m else None


class JPLSatelliteDiscoveryIngestor:
    BATCH = 10_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.path = (
            download_dir
            / "sources"
            / "position"
            / "jpl_satellite_discovery"
            / "moons.json"
        )

    def _clear(self) -> None:
        self.session.execute(
            update(Object)
            .where(Object.discovery_year.is_not(None))
            .values(discovery_year=None)
        )
        self.session.commit()

    def _link(self) -> list[dict]:
        rows = json.loads(self.path.read_text())
        by_name = {
            _norm_name(r["name"]): _first_year(r["year"]) for r in rows if r["name"]
        }
        by_desig: dict[str, int | None] = {}
        for r in rows:
            if r["provisional_designation"]:
                by_desig[_desig(r["provisional_designation"])] = _first_year(r["year"])
            if r["name"]:
                by_desig.setdefault(_desig(r["name"]), _first_year(r["year"]))

        moons = self.session.execute(
            select(Object.id, Object.name, Object.provisional_designation).where(
                Object.object_type == ObjectType.moon,
                Object.orbital_source.is_distinct_from(OrbitalSource.sbdb_moon),
            )
        ).all()

        updates, unmatched = [], 0
        for oid, name, prov in moons:
            year = by_name.get(_norm_name(name)) if name else None
            if year is None:
                year = by_desig.get(_desig(prov)) or by_desig.get(_desig(name))
            if year is not None:
                updates.append({"id": oid, "discovery_year": year})
            else:
                unmatched += 1
        logger.info(
            "Matched discovery year for %d/%d natural moons (%d unmatched)",
            len(updates),
            len(moons),
            unmatched,
        )
        return updates

    def run(self) -> None:
        if not self.path.exists():
            logger.warning("moons.json not found at %s, skipping", self.path)
            return
        self._clear()
        updates = self._link()
        for i in range(0, len(updates), self.BATCH):
            self.session.execute(update(Object), updates[i : i + self.BATCH])
        self.session.commit()


def ingest(download_dir: Path) -> None:
    JPLSatelliteDiscoveryIngestor(download_dir).run()
