/**
 * The model SystemMap draws: a primary framed off the left edge, its bodies on a
 * log distance axis at true relative diameters, and annular bands (belts, rings)
 * that link somewhere. The Solar System and every planetary system reduce to
 * this, which is what makes one map readable against another.
 */

export interface MapSatellite {
	id: string;
	name: string;
	radiusKm: number;
	color: string;
}

export interface MapBody {
	id: string;
	name: string;
	/** Orbit semi-major axis about the primary. */
	aKm: number;
	/** Orbit tilt to the primary's reference plane [deg]; > 90° is retrograde. */
	tiltDeg: number;
	radiusKm: number;
	color: string;
	/** Ring span as multiples of the body's own radius. */
	rings?: { inner: number; outer: number };
	/** Notable moons, drawn as a stack above the body. */
	satellites?: MapSatellite[];
	/** Every moon the body has, for the stack's tooltip. */
	satelliteCount?: number;
	/** The stack links to the body's moons tab; else to its largest moon. */
	satellitesTab?: boolean;
}

export interface MapBand {
	key: string;
	label: string;
	innerKm: number;
	outerKm: number;
	tone: 'muted' | 'sky' | 'amber';
	href?: string;
	onclick?: (e: MouseEvent) => void;
}

export interface SystemMapModel {
	primary: { id: string; name: string; radiusKm: number; color: string };
	bodies: MapBody[];
	bands: MapBand[];
	/** The axis unit in km (AU, or the primary's radius). */
	unitKm: number;
	/** Log axis domain and tick values, in `unitKm`. */
	domain: [number, number];
	ticks: number[];
	axisLabel: string;
	/** Drawn radius per km, shared by every body including the primary. */
	pxPerKm: number;
	/** Inclination → vertical offset. */
	pxPerDeg: number;
	/** Crop for the background variant; the whole map when absent. */
	backgroundView?: string;
	/** How the crop meets its box: anchored left and sliced by default; `fit`
	 *  shows it whole, centred. */
	backgroundFit?: 'slice' | 'fit';
}
