"""SQLAlchemy ORM model for AsterSat (NSDB/MULTI-SAT) asteroid moon orbits."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from space_map_data.models.object.base import Base

if TYPE_CHECKING:
    from space_map_data.models.object.main import Object


class AsterSatMoon(Base):
    """One row per asteroid or TNO satellite with a fitted mutual orbit in
    AsterSat, the satellites-of-asteroids service of the Natural Satellites
    Data Base (Sternberg Astronomical Institute + IMCCE).

    Every row carries a complete fixed-Keplerian element set — the whole point
    of taking this source. SBDB's satellite payload leaves the orientation
    angles null for all but a handful of radar binaries, so these are the only
    asteroid moons that can be placed at all.

    Elements are geocentric-equatorial J2000, satellite relative to the
    primary. The export rotates them to the ecliptic; see
    ``export/position/frames.py``.

    Units:
        a_km            — km
        i, om, w, ma    — deg
        n               — deg/day
        per_d           — days
        epoch_mjd       — Modified Julian Date
        gm              — km^3/s^2 (whole system, primary + satellite)
        rms_arcsec      — quadratic mean of the fit residuals
    """

    __tablename__ = "astersat_moon"

    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), primary_key=True)
    parent_object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), index=True)
    # AsterSat's own form value, e.g. `AN000022Kalliope` — the only stable
    # handle it exposes, and what a refresh re-queries.
    astersat_id: Mapped[str] = mapped_column(index=True)
    system_label: Mapped[str]  # "(22) Kalliope"
    satellite_label: Mapped[str]  # "Linus"

    # Orbit
    frame: Mapped[str]  # as printed, e.g. "geoequat J2000"
    epoch_mjd: Mapped[float]
    a_km: Mapped[float]
    e: Mapped[float]
    i: Mapped[float]
    om: Mapped[float]
    w: Mapped[float]
    ma: Mapped[float]
    n: Mapped[float]
    per_d: Mapped[float]

    # Fit provenance — how much weight the orbit deserves.
    gm: Mapped[float | None] = mapped_column(default=None)
    n_obs: Mapped[int | None] = mapped_column(default=None)
    rms_arcsec: Mapped[float | None] = mapped_column(default=None)
    obs_arc_start: Mapped[float | None] = mapped_column(default=None)  # decimal year
    obs_arc_end: Mapped[float | None] = mapped_column(default=None)
    primary_radius_km: Mapped[float | None] = mapped_column(default=None)
    satellite_radius_km: Mapped[float | None] = mapped_column(default=None)

    object: Mapped["Object"] = relationship(
        foreign_keys=[object_id], back_populates="astersat_moon"
    )
    parent: Mapped["Object"] = relationship(
        foreign_keys=[parent_object_id], back_populates="astersat_moons"
    )
