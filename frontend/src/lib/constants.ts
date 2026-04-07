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
	'naif-501': '#8a762e', // Io
	'naif-502': '#7c7f6c', // Europa
	'naif-503': '#7e6c5e', // Ganymede
	'naif-504': '#6c6453', // Callisto
	'naif-699': '#e8d8a0', // Saturn
	'naif-601': '#aba890', // Mimas
	'naif-602': '#71a29f', // Enceladus
	'naif-603': '#6c6645', // Tethys
	'naif-604': '#494a2a', // Dione
	'naif-605': '#5c5a3c', // Rhea
	'naif-606': '#835422', // Titan
	'naif-608': '#776b60', // Iapetus
	'naif-799': '#87ceeb', // Uranus
	'naif-701': '#b0b0b0', // Ariel
	'naif-702': '#a8a8a8', // Umbriel
	'naif-703': '#62534c', // Titania
	'naif-704': '#626a62', // Oberon
	'naif-705': '#625252', // Miranda
	'naif-899': '#3f54ba', // Neptune
	'naif-801': '#7c757c', // Triton
	'spkid-20134340': '#6c4d41' // Pluto
};

export const DEFAULT_BODY_COLOR = '#cccccc';
/** Default radius for unknown bodies, in km */
export const DEFAULT_BODY_RADIUS_KM = 100;
