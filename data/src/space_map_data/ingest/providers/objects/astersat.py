"""Ingest AsterSat mutual orbits onto the asteroid moons SBDB already created.

``sbdb_moons`` mints the Object rows; this only upgrades the ones AsterSat has
an orbit for — writing an ``AsterSatMoon`` row, repointing
``Object.orbital_source`` at it and flipping ``has_position``. SBDB's own
(usually element-less) row stays put so both sources remain readable side by
side, and the export keeps one file per provider.

AsterSat's satellite labels are the service's own display strings, not IAU
designations: spacing and diacritics differ from ours (``S/2001(107)1`` vs
``S/2001 (107) 1``, ``Ilmare`` vs ``Ilmarë``), and it writes "companion" for
most unnamed TNO satellites. Matching folds both sides to bare ASCII and falls
back to the parent's only moon; an unresolved label is logged and skipped
rather than guessed at.
"""

import logging
import re
from pathlib import Path

from sqlalchemy import delete, insert, select, update
from tqdm import tqdm

from space_map_data.ingest.providers.objects.sbdb_moons import KEPLER_REQUIRED
from space_map_data.ingest.providers.objects.small_body_match import (
    fold,
    moons_by_parent,
    small_body_index,
    strip_tags,
)
from space_map_data.models.object import (
    AsterSatMoon,
    Object,
    OrbitalSource,
    SBDBMoon,
)
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

# "Satellite orbit (geoequat J2000):" then the element block, as printed.
_ORBIT_RE = re.compile(r"Satellite orbit \(([^)]*)\):(.{0,600})", re.S)
_ELEMENTS = {
    "epoch_mjd": r"Epoch=\s*([\d.]+)",
    "a_km": r"a=\s*([\d.]+)\s*km",
    "n": r"n=\s*([-\d.]+)\s*deg/day",
    "per_d": r"Period=\s*([\d.]+)\s*day",
    "e": r"e=\s*([\d.eE+-]+)",
    "i": r"i=\s*([-\d.]+)\s*deg",
    "ma": r"M0=\s*([-\d.]+)\s*deg",
    "w": r"omega=\s*([-\d.]+)\s*deg",
    "om": r"Omega=\s*([-\d.]+)\s*deg",
}
_GM_RE = re.compile(r"Mass of the system=\s*([\d.eE+-]+)\s*km\^3")
_OBS_RE = re.compile(r"Observations on the time interval\s*([\d.]+)-([\d.]+)")
_FIT_RE = re.compile(r"(\d+)\s+observations giving RMS=\s*([\d.]+)")
_RADII_RE = {
    "primary_radius_km": r"Main body radius=\s*([\d.]+)",
    "satellite_radius_km": r"Satellite radius=\s*([\d.]+)",
}
# "(22) Kalliope  Satellite Linus" / "1998 WW31  Satellite S/2000(1998WW31)1"
_LABEL_RE = re.compile(r"^(.*?)\s+Satellite\s+(.*)$")


def _parse_orbit(page: str) -> dict | None:
    """Pull the element block and its fit provenance out of one response."""
    text = strip_tags(page)
    match = _ORBIT_RE.search(text)
    if match is None:
        return None
    row: dict = {"frame": match.group(1).strip()}
    block = match.group(2)
    for col, pattern in _ELEMENTS.items():
        found = re.search(pattern, block)
        if found is None:
            return None
        row[col] = float(found.group(1))
    if (gm := _GM_RE.search(block)) is not None:
        row["gm"] = float(gm.group(1))
    if (obs := _OBS_RE.search(text)) is not None:
        row["obs_arc_start"] = float(obs.group(1))
        row["obs_arc_end"] = float(obs.group(2))
    if (fit := _FIT_RE.search(text)) is not None:
        row["n_obs"] = int(fit.group(1))
        row["rms_arcsec"] = float(fit.group(2))
    for col, pattern in _RADII_RE.items():
        found = re.search(pattern, text)
        if found is not None:
            row[col] = float(found.group(1))
    return row


class AsterSatIngestor:
    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.dir = download_dir / "sources" / "position" / "astersat"
        self.no_parent = 0
        self.no_moon = 0
        self.unparsed = 0

    def _clear(self) -> None:
        """Drop our rows and hand the affected Objects back to SBDB.

        ``sbdb_moons`` owns those Object rows, so the reset restores what it
        wrote rather than deleting them — including whether SBDB's own
        elements could place the moon, which is true for the few radar
        binaries AsterSat also covers.
        """
        stale = [
            oid for (oid,) in self.session.execute(select(AsterSatMoon.object_id)).all()
        ]
        self.session.execute(delete(AsterSatMoon))
        if not stale:
            self.session.commit()
            return
        placeable = {
            oid
            for (oid,) in self.session.execute(
                select(SBDBMoon.object_id).where(
                    SBDBMoon.object_id.in_(stale),
                    *(
                        getattr(SBDBMoon, column).is_not(None)
                        for column in KEPLER_REQUIRED
                    ),
                )
            ).all()
        }
        for ids, positioned in ((placeable, True), (set(stale) - placeable, False)):
            if ids:
                self.session.execute(
                    update(Object)
                    .where(Object.id.in_(ids))
                    .values(
                        orbital_source=OrbitalSource.sbdb_moon,
                        has_position=positioned,
                    )
                )
        self.session.commit()

    def _resolve_parent(self, system_label: str, index: dict[str, str]) -> str | None:
        """``(22) Kalliope`` → the Object for 22; unnumbered → by designation."""
        numbered = re.match(r"\((\d+)\)", system_label)
        if numbered is not None:
            return index.get(numbered.group(1))
        return index.get(fold(system_label))

    def _resolve_moon(
        self,
        satellite_label: str,
        moons: list[tuple[str, str | None, str | None]],
    ) -> str | None:
        """Pick the moon the label names, else the only one the parent has."""
        wanted = fold(satellite_label)
        for oid, name, prov in moons:
            if wanted and wanted in {fold(name or ""), fold(prov or "")}:
                return oid
        # AsterSat writes "companion" for most unnamed TNO satellites and drops
        # the trailing index on some designations, so an unambiguous parent
        # settles it on its own.
        if len(moons) == 1:
            return moons[0][0]
        return None

    def run(self) -> None:
        index_file = self.dir / "satellites.tsv"
        if not index_file.exists():
            logger.warning("%s not found, skipping", index_file)
            return

        self._clear()
        parents = small_body_index(self.session)
        moons = moons_by_parent(self.session)

        rows: list[dict] = []
        claimed: set[str] = set()
        entries = [
            line.split("\t", 1)
            for line in index_file.read_text().splitlines()
            if "\t" in line
        ]
        for astersat_id, label in tqdm(
            entries, desc="AsterSat ingest", unit="sat", dynamic_ncols=True
        ):
            page = self.dir / f"{astersat_id}.html"
            if not page.exists():
                continue
            parsed = _parse_orbit(page.read_text())
            if parsed is None:
                logger.warning("%s: no orbit block in saved page", label)
                self.unparsed += 1
                continue

            split = _LABEL_RE.match(label)
            system_label = split.group(1).strip() if split else label
            satellite_label = split.group(2).strip() if split else ""

            parent_id = self._resolve_parent(system_label, parents)
            if parent_id is None:
                logger.info("%s: parent not in objects, skipping", label)
                self.no_parent += 1
                continue
            moon_id = self._resolve_moon(satellite_label, moons.get(parent_id, []))
            if moon_id is None:
                logger.warning(
                    "%s: no moon of %s matches %r, skipping",
                    label,
                    parent_id,
                    satellite_label,
                )
                self.no_moon += 1
                continue
            if moon_id in claimed:
                logger.warning("%s: %s already claimed by another row", label, moon_id)
                continue

            claimed.add(moon_id)
            rows.append(
                dict(
                    object_id=moon_id,
                    parent_object_id=parent_id,
                    astersat_id=astersat_id,
                    system_label=system_label,
                    satellite_label=satellite_label,
                    **parsed,
                )
            )

        if rows:
            self.session.execute(insert(AsterSatMoon), rows)
            self.session.execute(
                update(Object)
                .where(Object.id.in_(claimed))
                .values(orbital_source=OrbitalSource.astersat.value, has_position=True)
            )
            self.session.commit()

        logger.info("AsterSat: %d moons given a fitted mutual orbit", len(rows))
        if self.no_parent:
            logger.info("  %d skipped: parent not in the objects table", self.no_parent)
        if self.no_moon:
            logger.warning("  %d skipped: no matching moon row", self.no_moon)
        if self.unparsed:
            logger.warning("  %d skipped: saved page had no orbit block", self.unparsed)


def ingest(download_dir: Path) -> None:
    AsterSatIngestor(download_dir).run()
