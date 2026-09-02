"""Ingest CelesTrak satcat.csv into the satcat table (all ~65 k entries)."""

import csv
import logging
from collections import Counter
from pathlib import Path

from sqlalchemy import delete, insert
from tqdm import tqdm

from space_map_data.ingest.convert import count_csv_rows, int_or_none, string_or_none
from space_map_data.ingest.providers.objects.enrichment import (
    GroupData,
    groups_for,
    latest_day_dir,
    load_groups,
    parse_satcat_fields,
    resolve_bus_slug,
    resolve_categories,
    resolve_constellation,
    resolve_country_codes,
    resolve_manufacturer_qids,
    resolve_operator_qids,
)
from space_map_data.ingest.providers.objects.gcat_satcat import (
    GcatHardware,
    load_gcat_hardware,
)
from space_map_data.constants.earth_sats.satcat import SatcatObjectType
from space_map_data.models.object.satcat import Satcat
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)


class SatcatIngestor:
    BATCH = 10_000

    # A GCAT bus string this catalogue does not claim is normal for the long
    # tail (form-factor buckets, one-off platforms); one that covers a lot of
    # satellites means a bus worth naming, or a string GCAT has renamed.
    UNCLAIMED_BUS_REPORT = 20

    def __init__(self, download_dir: Path):
        self.session = get_session()
        self.provider_dir = download_dir / "sources" / "position" / "celestrak"
        self.satcat_path = self.provider_dir / "satcat.csv"
        self.groups_dir = latest_day_dir(self.provider_dir) / "groups"
        self.gcat: dict[int, GcatHardware] = load_gcat_hardware(download_dir)
        self.unclaimed_buses: Counter[str] = Counter()
        self.total_rows = 0
        self.missing_operator = 0
        self.constellation_conflicts = 0

    def _parse_row(self, row: dict[str, str], group_data: GroupData) -> dict | None:
        norad = int_or_none(row.get("NORAD_CAT_ID"))
        if norad is None:
            return None

        name = string_or_none(row.get("OBJECT_NAME"))
        if name == "UNKNOWN":
            name = None
        cospar = string_or_none(row.get("OBJECT_ID"))

        fields = parse_satcat_fields(row)
        owner = fields["owner"]
        groups = groups_for(norad, cospar, group_data)

        constellation = resolve_constellation(norad, name, owner, groups)
        categories = resolve_categories(constellation, groups)
        hardware = self.gcat.get(norad)
        gcat_bus = hardware.bus if hardware else None
        operator_qids = resolve_operator_qids(
            owner,
            constellation,
            fields["launch_date"],
            fields["decay_date"],
            (hardware.owner_code,) if hardware and hardware.owner_code else (),
            (hardware.owner_ucode,) if hardware and hardware.owner_ucode else (),
        )
        manufacturer_qids = resolve_manufacturer_qids(
            constellation,
            hardware.manufacturer_codes if hardware else (),
            hardware.manufacturer_ucodes if hardware else (),
        )
        bus_slug = resolve_bus_slug(norad, gcat_bus)
        if (
            bus_slug is None
            and gcat_bus is not None
            and fields["object_type"] is SatcatObjectType.PAYLOAD
        ):
            self.unclaimed_buses[gcat_bus] += 1
        country_codes = resolve_country_codes(
            owner, hardware.state if hardware else None
        )
        if not operator_qids:
            self.missing_operator += 1

        # Size and mass have no CelesTrak equivalent, so they are GCAT's or absent.
        physical = (
            dict(
                mass_kg=hardware.mass_kg,
                dry_mass_kg=hardware.dry_mass_kg,
                span_m=hardware.span_m,
                length_m=hardware.length_m,
                diameter_m=hardware.diameter_m,
                mass_estimated=hardware.mass_estimated,
                span_estimated=hardware.span_estimated,
            )
            if hardware
            else {}
        )

        return dict(
            NORAD_CAT_ID=norad,
            OBJECT_NAME=name,
            COSPAR_ID=cospar,
            constellation_slug=constellation,
            bus_slug=bus_slug,
            categories=categories,
            operator_qids=operator_qids,
            manufacturer_qids=manufacturer_qids,
            country_codes=country_codes,
            **physical,
            **fields,
        )

    def _insert(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.session.execute(insert(Satcat), rows)
        self.session.commit()

    def _clear(self) -> None:
        self.session.execute(delete(Satcat))
        self.session.commit()

    def run(self) -> None:
        if not self.satcat_path.exists():
            logger.warning("SATCAT CSV not found at %s, skipping", self.satcat_path)
            return

        self._clear()
        group_data = load_groups(self.groups_dir)

        total = count_csv_rows(self.satcat_path)
        batch: list[dict] = []

        with open(self.satcat_path, newline="") as f:
            for row in tqdm(csv.DictReader(f), total=total, desc="SATCAT ingest"):
                parsed = self._parse_row(row, group_data)
                if parsed is None:
                    continue
                batch.append(parsed)
                self.total_rows += 1
                if len(batch) >= self.BATCH:
                    self._insert(batch)
                    batch = []
        self._insert(batch)

        logger.info("Ingested %d SATCAT rows", self.total_rows)
        for bus, count in self.unclaimed_buses.most_common():
            if count < self.UNCLAIMED_BUS_REPORT:
                break
            logger.info("GCAT bus %r covers %d payloads and has no entry", bus, count)
        if self.missing_operator:
            logger.warning(
                "%d/%d satellites could not be matched to an operator",
                self.missing_operator,
                self.total_rows,
            )


def ingest(download_dir: Path) -> None:
    SatcatIngestor(download_dir).run()
