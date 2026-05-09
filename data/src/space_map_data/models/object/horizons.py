"""SQLAlchemy ORM model for the Horizons table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from space_map_data.models.object.base import Base

if TYPE_CHECKING:
    from space_map_data.models.object.main import Object


class Horizons(Base):
    """NAIF-keyed kepler element store.

    Mirrors horizons/bodies.csv at ingest, then SPICE ingest overwrites the
    rows for major bodies and moons (planets, moons, etc.) with values from
    spice/bodies.csv, including the secular drift rates `om_dot`/`w_dot` that
    SPICE computes for non-whitelisted moons. Horizons-source and SPICE-source
    Object rows both join here for orbital elements.
    """

    __tablename__ = "horizons"

    naif_id: Mapped[int | None] = mapped_column(
        default=None, primary_key=True
    )  # NAIF integer ID
    object_id: Mapped[str | None] = mapped_column(ForeignKey("objects.id"))

    cospar_id: Mapped[str | None] = mapped_column(
        default=None
    )  # See HorizonsIngestor.get_cospar_id()
    name: Mapped[str | None] = mapped_column(default=None)  # object name
    type: Mapped[str | None] = mapped_column(
        default=None
    )  # object type (star, planet, moon, ...)
    center: Mapped[str | None] = mapped_column(default=None)  # coordinate center name
    parent_naif_id: Mapped[int | None] = mapped_column(
        default=None
    )  # NAIF ID of parent body (0 = SSB)
    designation: Mapped[str | None] = mapped_column(default=None)  # IAU designation
    extra: Mapped[str | None] = mapped_column(default=None)  # additional metadata
    JDTDB: Mapped[float | None] = mapped_column(
        default=None
    )  # epoch [Julian Date, TDB]
    calendar_date_tdb: Mapped[str | None] = mapped_column(
        default=None
    )  # epoch [calendar date, TDB]
    EC: Mapped[float | None] = mapped_column(default=None)  # eccentricity
    QR: Mapped[float | None] = mapped_column(
        default=None
    )  # periapsis distance [AU or km]
    IN_: Mapped[float | None] = mapped_column("IN", default=None)  # inclination [deg]
    OM: Mapped[float | None] = mapped_column(
        default=None
    )  # longitude of ascending node [deg]
    W: Mapped[float | None] = mapped_column(default=None)  # argument of periapsis [deg]
    Tp: Mapped[float | None] = mapped_column(
        default=None
    )  # time of periapsis passage [JD, TDB]
    N: Mapped[float | None] = mapped_column(
        default=None
    )  # mean motion [deg/d or rev/d]
    MA: Mapped[float | None] = mapped_column(default=None)  # mean anomaly [deg]
    TA: Mapped[float | None] = mapped_column(default=None)  # true anomaly [deg]
    A: Mapped[float | None] = mapped_column(default=None)  # semi-major axis [AU or km]
    AD: Mapped[float | None] = mapped_column(
        default=None
    )  # apoapsis distance [AU or km]
    PR: Mapped[float | None] = mapped_column(
        default=None
    )  # sidereal orbital period [s]
    # Secular drift rates [deg/d] from SPICE Method C mean-element fit.
    # Populated only for non-whitelisted moons; horizons-only rows leave them null.
    om_dot: Mapped[float | None] = mapped_column(default=None)
    w_dot: Mapped[float | None] = mapped_column(default=None)

    object: Mapped["Object"] = relationship(back_populates="horizons")

    # Unified-name aliases so consumers can read kepler elements by the same
    # attribute names regardless of which sub-table they joined.
    @property
    def epoch_jd(self) -> float | None:
        return self.JDTDB

    @property
    def a(self) -> float | None:
        return self.A

    @property
    def e(self) -> float | None:
        return self.EC

    @property
    def i(self) -> float | None:
        return self.IN_

    @property
    def om(self) -> float | None:
        return self.OM

    @property
    def w(self) -> float | None:
        return self.W

    @property
    def ma(self) -> float | None:
        return self.MA

    @property
    def n(self) -> float | None:
        return self.N
