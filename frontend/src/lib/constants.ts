/** Colors keyed by prefixed body ID */
export const BODY_COLORS: Record<string, string> = {
	'naif-10': '#ffdd44', // Sun
	'naif-199': '#b5b5b5', // Mercury
	'naif-299': '#e8cda0', // Venus
	'naif-399': '#4da6ff', // Earth
	'naif-301': '#888888', // Moon
	'naif-499': '#c1440e', // Mars
	'naif-401': '#aa9988', // Phobos
	'naif-402': '#aa9988', // Deimos
	'naif-599': '#d4a66a', // Jupiter
	'naif-699': '#e8d8a0', // Saturn
	'naif-799': '#87ceeb', // Uranus
	'naif-899': '#3f54ba', // Neptune
	'spkid-20134340': '#ab908a' // Pluto
};

export const DEFAULT_BODY_COLOR = '#cccccc';
/** Default radius for unknown bodies, in km */
export const DEFAULT_BODY_RADIUS_KM = 100;
