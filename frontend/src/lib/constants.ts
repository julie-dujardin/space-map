/** 1 AU = this many Three.js units */
export const AU_SCALE = 10;

export const PLANET_COLORS: Record<string, string> = {
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

export const PLANET_RADII: Record<string, number> = {
	Mercury: 0.12,
	Venus: 0.22,
	Earth: 0.22,
	Moon: 0.06,
	Mars: 0.18,
	Phobos: 0.04,
	Deimos: 0.04,
	Jupiter: 0.4,
	Saturn: 0.35,
	Uranus: 0.3,
	Neptune: 0.3,
	Pluto: 0.1
};

export const DEFAULT_BODY_COLOR = '#cccccc';
export const DEFAULT_BODY_RADIUS = 0.1;
