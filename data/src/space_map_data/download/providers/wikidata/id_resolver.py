"""Resolve space-map object IDs to Wikidata QIDs via SPARQL."""

import csv
import io
import json
import logging
import time
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATIONS,
    SatelliteCategory,
)
from space_map_data.constants.minor_planet_moons import (
    MINOR_PLANET_MOONS,
    UNLINKED_MINOR_PLANET_MOON_QIDS,
)
from space_map_data.constants.providers import ID_TYPE_TO_WIKIDATA_PID, ID_TYPES
from space_map_data.ingest.providers.wikidata.csv_io import read_ids_csv
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object
from space_map_data.models.object.satcat import Satcat

# Massive constellations only: individual members lack meaningful Wikidata
# entries. Smaller constellations (in PREFIX_TO_SLUG) can have real entries.
CONSTELLATION_PREFIXES = [
    "STARLINK",
    "ONEWEB",
    "IRIDIUM",
    "KUIPER",
    "QIANFAN",
    "HULIANWANG DIGUI",
    "GLOBALSTAR",
    "ORBCOMM",
    "FLOCK",
    "SPACEBEE",
    "SITRO-AIS",
    "GEESAT",
    "GONETS-M",
    "TIANQI",
    "CONNECTA IOT",
    "TIANMU-1",
] + [
    prefix
    for c in CONSTELLATIONS
    if set(c.category) & {SatelliteCategory.DEBRIS, SatelliteCategory.ROCKET}
    and c.prefix
    for prefix in ((c.prefix,) if isinstance(c.prefix, str) else c.prefix)
]

logger = logging.getLogger(__name__)

SPARQL_URL = "https://query.wikidata.org/sparql"

AFTER_REQUEST_DELAY_SECONDS = 2  # pls don't ban me

# Many Wikidata items keep an older SPK-ID series, which SBDB moved by a fixed
# offset: numbered asteroids from 2,000,000 + n, unnumbered ones from 3,000,000.
OLD_SPKID_SERIES = (
    (range(2_000_000, 3_000_000), 18_000_000),
    (range(3_000_000, 4_000_000), 47_000_023),
)

# Past this many lost matches, and this share of the file, a rewrite is held.
MAX_GONE_MATCHES = 100
MAX_GONE_SHARE = 0.1

# "minor planet moon" — instance-of value shared by satellites of asteroids/TNOs.
MINOR_PLANET_MOON_P31_QID = "Q657829"

# Each ID type with the method that lists the IDs we hold for it.
SOURCES = (
    (ID_TYPES.NAIF, "_naif_ids"),
    (ID_TYPES.SPKID, "_spkids"),
    (ID_TYPES.MPC_DESIGNATION, "_mpc_designations"),
    (ID_TYPES.NORAD_SATCAT, "_norad_ids"),
    (ID_TYPES.COSPAR, "_cospar_ids"),
    (ID_TYPES.PROVISIONAL_DESIGNATION, "_provisional_designations"),
    (ID_TYPES.IAU_FEATURE_ID, "_iau_feature_ids"),
)


def _our_forms(id_type: ID_TYPES, value: str) -> tuple[str, ...]:
    """The IDs a Wikidata value can stand for, in the form we hold them."""
    if id_type == ID_TYPES.NORAD_SATCAT and value.isdecimal():
        return (value.zfill(5),)
    if id_type == ID_TYPES.SPKID and value.isdecimal():
        for series, offset in OLD_SPKID_SERIES:
            if int(value) in series:
                return (value, str(int(value) + offset))
    return (value,)


def _is_constellation(name: str | None) -> bool:
    return bool(name) and any(name.startswith(p) for p in CONSTELLATION_PREFIXES)


class WikidataIdResolver:
    """Match the IDs we hold to Wikidata QIDs, one ID type at a time.

    Each type takes one query for every item with its property, and its
    ``matches/<pid>.csv`` under ``ids_dir`` is rewritten whole, so items made
    or removed on Wikidata since the last run are picked up.
    """

    def __init__(
        self,
        client: httpx.Client,
        session: Session,
        ids_dir: Path,
    ) -> None:
        self.client = client
        self.session = session
        self.ids_dir = ids_dir
        self._matches_dir = ids_dir / "matches"
        self._conflicts_dir = ids_dir / "conflicts"

    # -- Public API --

    def resolve(self, id_types: list[ID_TYPES] | None = None) -> set[str]:
        """Match the given ID types (default: all) and return their QIDs,
        with the hand-resolved conflicts of those types."""
        self._matches_dir.mkdir(parents=True, exist_ok=True)
        qids: set[str] = set()
        for id_type, method in SOURCES:
            if id_types is None or id_type in id_types:
                pid = ID_TYPE_TO_WIKIDATA_PID[id_type]
                try:
                    mapping = self._resolve(id_type, getattr(self, method)())
                except (httpx.HTTPError, RuntimeError) as exc:
                    logger.error("  %s: query failed, kept the old file: %s", pid, exc)
                    mapping = self._read_ids_csv(pid)
                for matched in mapping.values():
                    qids.update(matched)
        qids.update(self._read_resolved_conflict_qids(id_types))
        return qids

    def warn_minor_planet_moon_drift(self) -> None:
        """Warn when Wikidata's P31=Q657829 set diverges from our hardcoded table.

        Minor-planet moons are linked from a hand-curated constant (their
        synthetic SPK-IDs match no external-ID property), so this doesn't change
        any linkage — it only flags, in either direction, moons to add or
        hardcoded entries that Wikidata reclassified/renamed, for manual review.
        """
        query = (
            "SELECT ?item ?itemLabel WHERE {\n"
            f"  ?item wdt:P31 wd:{MINOR_PLANET_MOON_P31_QID} .\n"
            '  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }\n'
            "}"
        )
        try:
            results = self._sparql_query(query)
        except (httpx.HTTPError, RuntimeError) as exc:
            logger.warning("Minor-planet-moon drift check skipped: %s", exc)
            return

        live = {
            row["item"]["value"].rsplit("/", 1)[-1]: row.get("itemLabel", {}).get(
                "value", ""
            )
            for row in results
        }
        hardcoded = {m.qid: m for m in MINOR_PLANET_MOONS}
        new_qids = live.keys() - hardcoded.keys() - UNLINKED_MINOR_PLANET_MOON_QIDS
        stale_qids = hardcoded.keys() - live.keys()
        for qid in sorted(new_qids):
            logger.warning(
                "Minor-planet moon %r (%s) is P31=Q657829 on Wikidata but not in "
                "constants/minor_planet_moons.py — consider adding",
                live[qid],
                qid,
            )
        for qid in sorted(stale_qids):
            moon = hardcoded[qid]
            logger.warning(
                "Hardcoded minor-planet moon %r (%s, parent %s) is no longer "
                "P31=Q657829 on Wikidata — renamed or reclassified?",
                moon.name,
                qid,
                moon.parent,
            )
        logger.info(
            "Minor-planet-moon drift: %d live, %d hardcoded, %d new, %d stale",
            len(live),
            len(hardcoded),
            len(new_qids),
            len(stale_qids),
        )

    # -- Match CSV --

    def _ids_csv_path(self, key: str) -> Path:
        return self._matches_dir / f"{key}.csv"

    def _read_ids_csv(self, key: str) -> dict[str, list[str]]:
        csv_path = self._ids_csv_path(key)
        return read_ids_csv(csv_path) if csv_path.exists() else {}

    def _write_ids_csv(self, key: str, mapping: dict[str, list[str]]) -> None:
        """Replace a property CSV with these rows."""
        buf = io.StringIO()
        writer = csv.writer(buf)
        for id_, qids in mapping.items():
            writer.writerow([id_, " ".join(qids)])
        csv_path = self._ids_csv_path(key)
        tmp = csv_path.with_suffix(".csv.tmp")
        tmp.write_text(buf.getvalue())
        tmp.replace(csv_path)

    # -- Resolved-conflict CSV --

    @staticmethod
    def _id_type_from_object_id(object_id: str) -> ID_TYPES | None:
        """Identify the ID_TYPES prefix of an object_id like ``naif--164``.

        Tolerates both the canonical ``<type>-<value>`` and a stray
        ``<type>:<value>`` form that has shown up in the manual CSV.
        """
        for id_type in ID_TYPES:
            prefix = str(id_type)
            if object_id.startswith((f"{prefix}-", f"{prefix}:")):
                return id_type
        return None

    def _read_resolved_conflict_qids(self, id_types: list[ID_TYPES] | None) -> set[str]:
        """QIDs from resolved_conflicts.csv whose object_id prefix matches id_types."""
        csv_path = self._conflicts_dir / "resolved_conflicts.csv"
        if not csv_path.exists():
            return set()
        allowed = set(id_types) if id_types is not None else None
        qids: set[str] = set()
        skipped = 0
        for row in csv.reader(io.StringIO(csv_path.read_text())):
            if not row or len(row) < 2:
                continue
            object_id, qid = row[0].strip(), row[1].strip()
            if not object_id or not qid:
                continue
            id_type = self._id_type_from_object_id(object_id)
            if id_type is None:
                logger.warning(
                    "resolved_conflicts.csv: unrecognized id_type prefix in %r",
                    object_id,
                )
                skipped += 1
                continue
            if allowed is None or id_type in allowed:
                qids.add(qid)
        if skipped:
            logger.warning(
                "resolved_conflicts.csv: skipped %d row(s) with unknown prefix",
                skipped,
            )
        return qids

    # -- Resolution --

    def _resolve(self, id_type: ID_TYPES, ours: set[str]) -> dict[str, list[str]]:
        """Match every Wikidata value of the type's property to the IDs we hold,
        and rewrite its match CSV. A result that would empty the file or drop a
        large share of it leaves the old file in place: it is rewritten whole,
        so a partial DB or a short answer would otherwise strip the QIDs."""
        pid = ID_TYPE_TO_WIKIDATA_PID[id_type]
        rows = self._sparql_query(f"SELECT ?item ?id WHERE {{ ?item wdt:{pid} ?id . }}")
        found: dict[str, set[str]] = {}
        for row in rows:
            forms = _our_forms(id_type, row["id"]["value"])
            key = next((f for f in forms if f in ours), None)
            if key is not None:
                qid = row["item"]["value"].rsplit("/", 1)[-1]
                found.setdefault(key, set()).add(qid)
        mapping = {k: sorted(found[k]) for k in sorted(found)}

        old = self._read_ids_csv(pid)
        gone = len(old.keys() - mapping.keys())
        changed = sum(
            1 for k in mapping.keys() & old.keys() if set(old[k]) != set(mapping[k])
        )
        logger.info(
            "  %s (%s): %d Wikidata values, %d of our %d IDs matched "
            "(%d new, %d gone, %d changed, %d with several items)",
            pid,
            id_type,
            len(rows),
            len(mapping),
            len(ours),
            len(mapping.keys() - old.keys()),
            gone,
            changed,
            sum(1 for q in mapping.values() if len(q) > 1),
        )
        if not mapping or gone > max(MAX_GONE_MATCHES, len(old) * MAX_GONE_SHARE):
            logger.error(
                "  %s: held %d of %d old rows that no longer match; delete "
                "matches/%s.csv to let them go",
                pid,
                gone,
                len(old),
                pid,
            )
            mapping = {
                k: old.get(k) or mapping[k] for k in sorted(old.keys() | mapping.keys())
            }
        self._write_ids_csv(pid, mapping)
        return mapping

    # -- The IDs we hold --

    def _naif_ids(self) -> set[str]:
        # Natural bodies: NAIF reuses spacecraft IDs, so a negative one can
        # name another craft on Wikidata.
        stmt = select(Object.naif_id).where(Object.naif_id >= 0)
        return {str(n) for n in self.session.scalars(stmt) if n is not None}

    def _spkids(self) -> set[str]:
        # Object.spkid, as the ingest matches P716: SBDB rows and the moons.
        stmt = select(Object.spkid).where(Object.spkid.is_not(None))
        return {str(n) for n in self.session.scalars(stmt) if n is not None}

    def _mpc_designations(self) -> set[str]:
        # The ingest matches P5736 on both columns.
        rows = self.session.execute(
            select(Object.mpc_designation, Object.provisional_designation).where(
                Object.mpc_designation.is_not(None)
                | Object.provisional_designation.is_not(None)
            )
        )
        return {v for row in rows for v in row if v}

    def _provisional_designations(self) -> set[str]:
        stmt = select(Object.provisional_designation).where(
            Object.provisional_designation.is_not(None)
        )
        return {v for v in self.session.scalars(stmt) if v}

    def _norad_ids(self) -> set[str]:
        ids = self._satellite_ids(Object.norad_cat_id, Satcat.NORAD_CAT_ID)
        return {str(n).zfill(5) for n in ids}

    def _cospar_ids(self) -> set[str]:
        return {str(c) for c in self._satellite_ids(Object.cospar_id, Satcat.COSPAR_ID)}

    def _satellite_ids(self, object_col, satcat_col) -> set:
        """Satellites outside the big constellations, with the Satcat rows no
        Object claims."""
        claimed = select(Object.satcat_norad_cat_id).where(
            Object.satcat_norad_cat_id.is_not(None)
        )
        rows = [
            *self.session.execute(
                select(object_col, Object.name).where(object_col.is_not(None))
            ),
            *self.session.execute(
                select(satcat_col, Satcat.OBJECT_NAME).where(
                    satcat_col.is_not(None), Satcat.NORAD_CAT_ID.notin_(claimed)
                )
            ),
        ]
        return {v for v, name in rows if v is not None and not _is_constellation(name)}

    def _iau_feature_ids(self) -> set[str]:
        stmt = select(Feature.feature_id).where(Feature.feature_id.is_not(None))
        return {str(f) for f in self.session.scalars(stmt) if f is not None}

    # -- SPARQL --

    def _sparql_query(self, query: str) -> list[dict]:
        """Execute a SPARQL query, retrying on 429, a server error, a timeout
        and a cut-off answer."""
        max_retries = 6
        for attempt in range(max_retries + 1):
            backoff = min(2 ** (attempt + 1), 60)
            try:
                response = self.client.post(
                    SPARQL_URL,
                    data={"query": query},
                    headers={"Accept": "application/sparql-results+json"},
                    timeout=120.0,
                )
            except httpx.TimeoutException:
                logger.warning("SPARQL timed out — retrying in %ds", backoff)
                time.sleep(backoff)
                continue
            if response.status_code >= 500:
                logger.warning(
                    "SPARQL %d — retrying in %ds", response.status_code, backoff
                )
                time.sleep(backoff)
                continue
            if response.status_code == 429:
                retry_after_header = response.headers.get("retry-after")
                if retry_after_header:
                    retry_after = int(retry_after_header)
                else:
                    retry_after = backoff
                logger.warning("SPARQL 429 — retrying in %ds", retry_after)
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            time.sleep(AFTER_REQUEST_DELAY_SECONDS)
            try:
                return response.json()["results"]["bindings"]
            except json.JSONDecodeError:
                # WDQS sends 200 and then stops a long answer at its time limit.
                logger.warning(
                    "SPARQL answer cut off at %d bytes — retrying in %ds",
                    len(response.content),
                    backoff,
                )
                time.sleep(backoff)

        raise RuntimeError("SPARQL failed after retries")
