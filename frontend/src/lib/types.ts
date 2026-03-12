export interface OrbitalElements {
	a: number; // semi-major axis (AU)
	e: number; // eccentricity
	i: number; // inclination (degrees)
	om: number; // longitude of ascending node (degrees)
	w: number; // argument of perihelion (degrees)
	ma: number; // mean anomaly (degrees)
}

export enum BodyType {
	BARYCENTER = 'barycenter',
	STAR = 'star',
	PLANET = 'planet',
	DWARF_PLANET = 'dwarf_planet',
	MOON = 'moon',
	ASTEROID = 'asteroid',
	COMET = 'comet',
	SPACECRAFT = 'spacecraft'
}

export interface HorizonsBody extends OrbitalElements {
	name: string | null;
	designation: string | null;
	naifId: number;
	type: BodyType;
	parentNaifId: number; // NAIF ID of parent (0 = SSB, 1-9 = planet barycenter)
}

export interface SmallBody extends OrbitalElements {
	fullName: string;
	name: string | null;
}

export interface Satellite {
	objectName: string;
	meanMotion: number; // rev/day
	eccentricity: number;
	inclination: number; // degrees
	raan: number; // degrees
	argOfPericenter: number; // degrees
	meanAnomaly: number; // degrees
}

export interface PositionedBody<T> {
	data: T;
	position: [number, number, number];
	/** Orbital elements to use for drawing the orbit (may differ from data's own elements, e.g. barycenter elements for planets) */
	orbitElements?: OrbitalElements;
	/** World-space center of the orbit (parent position). Defaults to origin. */
	orbitCenter?: [number, number, number];
}
