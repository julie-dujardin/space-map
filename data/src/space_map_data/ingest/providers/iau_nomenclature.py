"""Ingest IAU planetary nomenclature KML data into the database."""

import datetime
import logging
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

from sqlalchemy import case, delete, func, insert, update
from tqdm import tqdm

from space_map_data.constants.continents import Continent
from space_map_data.constants.providers import PROVIDERS
from space_map_data.ingest.convert import float_or_none, string_or_none
from space_map_data.models.feature import Feature
from space_map_data.models.object import SBDB, Object, ObjectType
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

KML_NS = "{http://www.opengis.net/kml/2.2}"

# Satellite-feature (SF) -> parent matching.
# SF names look like "<Parent> <A>" / "<Parent> <AB>", sometimes with
# "Inner"/"Outer" tacked on, or with a Latin parent prefix dropped
# ("Pico B" -> "Mons Pico"). When the simple stem misses, the IAU
# ``origin`` field often spells out the parent verbatim.
_SF_SUFFIX_RE = re.compile(r" [A-Z]{1,2}$")
_SF_ORIGIN_RE = re.compile(
    r"^Named (?:for|after)\b[^.()]*?(?:\(([^)]+)\)|\s+([A-Z][^.]+?))\.\s*$"
)
_SF_LATIN_PREFIXES = ("Mons ", "Montes ", "Promontorium ", "Vallis ", "Rupes ", "Rima ")
# Mean radius of the body that owns these features. Only the Moon has SFs.
_SF_MOON_RADIUS_KM = 1737.4
# Beyond this absolute distance the SF can't plausibly be a child of the
# matched parent; treat as a name collision and abort.
_SF_MAX_DISTANCE_KM = 500.0
# Soft warn threshold for small-parent edge cases (Linne, Censorinus, ...)
# where the ratio is huge but the absolute distance is still IAU-plausible.
_SF_WARN_RATIO = 30.0


def _normalize_name(s: str) -> str:
    """Drop apostrophes and collapse whitespace for fuzzy parent matching."""
    return re.sub(r"\s+", " ", s.replace("'", "").replace("'", "")).strip()


def _derive_sf_stem(name: str) -> str | None:
    """Strip Inner/Outer + trailing 1-2 letter SF suffix to get the parent stem."""
    if name.endswith(" Inner"):
        name = name[: -len(" Inner")]
    elif name.endswith(" Outer"):
        name = name[: -len(" Outer")]
    stripped = _SF_SUFFIX_RE.sub("", name)
    return stripped if stripped != name else None


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance on the Moon."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * _SF_MOON_RADIUS_KM * math.asin(math.sqrt(a))


def _parse_approval_date(val: str) -> datetime.date | None:
    """KML ``approvaldt`` is ``'YYYY/MM/DD HH:MM:SS'`` (time always midnight)."""
    val = (val or "").strip()
    if not val:
        return None
    date_part = val.split(" ", 1)[0]
    try:
        return datetime.datetime.strptime(date_part, "%Y/%m/%d").date()
    except ValueError:
        logger.warning("Unparseable IAU approval_date %r, dropping", val)
        return None


def _parse_continent(val: str) -> Continent | None:
    """Normalize the KML ``continent`` label to the Continent enum."""
    val = (val or "").strip()
    if not val:
        return None
    try:
        return Continent(val)
    except ValueError:
        logger.warning("Unknown IAU continent %r, dropping", val)
        return None


def _parse_kml(kml_bytes: bytes, target: str) -> list[dict]:
    """Parse a KML file and return a list of Feature dicts."""
    root = ET.fromstring(kml_bytes)
    rows: list[dict] = []

    for pm in root.iter(f"{KML_NS}Placemark"):
        name_el = pm.find(f"{KML_NS}name")
        if name_el is None or name_el.text is None:
            continue

        # Collect SimpleData fields into a dict.
        fields: dict[str, str] = {}
        for sd in pm.iter(f"{KML_NS}SimpleData"):
            field_name = sd.get("name")
            if field_name is not None and sd.text is not None:
                fields[field_name] = sd.text

        # Extract feature ID from the link URL.
        link = fields.get("link", "")
        if "/Feature/" not in link:
            logger.warning(
                "No feature ID in link %r for %s, skipping", link, name_el.text
            )
            continue
        feature_id = int(link.rsplit("/", 1)[-1])

        rows.append(
            dict(
                feature_id=feature_id,
                name=fields.get("clean_name", name_el.text),
                unicode_name=name_el.text,
                target=target,
                approval_date=_parse_approval_date(fields.get("approvaldt", "")),
                origin=string_or_none(fields.get("origin", "")),
                diameter=float_or_none(fields.get("diameter", "")),
                center_lon=float_or_none(fields.get("center_lon", "")),
                center_lat=float_or_none(fields.get("center_lat", "")),
                feature_type_code=string_or_none(fields.get("code", "")),
                min_lon=float_or_none(fields.get("min_lon", "")),
                max_lon=float_or_none(fields.get("max_lon", "")),
                min_lat=float_or_none(fields.get("min_lat", "")),
                max_lat=float_or_none(fields.get("max_lat", "")),
                ethnicity=string_or_none(fields.get("ethnicity", "")),
                continent=_parse_continent(fields.get("continent", "")),
                quad_name=string_or_none(fields.get("quad_name", "")),
                quad_code=string_or_none(fields.get("quad_code", "")),
            )
        )

    return rows


class IAUNomenclatureIngestor:
    BATCH = 10_000

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.provider_dir = download_dir / PROVIDERS.IAU_NOMENCLATURE
        self.total_rows = 0
        self.seen_ids: set[int] = set()

    def _insert(self, batch: list[dict]) -> None:
        if not batch:
            return
        self.session.execute(insert(Feature), batch)
        self.session.commit()

    def _insert_features(self) -> None:
        kmz_files = sorted(self.provider_dir.glob("*/*.kmz"))
        if not kmz_files:
            logger.warning("No KMZ files found in %s", self.provider_dir)
            return

        batch: list[dict] = []

        for kmz_path in tqdm(kmz_files, desc="IAU nomenclature ingest"):
            target = kmz_path.parent.name

            with zipfile.ZipFile(kmz_path) as zf:
                kml_names = [n for n in zf.namelist() if n.endswith(".kml")]
                if not kml_names:
                    logger.warning("No KML found in %s", kmz_path)
                    continue
                kml_bytes = zf.read(kml_names[0])

            for row in _parse_kml(kml_bytes, target):
                if row["feature_id"] in self.seen_ids:
                    continue
                self.seen_ids.add(row["feature_id"])
                batch.append(row)
                self.total_rows += 1

            if len(batch) >= self.BATCH:
                self._insert(batch)
                batch = []

        self._insert(batch)

    def _match_satellite_features(self) -> int:
        """Link each Satellite Feature to its parent (the named crater/mons/...).

        Raises if any SF ends up > _SF_MAX_DISTANCE_KM from the matched
        parent — that signals a name collision, not a real sub-feature.
        """
        rows = self.session.query(
            Feature.feature_id,
            Feature.name,
            Feature.unicode_name,
            Feature.target,
            Feature.feature_type_code,
            Feature.origin,
            Feature.center_lon,
            Feature.center_lat,
            Feature.diameter,
        ).all()

        by_id = {r.feature_id: r for r in rows}
        by_name: dict[tuple[str, str], list[int]] = defaultdict(list)
        by_norm_unicode: dict[tuple[str, str], list[int]] = defaultdict(list)
        for r in rows:
            by_name[(r.target, r.name)].append(r.feature_id)
            if r.unicode_name:
                by_norm_unicode[(r.target, _normalize_name(r.unicode_name))].append(
                    r.feature_id
                )

        updates: list[dict] = []
        too_far: list[str] = []
        for r in rows:
            if r.feature_type_code != "SF":
                continue
            parent_id = self._resolve_sf_parent(r, by_name, by_norm_unicode)
            if parent_id is None:
                logger.warning(
                    "SF %d %r has no parent on %s, skipping",
                    r.feature_id,
                    r.name,
                    r.target,
                )
                continue

            parent = by_id[parent_id]
            if (
                r.center_lon is not None
                and r.center_lat is not None
                and parent.center_lon is not None
                and parent.center_lat is not None
            ):
                dist = _haversine_km(
                    parent.center_lon, parent.center_lat, r.center_lon, r.center_lat
                )
                parent_r = (parent.diameter or 0.0) / 2.0
                if dist > _SF_MAX_DISTANCE_KM:
                    too_far.append(
                        f"  feature {r.feature_id} {r.name!r} -> "
                        f"{parent_id} {parent.name!r}: {dist:.0f}km"
                    )
                    continue
                if parent_r > 0 and (dist / parent_r) > _SF_WARN_RATIO:
                    logger.warning(
                        "SF %d %r is %.0fkm from parent %r (%.1fx parent radius); "
                        "keeping the link",
                        r.feature_id,
                        r.name,
                        dist,
                        parent.name,
                        dist / parent_r,
                    )
            updates.append({"feature_id": r.feature_id, "parent_feature_id": parent_id})

        if too_far:
            raise RuntimeError(
                f"{len(too_far)} satellite feature(s) matched to a parent "
                f"> {_SF_MAX_DISTANCE_KM:.0f}km away (likely name collision):\n"
                + "\n".join(too_far)
            )

        for batch_start in range(0, len(updates), self.BATCH):
            self.session.execute(
                update(Feature),
                updates[batch_start : batch_start + self.BATCH],
            )
        self.session.commit()
        return len(updates)

    @staticmethod
    def _resolve_sf_parent(
        row,
        by_name: dict[tuple[str, str], list[int]],
        by_norm_unicode: dict[tuple[str, str], list[int]],
    ) -> int | None:
        """Find the parent feature for one SF row.

        Priority: explicit ``origin`` text > exact stem match > normalized
        unicode_name match > stem + Latin prefix in conventional order.
        """
        stem = _derive_sf_stem(row.name)
        if stem is None:
            return None

        # Origin text is authoritative: "Named for Rima Bradley." wins over
        # a naive "Bradley" -> "Mons Bradley" stem guess.
        if row.origin:
            m = _SF_ORIGIN_RE.match(row.origin)
            if m:
                extracted = (m.group(1) or m.group(2) or "").strip()
                hits = by_name.get((row.target, extracted), []) or by_norm_unicode.get(
                    (row.target, _normalize_name(extracted)), []
                )
                hits = [h for h in hits if h != row.feature_id]
                if hits:
                    return hits[0]

        hits = by_name.get((row.target, stem), [])
        if hits:
            return hits[0]

        if row.unicode_name:
            norm = _normalize_name(row.unicode_name)
            stem_norm = _derive_sf_stem(norm) or norm
            hits = [
                h
                for h in by_norm_unicode.get((row.target, stem_norm), [])
                if h != row.feature_id
            ]
            if hits:
                return hits[0]

        for prefix in _SF_LATIN_PREFIXES:
            hits = by_name.get((row.target, prefix + stem), [])
            if hits:
                return hits[0]

        return None

    def _match_to_objects(self) -> int:
        # IAU nomenclature only covers natural bodies, so exclude man-made
        # objects to prevent e.g. the "DEIMOS" Earth-observation satellite
        # shadowing naif-402 (the moon). Also match against SBDB.name so
        # asteroid targets like "bennu" match objects named "101955 Bennu".
        # Prefer planets/moons/dwarf planets over asteroids on name ties so
        # e.g. "titania" hits the Uranian moon, not asteroid 593 Titania.
        excluded = {ObjectType.spacecraft, ObjectType.debris, ObjectType.undocumented}
        priority = case(
            (Object.object_type == ObjectType.planet, 0),
            (Object.object_type == ObjectType.moon, 1),
            (Object.object_type == ObjectType.dwarf_planet, 2),
            else_=3,
        )
        targets = [t for (t,) in self.session.query(Feature.target).distinct().all()]
        matched = 0
        for target in targets:
            obj = (
                self.session.query(Object.id)
                .outerjoin(SBDB, SBDB.object_id == Object.id)
                .where(Object.object_type.notin_(excluded))
                .where(
                    (func.lower(Object.name) == target)
                    | (func.lower(SBDB.name) == target)
                )
                .order_by(priority, Object.id)
                .first()
            )
            if obj is None:
                logger.warning(
                    "IAU nomenclature target %r didn't match any object", target
                )
                continue
            matched += self.session.execute(
                update(Feature)
                .where(Feature.target == target)
                .where(Feature.object_id.is_(None))
                .values(object_id=obj.id)
            ).rowcount  # type: ignore[union-attr]
        self.session.commit()
        return matched

    def run(self) -> None:
        if not self.provider_dir.exists():
            logger.warning(
                "IAU nomenclature dir not found at %s, skipping", self.provider_dir
            )
            return

        self.session.execute(delete(Feature))
        self.session.commit()
        self._insert_features()
        matched = self._match_to_objects()
        sf_linked = self._match_satellite_features()
        logger.info(
            "Ingested %d IAU nomenclature features (%d matched to objects, "
            "%d satellite features linked to parent)",
            self.total_rows,
            matched,
            sf_linked,
        )


def ingest(download_dir: Path) -> None:
    IAUNomenclatureIngestor(download_dir).run()
