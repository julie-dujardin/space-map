/** URL path discriminator: `/<type>/<id>/<name>`. Maps 1:1 to ID prefix. */
export enum UrlType {
	Body = 'b', // naif-
	SmallBody = 's', // spkid-
	EarthSatellite = 'e' // norad_satcat-
}

/**
 * Shape of the URL-backed app state. One source of truth for what gets shared,
 * bookmarked, restored on reload, and pushed onto the browser history stack.
 */
export interface MapViewState {
	type: string;
	id: string; // prefixed, e.g. "naif-10", "spkid-20134340"
	name: string;
	date: Date;
	isNow: boolean;
	latitude: number;
	longitude: number;
	zoom: number;
	/** 0-based index into the focused object's images; null when the viewer is closed. */
	imageIndex: number | null;
}

export const DEFAULT_VIEW: MapViewState = {
	type: UrlType.Body,
	id: 'naif-10',
	name: 'Sun',
	date: new Date(),
	isNow: true,
	latitude: 45,
	longitude: 0,
	zoom: 42.43,
	imageIndex: null
};
