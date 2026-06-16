"""Typed enums for the GCAT SatType field (launchlog ``Type`` column).

SatType is a 12-byte positional string; each byte is an independent flag.
In the launch log byte 1 is always ``P`` (payload) and bytes 10-12 are
McDowell's plot/bookkeeping bytes, so only bytes 2-9 are decoded here. A blank
or ``-`` byte is a positional filler (not applicable) → None; an unrecognised
code is logged and mapped to None rather than raised, since the field spans a
large combinatorial space.

Source: https://planet4589.org/space/gcat/web/intro/type.html
"""

import logging
from collections.abc import Mapping
from enum import StrEnum

logger = logging.getLogger(__name__)


# Byte 2 — type modifier (payload context, i.e. combined with byte-1 ``P``).
class TypeModifier(StrEnum):
    ALIAS = "alias"  # PA: leased / jointly-owned phase
    CREWED_SPACESHIP = "crewed_spaceship"  # PH
    UNCREWED_CABIN = "uncrewed_cabin"  # PP: pressurized cabin, no crew
    NON_STANDARD = "non_standard"  # PX


TYPE_MODIFIER_CODES: dict[str, TypeModifier] = {
    "A": TypeModifier.ALIAS,
    "H": TypeModifier.CREWED_SPACESHIP,
    "P": TypeModifier.UNCREWED_CABIN,
    "X": TypeModifier.NON_STANDARD,
}


# Byte 3 — attachment.
class Attachment(StrEnum):
    ATTACHED = "attached"
    FAILED_TO_SEPARATE = "failed_to_separate"
    INTERNAL = "internal"
    TO_SEPARATE_LATER = "to_separate_later"
    TRANSFERRED = "transferred"


ATTACHMENT_CODES: dict[str, Attachment] = {
    "A": Attachment.ATTACHED,
    "F": Attachment.FAILED_TO_SEPARATE,
    "I": Attachment.INTERNAL,
    "S": Attachment.TO_SEPARATE_LATER,
    "T": Attachment.TRANSFERRED,
}


# Byte 4 — subtype.
class Subtype(StrEnum):
    ADAPTER = "adapter"
    BATTERY_DEBRIS = "battery_debris"
    CALIBRATION = "calibration"
    DUMMY = "dummy"
    TETHERED_SPACESUIT = "tethered_spacesuit"
    FAIRING = "fairing"
    MISC_DEBRIS = "misc_debris"
    HUMAN_SPACEFLIGHT = "human_spaceflight"
    COLLISION_DEBRIS = "collision_debris"
    INSULATION_DEBRIS = "insulation_debris"
    MOTOR_SLAG = "motor_slag"
    POST_LANDING_SEPARATION = "post_landing_separation"
    JETTISONED_MOTOR = "jettisoned_motor"
    NUCLEAR_REACTOR = "nuclear_reactor"
    INSERTION_DEBRIS = "insertion_debris"
    PROPULSION_BREAKUP = "propulsion_breakup"
    AERODYNAMIC_BREAKUP = "aerodynamic_breakup"
    REENTRY_VEHICLE = "reentry_vehicle"
    SUBSATELLITE = "subsatellite"
    EJECTED_SECTION = "ejected_section"
    UNTETHERED_EVA = "untethered_eva"
    EJECTION_MECHANISM = "ejection_mechanism"
    ASAT_DEBRIS = "asat_debris"
    UNKNOWN_DEBRIS = "unknown_debris"
    DESPIN_DEVICE = "despin_device"
    DESTRUCT_DEBRIS = "destruct_debris"


SUBTYPE_CODES: dict[str, Subtype] = {
    "A": Subtype.ADAPTER,
    "B": Subtype.BATTERY_DEBRIS,
    "C": Subtype.CALIBRATION,
    "D": Subtype.DUMMY,
    "E": Subtype.TETHERED_SPACESUIT,
    "F": Subtype.FAIRING,
    "G": Subtype.MISC_DEBRIS,
    "H": Subtype.HUMAN_SPACEFLIGHT,
    "I": Subtype.COLLISION_DEBRIS,
    "J": Subtype.INSULATION_DEBRIS,
    "K": Subtype.MOTOR_SLAG,
    "L": Subtype.POST_LANDING_SEPARATION,
    "M": Subtype.JETTISONED_MOTOR,
    "N": Subtype.NUCLEAR_REACTOR,
    "O": Subtype.INSERTION_DEBRIS,
    "P": Subtype.PROPULSION_BREAKUP,
    "Q": Subtype.AERODYNAMIC_BREAKUP,
    "R": Subtype.REENTRY_VEHICLE,
    "S": Subtype.SUBSATELLITE,
    "T": Subtype.EJECTED_SECTION,
    "U": Subtype.UNTETHERED_EVA,
    "V": Subtype.EJECTION_MECHANISM,
    "W": Subtype.ASAT_DEBRIS,
    "X": Subtype.UNKNOWN_DEBRIS,
    "Y": Subtype.DESPIN_DEVICE,
    "Z": Subtype.DESTRUCT_DEBRIS,
}


# Byte 5 — orbit status.
class OrbitStatus(StrEnum):
    DEEP_SPACE = "deep_space"
    PAD_EXPLOSION = "pad_explosion"
    FAILED_TO_ORBIT = "failed_to_orbit"
    PLANETARY_SURFACE = "planetary_surface"
    MISSING_FROM_SATCAT = "missing_from_satcat"
    ORBITAL_ENERGY_NON_ORBIT = "orbital_energy_non_orbit"
    PARTIAL_ORBIT = "partial_orbit"
    REENTRY_ORBIT = "reentry_orbit"
    NEAR_ORBIT = "near_orbit"
    TRANSIENT_ORBIT = "transient_orbit"
    ESCAPE_ENERGY = "escape_energy"
    EXTRATERRESTRIAL_LAUNCH = "extraterrestrial_launch"
    EXTRATERRESTRIAL_BODY_LAUNCH = "extraterrestrial_body_launch"


ORBIT_STATUS_CODES: dict[str, OrbitStatus] = {
    "D": OrbitStatus.DEEP_SPACE,
    "E": OrbitStatus.PAD_EXPLOSION,
    "F": OrbitStatus.FAILED_TO_ORBIT,
    "L": OrbitStatus.PLANETARY_SURFACE,
    "M": OrbitStatus.MISSING_FROM_SATCAT,
    "O": OrbitStatus.ORBITAL_ENERGY_NON_ORBIT,
    "P": OrbitStatus.PARTIAL_ORBIT,
    "R": OrbitStatus.REENTRY_ORBIT,
    "S": OrbitStatus.NEAR_ORBIT,
    "T": OrbitStatus.TRANSIENT_ORBIT,
    "V": OrbitStatus.ESCAPE_ENERGY,
    "X": OrbitStatus.EXTRATERRESTRIAL_LAUNCH,
    "Z": OrbitStatus.EXTRATERRESTRIAL_BODY_LAUNCH,
}


# Byte 6 — human-spaceflight / special group.
class SpaceflightGroup(StrEnum):
    STATION_PROGRAM = "station_program"
    STATION_COMPONENT = "station_component"
    STATION_DEPLOYABLE = "station_deployable"
    STATION_EVA = "station_eva"
    STATION_CARGO = "station_cargo"
    STATION_MODULE = "station_module"
    SHUTTLE = "shuttle"
    VISITING_VEHICLE_PIECE = "visiting_vehicle_piece"
    VISITING_VEHICLE_STAGE = "visiting_vehicle_stage"
    STATION_VISITING_VEHICLE = "station_visiting_vehicle"


SPACEFLIGHT_GROUP_CODES: dict[str, SpaceflightGroup] = {
    "I": SpaceflightGroup.STATION_PROGRAM,
    "C": SpaceflightGroup.STATION_COMPONENT,
    "D": SpaceflightGroup.STATION_DEPLOYABLE,
    "E": SpaceflightGroup.STATION_EVA,
    "G": SpaceflightGroup.STATION_CARGO,
    "M": SpaceflightGroup.STATION_MODULE,
    "S": SpaceflightGroup.SHUTTLE,
    "T": SpaceflightGroup.VISITING_VEHICLE_PIECE,
    "U": SpaceflightGroup.VISITING_VEHICLE_STAGE,
    "V": SpaceflightGroup.STATION_VISITING_VEHICLE,
}


# Byte 7 — UN registration.
class UNRegistration(StrEnum):
    REGISTERED = "registered"
    MISREGISTERED = "misregistered"


UN_REGISTRATION_CODES: dict[str, UNRegistration] = {
    "U": UNRegistration.REGISTERED,
    "X": UNRegistration.MISREGISTERED,
}


# Byte 8 — failure / constellation operational status.
class OperationalStatus(StrEnum):
    CAUSED_LAUNCH_FAILURE = "caused_launch_failure"
    ASCENDING = "ascending"
    DRIFT = "drift"
    FAILED_EARLY = "failed_early"
    GRAVEYARD = "graveyard"
    REMOVED_FROM_CONSTELLATION = "removed_from_constellation"
    FAILED_DECAY = "failed_decay"
    OPERATIONAL = "operational"
    LOWERING_TO_REENTRY = "lowering_to_reentry"
    SPECIAL_TESTS = "special_tests"
    SLIGHTLY_REMOVED = "slightly_removed"
    MALFUNCTIONING = "malfunctioning"


OPERATIONAL_STATUS_CODES: dict[str, OperationalStatus] = {
    "*": OperationalStatus.CAUSED_LAUNCH_FAILURE,
    "A": OperationalStatus.ASCENDING,
    "D": OperationalStatus.DRIFT,
    "F": OperationalStatus.FAILED_EARLY,
    "G": OperationalStatus.GRAVEYARD,
    "L": OperationalStatus.REMOVED_FROM_CONSTELLATION,
    "M": OperationalStatus.FAILED_DECAY,
    "O": OperationalStatus.OPERATIONAL,
    "R": OperationalStatus.LOWERING_TO_REENTRY,
    "S": OperationalStatus.SPECIAL_TESTS,
    "T": OperationalStatus.SLIGHTLY_REMOVED,
    "U": OperationalStatus.MALFUNCTIONING,
}


# Byte 9 — id / status.
class IdStatus(StrEnum):
    UNCERTAIN_ID = "uncertain_id"
    STARLINK_OOS_MANEUVERABLE = "starlink_oos_maneuverable"
    STARLINK_DEAD = "starlink_dead"
    MULTIPLE_OBJECTS = "multiple_objects"
    SECRET = "secret"
    FORMERLY_SECRET = "formerly_secret"
    ISS_CARGO_LAUNCH_UNCERTAIN = "iss_cargo_launch_uncertain"
    ISS_CARGO_RETURN_UNCERTAIN = "iss_cargo_return_uncertain"
    UNKNOWN_LAUNCH_SOURCE = "unknown_launch_source"
    TLE_DISAGREEMENT = "tle_disagreement"


ID_STATUS_CODES: dict[str, IdStatus] = {
    "?": IdStatus.UNCERTAIN_ID,
    "+": IdStatus.STARLINK_OOS_MANEUVERABLE,
    "*": IdStatus.STARLINK_DEAD,
    "m": IdStatus.MULTIPLE_OBJECTS,
    "C": IdStatus.SECRET,
    "c": IdStatus.FORMERLY_SECRET,
    "U": IdStatus.ISS_CARGO_LAUNCH_UNCERTAIN,
    "D": IdStatus.ISS_CARGO_RETURN_UNCERTAIN,
    "X": IdStatus.UNKNOWN_LAUNCH_SOURCE,
    "s": IdStatus.TLE_DISAGREEMENT,
}


# (column name, 0-based byte index, code table). Byte 1 (index 0, always "P")
# and bytes 10-12 (plot/bookkeeping) are not decoded.
_SAT_TYPE_BYTES: tuple[tuple[str, int, Mapping[str, StrEnum]], ...] = (
    ("type_modifier", 1, TYPE_MODIFIER_CODES),
    ("attachment", 2, ATTACHMENT_CODES),
    ("subtype", 3, SUBTYPE_CODES),
    ("orbit_status", 4, ORBIT_STATUS_CODES),
    ("spaceflight_group", 5, SPACEFLIGHT_GROUP_CODES),
    ("un_registration", 6, UN_REGISTRATION_CODES),
    ("operational_status", 7, OPERATIONAL_STATUS_CODES),
    ("id_status", 8, ID_STATUS_CODES),
)


# Positional fillers ("not applicable" in this byte) → None, not unknown codes.
_FILLERS = ("", " ", "-", ".")

# (field, code) pairs already warned about — keeps the unknown-code warning to
# one line per distinct code instead of one per row.
_warned_unknown: set[tuple[str, str]] = set()


def parse_sat_type(raw: str | None) -> dict[str, StrEnum | None]:
    """Decode a GCAT SatType string into its byte-2..9 typed fields.

    Filler bytes (blank, ``-``, ``.``) and missing positions map to None; an
    unrecognised code maps to None and is logged once per distinct code.
    """
    result: dict[str, StrEnum | None] = {}
    for name, index, table in _SAT_TYPE_BYTES:
        ch = raw[index] if raw and index < len(raw) else ""
        if ch in _FILLERS:
            result[name] = None
            continue
        value = table.get(ch)
        if value is None and (name, ch) not in _warned_unknown:
            _warned_unknown.add((name, ch))
            logger.warning("Unknown GCAT SatType %s code: %r (e.g. %r)", name, ch, raw)
        result[name] = value
    return result
