/** Physical constants for trajectory math. Everything in this module works in
 * km, km/s and km³/s², with time in Julian days — the units the export's
 * gravitational parameters already use. */

/** IAU 2015 heliocentric gravitational constant, km³/s². */
export const GM_SUN_KM3_S2 = 1.32712440018e11;

export const SEC_PER_DAY = 86400;

/**
 * Parking-orbit altitude used for every launch/injection estimate, km. Real
 * missions vary this; a single value keeps bodies comparable, which is the
 * point of the ladder.
 */
export const PARKING_ALTITUDE_KM = 200;

/** Beyond a third of the Hill radius the primary stops being what you orbit. */
export const HILL_STABLE_FRACTION = 1 / 3;

/** Share of the room a body has that a low orbit may take up. A quarter of the
 *  way to the ceiling is still recognisably low; the whole way is the ceiling. */
export const LOW_ORBIT_CEILING_SHARE = 1 / 4;

/**
 * Apoapsis of the "captured" elliptical orbit, expressed as a multiple of the
 * target's radius. Capture into a loose ellipse is far cheaper than
 * circularizing, and is what real orbiters actually do on arrival.
 */
export const CAPTURE_APOAPSIS_RADII = 20;

/**
 * Gravity + steering losses on ascent as a fraction of surface circular
 * velocity. Calibrated against the three ascents with published numbers: Earth
 * to LEO ~9.4, the Apollo LM to lunar orbit ~1.87, Mars to low orbit ~4.1.
 */
export const ASCENT_GRAVITY_LOSS_FRACTION = 0.18;

/**
 * Extra ascent loss from drag, scaled by surface pressure in bar and capped —
 * Venus is thick enough that the linear term alone would run away.
 */
export const ASCENT_DRAG_LOSS_KMS_PER_BAR = 0.15;
export const ASCENT_DRAG_LOSS_CAP_KMS = 1.2;

/**
 * Pass periapsis altitude when a body has no scale height to derive one from, km.
 * Calibrated at Mars to reproduce the published post-pass burn; also floors
 * envelopes thinner than the target pressure (e.g. Pluto's whole atmosphere),
 * where the derived depth would otherwise sit at or below ground.
 */
export const AERO_PASS_ALTITUDE_KM = 50;

/**
 * Target pressure for the pass periapsis, Pa. With a body's own scale height this
 * places the entry interface at its real density altitude — ~50 km at Mars,
 * hundreds at Titan and the giants. Calibrated so Mars (636 Pa, 11 km) matches
 * the published post-pass burn altitude.
 */
export const AERO_PASS_PRESSURE_PA = 6.7;

/**
 * Ceiling on the derived pass altitude, km. Every orbit is quoted from the
 * 200 km parking convention and a pass must fit under it — so at Titan and the
 * giants this is the parking floor showing through, not the atmosphere's real top.
 */
export const AERO_PASS_ALTITUDE_MAX_KM = 150;

/**
 * Thinnest envelope a braking pass is credited against — pressure at the datum,
 * Pa. An order of magnitude under Pluto's ~1 Pa, the thinnest atmosphere with
 * published aerocapture studies, and three above the thickest exosphere: the
 * catalogue has nothing in between for the exact value to decide.
 */
export const AERO_MIN_PRESSURE_PA = 0.1;

/**
 * Δv for corridor control and apoapsis trim after an aerocapture pass, km/s, on
 * top of the derived periapsis raise. Aerocapture studies budget 33 m/s (Mars,
 * elliptical) to ~200 m/s (Mars, 500 km circular, 3σ) for post-pass clean-up;
 * this is the middle of that range.
 */
export const AEROCAPTURE_TRIM_KMS = 0.05;

/**
 * Δv drag removes per day of an aerobraking campaign, km/s. Fitted to the four
 * flown Mars campaigns (3.6–14 m/s/day: MGS 1220/290d, Odyssey 1080/77d,
 * MRO 1200/148d, TGO 1000/276d) — the spread is ballistic coefficient and how
 * hard it was flown, neither known here, so a reported duration is right to the
 * month, not the day. Nothing calibrates it away from Mars.
 */
export const AEROBRAKING_RATE_KMS_PER_DAY = 0.008;

/**
 * Terminal-descent Δv left after a parachute-assisted landing, km/s. Mars-class
 * EDL still needs powered touchdown; thicker atmospheres need less.
 */
export const POWERED_TOUCHDOWN_KMS = 0.3;

/**
 * Closest a swing-by may pass, km above the mean radius. Real missions pick this
 * per body (Galileo grazed Venus at 16,000 km, Io at 900) — one figure here is a
 * floor, not a plan, chosen clear of every atmosphere the model would otherwise
 * fly through.
 */
export const FLYBY_MIN_ALTITUDE_KM = 300;

/** Bulk density assumed when a small body has no mass, kg/m³ — rubble-pile typical. */
export const ASSUMED_DENSITY_KG_M3 = 2000;

/** Gravitational constant, km³/(kg·s²), for deriving GM from an assumed density. */
export const G_KM3_KG_S2 = 6.6743e-20;

/** Standard gravity, m/s² — the odd metric unit out here, because its uses are
 *  metric: Isp → exhaust speed, and readings quoted in gees. */
export const G0_M_S2 = 9.80665;
