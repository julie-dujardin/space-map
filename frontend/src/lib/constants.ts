/** Colors keyed by NAIF ID */
export const BODY_COLORS: Record<number, string> = {
	10: '#ffdd44', // Sun
	199: '#b5b5b5', // Mercury
	299: '#e8cda0', // Venus
	399: '#4da6ff', // Earth
	301: '#888888', // Moon
	499: '#c1440e', // Mars
	401: '#aa9988', // Phobos
	402: '#aa9988', // Deimos
	599: '#d4a66a', // Jupiter
	699: '#e8d8a0', // Saturn
	799: '#87ceeb', // Uranus
	899: '#3f54ba', // Neptune
	999: '#deb887' // Pluto
};

/** Override radii keyed by NAIF ID (km) */
export const BODY_RADII_KM: Record<number, number> = {
	10: 696_340, // Sun
	199: 2_439.7, // Mercury
	299: 6_051.8, // Venus
	399: 6_371, // Earth
	301: 1_737.4, // Moon
	499: 3_389.5, // Mars
	401: 11.267, // Phobos
	402: 6.2, // Deimos
	599: 69_911, // Jupiter
	699: 58_232, // Saturn
	799: 25_362, // Uranus
	899: 24_622, // Neptune
	999: 1_188.3 // Pluto
};

export const DEFAULT_BODY_COLOR = '#cccccc';
/** Default radius for unknown bodies, in km */
export const DEFAULT_BODY_RADIUS_KM = 100;
