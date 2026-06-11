"""Earth-orbit zone classification.

Primary zones (LEO/MEO/HEO/GSO/CIS/VHEO) partition the perigee/apogee
plane; overlay zones add inclination-based labels (GTO/GEO/Molniya/
Tundra/SSO/Polar/Retrograde/Equatorial). An object can hold one primary
plus any number of overlays.
"""

from enum import StrEnum

R_EARTH_KM = 6378.137
GEO_ALT_KM = 35786.0

LEO_APO_MAX = 2000
MEO_APO_MAX = 35000
HEO_APO_MAX = 50000
CISLUNAR_APO_MAX = 500000
GSO_BAND_HALF_WIDTH = 2000
GTO_APO_MIN, GTO_APO_MAX = 30000, 40000
MOLNIYA_APO_MIN, MOLNIYA_APO_MAX = 35000, 45000
GEO_INC_MAX_DEG = 1.0
MOLNIYA_INC_DEG, MOLNIYA_INC_TOL_DEG = 63.4, 3.0
TUNDRA_INC_TOL_DEG = 5.0
SSO_INC_MIN_DEG, SSO_INC_MAX_DEG = 96.0, 100.0
POLAR_INC_MIN_DEG, POLAR_INC_MAX_DEG = 80.0, 100.0
EQUATORIAL_INC_MAX_DEG = 10.0


class EarthOrbitClass(StrEnum):
    """Primary + overlay zones for Earth-orbiting payloads."""

    LEO = "LEO"
    MEO = "MEO"
    GSO = "GSO"
    HEO = "HEO"
    CIS = "CIS"
    VHEO = "VHEO"
    VLEO = "VLEO"
    GTO = "GTO"
    GEO = "GEO"
    IGSO = "IGSO"
    GRA = "GRA"
    MOL = "MOL"
    TUN = "TUN"
    SSO = "SSO"
    POL = "POL"
    RET = "RET"
    EQU = "EQU"


PRIMARY_ZONES: frozenset[EarthOrbitClass] = frozenset(
    {
        EarthOrbitClass.LEO,
        EarthOrbitClass.MEO,
        EarthOrbitClass.GSO,
        EarthOrbitClass.HEO,
        EarthOrbitClass.CIS,
        EarthOrbitClass.VHEO,
    }
)


def classify_earth_orbit(
    perigee_km: float | None,
    apogee_km: float | None,
    inclination_deg: float | None,
) -> list[EarthOrbitClass]:
    """Return every zone an Earth orbit fits into.

    Caller must pre-filter for active Earth-centred orbits. Returns empty
    when perigee or apogee is missing.
    """
    if perigee_km is None or apogee_km is None:
        return []

    classes: list[EarthOrbitClass] = []
    peri, apo = perigee_km, apogee_km

    if apo < LEO_APO_MAX:
        classes.append(EarthOrbitClass.LEO)
    elif apo < MEO_APO_MAX:
        if peri >= LEO_APO_MAX:
            classes.append(EarthOrbitClass.MEO)
        else:
            classes.append(EarthOrbitClass.HEO)
    elif apo < HEO_APO_MAX:
        if abs(peri - GEO_ALT_KM) < GSO_BAND_HALF_WIDTH:
            classes.append(EarthOrbitClass.GSO)
        else:
            classes.append(EarthOrbitClass.HEO)
    elif apo < CISLUNAR_APO_MAX:
        classes.append(EarthOrbitClass.CIS)
    else:
        classes.append(EarthOrbitClass.VHEO)

    if peri < LEO_APO_MAX and GTO_APO_MIN <= apo <= GTO_APO_MAX:
        classes.append(EarthOrbitClass.GTO)

    if inclination_deg is None:
        return classes

    inc = inclination_deg
    if (
        abs(peri - GEO_ALT_KM) < GSO_BAND_HALF_WIDTH
        and abs(apo - GEO_ALT_KM) < GSO_BAND_HALF_WIDTH
        and inc < GEO_INC_MAX_DEG
    ):
        classes.append(EarthOrbitClass.GEO)
    if (
        peri < LEO_APO_MAX
        and MOLNIYA_APO_MIN <= apo <= MOLNIYA_APO_MAX
        and abs(inc - MOLNIYA_INC_DEG) <= MOLNIYA_INC_TOL_DEG
    ):
        classes.append(EarthOrbitClass.MOL)
    if (
        20000 <= peri <= HEO_APO_MAX
        and MOLNIYA_APO_MIN <= apo <= HEO_APO_MAX
        and abs(inc - MOLNIYA_INC_DEG) <= TUNDRA_INC_TOL_DEG
    ):
        classes.append(EarthOrbitClass.TUN)

    is_sso = SSO_INC_MIN_DEG <= inc <= SSO_INC_MAX_DEG and apo < LEO_APO_MAX
    if is_sso:
        classes.append(EarthOrbitClass.SSO)
    if POLAR_INC_MIN_DEG <= inc <= POLAR_INC_MAX_DEG:
        classes.append(EarthOrbitClass.POL)
    # Exclude SSO so the few non-SSO retrograde sats aren't drowned out.
    if inc > 90 and not is_sso:
        classes.append(EarthOrbitClass.RET)
    if inc < EQUATORIAL_INC_MAX_DEG:
        classes.append(EarthOrbitClass.EQU)

    return classes
