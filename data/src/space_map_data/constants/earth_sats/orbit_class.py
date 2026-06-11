"""Earth-orbit zone classification.

Shape classes (VLEO/LEO/MEO/HEO/GSO/GEO/IGSO/GRA/MOL/TUN/GTO/CIS/VHEO)
are mutually exclusive — the most specific match wins. Low orbits add at
most one inclination band (SSO/Polar/Retrograde/Equatorial), GCAT-style.
Bands follow GCAT (planet4589.org/space/gcat/web/intro/orbits.html);
period/eccentricity-based GCAT cuts are approximated on the perigee/
apogee plane.
"""

from enum import StrEnum

R_EARTH_KM = 6378.137
GEO_ALT_KM = 35786.0

VLEO_APO_MAX = 600  # GCAT LLEO upper bound
LEO_APO_MAX = 2000
MEO_APO_MAX = 35000
HEO_APO_MAX = 50000
CISLUNAR_APO_MAX = 500000
GSO_BAND_HALF_WIDTH = 2000
# IADC/FCC disposal: re-orbit at least ~200-300 km above GEO.
GRAVEYARD_PERI_MIN = GEO_ALT_KM + 200
GTO_APO_MIN, GTO_APO_MAX = 30000, 40000
MOLNIYA_APO_MIN, MOLNIYA_APO_MAX = 35000, 45000
GEO_INC_MAX_DEG = 3.0
MOLNIYA_INC_MIN_DEG, MOLNIYA_INC_MAX_DEG = 62.0, 64.0
CRITICAL_INC_DEG, TUNDRA_INC_TOL_DEG = 63.4, 5.0
TUNDRA_PERI_MIN = 20000
SSO_INC_MIN_DEG, SSO_INC_MAX_DEG = 95.0, 104.0
POLAR_INC_MIN_DEG, POLAR_INC_MAX_DEG = 85.0, 95.0
EQUATORIAL_INC_MAX_DEG = 25.0


class EarthOrbitClass(StrEnum):
    """Shape classes + inclination bands for Earth-orbiting payloads."""

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
        EarthOrbitClass.VLEO,
        EarthOrbitClass.LEO,
        EarthOrbitClass.MEO,
        EarthOrbitClass.HEO,
        EarthOrbitClass.GSO,
        EarthOrbitClass.GEO,
        EarthOrbitClass.IGSO,
        EarthOrbitClass.GRA,
        EarthOrbitClass.MOL,
        EarthOrbitClass.TUN,
        EarthOrbitClass.GTO,
        EarthOrbitClass.CIS,
        EarthOrbitClass.VHEO,
    }
)


def classify_earth_orbit(
    perigee_km: float | None,
    apogee_km: float | None,
    inclination_deg: float | None,
) -> list[EarthOrbitClass]:
    """Return ``[shape_class]`` or ``[shape_class, inclination_band]``.

    Caller must pre-filter for active Earth-centred orbits. Returns empty
    when perigee or apogee is missing.
    """
    if perigee_km is None or apogee_km is None:
        return []

    classes = [_shape_class(perigee_km, apogee_km, inclination_deg)]
    if apogee_km < LEO_APO_MAX and inclination_deg is not None:
        band = _inclination_band(inclination_deg)
        if band is not None:
            classes.append(band)
    return classes


def _shape_class(peri: float, apo: float, inc: float | None) -> EarthOrbitClass:
    if apo < VLEO_APO_MAX:
        return EarthOrbitClass.VLEO
    if apo < LEO_APO_MAX:
        return EarthOrbitClass.LEO
    in_gso_band = (
        abs(peri - GEO_ALT_KM) < GSO_BAND_HALF_WIDTH
        and abs(apo - GEO_ALT_KM) < GSO_BAND_HALF_WIDTH
    )
    if in_gso_band:
        # Graveyard sats sit in the GSO band but are no longer
        # station-kept, so geometry trumps inclination. IGSO has no
        # inclination cap (BeiDou/QZSS fly at 43-55 deg).
        if peri >= GRAVEYARD_PERI_MIN:
            return EarthOrbitClass.GRA
        if inc is None:
            return EarthOrbitClass.GSO
        if inc < GEO_INC_MAX_DEG:
            return EarthOrbitClass.GEO
        return EarthOrbitClass.IGSO
    if apo < MEO_APO_MAX and peri >= LEO_APO_MAX:
        return EarthOrbitClass.MEO
    if apo < HEO_APO_MAX:
        # Eccentric near-sync (perigee in the band, apogee out).
        if abs(peri - GEO_ALT_KM) < GSO_BAND_HALF_WIDTH:
            return EarthOrbitClass.GSO
        if (
            peri < LEO_APO_MAX
            and MOLNIYA_APO_MIN <= apo <= MOLNIYA_APO_MAX
            and inc is not None
            and MOLNIYA_INC_MIN_DEG <= inc <= MOLNIYA_INC_MAX_DEG
        ):
            return EarthOrbitClass.MOL
        if (
            TUNDRA_PERI_MIN <= peri < GEO_ALT_KM - GSO_BAND_HALF_WIDTH
            and MOLNIYA_APO_MIN <= apo <= HEO_APO_MAX
            and inc is not None
            and abs(inc - CRITICAL_INC_DEG) <= TUNDRA_INC_TOL_DEG
        ):
            return EarthOrbitClass.TUN
        if peri < LEO_APO_MAX and GTO_APO_MIN <= apo <= GTO_APO_MAX:
            return EarthOrbitClass.GTO
        return EarthOrbitClass.HEO
    if apo < CISLUNAR_APO_MAX:
        return EarthOrbitClass.CIS
    return EarthOrbitClass.VHEO


def _inclination_band(inc: float) -> EarthOrbitClass | None:
    if SSO_INC_MIN_DEG <= inc <= SSO_INC_MAX_DEG:
        return EarthOrbitClass.SSO
    if POLAR_INC_MIN_DEG <= inc <= POLAR_INC_MAX_DEG:
        return EarthOrbitClass.POL
    # GCAT: retrograde band starts where sun-sync ends.
    if inc > SSO_INC_MAX_DEG:
        return EarthOrbitClass.RET
    if inc < EQUATORIAL_INC_MAX_DEG:
        return EarthOrbitClass.EQU
    return None
