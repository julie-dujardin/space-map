"""SQLAlchemy ORM model for the CelesTrak table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from space_map_data.constants.earth_sats.satcat import (
    DataStatus,
    OpsStatus,
    OrbitCenter,
    OrbitType,
    SatcatObjectType,
)
from space_map_data.models.object.base import Base

if TYPE_CHECKING:
    from space_map_data.models.object.main import Object


class CelesTrak(Base):
    """Full mirror of celes-trak/gp-active.csv."""

    __tablename__ = "celestrak"

    NORAD_CAT_ID: Mapped[int] = mapped_column(primary_key=True)  # NORAD catalog number
    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), unique=True)

    OBJECT_NAME: Mapped[str | None] = mapped_column(default=None)  # satellite name
    TRAK_OBJECT_ID: Mapped[str | None] = mapped_column(
        default=None
    )  # international designator / COSPAR ID (YYYY-NNNP)
    EPOCH: Mapped[str | None] = mapped_column(
        default=None
    )  # element set epoch [ISO 8601 UTC]
    MEAN_MOTION: Mapped[float | None] = mapped_column(
        default=None
    )  # mean motion [rev/d]
    ECCENTRICITY: Mapped[float | None] = mapped_column(default=None)  # eccentricity
    INCLINATION: Mapped[float | None] = mapped_column(default=None)  # inclination [deg]
    RA_OF_ASC_NODE: Mapped[float | None] = mapped_column(
        default=None
    )  # right ascension of ascending node [deg]
    ARG_OF_PERICENTER: Mapped[float | None] = mapped_column(
        default=None
    )  # argument of perigee [deg]
    MEAN_ANOMALY: Mapped[float | None] = mapped_column(
        default=None
    )  # mean anomaly [deg]
    EPHEMERIS_TYPE: Mapped[int | None] = mapped_column(
        default=None
    )  # ephemeris type (0=SGP4)
    CLASSIFICATION_TYPE: Mapped[str | None] = mapped_column(
        default=None
    )  # classification (U=unclassified, C=classified, S=secret)
    ELEMENT_SET_NO: Mapped[int | None] = mapped_column(
        default=None
    )  # element set number
    REV_AT_EPOCH: Mapped[int | None] = mapped_column(
        default=None
    )  # revolution number at epoch
    BSTAR: Mapped[float | None] = mapped_column(
        default=None
    )  # B* drag term [1/Earth radii]
    MEAN_MOTION_DOT: Mapped[float | None] = mapped_column(
        default=None
    )  # first derivative of mean motion [rev/d²]
    MEAN_MOTION_DDOT: Mapped[float | None] = mapped_column(
        default=None
    )  # second derivative of mean motion [rev/d³]

    # SATCAT fields (from satcat.csv). See https://celestrak.org/satcat/satcat-format.php
    object_type: Mapped[SatcatObjectType | None] = mapped_column(String, default=None)
    ops_status: Mapped[OpsStatus | None] = mapped_column(String, default=None)
    # SATCAT OWNER code; references SOURCES in constants/earth_sats/sources.py
    owner: Mapped[str | None] = mapped_column(String, default=None)
    launch_date: Mapped[str | None] = mapped_column(default=None)  # ISO date
    decay_date: Mapped[str | None] = mapped_column(default=None)  # ISO date
    period: Mapped[float | None] = mapped_column(default=None)  # minutes
    apogee: Mapped[float | None] = mapped_column(default=None)  # km
    perigee: Mapped[float | None] = mapped_column(default=None)  # km
    rcs: Mapped[float | None] = mapped_column(default=None)  # m²
    data_status: Mapped[DataStatus | None] = mapped_column(String, default=None)
    orbit_center: Mapped[OrbitCenter | None] = mapped_column(String, default=None)
    # NORAD catalog number of the object this one is docked to (only set when
    # orbit_center == DOCKED).
    orbit_center_docked_to: Mapped[int | None] = mapped_column(default=None)
    orbit_type: Mapped[OrbitType | None] = mapped_column(String, default=None)

    # References LAUNCH_SITES in constants/earth_sats/launch_sites.py
    launch_site_code: Mapped[str | None] = mapped_column(default=None)
    # References CONSTELLATIONS in constants/earth_sats/constellations.py
    constellation_slug: Mapped[str | None] = mapped_column(default=None)
    # SatelliteCategory values. A sat can belong to several (e.g. GPS is both
    # navigation and military).
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Wikidata QIDs of matched operators (OPERATOR_BY_SOURCE ∪ OPERATOR_BY_CONSTELLATION).
    operator_qids: Mapped[list[str]] = mapped_column(JSON, default=list)
    # ISO 3166-1 alpha-2 country codes derived from SATCAT owner → SOURCES.
    country_codes: Mapped[list[str]] = mapped_column(JSON, default=list)

    object: Mapped["Object"] = relationship(back_populates="celestrak")
