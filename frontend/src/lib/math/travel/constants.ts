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
 * Altitude of the periapsis an atmospheric pass is flown at, km.
 *
 * One value for every body, which is the model's weakest atmospheric
 * assumption: a real entry interface sits where the density does, so it is
 * ~50 km at Mars but several hundred at Titan and the giants. Calibrated at
 * Mars, where it reproduces the published post-pass burn; at a body with a
 * deeper atmosphere it puts periapsis too low and understates that burn.
 */
export const AERO_PASS_ALTITUDE_KM = 50;

/**
 * Δv allowed for corridor control and apoapsis trim after an aerocapture pass,
 * km/s, on top of the periapsis raise the model derives.
 *
 * Aerocapture studies budget 33 m/s (Mars, elliptical) to ~200 m/s (Mars, 500 km
 * circular, 3σ) for the whole post-pass clean-up, most of the spread being
 * correction of where the pass actually left the craft rather than the raise
 * itself. This is the middle of that.
 */
export const AEROCAPTURE_TRIM_KMS = 0.05;

/**
 * Δv drag removes per day of an aerobraking campaign, km/s.
 *
 * Fitted to the four flown Mars campaigns, which span 3.6–14 m/s per day:
 * MGS 1220 m/s over 290 active days, Odyssey 1080 over 77, MRO 1200 over 148,
 * TGO 1000 over 276. The spread is the spacecraft's ballistic coefficient and
 * how hard the campaign was flown — neither of which this model knows — so a
 * duration it reports is the right number of months, not the right number of
 * days. Nothing calibrates it away from Mars.
 */
export const AEROBRAKING_RATE_KMS_PER_DAY = 0.008;

/** Surface pressure (bar) above which aero assist and parachute EDL are credited. */
export const AEROCAPTURE_MIN_PRESSURE_BAR = 0.005;

/**
 * Terminal-descent Δv left after a parachute-assisted landing, km/s. Mars-class
 * EDL still needs powered touchdown; thicker atmospheres need less.
 */
export const POWERED_TOUCHDOWN_KMS = 0.3;

/**
 * Closest a swing-by may pass, km above the mean radius. Real missions pick this
 * per body — Galileo grazed Venus at 16,000 km and Io at 900 — so one figure is
 * a floor rather than a plan, chosen well clear of every atmosphere the model
 * would otherwise fly through.
 */
export const FLYBY_MIN_ALTITUDE_KM = 300;

/** Bulk density assumed when a small body has no mass, kg/m³ — rubble-pile typical. */
export const ASSUMED_DENSITY_KG_M3 = 2000;

/** Gravitational constant, km³/(kg·s²), for deriving GM from an assumed density. */
export const G_KM3_KG_S2 = 6.6743e-20;
