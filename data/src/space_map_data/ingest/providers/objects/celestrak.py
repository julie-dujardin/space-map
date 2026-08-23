"""Ingest the Space-Track catalogue + CelesTrak group TLE files into the database.

The object list and its SGP4 extras come from Space-Track's daily ``gp-active``;
CelesTrak supplies only the curated group memberships (constellations,
categories) that cannot be derived from a satellite's name.
"""

import csv
import logging
from pathlib import Path

from sqlalchemy import delete, insert, select, update
from tqdm import tqdm

from space_map_data.constants.earth_sats.satcat import SatcatObjectType
from space_map_data.constants.providers import ID_TYPES, make_object_id
from space_map_data.export.position.elements.spacetrack_source import (
    ARCHIVE_YEARS,
    archive_norad_set,
)
from space_map_data.ingest.convert import (
    count_csv_rows,
    float_or_none,
    int_or_none,
    string_or_none,
)
from space_map_data.ingest.providers.objects.enrichment import (
    latest_day_dir,
    load_groups,
)
from space_map_data.models.object import (
    Object,
    ObjectType,
    CelesTrak as CelesTrakRow,
    ElementsScale,
    OrbitalSource,
    Satcat,
)
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


class CelesTrakIngestor:
    BATCH = 10_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        position_dir = download_dir / "sources" / "position"
        self.provider_dir = position_dir / "celestrak"
        # Active catalogue (object list, names, SGP4 extras): the freshest GP
        # snapshot from either source. Space-Track is the target, but CelesTrak
        # keeps flowing during the migration, so use whichever has the newest day
        # (Space-Track wins a tie). Group CSVs are CelesTrak-only. The export
        # reads every day's snapshot off disk for time-sliced overlays, so what's
        # ingested here only matters outside the export.
        self.csv_path = latest_day_dir(position_dir / "spacetrack" / "current") / (
            "gp-active.csv"
        )
        self.groups_dir = latest_day_dir(self.provider_dir) / "groups"
        self.total_rows = 0
        self.missing_satcat = 0
        # Pre-loaded from the satcat DB table (ingested earlier).
        self.satcat_object_types: dict[int, SatcatObjectType | None] = {}
        # NORAD → probe-* Object.id. Primary lookup: when a probe registers a
        # NORAD (via its satcat FK), this celestrak row consolidates onto it
        # instead of minting a parallel `norad_satcat-N`. Joint-launch
        # siblings (Cassini + Huygens at 25008) tiebreak on lowest probe_id
        # (= lowest inception_mjd) — only the primary spacecraft owns the
        # active TLE.
        self.norad_to_probe: dict[int, str] = {}
        # COSPAR → probe-* Object.id, fallback for probes whose registry
        # entry has cospar but no NORAD (S-IVB upper stages etc.).
        self.cospar_to_probe: dict[str, str] = {}

    def _load_satcat_object_types(self) -> None:
        """Pre-load object_type from the satcat table for ObjectType classification."""
        rows = self.session.execute(
            select(Satcat.NORAD_CAT_ID, Satcat.object_type)
        ).all()
        self.satcat_object_types = {norad: otype for norad, otype in rows}
        logger.info(
            "Loaded %d SATCAT object types from DB", len(self.satcat_object_types)
        )

    def _load_probe_claims(self) -> None:
        """Build NORAD/COSPAR → probe-* lookups for celestrak consolidation.

        Multiple probes can share a NORAD (joint-launch siblings); the lowest
        probe_id wins ownership of the celestrak row, which represents the
        physically tracked primary spacecraft. Probe rows already carry the
        satcat FK (set by probe ingest); celestrak only adds the celestrak
        FK on top.

        COSPAR fallback covers registry entries with cospar but no NORAD
        (Apollo S-IVB stages etc.).
        """
        rows = self.session.execute(
            select(Object.norad_cat_id, Object.cospar_id, Object.probe_id, Object.id)
            .where(Object.id.like("probe-%"))
            .order_by(Object.probe_id.asc())
        ).all()
        norad_collisions: dict[int, list[str]] = {}
        for norad, cospar, _probe_id, oid in rows:
            if norad is not None:
                if norad in self.norad_to_probe:
                    norad_collisions.setdefault(
                        norad, [self.norad_to_probe[norad]]
                    ).append(oid)
                else:
                    self.norad_to_probe[norad] = oid
            if cospar is not None and norad is None:
                # Cospar fallback only for probes without NORAD claim.
                self.cospar_to_probe.setdefault(cospar, oid)
        for norad, claimants in norad_collisions.items():
            logger.info(
                "joint-launch NORAD %d claimed by multiple probes %s — "
                "owner of celestrak row: %s",
                norad,
                claimants,
                claimants[0],
            )
        logger.info(
            "Loaded %d NORAD + %d COSPAR probe claims for consolidation",
            len(self.norad_to_probe),
            len(self.cospar_to_probe),
        )

    def _parse_row(self, row: dict) -> dict:
        norad = int(row["NORAD_CAT_ID"])
        cospar = string_or_none(row["OBJECT_ID"])
        name = string_or_none(row["OBJECT_NAME"])
        if name == "UNKNOWN":
            name = None

        satcat_object_type = self.satcat_object_types.get(norad)
        if satcat_object_type is None:
            self.missing_satcat += 1
        object_type = (
            ObjectType.debris
            if satcat_object_type
            in (SatcatObjectType.ROCKET_BODY, SatcatObjectType.DEBRIS)
            else ObjectType.spacecraft
        )

        # If a probe row already owns this NORAD (or, fallback, this COSPAR),
        # consolidate: no parallel `norad_satcat-N` Object — the probe row
        # claims the celestrak FK in `_link_celestrak_to_probes`. The probe's
        # `satcat_norad_cat_id` was set at probe-ingest time and isn't touched
        # here.
        probe_object_id = self.norad_to_probe.get(norad)
        if probe_object_id is None and cospar:
            probe_object_id = self.cospar_to_probe.get(cospar)
        has_satcat = norad in self.satcat_object_types
        if probe_object_id is not None:
            obj = None
            claim_object_id = probe_object_id
        else:
            object_id = make_object_id(ID_TYPES.NORAD_SATCAT, row["NORAD_CAT_ID"])
            obj = dict(
                id=object_id,
                name=name,
                object_type=object_type,
                norad_cat_id=norad,
                cospar_id=cospar,
                # CelesTrak row is being minted right now; satcat row may or
                # may not exist for this NORAD.
                celestrak_norad_cat_id=norad,
                satcat_norad_cat_id=norad if has_satcat else None,
                scale=ElementsScale.planet,
                parent_id="naif-399",
                orbital_source=OrbitalSource.spacetrack,
                # Earth sats live in the daily TLE snapshots; rows with no
                # current TLE are dropped at overlay time, not here.
                has_position=True,
            )
            claim_object_id = object_id
        # Orbital elements proper (epoch, mean motion, eccentricity, etc.) are
        # not persisted: the export reads fresh values from the daily snapshot
        # files. Keep only metadata + SGP4 extras the writer reads at export
        # time (those get overwritten per-day too, but ingest seeds them so
        # consumers querying the DB outside export still see something).
        ct = dict(
            OBJECT_NAME=row["OBJECT_NAME"],
            TRAK_OBJECT_ID=row["OBJECT_ID"],
            EPHEMERIS_TYPE=int_or_none(row["EPHEMERIS_TYPE"]),
            CLASSIFICATION_TYPE=string_or_none(row["CLASSIFICATION_TYPE"]),
            NORAD_CAT_ID=norad,
            ELEMENT_SET_NO=int_or_none(row["ELEMENT_SET_NO"]),
            REV_AT_EPOCH=int_or_none(row["REV_AT_EPOCH"]),
            BSTAR=float_or_none(row["BSTAR"]),
            MEAN_MOTION_DOT=float_or_none(row["MEAN_MOTION_DOT"]),
            MEAN_MOTION_DDOT=float_or_none(row["MEAN_MOTION_DDOT"]),
        )
        return {
            "object": obj,
            "celestrak": ct,
            "norad": norad,
            "claim_object_id": claim_object_id,
            "has_satcat": has_satcat,
        }

    def _insert(self, rows: list[dict]) -> None:
        if not rows:
            return
        objects = [r["object"] for r in rows if r["object"] is not None]
        if objects:
            self.session.execute(insert(Object), objects)
        ct_rows = [r["celestrak"] for r in rows]
        self.session.execute(insert(CelesTrakRow), ct_rows)
        self.session.commit()

    def _link_probe_claims(self, rows: list[dict]) -> None:
        """Set FK claim on probe rows consolidating against this batch.

        For rows whose Object is None (consolidated onto a probe via COSPAR
        match), set the probe Object's `celestrak_norad_cat_id` and — if a
        satcat row exists for the NORAD — `satcat_norad_cat_id`. New
        `norad_satcat-N` rows already have these set at insert time.
        """
        ct_updates: list[dict] = []
        sat_updates: list[dict] = []
        for r in rows:
            if r["object"] is not None:
                continue
            ct_updates.append(
                {"id": r["claim_object_id"], "celestrak_norad_cat_id": r["norad"]}
            )
            if r["has_satcat"]:
                sat_updates.append(
                    {"id": r["claim_object_id"], "satcat_norad_cat_id": r["norad"]}
                )
        if ct_updates:
            self.session.execute(update(Object), ct_updates)
        if sat_updates:
            self.session.execute(update(Object), sat_updates)
        if ct_updates or sat_updates:
            self.session.commit()

    def _clear(self) -> None:
        # CelesTrak rows are recomputed from scratch each ingest.
        self.session.execute(delete(CelesTrakRow))
        # Reset stale celestrak claims on probe rows. The satcat FK is owned
        # by probe ingest (which ran before celestrak in the new order) and
        # must not be cleared here — a probe whose celestrak row is gone may
        # still legitimately FK its satcat row.
        self.session.execute(
            update(Object)
            .where(Object.id.like("probe-%"))
            .values(celestrak_norad_cat_id=None)
        )
        # `norad_satcat-%` rows are owned entirely by this ingest — drop them
        # and re-mint as needed.
        self.session.execute(delete(Object).where(Object.id.like("norad_satcat-%")))
        self.session.commit()

    def run(self) -> None:
        if not self.csv_path.exists():
            logger.warning(
                "Space-Track catalogue not found at %s, skipping", self.csv_path
            )
            return
        self._clear()
        self._load_satcat_object_types()
        self._load_probe_claims()
        group_data = load_groups(self.groups_dir)

        total = count_csv_rows(self.csv_path)

        batch: list[dict] = []
        seen_norad: set[int] = set()
        seen_cospar: set[str] = set()
        with open(self.csv_path, newline="") as f:
            for row in tqdm(csv.DictReader(f), total=total, desc="CelesTrak ingest"):
                seen_norad.add(int(row["NORAD_CAT_ID"]))
                cospar = string_or_none(row["OBJECT_ID"])
                if cospar is not None:
                    seen_cospar.add(cospar)
                batch.append(self._parse_row(row))
                self.total_rows += 1

                if len(batch) >= self.BATCH:
                    self._insert(batch)
                    self._link_probe_claims(batch)
                    batch = []
        self._insert(batch)
        self._link_probe_claims(batch)

        # Sats present only in group CSVs (e.g. debris not on the active list).
        batch = []
        group_only = 0
        for norad, row in tqdm(
            group_data.group_only_rows.items(),
            desc="CelesTrak group-only",
            unit="sat",
        ):
            if norad in seen_norad:
                continue
            cospar = string_or_none(row["OBJECT_ID"])
            if cospar is not None and cospar in seen_cospar:
                continue
            if cospar is not None:
                seen_cospar.add(cospar)
            batch.append(self._parse_row(row))
            self.total_rows += 1
            group_only += 1
            if len(batch) >= self.BATCH:
                self._insert(batch)
                self._link_probe_claims(batch)
                batch = []
        self._insert(batch)
        self._link_probe_claims(batch)

        logger.info(
            "Ingested %d CelesTrak satellites (%d from group CSVs only)",
            self.total_rows,
            group_only,
        )
        if self.missing_satcat:
            logger.info(
                "%d/%d satellites had no SATCAT match",
                self.missing_satcat,
                self.total_rows,
            )

        # Backfill Object rows for every satcat entry CelesTrak didn't cover
        # (decayed/inactive sats without current TLEs). A stub still ships in
        # the historical Earth weeks if its NORAD is in the Space-Track archive
        # (has_position then True); the rest are link-only rows so model ingest
        # and any other consumer can resolve them via NORAD.
        self._backfill_inactive_satcat()

    def _backfill_inactive_satcat(self) -> None:
        """Mint `norad_satcat-N` rows for satcat entries no Object yet claims.

        Probe ingest already FK'd every probe whose registry NORAD matches a
        satcat row. The active-celestrak loop set the FK on probes whose
        cospar-only entry matched a satcat row via cospar. Anything still
        unclaimed here is genuinely satcat-only — decayed debris, retired
        birds without current TLEs, satcat dust. Two paths:

        * Cospar matches a probe row that lacks a NORAD in the registry
          (Apollo S-IVB stages etc.) — set the probe's `satcat_norad_cat_id`
          FK; no parallel row minted.
        * No cospar match — mint a `norad_satcat-N` Object with the satcat
          FK set and no `orbital_source`. `has_position` is True iff the NORAD
          appears in the Space-Track archive: those sats ship in the historical
          Earth weeks (the writer's None-source rows inherit the file's
          spacetrack source), so they're renderable in 3D even though they've
          decayed off the current catalogue. Archive-absent stubs stay
          link-only — model ingest + focus URLs still resolve them via NORAD.
        """
        archive_norads = archive_norad_set(ARCHIVE_YEARS)
        # Satcat NORADs already claimed by some Object via the new FK.
        claimed = {
            n
            for (n,) in self.session.execute(
                select(Object.satcat_norad_cat_id).where(
                    Object.satcat_norad_cat_id.is_not(None)
                )
            ).all()
        }
        rows = self.session.execute(
            select(
                Satcat.NORAD_CAT_ID,
                Satcat.OBJECT_NAME,
                Satcat.COSPAR_ID,
                Satcat.object_type,
            )
        ).all()
        rows = [r for r in rows if r[0] not in claimed]
        if not rows:
            return

        new_objects: list[dict] = []
        probe_claim_updates: list[dict] = []
        reused = 0
        archived = 0
        for norad, name, cospar, sotype in rows:
            # Inactive sat whose spacecraft is already a probe row — reuse it
            # via cospar match. The probe row claims the satcat FK; no new
            # Object minted.
            reuse_id = self.cospar_to_probe.get(cospar) if cospar else None
            if reuse_id:
                probe_claim_updates.append(
                    {"id": reuse_id, "satcat_norad_cat_id": norad}
                )
                reused += 1
                continue
            object_id = make_object_id(ID_TYPES.NORAD_SATCAT, norad)
            object_type = (
                ObjectType.debris
                if sotype in (SatcatObjectType.ROCKET_BODY, SatcatObjectType.DEBRIS)
                else ObjectType.spacecraft
            )
            in_archive = norad in archive_norads
            if in_archive:
                archived += 1
            new_objects.append(
                dict(
                    id=object_id,
                    name=name,
                    object_type=object_type,
                    norad_cat_id=norad,
                    cospar_id=cospar,
                    satcat_norad_cat_id=norad,
                    scale=ElementsScale.planet,
                    parent_id="naif-399",
                    orbital_source=None,
                    has_position=in_archive,
                )
            )

        for i in range(0, len(new_objects), self.BATCH):
            self.session.execute(insert(Object), new_objects[i : i + self.BATCH])
        if probe_claim_updates:
            self.session.execute(update(Object), probe_claim_updates)
        self.session.commit()
        logger.info(
            "Backfilled %d inactive SATCAT Object stubs (%d with archive "
            "back-history positions), reused %d existing probe Objects via COSPAR",
            len(new_objects),
            archived,
            reused,
        )


def _day_key(day_dir: Path) -> tuple[int, int, int]:
    """``(year, month, day)`` parsed from a ``.../YYYY/MM/DD`` path, else zeros."""
    try:
        y, m, d = day_dir.parts[-3:]
        return (int(y), int(m), int(d))
    except ValueError:
        return (0, 0, 0)


def ingest(download_dir: Path) -> None:
    CelesTrakIngestor(download_dir).run()
