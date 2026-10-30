"""The orbit of a pair in each orbit source, as the secondary's about the
primary.

`Elements` hold that relative orbit on the plane of the sky (`frame`): P in
d, a in AU or arcsec, angles in degrees, epochs as JD. ω is the secondary's.
Ω is the ascending node when `node_ascending` is true, else either node:
(Ω, ω) and (Ω + 180°, ω + 180°) give the same track on the sky.

Whose ω each source gives:
- ORB6 and the visual orbits of the MSC: the secondary's, from the node as
  listed. The last WDS measures test it: 2,708 ORB6 orbits put the secondary
  at the measured position angle, 158 at 180° from it.
- the spectroscopic orbits of the MSC, SBX and Gaia DR3: the primary's.
- a paper: as its `arg_periastron_of` says. A paper that does not say gives
  the primary's: Kepler-34 and -35 then have their primary eclipse at
  ω + ν = 90°, and Kepler-16 has the ω of its Gaia orbit.
- OEC: the secondary's with a node (a visual orbit), else the primary's.
- a Gaia DR3 astrometric orbit: the photocentre's. The photocentre is at
  −(B − β) times the secondary's offset, with B = m2 / (m1 + m2) and β the
  secondary's share of the light. Its i and Ω are the secondary's. Its ω
  and a give the secondary's only with both masses and the flux ratio. An
  AstroSpectroSB1 orbit has the primary's ω from its velocities, which also
  fix the ascending node.

The secondary's ω is the primary's + 180°. A secondary in front of the
primary, at the primary eclipse, is at ω + ν = 270°. The mean anomaly at the
epoch says where the pair is: 0 at periastron, from ω + ν = 270° at a primary
eclipse, λ − ω at the osculating epoch of a fit that gives the mean
longitude λ.
"""

import math
from typing import NamedTuple

from space_map_data.constants.stars import binaries
from space_map_data.download.providers.stars import orb6
from space_map_data.extrasolar.exoplanets.catalogues import OEC
from space_map_data.extrasolar.frame import mean_anomaly_from_true
from space_map_data.extrasolar.sources.gaia_orbits import ASTROMETRIC, ECLIPSING
from space_map_data.extrasolar.systems.nodes import GAIA_ORBITS
from space_map_data.extrasolar.systems.orbits import (
    LITERATURE,
    MSC,
    ORB6,
    SBX,
    TRANSIT,
)

# Where the mean anomaly at the epoch comes from.
PERIASTRON, ECLIPSE, OSCULATING = "periastron", "eclipse", "osculating"
# Gaia DR3 times of periastron are days from J2016.0.
GAIA_EPOCH = 2_457_389.0
ASTRO_SPECTRO = "AstroSpectroSB1"
# A secondary in front of the primary is at this ω + ν.
IN_FRONT = 270.0
# ω of a circular orbit, which draws the same for any value.
CIRCULAR_OMEGA = 90.0
ECLIPSE_EVENTS = frozenset({binaries.PRIMARY_ECLIPSE, binaries.CONJUNCTION, TRANSIT})
# The columns of a Gaia DR3 orbit that `gaia_elements` reads.
GAIA_ELEMENTS = (
    "solution_id",
    "nss_solution_type",
    "period",
    "t_periastron",
    "eccentricity",
    "arg_periastron",
    "inclination",
    *(f"{name}_thiele_innes" for name in "abfgch"),
    "parallax_nss",
    "semi_amplitude_primary",
    "semi_amplitude_secondary",
    "m1",
    "m2",
    "fluxratio",
)


class Elements(NamedTuple):
    source: str
    # The row of the source's table, for the order and the report.
    row: int
    reference: str | None
    period: float | None
    a_au: float | None
    a_arcsec: float | None
    eccentricity: float | None
    inclination: float | None
    node: float | None
    node_ascending: bool
    arg_periastron: float | None
    # ω tells which side of the sky plane is near: it comes from velocities,
    # an eclipse or an identified node.
    omega_fixed: bool
    epoch: float | None
    mean_anomaly: float | None
    phase: str | None
    # In the order of the orbit's own primary and secondary.
    k1: float | None = None
    k2: float | None = None
    mass1: float | None = None
    mass2: float | None = None
    # ORB6 grade, 1 best; 0 where the source has none.
    grade: int = 0
    # Values that the row fills itself: an e or ω of a circular orbit.
    assumed: frozenset[str] = frozenset()

    def flipped(self) -> Elements:
        """The same orbit as the first star's about the second."""
        return self._replace(
            arg_periastron=_turn(self.arg_periastron),
            k1=self.k2,
            k2=self.k1,
            mass1=self.mass2,
            mass2=self.mass1,
        )

    def drawn_elements(self) -> int:
        """How many of P, a, e, i, Ω, ω and the epoch it has."""
        return sum(
            value is not None
            for value in (
                self.period,
                self.a_au if self.a_au is not None else self.a_arcsec,
                self.eccentricity,
                self.inclination,
                self.node,
                self.arg_periastron,
                self.epoch,
            )
        )


def _turn(angle: float | None) -> float | None:
    return None if angle is None else (angle + 180.0) % 360.0


def _circular(
    e: float | None, omega: float | None
) -> tuple[float | None, float | None, frozenset[str]]:
    """e and ω, with those of a circular orbit filled: an e of none is 0, and
    a circular orbit with no ω takes CIRCULAR_OMEGA."""
    assumed = set()
    if e is None:
        e = 0.0
        assumed.add("eccentricity")
    if e == 0 and omega is None:
        omega = CIRCULAR_OMEGA
        assumed.add("arg_periastron")
    return e, omega, frozenset(assumed)


def eclipse_anomaly(omega: float, e: float) -> float:
    """The mean anomaly at the primary eclipse, from the secondary's ω."""
    return mean_anomaly_from_true(IN_FRONT - omega, e)


def _epoch(
    row: dict, omega: float | None, e: float | None
) -> tuple[float | None, float | None, str | None]:
    """The epoch, the mean anomaly then and its phase, from an ORBITS row."""
    if row["mean_longitude"] is not None and row["osculating_epoch"] is not None:
        if row["arg_periastron"] is None:
            return None, None, None
        anomaly = (row["mean_longitude"] - row["arg_periastron"]) % 360.0
        return row["osculating_epoch"], anomaly, OSCULATING
    epoch, event = row["epoch"], row["epoch_event"]
    if epoch is None:
        return None, None, None
    if event == binaries.PERIASTRON:
        return epoch, 0.0, PERIASTRON
    if event in ECLIPSE_EVENTS and omega is not None and e is not None and e < 1:
        return epoch, eclipse_anomaly(omega, e), ECLIPSE
    return None, None, None


def catalogue_elements(row: dict) -> Elements | None:
    """The relative orbit of an ORBITS row, None without a period."""
    if not row["period"]:
        return None
    source = row["source"]
    omega = row["arg_periastron"]
    node, ascending = row["node"], bool(row["node_ascending"])
    a_au, a_arcsec = row["semi_major_axis_au"], row["semi_major_axis"]
    fixed = False
    grade = 0
    if source == LITERATURE:
        if row["arg_periastron_of"] != binaries.SECONDARY:
            omega = _turn(omega)
        fixed = True
    elif source == MSC:
        if a_arcsec is None and row["inclination"] is None:
            omega, fixed = _turn(omega), True
        elif row["k1"] is not None:
            # A visual orbit with velocities gives the ascending node.
            ascending = node is not None
            fixed = ascending
    elif source == ORB6:
        grade = int(row["grade"]) if row["grade"] else 0
        fixed = ascending
        if grade == orb6.ASTROMETRIC_GRADE:
            # The photocentre's, with no flux ratio to give the secondary's.
            omega, a_arcsec, fixed = None, None, False
    elif source == SBX:
        omega, fixed = _turn(omega), True
    elif source == OEC:
        if node is None:
            omega = _turn(omega)
        fixed = node is None or ascending
    e, omega, assumed = _circular(row["eccentricity"], omega)
    epoch, anomaly, phase = _epoch(row, omega, e)
    return Elements(
        source=source,
        row=row["row"],
        reference=row["reference"],
        period=row["period"],
        a_au=a_au,
        a_arcsec=a_arcsec,
        eccentricity=e,
        inclination=row["inclination"],
        node=None if node is None else node % 360.0,
        node_ascending=ascending and node is not None,
        arg_periastron=omega,
        omega_fixed=fixed and omega is not None,
        epoch=epoch,
        mean_anomaly=anomaly,
        phase=phase,
        k1=row["k1"],
        k2=row["k2"],
        grade=grade,
        assumed=assumed,
    )


def thiele_innes(
    a: float, b: float, f: float, g: float
) -> tuple[float, float, float, float]:
    """a0 (the unit of A), i, Ω and ω in degrees from the Thiele-Innes A, B,
    F and G, with Ω in [0°, 180°)."""
    u = (a * a + b * b + f * f + g * g) / 2
    v = a * g - b * f
    a0 = math.sqrt(u + math.sqrt(max(0.0, (u + v) * (u - v))))
    inclination = math.degrees(math.acos(max(-1.0, min(1.0, v / (a0 * a0)))))
    plus = math.atan2(b - f, a + g)
    minus = math.atan2(-b - f, a - g)
    omega = math.degrees((plus + minus) / 2)
    node = math.degrees((plus - minus) / 2)
    if not 0 <= node % 360 < 180:
        node, omega = node + 180, omega + 180
    return a0, inclination, node % 360, omega % 360


def gaia_elements(row: dict, at: int) -> Elements | None:
    """The relative orbit of a Gaia DR3 orbit row (GAIA_ELEMENTS), None
    without a period. `at` is its row."""
    kind = row["nss_solution_type"]
    if not row["period"]:
        return None
    m1, m2 = row["m1"], row["m2"]
    both = m1 is not None and m2 is not None and m1 + m2 > 0
    epoch = None if row["t_periastron"] is None else GAIA_EPOCH + row["t_periastron"]
    item = Elements(
        source=GAIA_ORBITS,
        row=at,
        reference=str(row["solution_id"]) if row["solution_id"] else None,
        period=row["period"],
        a_au=None,
        a_arcsec=None,
        eccentricity=None,
        inclination=None,
        node=None,
        node_ascending=False,
        arg_periastron=None,
        omega_fixed=False,
        epoch=epoch,
        mean_anomaly=None if epoch is None else 0.0,
        phase=None if epoch is None else PERIASTRON,
        k1=row["semi_amplitude_primary"],
        k2=row["semi_amplitude_secondary"],
        mass1=m1 if both else None,
        mass2=m2 if both else None,
    )
    if kind in ASTROMETRIC:
        a, b, f, g = (row[f"{name}_thiele_innes"] for name in "abfg")
        if None in (a, b, f, g):
            return None
        a0, inclination, node, omega = thiele_innes(a, b, f, g)
        item = item._replace(inclination=inclination, node=node)
        if kind == ASTRO_SPECTRO and row["c_thiele_innes"] is not None:
            velocity = math.degrees(
                math.atan2(row["c_thiele_innes"], row["h_thiele_innes"])
            )
            if abs((omega - velocity + 180) % 360 - 180) > 90:
                node, omega = (node + 180) % 360, (omega + 180) % 360
            item = item._replace(
                node=node,
                node_ascending=True,
                arg_periastron=_turn(omega),
                omega_fixed=True,
            )
        flux = row["fluxratio"]
        if both and flux is not None:
            share, light = m2 / (m1 + m2), flux / (1 + flux)
            if share != light and kind != ASTRO_SPECTRO:
                item = item._replace(
                    arg_periastron=omega if light > share else _turn(omega)
                )
            parallax = row["parallax_nss"]
            if share != light and parallax and parallax > 0:
                item = item._replace(a_au=a0 / abs(share - light) / parallax)
    else:
        omega = row["arg_periastron"]
        item = item._replace(
            arg_periastron=_turn(omega),
            omega_fixed=omega is not None,
            inclination=row["inclination"] if kind in ECLIPSING else None,
        )
    e, omega, assumed = _circular(row["eccentricity"], item.arg_periastron)
    return item._replace(eccentricity=e, arg_periastron=omega, assumed=assumed)
