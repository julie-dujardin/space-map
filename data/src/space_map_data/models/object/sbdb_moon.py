"""SQLAlchemy ORM model for SBDB satellite (asteroid moon) data."""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from space_map_data.models.object.base import Base

if TYPE_CHECKING:
    from space_map_data.models.object.main import Object


class SBDBMoon(Base):
    """One row per known satellite of a small body, sourced from the SBDB
    per-object API (`sbdb.api?spk=<id>&sat=1`).

    The bulk SBDB Query API exposes only a `sats` count; per-object queries
    return the satellite payload (name, orbit, references). Most rows have
    partial or missing data — many are publication placeholders ("a moon
    was claimed in this paper") with no orbit or name. All identity and
    orbit columns are nullable for that reason.

    Units in the orbit columns:
        a_km, q_km          — km
        i, om, w, ma        — deg
        n                   — deg/day
        per_h               — hours
        tp_jd               — Julian Date (TDB)
        dn_dt               — deg/year²
    """

    __tablename__ = "sbdb_moon"

    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), primary_key=True)
    parent_object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), index=True)
    parent_spkid: Mapped[int] = mapped_column(index=True)
    sat_index: Mapped[int]  # 0-based ordinal in the parent's `.sat` array

    # Identity
    fullname: Mapped[str | None] = mapped_column(default=None)
    iau_num: Mapped[int | None] = mapped_column(default=None)
    iau_name: Mapped[str | None] = mapped_column(default=None)
    prov_des: Mapped[str | None] = mapped_column(default=None, index=True)
    oid: Mapped[int | None] = mapped_column(default=None)
    year: Mapped[int | None] = mapped_column(default=None)
    confirmed: Mapped[bool | None] = mapped_column(default=None)
    discovery_ref: Mapped[str | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(default=None)

    # Orbit metadata
    epoch_jd: Mapped[float | None] = mapped_column(default=None)
    frame: Mapped[str | None] = mapped_column(default=None)
    equinox: Mapped[str | None] = mapped_column(default=None)
    orbit_ref: Mapped[str | None] = mapped_column(default=None)
    orbit_notes: Mapped[str | None] = mapped_column(default=None)

    # Orbit elements
    a_km: Mapped[float | None] = mapped_column(default=None)
    q_km: Mapped[float | None] = mapped_column(default=None)
    e: Mapped[float | None] = mapped_column(default=None)
    i: Mapped[float | None] = mapped_column(default=None)
    om: Mapped[float | None] = mapped_column(default=None)
    w: Mapped[float | None] = mapped_column(default=None)
    ma: Mapped[float | None] = mapped_column(default=None)
    n: Mapped[float | None] = mapped_column(default=None)
    per_h: Mapped[float | None] = mapped_column(default=None)
    tp_jd: Mapped[float | None] = mapped_column(default=None)
    dn_dt: Mapped[float | None] = mapped_column(default=None)
    a_d: Mapped[float | None] = mapped_column(default=None)  # a/D ratio

    # 1-σ uncertainties
    sigma_a: Mapped[float | None] = mapped_column(default=None)
    sigma_e: Mapped[float | None] = mapped_column(default=None)
    sigma_i: Mapped[float | None] = mapped_column(default=None)
    sigma_om: Mapped[float | None] = mapped_column(default=None)
    sigma_w: Mapped[float | None] = mapped_column(default=None)
    sigma_ma: Mapped[float | None] = mapped_column(default=None)
    sigma_per: Mapped[float | None] = mapped_column(default=None)
    sigma_tp: Mapped[float | None] = mapped_column(default=None)

    object: Mapped["Object"] = relationship(
        foreign_keys=[object_id], back_populates="sbdb_moon"
    )
    parent: Mapped["Object"] = relationship(
        foreign_keys=[parent_object_id],
        back_populates="sbdb_moons",
    )
