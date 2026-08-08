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
 * Fraction of the capture burn an atmosphere can absorb via aerocapture. Not a
 * measured number — a stand-in for "thick enough to brake against", deliberately
 * conservative against the ~0 propellant an ideal aerocapture would use.
 */
export const AEROCAPTURE_SAVING_FRACTION = 0.9;

/** Surface pressure (bar) above which aerocapture and parachute EDL are credited. */
export const AEROCAPTURE_MIN_PRESSURE_BAR = 0.005;

/**
 * Terminal-descent Δv left after a parachute-assisted landing, km/s. Mars-class
 * EDL still needs powered touchdown; thicker atmospheres need less.
 */
export const POWERED_TOUCHDOWN_KMS = 0.3;

/** Bulk density assumed when a small body has no mass, kg/m³ — rubble-pile typical. */
export const ASSUMED_DENSITY_KG_M3 = 2000;

/** Gravitational constant, km³/(kg·s²), for deriving GM from an assumed density. */
export const G_KM3_KG_S2 = 6.6743e-20;
