"""SQLAlchemy ORM models for Johnston's Archive asteroid/TNO satellite data."""

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from space_map_data.models.object.base import Base

if TYPE_CHECKING:
    from space_map_data.models.object.main import Object


class JohnstonConfidence(StrEnum):
    """Johnston's own four-level ranking of how sure a companion is.

    Taken verbatim from his ``asteroidmoonslist3`` table; the definitions are
    his. SBDB collapses the same judgement into one ``confirmed`` Y/N flag.
    """

    permanent = "permanent"  # IAU permanent name and designation assigned
    well_observed = "well_observed"  # orbit computed
    confirmed = "confirmed"  # detection confirmed by follow-up
    probable = "probable"  # single set of observations / single apparition


class JohnstonSystem(Base):
    """One row per binary/multiple system, holding the whole-system and
    primary-body columns of a Johnston per-object page.

    Johnston compiles the published literature per system, so this overlaps
    SBDB on a few columns (H, albedo, diameter) and adds what SBDB's satellite
    payload has none of: system mass and density, Hill radius, primary pole
    and triaxial shape, and the confidence ranking.
    """

    __tablename__ = "johnston_system"

    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), primary_key=True)
    page: Mapped[str]  # "am-00022", the archive's own page id
    designation: Mapped[str]  # "(22) Kalliope", as the index lists it
    last_updated: Mapped[str | None] = mapped_column(default=None)
    confidence: Mapped[JohnstonConfidence | None] = mapped_column(String, default=None)
    dynamical_type: Mapped[str | None] = mapped_column(default=None)  # "main belt"

    # System (combined) — measurements that don't separate the components
    h_mag: Mapped[float | None] = mapped_column(default=None)
    slope_g: Mapped[float | None] = mapped_column(default=None)
    diameter_km: Mapped[float | None] = mapped_column(default=None)
    diameter_km_sigma: Mapped[float | None] = mapped_column(default=None)
    albedo: Mapped[float | None] = mapped_column(default=None)
    albedo_sigma: Mapped[float | None] = mapped_column(default=None)
    taxonomy: Mapped[str | None] = mapped_column(default=None)
    mass_kg: Mapped[float | None] = mapped_column(default=None)
    mass_kg_sigma: Mapped[float | None] = mapped_column(default=None)
    density_g_cm3: Mapped[float | None] = mapped_column(default=None)
    density_g_cm3_sigma: Mapped[float | None] = mapped_column(default=None)
    hill_radius_km: Mapped[float | None] = mapped_column(default=None)
    colour_ub: Mapped[float | None] = mapped_column(default=None)
    colour_bv: Mapped[float | None] = mapped_column(default=None)
    colour_vr: Mapped[float | None] = mapped_column(default=None)
    colour_vi: Mapped[float | None] = mapped_column(default=None)

    # Primary body
    primary_diameter_km: Mapped[float | None] = mapped_column(default=None)
    primary_diameter_km_sigma: Mapped[float | None] = mapped_column(default=None)
    primary_dimensions: Mapped[str | None] = mapped_column(default=None)
    primary_axial_ratios: Mapped[str | None] = mapped_column(default=None)
    primary_rotation_h: Mapped[float | None] = mapped_column(default=None)
    primary_rotation_h_sigma: Mapped[float | None] = mapped_column(default=None)
    primary_amplitude_mag: Mapped[float | None] = mapped_column(default=None)
    pole_beta_deg: Mapped[float | None] = mapped_column(default=None)
    pole_lambda_deg: Mapped[float | None] = mapped_column(default=None)

    object: Mapped["Object"] = relationship(
        foreign_keys=[object_id], back_populates="johnston_system"
    )
    moons: Mapped[list["JohnstonMoon"]] = relationship(
        foreign_keys="JohnstonMoon.parent_object_id", back_populates="system"
    )


class JohnstonMoon(Base):
    """One row per companion, from the matching ``orbital data, <label>`` and
    ``other data, <label>`` blocks of its system's page.

    Most companions carry only a semi-major axis and a period: they were found
    by lightcurve, which cannot measure an orbit's orientation. The angles are
    present for the resolved-imaging and radar systems only, so this is a
    physical-data and provenance source, not a position source — see
    ``AsterSatMoon`` for that.

    Units:
        a_km, diameter_km       — km
        i, om, w, ma            — deg, frame unstated (see class note below)
        per_d                   — days
        rotation_h              — hours

    Johnston reprints each paper's angles as published and does not say which
    frame they are in, so ``i``/``om``/``w`` — and ``ma``, which is only
    meaningful alongside them — are held here but never exported. Their
    uncertainties are kept for the same reason: the numbers they qualify are.
    """

    __tablename__ = "johnston_moon"

    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), primary_key=True)
    parent_object_id: Mapped[str] = mapped_column(
        ForeignKey("johnston_system.object_id"), index=True
    )
    label: Mapped[str]  # block label: "secondary", "Romulus", "S/2003 (130) 1"
    binary_type: Mapped[str | None] = mapped_column(
        default=None
    )  # Pravec A/B/C/L/O/U/W

    # Mutual orbit
    a_km: Mapped[float | None] = mapped_column(default=None)
    a_km_sigma: Mapped[float | None] = mapped_column(default=None)
    a_over_primary_radius: Mapped[float | None] = mapped_column(default=None)
    a_over_hill_radius: Mapped[float | None] = mapped_column(default=None)
    per_d: Mapped[float | None] = mapped_column(default=None)
    per_d_sigma: Mapped[float | None] = mapped_column(default=None)
    e: Mapped[float | None] = mapped_column(default=None)
    e_sigma: Mapped[float | None] = mapped_column(default=None)
    i: Mapped[float | None] = mapped_column(default=None)
    i_sigma: Mapped[float | None] = mapped_column(default=None)
    om: Mapped[float | None] = mapped_column(default=None)
    om_sigma: Mapped[float | None] = mapped_column(default=None)
    w: Mapped[float | None] = mapped_column(default=None)
    w_sigma: Mapped[float | None] = mapped_column(default=None)
    ma: Mapped[float | None] = mapped_column(default=None)
    ma_sigma: Mapped[float | None] = mapped_column(default=None)
    epoch: Mapped[str | None] = mapped_column(
        default=None
    )  # as printed, e.g. "2004 Sep 01.0"
    normalised_ang_mom: Mapped[float | None] = mapped_column(default=None)

    # Component
    diameter_km: Mapped[float | None] = mapped_column(default=None)
    diameter_km_sigma: Mapped[float | None] = mapped_column(default=None)
    diameter_ratio: Mapped[float | None] = mapped_column(default=None)
    diameter_ratio_sigma: Mapped[float | None] = mapped_column(default=None)
    dimensions: Mapped[str | None] = mapped_column(default=None)
    mag_difference: Mapped[float | None] = mapped_column(default=None)
    rotation_h: Mapped[float | None] = mapped_column(default=None)

    # Discovery — SBDB gives a year and one free-text reference; this is the
    # rest of what the archive records.
    discovery_date: Mapped[str | None] = mapped_column(default=None)
    discoverers: Mapped[str | None] = mapped_column(default=None)
    discovery_method: Mapped[str | None] = mapped_column(default=None)
    discovery_facility: Mapped[str | None] = mapped_column(default=None)
    announced: Mapped[str | None] = mapped_column(default=None)  # "2001 Sep 03"
    provisional_designation: Mapped[str | None] = mapped_column(
        default=None, index=True
    )

    object: Mapped["Object"] = relationship(
        foreign_keys=[object_id], back_populates="johnston_moon"
    )
    system: Mapped["JohnstonSystem"] = relationship(
        foreign_keys=[parent_object_id], back_populates="moons"
    )
