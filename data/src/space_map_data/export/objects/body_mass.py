"""One mass for each solar-system body, from the best source that has one.

The sources, best first:

1. The GM of JPL's satellite physical parameters table. Nominal when it is an
   upper limit, when it has no 1σ, or when its 1σ is not smaller than it.
   Where the table prints the `gm_de440.tpc` GM to fewer digits, the value is
   that of the kernel and the nominal mark that of the table.
2. The GM of `gm_de440.tpc`, JPL's ephemeris GM file.
3. A GM from another kernel: the mission target PCKs, and the kernels that
   `target_bodies` writes from the papers of `constants.body_literature`. A
   paper's GM is credited to the paper.
4. The SBDB GM, of a body with no satellite.
5. The SsODNet mass, of a body with no satellite.
6. The AsterSat system mass, from its fit of the satellite orbit.
7. The Johnston's Archive system mass.
8. A nominal catalogue mass: SsODNet with no error, Johnston flagged assumed
   or estimated.
9. A GM from a kernel of NOMINAL_GM_KERNELS. Nominal. `target_bodies`'s own
   estimates (volume x an assumed density) are credited to no one.
10. The Wikidata mass (P2067), only from a statement that cites a source.

A GM of 0 is no value. Every nominal mark comes from the source's own data.
SBDB and SsODNet do not say whether the mass of a body with a satellite is its
own or its system's, so such a body takes neither.
Where a kernel gives a binary system and its primary apart, the primary takes
its own GM when it differs from the system GM. A system mass is the mass of a
body and its satellites together: the AsterSat and Johnston masses, the GMs of
SYSTEM_GM_KERNELS, and a system GM equal to the GM of its primary. A
barycentre has no body mass. The object bundles and the lineups take a body's
mass from here, so they agree.
"""

import logging
from collections import defaultdict
from collections.abc import Callable, Mapping
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import NamedTuple

from sqlalchemy.orm import Session

from space_map_data.constants import body_literature
from space_map_data.download.providers.spice.probes.target_bodies import (
    GM_ESTIMATES_NAME,
    GM_PATCH_NAME,
    GM_SYSTEMS_NAME,
)
from space_map_data.export.names import resolve_wikidata_qid
from space_map_data.export.objects.body_radius import NOT_BODIES
from space_map_data.export.objects.wikidata_claims import (
    claim_reader,
    referenced_mass_kg_from_claims,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.systems import GmTable
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.ingest.providers.objects.sbdb import mass_kg_from_gm
from space_map_data.models.object import (
    SBDB,
    AsterSatMoon,
    JohnstonSystem,
    JPLSatellitePhysical,
    Object,
    ObjectType,
    SsODNet,
)

logger = logging.getLogger(__name__)

MASS_SOURCE_JPL_SATELLITES = "jpl_satellite_physical"
MASS_SOURCE_PCK = "pck"
MASS_SOURCE_LITERATURE = "literature"
# An estimate of `target_bodies`'s own, so there is no work to credit.
MASS_SOURCE_ESTIMATE = "estimate"
MASS_SOURCE_SBDB = "sbdb"
MASS_SOURCE_SSODNET = "ssodnet"
MASS_SOURCE_ASTERSAT = "astersat"
MASS_SOURCE_JOHNSTON = "johnston"
MASS_SOURCE_WIKIDATA = "wikidata"

EPHEMERIS_GM_KERNEL = "gm_de440.tpc"
# Kernels whose GMs are not measured. `Gravity.tpc` is a 1994 NAIF mail of
# one-digit 1992 Explanatory Supplement ratios. The estimates kernel holds
# volume x an assumed density.
NOMINAL_GM_KERNELS = frozenset(("Gravity.tpc", GM_ESTIMATES_NAME))
# Kernels whose GMs are those of a whole binary system.
SYSTEM_GM_KERNELS = frozenset((GM_SYSTEMS_NAME,))
# The kernels `target_bodies` writes from `constants.body_literature`: NAIF did
# not publish their GMs, the papers did.
_PAPER_GMS = {**body_literature.GMS, **body_literature.SYSTEM_GMS}
_PAPER_GM_KERNELS = frozenset((GM_PATCH_NAME, GM_SYSTEMS_NAME))

# A craft's Wikidata mass is its launch mass. A barycentre is not a body.
_NO_BODY_MASS = NOT_BODIES | {ObjectType.barycenter}


class BodyMass(NamedTuple):
    """A body's mass (kg) and the source of it."""

    kg: float
    source: str
    # A placeholder, an upper limit or an estimate, not a measurement.
    nominal: bool = False
    # The ephemeris of a JPL GM or the kernel of a PCK GM; the paper
    # ({title, url}) of a literature GM.
    reference: str | dict | None = None
    # The mass of the body and its satellites together.
    system: bool = False


class JPLGm(NamedTuple):
    """A GM of JPL's satellite table (km^3/s^2)."""

    # As the table prints it: its digits are the precision of the fit.
    gm: str | None
    sigma: float | None
    upper_limit: bool
    ephemeris: str | None


class Satellite(NamedTuple):
    """The ids of a satellite, in the order of `BodyRadii.pick`."""

    object_id: str
    naif_id: int | None
    qid: str | None
    object_type: ObjectType


def same_fit(printed: str, full: float) -> bool:
    """True when ``printed`` is ``full`` cut or rounded to the digits it shows."""
    shown = Decimal(printed)
    return any(
        Decimal(repr(full)).quantize(shown, rounding=rounding) == shown
        for rounding in (ROUND_DOWN, ROUND_HALF_EVEN)
    )


def jpl_mass(row: JPLGm, ephemeris_gm: float | None = None) -> BodyMass | None:
    """The mass of one row of JPL's satellite table. A GM of 0 is no value.

    ``ephemeris_gm`` is the GM of the body in EPHEMERIS_GM_KERNEL.
    """
    printed = row.gm
    if not printed or not (gm := float(printed)):
        return None
    nominal = row.upper_limit or row.sigma is None or row.sigma >= gm
    if ephemeris_gm is not None and same_fit(printed, ephemeris_gm):
        return BodyMass(
            mass_kg_from_gm(ephemeris_gm),
            MASS_SOURCE_PCK,
            nominal,
            EPHEMERIS_GM_KERNEL,
        )
    return BodyMass(
        mass_kg_from_gm(gm), MASS_SOURCE_JPL_SATELLITES, nominal, row.ephemeris
    )


def _kernel_mass(naif_id: int, gm: float, kernel: str | None, system: bool) -> BodyMass:
    """The mass of a kernel GM, credited to whoever made the value."""
    kg = mass_kg_from_gm(gm)
    if kernel in _PAPER_GM_KERNELS:
        paper = body_literature.REFERENCES[_PAPER_GMS[naif_id].reference]
        return BodyMass(
            kg, MASS_SOURCE_LITERATURE, reference=paper._asdict(), system=system
        )
    if kernel == GM_ESTIMATES_NAME:
        return BodyMass(kg, MASS_SOURCE_ESTIMATE, True, system=system)
    return BodyMass(kg, MASS_SOURCE_PCK, kernel in NOMINAL_GM_KERNELS, kernel, system)


def kernel_masses(
    table: GmTable,
) -> tuple[dict[int, BodyMass], dict[int, BodyMass], dict[int, BodyMass]]:
    """The GMs of ``load_gms`` as masses by NAIF id.

    The primary of a binary system takes its own GM when it differs from the
    system GM, and that is not a system mass whatever the kernel of the system
    GM. Otherwise the GM is a system mass. Returns those of the ephemeris GM
    file, of the other kernels, and of NOMINAL_GM_KERNELS apart.
    """
    ephemeris: dict[int, BodyMass] = {}
    others: dict[int, BodyMass] = {}
    nominal: dict[int, BodyMass] = {}
    for naif_id, gm in table.gms.items():
        kernel = table.kernels[naif_id] or None
        system = kernel in SYSTEM_GM_KERNELS
        if naif_id in table.primaries:
            # A primary GM equal to the system GM gives the moons no mass.
            primary_gm, primary_kernel = table.primaries[naif_id]
            if primary_gm == gm:
                system = True
            else:
                gm, kernel, system = primary_gm, primary_kernel, False
        mass = _kernel_mass(naif_id, gm, kernel, system)
        if kernel in NOMINAL_GM_KERNELS:
            nominal[naif_id] = mass
        elif kernel == EPHEMERIS_GM_KERNEL:
            ephemeris[naif_id] = mass
        else:
            others[naif_id] = mass
    return ephemeris, others, nominal


class BodyMasses:
    """The mass of each body, by the source order of this module.

    ``jpl``, ``ephemeris``, ``kernels`` and ``nominal_kernels`` are keyed by
    NAIF id. ``catalogues``, ``nominal_catalogues`` and ``satellites`` are
    keyed by Object.id.
    """

    def __init__(
        self,
        jpl: Mapping[int, BodyMass] | None = None,
        ephemeris: Mapping[int, BodyMass] | None = None,
        kernels: Mapping[int, BodyMass] | None = None,
        catalogues: Mapping[str, BodyMass] | None = None,
        wikidata_kg: Callable[[str], float | None] | None = None,
        nominal_catalogues: Mapping[str, BodyMass] | None = None,
        nominal_kernels: Mapping[int, BodyMass] | None = None,
        satellites: Mapping[str, tuple[Satellite, ...]] | None = None,
    ) -> None:
        self._by_naif = (jpl or {}, ephemeris or {}, kernels or {})
        self._catalogues = catalogues or {}
        self._wikidata_kg = wikidata_kg
        self._nominal_catalogues = nominal_catalogues or {}
        self._nominal_kernels = nominal_kernels or {}
        self._satellites = satellites or {}

    def pick(
        self,
        object_id: str,
        naif_id: int | None,
        qid: str | None,
        object_type: ObjectType,
    ) -> BodyMass | None:
        if object_type in _NO_BODY_MASS:
            return None
        if naif_id is not None:
            for source in self._by_naif:
                if (mass := source.get(naif_id)) is not None:
                    return mass
        if (mass := self._catalogues.get(object_id)) is not None:
            return mass
        if (mass := self._nominal_catalogues.get(object_id)) is not None:
            return mass
        if naif_id is not None and (mass := self._nominal_kernels.get(naif_id)):
            return mass
        if qid and self._wikidata_kg and (kg := self._wikidata_kg(qid)):
            return BodyMass(kg, MASS_SOURCE_WIKIDATA)
        return None

    def of(self, obj: Object) -> BodyMass | None:
        return self.pick(
            obj.id, obj.naif_id, resolve_wikidata_qid(obj), obj.object_type
        )

    def satellites(self, object_id: str) -> tuple[Satellite, ...]:
        """The moons of a body, which share its system mass."""
        return self._satellites.get(object_id, ())


def jpl_masses(
    session: Session, ephemeris_gms: Mapping[int, float]
) -> dict[int, BodyMass]:
    """The masses of JPL's satellite table by NAIF id.

    ``ephemeris_gms`` are the GMs of EPHEMERIS_GM_KERNEL by NAIF id.
    """
    out: dict[int, BodyMass] = {}
    for row in session.query(JPLSatellitePhysical):
        mass = jpl_mass(
            JPLGm(
                row.gm_km3_s2, row.gm_sigma_km3_s2, row.gm_upper_limit, row.ephemeris
            ),
            ephemeris_gms.get(row.naif_id),
        )
        if mass is None:
            logger.debug("JPL GM of %d is %s: no value", row.naif_id, row.gm_km3_s2)
            continue
        out[row.naif_id] = mass
    return out


def binary_ids(session: Session) -> set[str]:
    """The Object.ids of the bodies with a satellite: the parent of a moon,
    of an AsterSat orbit or of a Johnston system."""
    found = {row[0] for row in session.query(AsterSatMoon.parent_object_id)}
    found |= {row[0] for row in session.query(JohnstonSystem.object_id)}
    moons = session.query(Object.parent_id).filter(
        Object.object_type == ObjectType.moon, Object.parent_id.is_not(None)
    )
    found |= {row[0] for row in moons}
    return found


def catalogue_masses(
    session: Session,
) -> tuple[dict[str, BodyMass], dict[str, BodyMass]]:
    """The SBDB, SsODNet, AsterSat and Johnston masses by Object.id, best
    source per body.

    Returns the measured ones and the nominal ones apart.
    """
    measured: dict[str, BodyMass] = {}
    nominal: dict[str, BodyMass] = {}
    binaries = binary_ids(session)
    dropped: set[str] = set()

    def add(body_id: str, mass: BodyMass) -> None:
        (nominal if mass.nominal else measured).setdefault(body_id, mass)

    for body_id, gm in session.query(SBDB.object_id, SBDB.GM).filter(
        SBDB.GM.is_not(None), SBDB.GM > 0
    ):
        if body_id in binaries:
            dropped.add(body_id)
        else:
            add(body_id, BodyMass(mass_kg_from_gm(gm), MASS_SOURCE_SBDB))
    for body_id, kg, sigma in session.query(
        SsODNet.object_id, SsODNet.mass_kg, SsODNet.mass_kg_sigma
    ).filter(SsODNet.mass_kg.is_not(None), SsODNet.mass_kg > 0):
        if body_id in binaries:
            dropped.add(body_id)
        else:
            add(body_id, BodyMass(kg, MASS_SOURCE_SSODNET, sigma is None))
    logger.info("%d bodies with a satellite take no SBDB or SsODNet mass", len(dropped))
    for body_id, gm in (
        session.query(AsterSatMoon.parent_object_id, AsterSatMoon.gm)
        .filter(AsterSatMoon.gm.is_not(None), AsterSatMoon.gm > 0)
        .order_by(AsterSatMoon.parent_object_id, AsterSatMoon.gm)
    ):
        add(body_id, BodyMass(mass_kg_from_gm(gm), MASS_SOURCE_ASTERSAT, system=True))
    for body_id, kg, is_nominal in session.query(
        JohnstonSystem.object_id, JohnstonSystem.mass_kg, JohnstonSystem.mass_kg_nominal
    ).filter(JohnstonSystem.mass_kg.is_not(None), JohnstonSystem.mass_kg > 0):
        add(body_id, BodyMass(kg, MASS_SOURCE_JOHNSTON, is_nominal, system=True))
    return measured, nominal


def moon_satellites(session: Session) -> dict[str, tuple[Satellite, ...]]:
    """The moons of each body, by Object.id of the body."""
    out: defaultdict[str, list[Satellite]] = defaultdict(list)
    moons = session.query(Object).filter(Object.object_type == ObjectType.moon)
    for moon in moons.order_by(Object.id):
        if moon.parent_id is not None:
            out[moon.parent_id].append(
                Satellite(
                    moon.id, moon.naif_id, resolve_wikidata_qid(moon), moon.object_type
                )
            )
    return {body_id: tuple(moons) for body_id, moons in out.items()}


def load_body_masses(
    session: Session,
    gms: GmTable,
    entities: WikidataEntityCache,
    units: UnitConverter,
) -> BodyMasses:
    """The masses of every body for one export. ``gms`` is `load_gms`."""
    ephemeris, kernels, nominal_kernels = kernel_masses(gms)
    catalogues, nominal_catalogues = catalogue_masses(session)
    ephemeris_gms = {
        naif_id: gm
        for naif_id, gm in gms.gms.items()
        if gms.kernels[naif_id] == EPHEMERIS_GM_KERNEL
    }
    return BodyMasses(
        jpl=jpl_masses(session, ephemeris_gms),
        ephemeris=ephemeris,
        kernels=kernels,
        catalogues=catalogues,
        wikidata_kg=claim_reader(entities, units, referenced_mass_kg_from_claims),
        nominal_catalogues=nominal_catalogues,
        nominal_kernels=nominal_kernels,
        satellites=moon_satellites(session),
    )


def bundle_fields(mass: BodyMass | None) -> dict:
    """The mass fields of an object bundle and of a lineup entry."""
    if mass is None:
        return {}
    out: dict = {"mass_kg": mass.kg, "mass_source": mass.source}
    if mass.reference is not None:
        out["mass_reference"] = mass.reference
    if mass.nominal:
        out["mass_nominal"] = True
    if mass.system:
        out["mass_system"] = True
    return out
