"""SQLAlchemy ORM model for the CelesTrak table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    # SATCAT fields (from satcat.csv)
    OBJECT_TYPE: Mapped[str | None] = mapped_column(default=None)  # PAY/R/B/DEB/UNK
    OPS_STATUS_CODE: Mapped[str | None] = mapped_column(default=None)
    OWNER: Mapped[str | None] = mapped_column(default=None)  # UN/COSPAR country code
    LAUNCH_DATE: Mapped[str | None] = mapped_column(default=None)  # ISO date
    LAUNCH_SITE: Mapped[str | None] = mapped_column(default=None)  # CelesTrak site code
    DECAY_DATE: Mapped[str | None] = mapped_column(default=None)  # ISO date
    PERIOD: Mapped[float | None] = mapped_column(default=None)  # minutes
    APOGEE: Mapped[float | None] = mapped_column(default=None)  # km
    PERIGEE: Mapped[float | None] = mapped_column(default=None)  # km
    RCS: Mapped[float | None] = mapped_column(default=None)  # m²
    DATA_STATUS_CODE: Mapped[str | None] = mapped_column(default=None)
    ORBIT_CENTER: Mapped[str | None] = mapped_column(default=None)
    ORBIT_TYPE: Mapped[str | None] = mapped_column(default=None)

    constellation_slug: Mapped[str | None] = mapped_column(
        ForeignKey("constellation.slug"), default=None
    )

    object: Mapped["Object"] = relationship(back_populates="celestrak")
