"""SQLAlchemy ORM model for the SBDB table."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from space_map_data.models.object.base import Base

if TYPE_CHECKING:
    from space_map_data.models.object.main import Object


class OrbitClass(StrEnum):
    """Small body orbit classification

    See:
    - https://ssd-api.jpl.nasa.gov/doc/sbdb_filter.html
    - https://pdssbn.astro.umd.edu/data_other/objclass.shtml

    e - eccentricity
    q - perihelion distance
    a - semimajor axis
    Q - aphelion distance
    P - orbital period
    Tj - Jupiter Tisserand parameter
    aJ - Jupiter nominal semimajor axis
    """

    # Asteroids
    Atira = "IEO"  # Atira — orbit entirely within Earth's orbit (Q < 0.983 au)
    Aten = "ATE"  # Aten — a < 1.0 au; Q > 0.983 au
    Apollo = "APO"  # Apollo — a > 1.0 au; q < 1.017 au
    Amor = "AMO"  # Amor — 1.017 au < q < 1.3 au
    MarsCrossing = "MCA"  # Mars-crossing — 1.3 au < q < 1.666 au; a < 3.2 au
    InnerMainBelt = "IMB"  # Inner Main-belt — a < 2.0 au; q > 1.666 au
    MainBelt = "MBA"  # Main-belt — 2.0 au < a < 3.2 au; q > 1.666 au
    OuterMainBelt = "OMB"  # Outer Main-belt — 3.2 au < a < 4.6 au
    JupiterTrojan = "TJN"  # Jupiter Trojan — 4.6 au < a < 5.5 au; e < 0.3
    Asteroid = "AST"  # Asteroid (unclassified)
    # Trans-Jovian / outer solar system
    Centaur = "CEN"  # Centaur — 5.5 au < a < 30.1 au
    TransNeptunian = "TNO"  # TransNeptunian Object — a > 30.1 au
    # Non-elliptic asteroids
    ParabolicAsteroid = "PAA"  # Parabolic "Asteroid" — e = 1.0
    HyperbolicAsteroid = "HYA"  # Hyperbolic "Asteroid" — e > 1.0
    # Comets
    EnckeType = "ETc"  # Encke-type Comet — Tj > 3; a < aJ
    JupiterFamilyLD = "JFc"  # Jupiter-family Comet (Levison & Duncan) — 2 < Tj < 3
    JupiterFamilyC = "JFC"  # Jupiter-family Comet (classical) — P < 20 y
    ChironType = "CTc"  # Chiron-type Comet — Tj > 3; a > aJ
    HalleyType = "HTC"  # Halley-type Comet (classical) — 20 y < P < 200 y
    ParabolicComet = "PAR"  # Parabolic Comet — e = 1.0
    HyperbolicComet = "HYP"  # Hyperbolic Comet — e > 1.0
    Comet = "COM"  # Comet (unclassified)


class CometPrefix(StrEnum):
    """Comet designation prefix (the letter before the slash in e.g. 1P/Halley).

    See:
    - https://www.minorplanetcenter.net/iau/lists/CometResolution.html
    - https://iauarchive.eso.org/news/announcements/detail/ann17045/
    """

    Periodic = "P"  # Periodic comet — P < 200 y, or confirmed at >1 perihelion (e.g. 1P/Halley)
    NonPeriodic = "C"  # Non-periodic comet — P ≥ 200 y, or periodicity unconfirmed
    Defunct = "D"  # Defunct comet — no longer exists or disappeared (e.g. D/1993 F2 Shoemaker-Levy 9)
    Uncertain = (
        "X"  # Uncertain comet — no meaningful orbit computable; typically historical
    )
    Asteroid = "A"  # Minor planet with cometary designation — asteroidal object or near-parabolic/hyperbolic without cometary activity
    Interstellar = "I"  # Interstellar object — not gravitationally bound to the solar system (e.g. 1I/ʻOumuamua); prefix introduced 2017


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
    provisional_designation: Mapped[str | None] = mapped_column(
        default=None
    )  # extracted from full_name parentheses
    prefix: Mapped[CometPrefix | None] = mapped_column(
        default=None
    )  # comet designation prefix
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
    mass_kg: Mapped[int | None] = mapped_column(default=None)  # Object mass

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
    class_: Mapped[OrbitClass] = mapped_column("class")  # orbit classification
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
