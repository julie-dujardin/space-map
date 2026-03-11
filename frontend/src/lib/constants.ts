/** 1 AU = this many Three.js units */
export const AU_SCALE = 10;

/** 1 AU in km */
const AU_KM = 149_597_870.7;

/** Convert km to scene units */
export function kmToScene(km: number): number {
	return (km / AU_KM) * AU_SCALE;
}

export const PLANET_COLORS: Record<string, string> = {
	Sun: '#ffdd44',
	Mercury: '#b5b5b5',
	Venus: '#e8cda0',
	Earth: '#4da6ff',
	Moon: '#888888',
	Mars: '#c1440e',
	Phobos: '#aa9988',
	Deimos: '#aa9988',
	Jupiter: '#d4a66a',
	Saturn: '#e8d8a0',
	Uranus: '#87ceeb',
	Neptune: '#3f54ba',
	Pluto: '#deb887'
};

/** Real mean volumetric radii in km */
export const BODY_RADII_KM: Record<string, number> = {
	Sun: 696_340,
	Mercury: 2_439.7,
	Venus: 6_051.8,
	Earth: 6_371,
	Moon: 1_737.4,
	Mars: 3_389.5,
	Phobos: 11.267,
	Deimos: 6.2,
	Jupiter: 69_911,
	Saturn: 58_232,
	Uranus: 25_362,
	Neptune: 24_622,
	Pluto: 1_188.3
};

export const DEFAULT_BODY_COLOR = '#cccccc';
/** Default radius for unknown bodies, in km */
export const DEFAULT_BODY_RADIUS_KM = 100;
