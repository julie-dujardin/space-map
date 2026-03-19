"""SQLAlchemy ORM model for IAU planetary nomenclature features."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from space_map_data.models.object import Base


class Feature(Base):
    """Mirror of IAU planetary nomenclature KML data."""

    __tablename__ = "features"

    feature_id: Mapped[int] = mapped_column(primary_key=True)  # IAU feature ID
    object_id: Mapped[str | None] = mapped_column(
        ForeignKey("objects.id"), default=None, index=True
    )  # parent body in objects table
    name: Mapped[str] = mapped_column()  # feature name
    unicode_name: Mapped[str | None] = mapped_column(
        default=None
    )  # feature name (Unicode)
    target: Mapped[str] = mapped_column(index=True)  # celestial body name
    approval_date: Mapped[str | None] = mapped_column(default=None)  # approval date
    origin: Mapped[str | None] = mapped_column(default=None)  # name origin/etymology
    diameter: Mapped[float | None] = mapped_column(default=None)  # diameter [km]
    center_lon: Mapped[float | None] = mapped_column(
        default=None
    )  # center longitude [deg]
    center_lat: Mapped[float | None] = mapped_column(
        default=None
    )  # center latitude [deg]
    feature_type: Mapped[str | None] = mapped_column(
        default=None
    )  # e.g. "Crater, craters"
    feature_type_code: Mapped[str | None] = mapped_column(default=None)  # e.g. "AA"
    approval_status: Mapped[str | None] = mapped_column(
        default=None
    )  # e.g. "Adopted by IAU"
    min_lon: Mapped[float | None] = mapped_column(default=None)  # bounding box [deg]
    max_lon: Mapped[float | None] = mapped_column(default=None)
    min_lat: Mapped[float | None] = mapped_column(default=None)
    max_lat: Mapped[float | None] = mapped_column(default=None)
    ethnicity: Mapped[str | None] = mapped_column(default=None)  # name origin ethnicity
    continent: Mapped[str | None] = mapped_column(default=None)  # name origin continent
    quad_name: Mapped[str | None] = mapped_column(default=None)  # quadrangle name
    quad_code: Mapped[str | None] = mapped_column(default=None)  # quadrangle code
