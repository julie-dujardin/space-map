"""SQLAlchemy ORM model for the main objects table."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from space_map_data.constants.providers import PROVIDERS
from space_map_data.models.object.base import Base

if TYPE_CHECKING:
    from space_map_data.models.object.celestrak import CelesTrak
    from space_map_data.models.object.horizons import Horizons
    from space_map_data.models.object.satcat import Satcat
    from space_map_data.models.object.sbdb import SBDB
    from space_map_data.models.object.sbdb_moon import SBDBMoon


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
    sbdb = PROVIDERS.SBDB
    sbdb_moon = PROVIDERS.SBDB_MOONS
    celestrak = PROVIDERS.CELESTRAK
    spice = PROVIDERS.SPICE
    spice_probe = PROVIDERS.SPICE_PROBES


class Object(Base):
    __tablename__ = "objects"

    id: Mapped[str] = mapped_column(
        primary_key=True
    )  # <id_type>-<value> (e.g. spkid-2000433, naif-399, norad-25544)
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
    naif_id: Mapped[int | None] = mapped_column(
        # Not unique: NAIF IDs recycle across spacecraft (-76 = Mariner 10 and
        # MSL, -12 = LADEE and Pioneer Venus Multiprobe, -66 = Vega 2 and
        # MarCO-B, ...). Natural-body NAIF IDs are positive and effectively
        # unique by data, but the constraint is too strict to enforce DB-wide.
        default=None,
        index=True,
    )  # NAIF/SPK ID (from Horizons or SPICE)
    spkid: Mapped[int | None] = mapped_column(
        unique=True, default=None, index=True
    )  # SBDB primary SPK-ID
    random_int: Mapped[int] = mapped_column(
        default=lambda ctx: hash(ctx.get_current_parameters()["id"]),
        index=True,
    )  # Deterministic integer for export partitioning (hash of PK); range: [-(sys.maxsize+1), sys.maxsize], typically [-2^63, 2^63-1] on 64-bit
    mpc_designation: Mapped[str | None] = mapped_column(
        unique=False, default=None, index=True
    )  # Minor Planet Center database designation (e.g. 2024 FG9, 1 [ceres]), from JPL SBDB
    norad_cat_id: Mapped[int | None] = mapped_column(
        # Not unique: sub-spacecraft that ride a primary into orbit and split
        # off beyond Earth share their launch's NORAD with the parent. Huygens
        # rode 1997-061A with Cassini (NORAD 25008); LICIACube rode DART
        # (NORAD 49497); Ingenuity rode Mars 2020 (NORAD 47545). Both the
        # parent's probe row and the sub-spacecraft's probe row carry the
        # same NORAD so cross-system search by catalog number resolves either.
        default=None,
        index=True,
    )  # NORAD catalog number (from CelesTrak or SATCAT)
    cospar_id: Mapped[str | None] = mapped_column(
        default=None, index=True
    )  # COSPAR international designator (YYYY-NNNP). Not unique: a satcat row
    # and a probe row for the same spacecraft both legitimately carry the same
    # COSPAR (e.g. NORAD 25008 + probe-88592384 = Cassini, 1997-061A).
    iau_roman_designation: Mapped[str | None] = mapped_column(
        unique=False, default=None, index=True
    )  # IAU satellite designation (planet letter + Roman numeral, e.g. JLVII)
    naif_id_extended: Mapped[int | None] = mapped_column(
        unique=True, default=None, index=True
    )  # 5-digit extended NAIF ID used by SPICE for irregular-moon kernels
    probe_id: Mapped[int | None] = mapped_column(
        unique=True, default=None, index=True
    )  # int32 ID packing inception MJD + dedupe for spacecraft (see probes/probe_id.py).
    # Used because NAIF IDs are recycled across missions (e.g. -76 was Mariner 10, now MSL).

    # Namespace-claim FKs into the Earth-sat tables. Non-unique at the column
    # level: joint-launch sub-spacecraft (Cassini orbiter + Huygens probe both
    # tracked under NORAD 25008) each get their own probe Object pointing at
    # the same satcat row. A partial unique index (below) enforces uniqueness
    # within the `norad_satcat-%` namespace so two sat-only Object rows can't
    # claim the same satcat/celestrak row.
    satcat_norad_cat_id: Mapped[int | None] = mapped_column(
        ForeignKey("satcat.NORAD_CAT_ID"),
        default=None,
        index=True,
    )
    celestrak_norad_cat_id: Mapped[int | None] = mapped_column(
        ForeignKey("celestrak.NORAD_CAT_ID"),
        default=None,
        index=True,
    )

    # Orbital element scale + central body. Kepler elements themselves live
    # on the sub-tables (Horizons / SBDB / CelesTrak); join via orbital_source.
    scale: Mapped[ElementsScale] = mapped_column(
        String, default=ElementsScale.system
    )  # element scale
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("objects.id"), default=None
    )  # Object.id of the central body (e.g. "naif-399" for Earth)

    orbital_source: Mapped[OrbitalSource | None] = mapped_column(
        default=None, index=True
    )  # which source provided the orbital elements (= which sub-table to join)

    map_texture_available: Mapped[bool] = mapped_column(default=False)
    image_available: Mapped[bool] = mapped_column(default=False)
    has_wikipedia_description: Mapped[bool] = mapped_column(default=False)
    has_rings: Mapped[bool] = mapped_column(default=False)
    # Slug of the 3D-model bundle under EXPORT_DIR/v1/models/{slug}/. Many
    # objects may point at the same slug (Viking 1/2 share an orbiter model;
    # Cluster II spacecraft share a constellation model). Authored by the
    # models ingest provider; null when no model is available.
    model_name: Mapped[str | None] = mapped_column(default=None)
    # True when this row carries the orbital elements needed to ship in a
    # position file (Keplerian/SGP4/parabolic). Computed at ingest from the
    # source-specific required-element set; consumed by export queries to
    # gate the per-source position-zone selects and by the labels writer to
    # gate auto-promotion (label-only entries make the renderer's pending-
    # promotion loop retry an unfindable getBody every frame).
    has_position: Mapped[bool] = mapped_column(default=False, index=True)

    # Relationships
    horizons: Mapped["Horizons | None"] = relationship(back_populates="object")
    sbdb: Mapped["SBDB | None"] = relationship(back_populates="object")
    celestrak: Mapped["CelesTrak | None"] = relationship(
        foreign_keys=[celestrak_norad_cat_id]
    )
    satcat: Mapped["Satcat | None"] = relationship(foreign_keys=[satcat_norad_cat_id])
    sbdb_moon: Mapped["SBDBMoon | None"] = relationship(
        foreign_keys="SBDBMoon.object_id", back_populates="object"
    )
    sbdb_moons: Mapped[list["SBDBMoon"]] = relationship(
        foreign_keys="SBDBMoon.parent_object_id", back_populates="parent"
    )

    __table_args__ = (
        Index("idx_objects_type", "object_type"),
        Index("idx_objects_parent", "parent_id"),
        Index(
            "idx_objects_satcat_norad_unique",
            "satcat_norad_cat_id",
            unique=True,
            sqlite_where=text("id LIKE 'norad_satcat-%'"),
        ),
        Index(
            "idx_objects_celestrak_norad_unique",
            "celestrak_norad_cat_id",
            unique=True,
            sqlite_where=text("id LIKE 'norad_satcat-%'"),
        ),
    )
