import { type ObjectType } from './format';

export interface OrbitalElements {
	a: number; // semi-major axis (AU)
	e: number; // eccentricity
	i: number; // inclination (degrees)
	om: number; // longitude of ascending node (degrees)
	w: number; // argument of perihelion (degrees)
	ma: number; // mean anomaly at epoch (degrees)
	n: number; // mean motion (degrees/day)
	epoch: number; // epoch (Julian Date)
}

/** Unified body data from the binary export. */
export interface BodyData extends OrbitalElements {
	id: number; // type-specific ID (NAIF ID for bodies/probes, SPK ID for small bodies, NORAD cat ID for satellites)
	name: string | null;
	objectType: ObjectType;
	parentId: number; // NAIF ID of parent (0 = SSB, 399 = Earth, etc.)
	radiusKm: number;
}

export interface PositionedBody {
	data: BodyData;
	position: [number, number, number];
	/** Orbital elements to use for drawing the orbit (may differ from data's own elements, e.g. barycenter elements for planets) */
	orbitElements?: OrbitalElements;
	/** World-space center of the orbit (parent position). Defaults to origin. */
	orbitCenter?: [number, number, number];
}
