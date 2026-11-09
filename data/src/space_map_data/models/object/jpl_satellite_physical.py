"""SQLAlchemy ORM model for JPL's planetary-satellite physical parameters."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from space_map_data.models.object.base import Base


class JPLSatellitePhysical(Base):
    """One row per satellite in JPL's physical parameters table.

    The GM comes with its 1σ and the ephemeris that fitted it. An upper limit
    keeps its bound in ``gm_km3_s2``. A GM of 0 is kept as JPL prints it.
    """

    __tablename__ = "jpl_satellite_physical"

    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), primary_key=True)
    naif_id: Mapped[int]
    # The GM as JPL prints it ("4.30"): its digits are the precision of the fit.
    gm_km3_s2: Mapped[str | None] = mapped_column(default=None)
    gm_sigma_km3_s2: Mapped[float | None] = mapped_column(default=None)
    gm_upper_limit: Mapped[bool] = mapped_column(default=False)
    # "JUP365", "PLU060": the ephemeris the GM is from.
    ephemeris: Mapped[str | None] = mapped_column(default=None)
