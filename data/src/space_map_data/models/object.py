"""SQLAlchemy ORM models for the space-map unified database."""

import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from space_map_data.constants.providers import PROVIDERS


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


class Base(DeclarativeBase):
    pass


class Object(Base):
    __tablename__ = "objects"

    id: Mapped[str] = mapped_column(
        primary_key=True
    )  # <authoritative_source>:<authoritative_id> (e.g. sbdb:2000433, horizons:399, wikidata:Q2)
    name: Mapped[str | None] = mapped_column(
        default=None
    )  # best available name (IAU name, designation, or object name)
    object_type: Mapped[ObjectType] = mapped_column(String)  # ObjectType enum value

    provisional_designation: Mapped[str | None] = mapped_column(
        unique=True, default=None, index=True
    )
    # Cross-reference IDs (nullable — an object won't have IDs in all sources)
    wikidata_qid: Mapped[str | None] = mapped_column(
        unique=True, default=None, index=True
    )  # Wikidata entity ID (e.g. Q2)
    horizons_naif_id: Mapped[int | None] = mapped_column(
        unique=True, default=None, index=True
    )  # JPL Horizons NAIF/SPK ID
    sbdb_spkid: Mapped[int | None] = mapped_column(
        unique=True, default=None, index=True
    )  # JPL SBDB primary SPK-ID
    sbdb_mcp_designation: Mapped[str | None] = mapped_column(
        unique=True, default=None, index=True
    )  # Minor Planet Center database designation (e.g. 2024 FG9, 1 [ceres]), from JPL SBDB
    celestrak_norad_cat_id: Mapped[int | None] = mapped_column(
        unique=True, default=None, index=True
    )  # NORAD catalog number, from CelesTrak
    celestrak_cospar_id: Mapped[str | None] = mapped_column(
        unique=True, default=None, index=True
    )  # COSPAR international designator (YYYY-NNNP), from CelesTrak

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

    # Physical
    mass_kg: Mapped[float | None] = mapped_column(default=None)  # mass [kg]
    radius_km: Mapped[float | None] = mapped_column(default=None)  # mean radius [km]
    discovery_date: Mapped[datetime.date | None] = mapped_column(
        default=None
    )  # discovery date

    orbital_source: Mapped[OrbitalSource | None] = mapped_column(
        default=None
    )  # which source provided the orbital elements

    # Relationships
    horizons: Mapped["Horizons | None"] = relationship(back_populates="object")
    sbdb: Mapped["SBDB | None"] = relationship(back_populates="object")
    celestrak: Mapped["CelesTrak | None"] = relationship(back_populates="object")

    __table_args__ = (
        Index("idx_objects_type", "object_type"),
        Index("idx_objects_a", "a"),
        Index("idx_objects_parent", "parent_naif_id"),
    )


class Horizons(Base):
    """Full mirror of horizons/bodies.csv."""

    __tablename__ = "horizons"

    naif_id: Mapped[int | None] = mapped_column(
        default=None, primary_key=True
    )  # NAIF integer ID
    object_id: Mapped[str | None] = mapped_column(ForeignKey("objects.id"))

    computed_spk_id: Mapped[str | None] = mapped_column(
        default=None
    )  # See HorizonsIngestor.get_spk_id()
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

    object: Mapped["Object"] = relationship(back_populates="horizons")


class SBDB(Base):
    """Full mirror of sbdb/small-bodies_*.csv."""

    __tablename__ = "sbdb"

    spkid: Mapped[str | None] = mapped_column(
        default=None, primary_key=True
    )  # object primary SPK-ID
    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"))

    # Object fields
    full_name: Mapped[str | None] = mapped_column(
        default=None
    )  # object full name/designation
    pdes: Mapped[str | None] = mapped_column(default=None)  # object primary designation
    name: Mapped[str | None] = mapped_column(default=None)  # object IAU name
    prefix: Mapped[str | None] = mapped_column(default=None)  # comet designation prefix
    neo: Mapped[bool | None] = mapped_column(
        default=None
    )  # Near-Earth Object (NEO) flag
    pha: Mapped[bool | None] = mapped_column(
        default=None
    )  # Potentially Hazardous Asteroid (PHA) flag
    sats: Mapped[int | None] = mapped_column(default=None)  # number of known satellites

    # Physical parameters
    H: Mapped[float | None] = mapped_column(
        default=None
    )  # absolute magnitude parameter
    G: Mapped[float | None] = mapped_column(
        default=None
    )  # magnitude slope parameter (default 0.15)
    M1: Mapped[float | None] = mapped_column(
        default=None
    )  # comet total magnitude parameter
    M2: Mapped[float | None] = mapped_column(
        default=None
    )  # comet nuclear magnitude parameter
    K1: Mapped[float | None] = mapped_column(
        default=None
    )  # comet total magnitude slope parameter
    K2: Mapped[float | None] = mapped_column(
        default=None
    )  # comet nuclear magnitude slope parameter
    PC: Mapped[float | None] = mapped_column(
        default=None
    )  # comet nuclear magnitude law — phase coefficient
    diameter: Mapped[float | None] = mapped_column(
        default=None
    )  # object diameter from equivalent sphere [km]
    extent: Mapped[str | None] = mapped_column(
        default=None
    )  # bi/tri-axial ellipsoid dimensions [km]
    albedo: Mapped[float | None] = mapped_column(default=None)  # geometric albedo
    rot_per: Mapped[float | None] = mapped_column(default=None)  # rotation period [h]
    GM: Mapped[float | None] = mapped_column(
        default=None
    )  # standard gravitational parameter [km³/s²]
    BV: Mapped[float | None] = mapped_column(
        default=None
    )  # color index B-V magnitude difference
    UB: Mapped[float | None] = mapped_column(
        default=None
    )  # color index U-B magnitude difference
    IR: Mapped[float | None] = mapped_column(
        default=None
    )  # color index I-R magnitude difference
    spec_B: Mapped[str | None] = mapped_column(
        default=None
    )  # spectral taxonomic type [SMASSII]
    spec_T: Mapped[str | None] = mapped_column(
        default=None
    )  # spectral taxonomic type [Tholen]
    H_sigma: Mapped[float | None] = mapped_column(
        default=None
    )  # 1-σ uncertainty in absolute magnitude H
    # Left as string due to 16 psyche
    diameter_sigma: Mapped[str | None] = mapped_column(
        default=None
    )  # 1-σ uncertainty in diameter [km]

    # Orbital elements
    orbit_id: Mapped[str | None] = mapped_column(default=None)  # orbit solution ID
    epoch: Mapped[float | None] = mapped_column(
        default=None
    )  # epoch of osculation [JD, TDB]
    epoch_mjd: Mapped[float | None] = mapped_column(
        default=None
    )  # epoch of osculation [MJD, TDB]
    epoch_cal: Mapped[str | None] = mapped_column(
        default=None
    )  # epoch of osculation [calendar, TDB]
    equinox: Mapped[str | None] = mapped_column(
        default=None
    )  # equinox of reference frame
    e: Mapped[float | None] = mapped_column(default=None)  # eccentricity
    a: Mapped[float | None] = mapped_column(default=None)  # semi-major axis [AU]
    q: Mapped[float | None] = mapped_column(default=None)  # perihelion distance [AU]
    i: Mapped[float | None] = mapped_column(
        default=None
    )  # inclination w.r.t. x-y ecliptic plane [deg]
    om: Mapped[float | None] = mapped_column(
        default=None
    )  # longitude of the ascending node [deg]
    w: Mapped[float | None] = mapped_column(
        default=None
    )  # argument of perihelion [deg]
    ma: Mapped[float | None] = mapped_column(default=None)  # mean anomaly [deg]
    ad: Mapped[float | None] = mapped_column(default=None)  # aphelion distance [AU]
    n: Mapped[float | None] = mapped_column(default=None)  # mean motion [deg/d]
    tp: Mapped[float | None] = mapped_column(
        default=None
    )  # time of perihelion passage [JD, TDB]
    tp_cal: Mapped[str | None] = mapped_column(
        default=None
    )  # time of perihelion passage [calendar, TDB]
    per: Mapped[float | None] = mapped_column(
        default=None
    )  # sidereal orbital period [d]
    per_y: Mapped[float | None] = mapped_column(
        default=None
    )  # sidereal orbital period [years]
    moid: Mapped[float | None] = mapped_column(default=None)  # Earth MOID [AU]
    moid_ld: Mapped[float | None] = mapped_column(
        default=None
    )  # Earth MOID [lunar distances]
    moid_jup: Mapped[float | None] = mapped_column(default=None)  # Jupiter MOID [AU]
    t_jup: Mapped[float | None] = mapped_column(
        default=None
    )  # Jupiter Tisserand Invariant

    # 1-σ uncertainties
    sigma_e: Mapped[float | None] = mapped_column(default=None)  # eccentricity
    sigma_a: Mapped[float | None] = mapped_column(default=None)  # semi-major axis [AU]
    sigma_q: Mapped[float | None] = mapped_column(
        default=None
    )  # perihelion distance [AU]
    sigma_i: Mapped[float | None] = mapped_column(default=None)  # inclination [deg]
    sigma_om: Mapped[float | None] = mapped_column(
        default=None
    )  # longitude of asc. node [deg]
    sigma_w: Mapped[float | None] = mapped_column(
        default=None
    )  # argument of perihelion [deg]
    sigma_ma: Mapped[float | None] = mapped_column(default=None)  # mean anomaly [deg]
    sigma_ad: Mapped[float | None] = mapped_column(
        default=None
    )  # aphelion distance [AU]
    sigma_n: Mapped[float | None] = mapped_column(default=None)  # mean motion [deg/d]
    sigma_tp: Mapped[float | None] = mapped_column(
        default=None
    )  # time of perihelion passage [d]
    sigma_per: Mapped[float | None] = mapped_column(
        default=None
    )  # sidereal orbital period [d]

    # Orbit metadata
    class_: Mapped[str | None] = mapped_column(
        "class", default=None
    )  # orbit classification
    producer: Mapped[str | None] = mapped_column(
        default=None
    )  # person/institution who computed the orbit
    data_arc: Mapped[int | None] = mapped_column(default=None)  # data-arc span [d]
    first_obs: Mapped[str | None] = mapped_column(
        default=None
    )  # date of first observation used in fit [UT] — YYYY-MM-DD or YYYY if partial
    last_obs: Mapped[str | None] = mapped_column(
        default=None
    )  # date of last observation used in fit [UT] — YYYY-MM-DD or YYYY if partial
    n_obs_used: Mapped[int | None] = mapped_column(
        default=None
    )  # total observations used in fit
    n_del_obs_used: Mapped[int | None] = mapped_column(
        default=None
    )  # delay-radar observations used in fit
    n_dop_obs_used: Mapped[int | None] = mapped_column(
        default=None
    )  # Doppler-radar observations used in fit
    condition_code: Mapped[str | None] = mapped_column(
        default=None
    )  # orbit condition code (MPC 'U' parameter)
    rms: Mapped[float | None] = mapped_column(
        default=None
    )  # normalized RMS of orbit fit [arcsec]
    two_body: Mapped[bool | None] = mapped_column(
        default=None
    )  # 2-body dynamics used flag

    # Non-gravitational parameters
    A1: Mapped[float | None] = mapped_column(default=None)  # non-grav. radial parameter
    A1_sigma: Mapped[float | None] = mapped_column(
        default=None
    )  # non-grav. radial parameter (1-σ)
    A2: Mapped[float | None] = mapped_column(
        default=None
    )  # non-grav. transverse parameter
    A2_sigma: Mapped[float | None] = mapped_column(
        default=None
    )  # non-grav. transverse parameter (1-σ)
    A3: Mapped[float | None] = mapped_column(default=None)  # non-grav. normal parameter
    A3_sigma: Mapped[float | None] = mapped_column(
        default=None
    )  # non-grav. normal parameter (1-σ)
    DT: Mapped[float | None] = mapped_column(
        default=None
    )  # non-grav. perihelion-maximum offset [d]
    DT_sigma: Mapped[float | None] = mapped_column(
        default=None
    )  # non-grav. perihelion-maximum offset (1-σ) [d]

    object: Mapped["Object"] = relationship(back_populates="sbdb")


class CelesTrak(Base):
    """Full mirror of celes-trak/gp-active.csv."""

    __tablename__ = "celestrak"

    NORAD_CAT_ID: Mapped[int] = mapped_column(primary_key=True)  # NORAD catalog number
    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), unique=True)

    OBJECT_NAME: Mapped[str | None] = mapped_column(default=None)  # satellite name
    TRAK_OBJECT_ID: Mapped[str | None] = mapped_column(
        default=None
    )  # international designator / COSPAR ID (YYYY-NNNP)
    EPOCH: Mapped[str | None] = mapped_column(
        default=None
    )  # element set epoch [ISO 8601 UTC]
    MEAN_MOTION: Mapped[float | None] = mapped_column(
        default=None
    )  # mean motion [rev/d]
    ECCENTRICITY: Mapped[float | None] = mapped_column(default=None)  # eccentricity
    INCLINATION: Mapped[float | None] = mapped_column(default=None)  # inclination [deg]
    RA_OF_ASC_NODE: Mapped[float | None] = mapped_column(
        default=None
    )  # right ascension of ascending node [deg]
    ARG_OF_PERICENTER: Mapped[float | None] = mapped_column(
        default=None
    )  # argument of perigee [deg]
    MEAN_ANOMALY: Mapped[float | None] = mapped_column(
        default=None
    )  # mean anomaly [deg]
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
