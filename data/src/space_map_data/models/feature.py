"""SQLAlchemy ORM model for IAU planetary nomenclature features."""

import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from space_map_data.constants.continents import Continent
from space_map_data.models.object import Base


class Feature(Base):
    """Mirror of IAU planetary nomenclature KML data.

    ``feature_type_code`` is a 2-letter IAU code (e.g. ``"AA"``); the human-
    readable singular/plural names live in ``constants.feature_types``.
    """

    __tablename__ = "features"

    feature_id: Mapped[int] = mapped_column(primary_key=True)  # IAU feature ID
    object_id: Mapped[str | None] = mapped_column(
        ForeignKey("objects.id"), default=None, index=True
    )  # parent body in objects table
    wikidata_qid: Mapped[str | None] = mapped_column(
        default=None, index=True
    )  # Wikidata entity QID
    name: Mapped[str] = mapped_column()  # feature name
    unicode_name: Mapped[str | None] = mapped_column(
        default=None
    )  # feature name (Unicode)
    target: Mapped[str] = mapped_column(index=True)  # celestial body name
    approval_date: Mapped[datetime.date | None] = mapped_column(default=None)
    origin: Mapped[str | None] = mapped_column(default=None)  # name origin/etymology
    diameter: Mapped[float | None] = mapped_column(default=None)  # diameter [km]
    center_lon: Mapped[float | None] = mapped_column(
        default=None
    )  # center longitude [deg]
    center_lat: Mapped[float | None] = mapped_column(
        default=None
    )  # center latitude [deg]
    feature_type_code: Mapped[str | None] = mapped_column(default=None)  # e.g. "AA"
    min_lon: Mapped[float | None] = mapped_column(default=None)  # bounding box [deg]
    max_lon: Mapped[float | None] = mapped_column(default=None)
    min_lat: Mapped[float | None] = mapped_column(default=None)
    max_lat: Mapped[float | None] = mapped_column(default=None)
    ethnicity: Mapped[str | None] = mapped_column(default=None)  # name origin ethnicity
    continent: Mapped[Continent | None] = mapped_column(
        String, default=None
    )  # name origin continent
    quad_name: Mapped[str | None] = mapped_column(default=None)  # quadrangle name
    quad_code: Mapped[str | None] = mapped_column(default=None)  # quadrangle code
