"""SQLAlchemy ORM model for CelesTrak TLE/GP orbital elements."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from space_map_data.models.object.base import Base

if TYPE_CHECKING:
    from space_map_data.models.object.main import Object


class CelesTrak(Base):
    """SGP4-extra fields and metadata from CelesTrak gp-active.csv + group CSVs.

    Orbital elements proper (epoch, mean motion, eccentricity, inclination,
    RAAN, arg-of-pericenter, mean anomaly) live in the daily snapshot files on
    disk and are read fresh at export time by ``celestrak_source.load_all_days``.
    Persisting them in the DB would just stale-bait consumers, so this table
    only stores the fields that can't be re-derived per snapshot: classification
    metadata and the SGP4 extras (BSTAR, MEAN_MOTION_DOT/DDOT, ELEMENT_SET_NO,
    REV_AT_EPOCH) that the SGP4 writer reads. The export overlay overwrites
    those too with the per-day snapshot values before writing.
    """

    __tablename__ = "celestrak"

    NORAD_CAT_ID: Mapped[int] = mapped_column(primary_key=True)  # NORAD catalog number
    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), unique=True)

    OBJECT_NAME: Mapped[str | None] = mapped_column(default=None)  # satellite name
    TRAK_OBJECT_ID: Mapped[str | None] = mapped_column(
        default=None
    )  # international designator / COSPAR ID (YYYY-NNNP)
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

    object: Mapped["Object"] = relationship(back_populates="celestrak")
