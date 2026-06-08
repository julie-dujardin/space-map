"""SQLAlchemy ORM model for the SATCAT table (CelesTrak satellite catalogue)."""

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from space_map_data.constants.earth_sats.satcat import (
    DataStatus,
    OpsStatus,
    OrbitCenter,
    OrbitType,
    SatcatObjectType,
)
from space_map_data.models.object.base import Base


class Satcat(Base):
    """Full mirror of CelesTrak satcat.csv — all ~65 k entries.

    The Object→Satcat link lives on the Object side (`Object.satcat_norad_cat_id`).
    Multiple Objects can claim the same Satcat row when a joint launch (e.g.
    Cassini+Huygens, NORAD 25008) gets one probe row per sub-spacecraft.
    """

    __tablename__ = "satcat"

    NORAD_CAT_ID: Mapped[int] = mapped_column(primary_key=True)

    OBJECT_NAME: Mapped[str | None] = mapped_column(default=None)
    COSPAR_ID: Mapped[str | None] = mapped_column(default=None)

    # SATCAT fields — see https://celestrak.org/satcat/satcat-format.php
    object_type: Mapped[SatcatObjectType | None] = mapped_column(String, default=None)
    ops_status: Mapped[OpsStatus | None] = mapped_column(String, default=None)
    owner: Mapped[str | None] = mapped_column(String, default=None)
    launch_date: Mapped[str | None] = mapped_column(default=None)
    launch_site_code: Mapped[str | None] = mapped_column(default=None)
    decay_date: Mapped[str | None] = mapped_column(default=None)
    period: Mapped[float | None] = mapped_column(default=None)
    apogee: Mapped[float | None] = mapped_column(default=None)
    perigee: Mapped[float | None] = mapped_column(default=None)
    rcs: Mapped[float | None] = mapped_column(default=None)
    data_status: Mapped[DataStatus | None] = mapped_column(String, default=None)
    orbit_center: Mapped[OrbitCenter | None] = mapped_column(String, default=None)
    orbit_center_docked_to: Mapped[int | None] = mapped_column(default=None)
    orbit_type: Mapped[OrbitType | None] = mapped_column(String, default=None)

    # Enrichment (derived from SATCAT owner, object name, group memberships)
    constellation_slug: Mapped[str | None] = mapped_column(default=None)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    operator_qids: Mapped[list[str]] = mapped_column(JSON, default=list)
    manufacturer_qids: Mapped[list[str]] = mapped_column(JSON, default=list)
    country_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    wikidata_qid: Mapped[str | None] = mapped_column(default=None, index=True)
