/**
 * The model the system map draws: a primary framed off the left edge, its bodies on a
 * log distance axis at true relative diameters, and annular bands (belts, rings)
 * that link somewhere. The Solar System and every planetary system reduce to
 * this, which is what makes one map readable against another.
 */

/** What a target does when picked. With an `href` it is a real link, so a
 *  modified click opens it; with `onclick` alone it is a button. */
export interface MapLink {
	href?: string;
	onclick?: (e: MouseEvent) => void;
}

export interface MapSatellite {
	id: string;
	name: string;
	radiusKm: number;
	color: string;
	/** A target of its own, for a stack with no page to stand for it. */
	link?: MapLink;
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
	link?: MapLink;
	/** Where the stack as a whole leads. */
	satellitesLink?: MapLink;
	/** Body and stack are one target, led by `link`. */
	grouped?: boolean;
	/** A landmark to read the axis by rather than something to pick. */
	reference?: boolean;
}

export interface MapBand extends MapLink {
	key: string;
	/** Drawn across the band, so it has to survive a band a few px wide. */
	label: string;
	/** Tooltip and aria title; `label` when absent. */
	name?: string;
	innerKm: number;
	outerKm: number;
	/** Tooltip second line; the band's own distance span when absent. */
	sub?: string;
	tone: 'muted' | 'sky' | 'amber';
}

/** A population too large and too anonymous to draw as bodies: no name, no
 *  link, no tooltip, one dot per member at its own semi-major axis. */
export interface MapCloud {
	points: { aKm: number; tiltDeg: number }[];
	color: string;
}

/** The words the map writes itself, which its host owns the language of. */
export interface MapText {
	primary: string;
	retrograde: string;
	moons: (count: number) => string;
	distance: (km: number) => string;
	/** The axis label of a view measured from the Sun: the unit and the scale. */
	axisAu: string;
}

export interface SystemMapModel {
	primary: { id: string; name: string; radiusKm: number; color: string; link?: MapLink };
	bodies: MapBody[];
	bands: MapBand[];
	cloud?: MapCloud;
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
	text: MapText;
	/** Crop for the background variant; the whole map when absent. */
	backgroundView?: string;
	/** How the crop meets its box: anchored left and sliced by default; `fit`
	 *  shows it whole, centred. */
	backgroundFit?: 'slice' | 'fit';
}
