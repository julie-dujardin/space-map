export interface OrbitalElements {
	a: number; // semi-major axis (AU)
	e: number; // eccentricity
	i: number; // inclination (degrees)
	om: number; // longitude of ascending node (degrees)
	w: number; // argument of perihelion (degrees)
	ma: number; // mean anomaly (degrees)
}

export interface HorizonsBody extends OrbitalElements {
	name: string;
	naifId: number;
	parentNaifId: number | null; // null = heliocentric, number = parent-relative (moon)
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
}
