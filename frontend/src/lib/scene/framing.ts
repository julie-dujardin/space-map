import { EARTH_ID } from '$lib/constants';

/** Default vantage angle for a body framed with no explicit camera (search, click, group). */
export const DEFAULT_FRAMING_LAT = 45;
export const DEFAULT_FRAMING_LON = 0;
/** Wide heliocentric framing for Sun-anchored group pages. */
export const SUN_VIEW_ZOOM = 42.43;
/** Landing-view tilt above the ecliptic, looking sunward from Earth. */
export const DEFAULT_VIEW_ELEVATION_DEG = 30;
/** Where a map opens when nothing is asked of it: Earth, ~1.5 AU out. */
export const DEFAULT_FOCUS_ID = EARTH_ID;
export const DEFAULT_ZOOM = 15;
