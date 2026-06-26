import { pushState as sveltePushState, replaceState as svelteReplaceState } from '$app/navigation';
import { DEFAULT_VIEW, UrlType, type DrawerTab, type MapViewState } from './view';
import { applyFeature, applyFocus, applyGroup, parseUrl, serializeUrl, urlTypeFromId } from './url';
import { serializeSearchSuffix, type SearchUrlState } from '$lib/search/url';

// The sim clock ticks ~2×/s, so its URL writes are throttled to at most one per
// minute (trailing). Everything else writes immediately — camera settles, focus
// changes and search edits are discrete and infrequent.
const DATE_THROTTLE_MS = 60_000;

/**
 * Single source of truth for URL-backed app state. Components call targeted
 * setters (setCamera / setDate / setFocus / setImage) instead of assembling a
 * whole MapViewState and calling replaceState themselves — the setter is what
 * knows how to merge its field(s) and sync the URL.
 *
 * setCamera/setSearch use replaceState immediately (in-place updates, no history
 * entry). setDate uses replaceState too but throttled, since it streams.
 * setFocus uses pushState (new object = new history entry, browser back works).
 * setImage uses pushState only when opening/closing the viewer; within-viewer
 * navigation uses replaceState so 10-image galleries don't pollute history.
 */
export class AppState {
	view = $state<MapViewState>(DEFAULT_VIEW);

	// Pending throttled clock write; any immediate write subsumes and clears it.
	private dateTimer: ReturnType<typeof setTimeout> | undefined;
	// Ephemeral search query/filters as a `&q=…&f=…` suffix. Rides along on
	// in-place (replaceState) writes so a camera nudge doesn't drop it; cleared on
	// navigation (pushState) so a new history entry starts without stale search.
	private searchSuffix = '';

	constructor(initial: MapViewState) {
		this.view = initial;
	}

	private replaceNow() {
		clearTimeout(this.dateTimer);
		this.dateTimer = undefined;
		const url = serializeUrl(this.view) + this.searchSuffix;
		// $state.snapshot unwraps the reactive proxy — history.state must be
		// structured-cloneable, and proxies aren't.
		svelteReplaceState(url, { view: $state.snapshot(this.view) });
	}

	private pushNow() {
		clearTimeout(this.dateTimer);
		this.dateTimer = undefined;
		// Navigation starts a fresh entry — search doesn't carry across it.
		this.searchSuffix = '';
		const url = serializeUrl(this.view);
		sveltePushState(url, { view: $state.snapshot(this.view) });
	}

	/** Mirror the live search panel state into the URL (replaceState, immediate).
	 *  Pass null to clear. No-op when the serialized form is unchanged, so the
	 *  driving effect can fire freely without spamming history.replaceState. */
	setSearch(search: SearchUrlState | null) {
		const suffix = serializeSearchSuffix(search);
		if (suffix === this.searchSuffix) return;
		this.searchSuffix = suffix;
		this.replaceNow();
	}

	setCamera(cam: { latitude: number; longitude: number; zoom: number }) {
		this.view = { ...this.view, ...cam };
		this.replaceNow();
	}

	setDate(date: Date, isNow: boolean) {
		this.view = { ...this.view, date, isNow };
		// Throttle: the clock streams updates, so coalesce into one trailing write
		// per window. An immediate write (camera/focus) meanwhile flushes the
		// current date and resets the window. Already scheduled → nothing to do.
		if (this.dateTimer) return;
		this.dateTimer = setTimeout(() => {
			this.dateTimer = undefined;
			this.replaceNow();
		}, DATE_THROTTLE_MS);
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
			name: '',
			tab: null,
			memberPage: null
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
			featureId: null,
			tab: null,
			memberPage: null
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

	/** Switch tabs (replaceState — no history spam). Resets member-page depth: a
	 *  manual switch lands at the top. Pass 'overview' to clear. */
	setTab(tab: DrawerTab) {
		const next = tab === 'overview' ? null : tab;
		if (next === this.view.tab && this.view.memberPage === null) return;
		this.view = { ...this.view, tab: next, memberPage: null };
		this.replaceNow();
	}

	/** Persist members-list scroll depth so a shared link restores it.
	 *  replaceState; no-op when unchanged. */
	setMemberPage(page: number) {
		const next = page > 1 ? page : null;
		if (next === this.view.memberPage) return;
		this.view = { ...this.view, memberPage: next };
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
