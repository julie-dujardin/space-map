import { pushState as sveltePushState, replaceState as svelteReplaceState } from '$app/navigation';
import { DEFAULT_VIEW, UrlType, type MapViewState } from './view';
import { applyFeature, applyFocus, applyGroup, parseUrl, serializeUrl, urlTypeFromId } from './url';

const WRITE_DEBOUNCE_MS = 250;

/**
 * Single source of truth for URL-backed app state. Components call targeted
 * setters (setCamera / setDate / setFocus / setImage) instead of assembling a
 * whole MapViewState and calling replaceState themselves — the setter is what
 * knows how to merge its field(s) and sync the URL.
 *
 * setCamera/setDate use replaceState (frequent updates, no history entry).
 * setFocus uses pushState (new object = new history entry, browser back works).
 * setImage uses pushState only when opening/closing the viewer; within-viewer
 * navigation uses replaceState so 10-image galleries don't pollute history.
 */
export class AppState {
	view = $state<MapViewState>(DEFAULT_VIEW);

	private writeTimer: ReturnType<typeof setTimeout> | undefined;

	constructor(initial: MapViewState) {
		this.view = initial;
	}

	private replaceDebounced() {
		clearTimeout(this.writeTimer);
		this.writeTimer = setTimeout(() => this.replaceNow(), WRITE_DEBOUNCE_MS);
	}

	private replaceNow() {
		clearTimeout(this.writeTimer);
		const url = serializeUrl(this.view);
		// $state.snapshot unwraps the reactive proxy — history.state must be
		// structured-cloneable, and proxies aren't.
		svelteReplaceState(url, { view: $state.snapshot(this.view) });
	}

	private pushNow() {
		clearTimeout(this.writeTimer);
		const url = serializeUrl(this.view);
		sveltePushState(url, { view: $state.snapshot(this.view) });
	}

	setCamera(cam: { latitude: number; longitude: number; zoom: number }) {
		this.view = { ...this.view, ...cam };
		this.replaceDebounced();
	}

	setDate(date: Date, isNow: boolean) {
		this.view = { ...this.view, date, isNow };
		this.replaceDebounced();
	}

	setFocus(focus: { type: string; id: string; name: string }) {
		this.view = applyFocus(this.view, focus);
		this.pushNow();
	}

	/** Open the /g/<slug> group view. Parks `view.id` on the group's camera
	 *  anchor body so Scene's onFocusChange guard recognizes the landing body
	 *  as the intended target and doesn't stomp groupSlug via setFocus. */
	setGroup(slug: string, name: string) {
		this.view = applyGroup(this.view, slug, name);
		this.pushNow();
	}

	/** Tear down every focus layer (group + feature + body); URL parks on
	 *  anchorId so refresh still resolves somewhere. Type must be derived from
	 *  the id — anchorId may be a satellite/small-body/probe, not a NAIF body. */
	closeDetail(anchorId: string) {
		this.view = {
			...this.view,
			type: urlTypeFromId(anchorId),
			id: anchorId,
			groupSlug: null,
			featureId: null,
			name: ''
		};
		this.pushNow();
	}

	/** Open a nomenclature feature on its parent body. */
	setFeature(focus: { bodyId: string; featureId: number; featureName: string }) {
		this.view = applyFeature(this.view, focus);
		this.pushNow();
	}

	/** Return the URL to the parent-body view of the currently-selected feature. */
	clearFeature(bodyName: string) {
		this.view = {
			...this.view,
			type: UrlType.Body,
			name: bodyName,
			featureId: null
		};
		this.pushNow();
	}

	/**
	 * Update just the URL slug name for the currently focused object — used
	 * when the localized display name resolves *after* the click (drawer
	 * detail fetch) and we want the URL/title to catch up without growing
	 * history.
	 */
	replaceFocusName(name: string) {
		if (this.view.name === name) return;
		this.view = { ...this.view, name };
		this.replaceNow();
	}

	setImage(index: number | null) {
		const prev = this.view.imageIndex;
		this.view = { ...this.view, imageIndex: index };
		// Push on open/close so browser-back toggles the viewer; replace on
		// in-viewer navigation so each arrow-press doesn't grow history.
		const toggled = (prev === null) !== (index === null);
		if (toggled) this.pushNow();
		else this.replaceNow();
	}

	/** Called by the popstate handler with the view from history.state (or a re-parse). */
	syncFromPopState(view: MapViewState) {
		this.view = view;
	}
}

/** Convenience: parse the current URL once and hand back an AppState wrapping it. */
export function createAppState(): AppState {
	return new AppState(parseUrl() ?? DEFAULT_VIEW);
}
