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
import unicodedata
from pathlib import Path

from sqlalchemy import delete, insert, select, update
from tqdm import tqdm

from space_map_data.models.object import (
    AsterSatMoon,
    Object,
    ObjectType,
    OrbitalSource,
    SBDBMoon,
)
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

# What SBDB's own row needs before it could place the moon on its own —
# mirrors ``sbdb_moons``' gate, so releasing a row restores what it had.
_SBDB_KEPLER_REQUIRED = ("epoch_jd", "a_km", "e", "i", "om", "w", "ma", "n")

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


def _fold(text: str) -> str:
    """Reduce a name or designation to comparable ASCII alphanumerics.

    Drops spacing, punctuation and diacritics, so ``S/2001 (107) 1`` and
    ``S/2001(107)1`` collapse together, as do ``Ilmarë`` and ``Ilmare``.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed.lower() if c.isascii() and c.isalnum())


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _parse_orbit(page: str) -> dict | None:
    """Pull the element block and its fit provenance out of one response."""
    text = _strip_tags(page)
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
                        for column in _SBDB_KEPLER_REQUIRED
                    ),
                )
            ).all()
        }
        for oid in stale:
            self.session.execute(
                update(Object)
                .where(Object.id == oid)
                .values(
                    orbital_source=OrbitalSource.sbdb_moon,
                    has_position=oid in placeable,
                )
            )
        self.session.commit()

    def _parent_index(self) -> dict[str, str]:
        """Map folded parent token -> Object.id for every small body.

        Keyed on number, designation and name so AsterSat's mix of
        ``(22) Kalliope`` and ``1998 WW31`` labels all resolve.
        """
        rows = self.session.execute(
            select(
                Object.id,
                Object.spkid,
                Object.name,
                Object.mpc_designation,
                Object.provisional_designation,
            ).where(Object.spkid.is_not(None))
        ).all()
        index: dict[str, str] = {}
        for oid, spkid, name, mpc, prov in rows:
            # Asteroid SPK-IDs are 20000000 + catalogue number.
            if spkid is not None and 20000001 <= spkid <= 21000000:
                index.setdefault(str(spkid - 20000000), oid)
            for token in (name, mpc, prov):
                if token:
                    index.setdefault(_fold(token), oid)
        return index

    def _moons_by_parent(self) -> dict[str, list[tuple[str, str | None, str | None]]]:
        rows = self.session.execute(
            select(
                Object.id,
                Object.parent_id,
                Object.name,
                Object.provisional_designation,
            ).where(
                Object.object_type == ObjectType.moon, Object.parent_id.is_not(None)
            )
        ).all()
        out: dict[str, list[tuple[str, str | None, str | None]]] = {}
        for oid, parent_id, name, prov in rows:
            out.setdefault(parent_id, []).append((oid, name, prov))
        return out

    def _resolve_parent(self, system_label: str, index: dict[str, str]) -> str | None:
        """``(22) Kalliope`` → the Object for 22; unnumbered → by designation."""
        numbered = re.match(r"\((\d+)\)", system_label)
        if numbered is not None:
            return index.get(numbered.group(1))
        return index.get(_fold(system_label))

    def _resolve_moon(
        self,
        parent_id: str,
        satellite_label: str,
        moons: list[tuple[str, str | None, str | None]],
    ) -> str | None:
        """Pick the moon the label names, else the only one the parent has."""
        wanted = _fold(satellite_label)
        for oid, name, prov in moons:
            if wanted and wanted in {_fold(name or ""), _fold(prov or "")}:
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
        parents = self._parent_index()
        moons_by_parent = self._moons_by_parent()

        rows: list[dict] = []
        claimed: list[str] = []
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
            moon_id = self._resolve_moon(
                parent_id, satellite_label, moons_by_parent.get(parent_id, [])
            )
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

            claimed.append(moon_id)
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
