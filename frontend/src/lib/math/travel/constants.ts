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
 * Altitude of the periapsis an atmospheric pass is flown at when the body
 * carries no scale height to derive one from, km. Calibrated at Mars, where it
 * reproduces the published post-pass burn. Doubles as the floor for envelopes
 * thinner than the target pass pressure — Pluto's whole atmosphere is — where
 * the derived depth would otherwise sit at or under the ground.
 */
export const AERO_PASS_ALTITUDE_KM = 50;

/**
 * Pressure the pass periapsis aims for, Pa. With a body's own scale height this
 * places the entry interface where its density actually is — ~50 km at Mars but
 * hundreds of km at Titan and the giants. Calibrated so Mars (636 Pa, 11 km)
 * lands on the altitude the published post-pass burn was matched at.
 */
export const AERO_PASS_PRESSURE_PA = 6.7;

/**
 * Ceiling on the derived pass altitude, km. Every orbit here is quoted from the
 * one 200 km parking convention, and a pass has to fit under the orbit it
 * delivers — so at Titan and the giants this is the parking convention's floor
 * showing through, not the atmosphere's real top.
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
