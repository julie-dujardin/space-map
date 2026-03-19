"""Ingest IAU planetary nomenclature KML data into the database."""

import logging
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from sqlalchemy import func, insert, update
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.ingest.convert import float_or_none, string_or_none
from space_map_data.models.feature import Feature
from space_map_data.models.object import Object
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

KML_NS = "{http://www.opengis.net/kml/2.2}"
BATCH = 10_000


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
                approval_date=string_or_none(fields.get("approvaldt", "")),
                origin=string_or_none(fields.get("origin", "")),
                diameter=float_or_none(fields.get("diameter", "")),
                center_lon=float_or_none(fields.get("center_lon", "")),
                center_lat=float_or_none(fields.get("center_lat", "")),
                feature_type=string_or_none(fields.get("type", "")),
                feature_type_code=string_or_none(fields.get("code", "")),
                approval_status=string_or_none(fields.get("approval", "")),
                min_lon=float_or_none(fields.get("min_lon", "")),
                max_lon=float_or_none(fields.get("max_lon", "")),
                min_lat=float_or_none(fields.get("min_lat", "")),
                max_lat=float_or_none(fields.get("max_lat", "")),
                ethnicity=string_or_none(fields.get("ethnicity", "")),
                continent=string_or_none(fields.get("continent", "")),
                quad_name=string_or_none(fields.get("quad_name", "")),
                quad_code=string_or_none(fields.get("quad_code", "")),
            )
        )

    return rows


class IAUNomenclatureIngestor:
    BATCH = 10_000

    def __init__(self, download_dir: Path, *, limit: int | None = None):
        self.session = get_session()
        self.limit = limit
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

            if self.limit and self.total_rows >= self.limit:
                break

        self._insert(batch)

    def _match_to_objects(self) -> int:
        # Build a lookup from the ~50 distinct targets instead of a
        # correlated subquery over 1.5M objects.
        targets = [t for (t,) in self.session.query(Feature.target).distinct().all()]
        matched = 0
        for target in targets:
            obj = (
                self.session.query(Object.id)
                .where(func.lower(Object.name) == target)
                .first()
            )
            if obj is None:
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

        self._insert_features()
        matched = self._match_to_objects()
        logger.info(
            "Ingested %d IAU nomenclature features (%d matched to objects)",
            self.total_rows,
            matched,
        )


def ingest(download_dir: Path, *, limit: int | None = None) -> None:
    IAUNomenclatureIngestor(download_dir, limit=limit).run()
