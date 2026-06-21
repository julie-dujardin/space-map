/** URL path discriminator. Body types map 1:1 to ID prefix; Feature is a
 *  sub-selection on top of a body and uses a nested route shape
 *  (/<type>/<bodyId>/f/<featureId>/<name>). Group is a top-level aggregation
 *  view (/g/<slug>/<name>) that filters which bodies render but keeps a
 *  default anchor body for camera framing. */
export enum UrlType {
	Body = 'b', // naif-
	SmallBody = 's', // spkid-
	EarthSatellite = 'e', // norad_satcat-
	Probe = 'p', // probe-
	Feature = 'f', // IAU nomenclature feature on a body
	Group = 'g', // /g/<slug>/<name> — constellation / operator / asteroid class / ...
	Extra = 'u' // /u/<id>/<name> — hand-authored extra object addressed by its id
}

/**
 * Shape of the URL-backed app state. One source of truth for what gets shared,
 * bookmarked, restored on reload, and pushed onto the browser history stack.
 */
export interface MapViewState {
	type: string;
	id: string; // prefixed body id, e.g. "naif-10", "spkid-20134340" — the renderer always focuses a body, even in feature/group mode
	name: string; // active object's display name (body in body mode, feature in feature mode, group in group mode)
	date: Date;
	isNow: boolean;
	latitude: number;
	longitude: number;
	zoom: number;
	/** Camera framing (lat/lon/zoom) was explicit — an `?at=` block or group
	 *  anchor. Absent for a bare deep link, which frames by target size/model. */
	framed?: boolean;
	/** 0-based index into the focused object's images; null when the viewer is closed. */
	imageIndex: number | null;
	/** IAU feature id when a surface feature is the active selection; null otherwise. */
	featureId: number | null;
	/** Slug when /g/<slug> is active; filters the group's applies_to category. */
	groupSlug: string | null;
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
	imageIndex: null,
	featureId: null,
	groupSlug: null
};
