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
	20134340: '#deb887' // Pluto
};

export const DEFAULT_BODY_COLOR = '#cccccc';
/** Default radius for unknown bodies, in km */
export const DEFAULT_BODY_RADIUS_KM = 100;
