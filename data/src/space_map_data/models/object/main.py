"""SQLAlchemy ORM model for the main objects table."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from space_map_data.constants.providers import PROVIDERS
from space_map_data.models.object.base import Base

if TYPE_CHECKING:
    from space_map_data.models.object.celestrak import CelesTrak
    from space_map_data.models.object.horizons import Horizons
    from space_map_data.models.object.sbdb import SBDB


# IAU-recognized dwarf planets
# TODO: get from wikidata, P31
DWARF_PLANETS = {
    "ceres",
    "orcus",
    "pluto",
    "salacia",
    "haumea",
    "quaoar",
    "makemake",
    "gonggong",
    "eris",
    "sedna",
}


class ObjectType(StrEnum):
    barycenter = "barycenter"
    lagrange_point = "lagrange_point"
    star = "star"
    planet = "planet"
    dwarf_planet = "dwarf_planet"
    moon = "moon"
    asteroid = "asteroid"
    asteroid_inner = "asteroid_inner"
    asteroid_main_belt = "asteroid_main_belt"
    asteroid_trojan = "asteroid_trojan"
    asteroid_centaur = "asteroid_centaur"
    asteroid_tno = "asteroid_tno"
    comet = "comet"
    spacecraft = "spacecraft"
    # TODO: Spacecraft types:
    # exploration: probe, lander, rover
    # satellites: telescope, telecom, navigation, reconnaissance, weather, military, science
    # manned: station, crewed, cargo
    debris = "debris"
    # TODO: debris types:
    # rocket_body, fragmentation
    undocumented = "undocumented"  # Data is available but provider doesn't specify what it refers to


class ElementsScale(StrEnum):
    """Refers to the orbital element units.

    planet scale has smaller units.
    """

    planet = "planet"  # Orbits a planet (data provided by celestrak)
    system = (
        "system"  # Orbits the sun or another body (data provided by horizons or SBDB)
    )


class OrbitalSource(StrEnum):
    horizons = PROVIDERS.HORIZONS
    sbdb = PROVIDERS.SBDB
    celestrak = PROVIDERS.CELESTRAK
    spice = PROVIDERS.SPICE


class Object(Base):
    __tablename__ = "objects"

    id: Mapped[str] = mapped_column(
        primary_key=True
    )  # <id_type>-<value> (e.g. spkid-2000433, naif-399, norad_satcat-25544)
    name: Mapped[str | None] = mapped_column(
        default=None
    )  # best available name (IAU name, designation, or object name)
    object_type: Mapped[ObjectType] = mapped_column(String)  # ObjectType enum value

    provisional_designation: Mapped[str | None] = mapped_column(
        unique=False,
        default=None,
        index=True,  # Can't be unique due to comets
    )
    # Cross-reference IDs (nullable — an object won't have IDs in all sources)
    wikidata_qid: Mapped[str | None] = mapped_column(
        unique=False,  # Some pages match multiple objects (comets: Q4178666, Q25402132, Q872242)
        default=None,
        index=True,
    )  # Wikidata entity ID (e.g. Q2)
    horizons_naif_id: Mapped[int | None] = mapped_column(
        unique=True, default=None, index=True
    )  # JPL Horizons NAIF/SPK ID
    sbdb_spkid: Mapped[int | None] = mapped_column(
        unique=True, default=None, index=True
    )  # JPL SBDB primary SPK-ID
    random_int: Mapped[int] = mapped_column(
        default=lambda ctx: hash(ctx.get_current_parameters()["id"]),
        index=True,
    )  # Deterministic integer for export partitioning (hash of PK); range: [-(sys.maxsize+1), sys.maxsize], typically [-2^63, 2^63-1] on 64-bit
    sbdb_mcp_designation: Mapped[str | None] = mapped_column(
        unique=False, default=None, index=True
    )  # Minor Planet Center database designation (e.g. 2024 FG9, 1 [ceres]), from JPL SBDB
    celestrak_norad_cat_id: Mapped[int | None] = mapped_column(
        unique=True, default=None, index=True
    )  # NORAD catalog number, from CelesTrak
    celestrak_cospar_id: Mapped[str | None] = mapped_column(
        unique=True, default=None, index=True
    )  # COSPAR international designator (YYYY-NNNP), from CelesTrak
    iau_roman_designation: Mapped[str | None] = mapped_column(
        unique=False, default=None, index=True
    )  # IAU satellite designation (planet letter + Roman numeral, e.g. JLVII)
    horizons_naif_id_extended: Mapped[int | None] = mapped_column(
        unique=True, default=None, index=True
    )  # 5-digit extended NAIF ID used by SPICE for irregular-moon kernels

    # Keplerian elements (osculating, from best available source)
    epoch_jd: Mapped[float | None] = mapped_column(
        default=None
    )  # epoch of osculation [Julian Date, TDB]
    a: Mapped[float | None] = mapped_column(
        default=None
    )  # semi-major axis [AU scale=system, km scale=planet]
    e: Mapped[float | None] = mapped_column(default=None)  # eccentricity
    i: Mapped[float | None] = mapped_column(default=None)  # inclination [deg]
    om: Mapped[float | None] = mapped_column(
        default=None
    )  # longitude of the ascending node [deg]
    w: Mapped[float | None] = mapped_column(
        default=None
    )  # argument of perihelion [deg]
    ma: Mapped[float | None] = mapped_column(default=None)  # mean anomaly [deg]
    n: Mapped[float | None] = mapped_column(
        default=None
    )  # mean motion [deg/d scale=system, rev/d scale=planet]

    # scale
    scale: Mapped[ElementsScale] = mapped_column(
        String, default=ElementsScale.system
    )  # element scale
    parent_naif_id: Mapped[int | None] = mapped_column(
        default=None
    )  # NAIF ID of central body (0=SSB, 399=Earth)

    orbital_source: Mapped[OrbitalSource | None] = mapped_column(
        default=None
    )  # which source provided the orbital elements

    map_texture_available: Mapped[bool] = mapped_column(default=False)

    # Relationships
    horizons: Mapped["Horizons | None"] = relationship(back_populates="object")
    sbdb: Mapped["SBDB | None"] = relationship(back_populates="object")
    celestrak: Mapped["CelesTrak | None"] = relationship(back_populates="object")

    __table_args__ = (
        Index("idx_objects_type", "object_type"),
        Index("idx_objects_a", "a"),
        Index("idx_objects_parent", "parent_naif_id"),
    )
