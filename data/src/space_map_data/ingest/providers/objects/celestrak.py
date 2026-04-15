"""Ingest CelesTrak gp-active.csv + satcat.csv + group files into the database."""

import csv
import logging
from pathlib import Path

from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_BY_SLUG,
    GROUP_TO_CATEGORY,
    GROUP_TO_SLUG,
    PREFERRED_SLUGS,
    SOURCE_TO_SLUG,
    UNPREFERRED_SLUGS,
    slug_from_name,
)
from space_map_data.constants.earth_sats.launch_sites import LAUNCH_SITE_CODES
from space_map_data.constants.earth_sats.operators import (
    OPERATOR_BY_CONSTELLATION,
    OPERATOR_BY_SOURCE,
)
from space_map_data.constants.providers import ID_TYPES, PROVIDERS, make_object_id
from space_map_data.constants.earth_sats.satcat import (
    parse_data_status,
    parse_object_type,
    parse_ops_status,
    parse_orbit_center,
    parse_orbit_type,
)
from space_map_data.constants.earth_sats.sources import SOURCE_BY_CODE, parse_source
from sqlalchemy import delete, insert
from tqdm import tqdm

from space_map_data.models.object import (
    Object,
    ObjectType,
    CelesTrak as CelesTrakRow,
    ElementsScale,
    OrbitalSource,
)
from space_map_data.ingest.convert import (
    mean_motion_to_a_km,
    float_or_none,
    int_or_none,
    string_or_none,
)
from space_map_data.utils.convert import date_to_julian
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


class CelesTrakIngestor:
    BATCH = 10_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.provider_dir = download_dir / PROVIDERS.CELESTRAK
        self.csv_path = self.provider_dir / "gp-active.csv"
        self.satcat_path = self.provider_dir / "satcat.csv"
        self.groups_dir = self.provider_dir / "groups"
        self.total_rows = 0
        self.missing_satcat = 0
        self.missing_operator = 0
        self.constellation_conflicts = 0
        self.satcat: dict[int, dict[str, str]] = {}
        # Group memberships indexed two ways so sats sharing a COSPAR across
        # NORADs (analyst entries etc.) still inherit each other's group tags.
        self.group_memberships_by_norad: dict[int, set[str]] = {}
        self.group_memberships_by_cospar: dict[str, set[str]] = {}
        # norad -> TLE row sourced from a group CSV (used for sats missing
        # from gp-active.csv, e.g. debris not on the active list)
        self.group_only_rows: dict[int, dict[str, str]] = {}

    def _load_satcat(self) -> None:
        if not self.satcat_path.exists():
            logger.warning(
                "SATCAT not found at %s; skipping enrichment", self.satcat_path
            )
            return
        with open(self.satcat_path, newline="") as f:
            for row in csv.DictReader(f):
                norad = int_or_none(row.get("NORAD_CAT_ID"))
                if norad is None:
                    continue
                self.satcat[norad] = row
        logger.info("Loaded %d SATCAT rows", len(self.satcat))

    def _load_groups(self) -> None:
        """Record group membership + stash full TLE rows for later fallback."""
        if not self.groups_dir.exists():
            logger.warning(
                "Groups dir not found at %s; skipping group tagging",
                self.groups_dir,
            )
            return
        for group_file in sorted(self.groups_dir.glob("*.csv")):
            group = group_file.stem
            if group not in GROUP_TO_SLUG and group not in GROUP_TO_CATEGORY:
                logger.warning(
                    "Group file %s has no mapped slug or category; skipping",
                    group_file.name,
                )
                continue
            if group_file.stat().st_size == 0:
                logger.info("Group file %s is empty", group_file.name)
                continue
            count = 0
            with open(group_file, newline="") as f:
                for row in csv.DictReader(f):
                    norad = int_or_none(row.get("NORAD_CAT_ID"))
                    if norad is None:
                        continue
                    self.group_memberships_by_norad.setdefault(norad, set()).add(group)
                    cospar = string_or_none(row.get("OBJECT_ID"))
                    if cospar is not None:
                        self.group_memberships_by_cospar.setdefault(cospar, set()).add(
                            group
                        )
                    self.group_only_rows.setdefault(norad, row)
                    count += 1
            logger.info("Group %s -> %d sats", group, count)

    def _resolve_constellation(
        self,
        norad: int,
        name: str | None,
        owner: str | None,
        groups: set[str],
    ) -> str | None:
        """Pick a single constellation slug; log an error if candidates disagree."""
        candidates: list[tuple[str, str]] = []  # (source, slug)
        name_slug = slug_from_name(name)
        if name_slug is not None:
            candidates.append(("name-prefix", name_slug))
        for group in groups:
            group_slug = GROUP_TO_SLUG.get(group)
            if group_slug is not None:
                candidates.append((f"group:{group}", group_slug))
        if owner is not None:
            owner_slug = SOURCE_TO_SLUG.get(owner)
            if owner_slug is not None:
                candidates.append((f"owner:{owner}", owner_slug))

        if not candidates:
            return None
        unique = {slug for _, slug in candidates}
        if len(unique) == 1:
            return candidates[0][1]

        # Conflict: try the explicit preference list before the priority order.
        preferred = next(
            (slug for slug in PREFERRED_SLUGS if slug in unique),
            None,
        )
        if preferred is not None:
            return preferred
        # Drop any unpreferred candidates if a real alternative exists.
        filtered = [c for c in candidates if c[1] not in UNPREFERRED_SLUGS]
        if filtered and {slug for _, slug in filtered} != unique:
            return filtered[0][1]
        self.constellation_conflicts += 1
        logger.error(
            "NORAD %d has conflicting constellation matches: %s — picking %s",
            norad,
            ", ".join(f"{src}={slug}" for src, slug in candidates),
            candidates[0][1],
        )
        return candidates[0][1]

    def _resolve_categories(
        self, constellation: str | None, groups: set[str]
    ) -> list[str]:
        cats: set[str] = set()
        if constellation is not None:
            spec = CONSTELLATION_BY_SLUG.get(constellation)
            if spec is not None:
                cats.add(spec.category.value)
        for group in groups:
            cat = GROUP_TO_CATEGORY.get(group)
            if cat is not None:
                cats.add(cat.value)
        return sorted(cats)

    def _resolve_operator_qids(
        self, owner: str | None, constellation: str | None
    ) -> list[str]:
        qids: set[str] = set()
        if owner is not None:
            op = OPERATOR_BY_SOURCE.get(owner)
            if op is not None and op.wikidata_qid is not None:
                qids.add(op.wikidata_qid)
        if constellation is not None:
            op = OPERATOR_BY_CONSTELLATION.get(constellation)
            if op is not None and op.wikidata_qid is not None:
                qids.add(op.wikidata_qid)
        return sorted(qids)

    def _resolve_country_codes(self, owner: str | None) -> list[str]:
        if owner is None:
            return []
        source = SOURCE_BY_CODE.get(owner)
        if source is None:
            return []
        return list(source.countries)

    def _parse_row(self, row: dict) -> dict:
        mean_motion = float_or_none(row["MEAN_MOTION"])
        a_km = mean_motion_to_a_km(mean_motion) if mean_motion else None

        object_id = make_object_id(ID_TYPES.NORAD_SATCAT, row["NORAD_CAT_ID"])
        norad = int(row["NORAD_CAT_ID"])
        name = string_or_none(row["OBJECT_NAME"])
        if name == "UNKNOWN":
            name = None
        sat = self.satcat.get(norad)
        if sat is None:
            self.missing_satcat += 1
        satcat_fields = _satcat_fields(sat)
        owner = satcat_fields["owner"]
        cospar = string_or_none(row["OBJECT_ID"])
        groups = set(self.group_memberships_by_norad.get(norad, set()))
        if cospar is not None:
            groups |= self.group_memberships_by_cospar.get(cospar, set())
        constellation = self._resolve_constellation(norad, name, owner, groups)
        categories = self._resolve_categories(constellation, groups)
        operator_qids = self._resolve_operator_qids(owner, constellation)
        country_codes = self._resolve_country_codes(owner)
        if not operator_qids:
            self.missing_operator += 1

        obj = dict(
            id=object_id,
            name=name,
            object_type=ObjectType.spacecraft,
            celestrak_norad_cat_id=norad,
            celestrak_cospar_id=string_or_none(row["OBJECT_ID"]),
            epoch_jd=date_to_julian(row["EPOCH"]),
            a=a_km,
            e=float_or_none(row["ECCENTRICITY"]),
            i=float_or_none(row["INCLINATION"]),
            om=float_or_none(row["RA_OF_ASC_NODE"]),
            w=float_or_none(row["ARG_OF_PERICENTER"]),
            ma=float_or_none(row["MEAN_ANOMALY"]),
            n=mean_motion,
            scale=ElementsScale.planet,
            parent_naif_id=399,
            orbital_source=OrbitalSource.celestrak,
        )
        ct = dict(
            object_id=object_id,
            OBJECT_NAME=row["OBJECT_NAME"],
            TRAK_OBJECT_ID=row["OBJECT_ID"],
            EPOCH=row["EPOCH"],
            MEAN_MOTION=mean_motion,
            ECCENTRICITY=float_or_none(row["ECCENTRICITY"]),
            INCLINATION=float_or_none(row["INCLINATION"]),
            RA_OF_ASC_NODE=float_or_none(row["RA_OF_ASC_NODE"]),
            ARG_OF_PERICENTER=float_or_none(row["ARG_OF_PERICENTER"]),
            MEAN_ANOMALY=float_or_none(row["MEAN_ANOMALY"]),
            EPHEMERIS_TYPE=int_or_none(row["EPHEMERIS_TYPE"]),
            CLASSIFICATION_TYPE=string_or_none(row["CLASSIFICATION_TYPE"]),
            NORAD_CAT_ID=norad,
            ELEMENT_SET_NO=int_or_none(row["ELEMENT_SET_NO"]),
            REV_AT_EPOCH=int_or_none(row["REV_AT_EPOCH"]),
            BSTAR=float_or_none(row["BSTAR"]),
            MEAN_MOTION_DOT=float_or_none(row["MEAN_MOTION_DOT"]),
            MEAN_MOTION_DDOT=float_or_none(row["MEAN_MOTION_DDOT"]),
            constellation_slug=constellation,
            categories=categories,
            operator_qids=operator_qids,
            country_codes=country_codes,
            **satcat_fields,
        )
        return {"object": obj, "celestrak": ct}

    def _insert(self, rows: list[dict]) -> None:
        if not rows:
            return
        objects = [r["object"] for r in rows]
        self.session.execute(insert(Object), objects)
        ct_rows = [r["celestrak"] for r in rows]
        self.session.execute(insert(CelesTrakRow), ct_rows)
        self.session.commit()

    def _clear(self) -> None:
        self.session.execute(delete(CelesTrakRow))
        self.session.execute(
            delete(Object).where(Object.orbital_source == OrbitalSource.celestrak)
        )
        self.session.commit()

    def run(self) -> None:
        if not self.csv_path.exists():
            logger.warning("CelesTrak CSV not found at %s, skipping", self.csv_path)
            return
        self._clear()
        self._load_satcat()
        self._load_groups()

        total = _count_csv_rows(self.csv_path)

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
                    batch = []
        self._insert(batch)

        # Sats present only in group CSVs (e.g. debris not on the active list).
        batch = []
        group_only = 0
        for norad, row in tqdm(
            self.group_only_rows.items(), desc="CelesTrak group-only", unit="sat"
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
                batch = []
        self._insert(batch)

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
        if self.missing_operator:
            logger.warning(
                "%d/%d satellites could not be matched to an operator",
                self.missing_operator,
                self.total_rows,
            )
        if self.constellation_conflicts:
            logger.error(
                "%d satellites had conflicting constellation matches",
                self.constellation_conflicts,
            )


def _count_csv_rows(path: Path) -> int:
    with open(path) as f:
        return sum(1 for _ in f) - 1


_EMPTY_SATCAT: dict[str, None] = {
    "object_type": None,
    "ops_status": None,
    "owner": None,
    "launch_date": None,
    "launch_site_code": None,
    "decay_date": None,
    "period": None,
    "apogee": None,
    "perigee": None,
    "rcs": None,
    "data_status": None,
    "orbit_center": None,
    "orbit_center_docked_to": None,
    "orbit_type": None,
}


def _satcat_fields(sat: dict[str, str] | None) -> dict:
    if sat is None:
        return dict(_EMPTY_SATCAT)
    orbit_center, docked_to = parse_orbit_center(sat["ORBIT_CENTER"])
    launch_site_code = string_or_none(sat["LAUNCH_SITE"])
    if launch_site_code is not None and launch_site_code not in LAUNCH_SITE_CODES:
        raise ValueError(f"Unknown SATCAT LAUNCH_SITE code: {launch_site_code!r}")
    return dict(
        object_type=parse_object_type(sat["OBJECT_TYPE"]),
        ops_status=parse_ops_status(sat["OPS_STATUS_CODE"]),
        owner=parse_source(sat["OWNER"]),
        launch_date=string_or_none(sat["LAUNCH_DATE"]),
        launch_site_code=launch_site_code,
        decay_date=string_or_none(sat["DECAY_DATE"]),
        period=float_or_none(sat["PERIOD"]),
        apogee=float_or_none(sat["APOGEE"]),
        perigee=float_or_none(sat["PERIGEE"]),
        rcs=float_or_none(sat["RCS"]),
        data_status=parse_data_status(sat["DATA_STATUS_CODE"]),
        orbit_center=orbit_center,
        orbit_center_docked_to=docked_to,
        orbit_type=parse_orbit_type(sat["ORBIT_TYPE"]),
    )


def ingest(download_dir: Path) -> None:
    CelesTrakIngestor(download_dir).run()
