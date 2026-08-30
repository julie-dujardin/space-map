/**
 * Shared link behaviour for in-app navigation.
 *
 * Anything that moves the app to another view renders an `<a href>` (so
 * middle-click / ⌘-click open a real URL, and the status bar shows where it
 * goes) whose left-click is intercepted to navigate in-session instead. This
 * bundles the repeated pieces: the href for each kind of target, the
 * modified-click test, and the click handler that focuses + flies the camera.
 */
import type { RouteOption, TripState } from '$lib/travel/trip';
import type { AppState } from './app-state.svelte';
import type { FocusObject } from './focusable';
import type { DrawerTab } from './view';
import {
	applyFocus,
	applyGallery,
	applyGroup,
	applyImage,
	applyNav,
	applyQuad,
	applyTab,
	serializeUrl,
	urlTypeFromId,
	type NavEnd
} from './url';

/** The focus URL for a body; `undefined` until appState is available. Pass
 *  `tab` to land on a non-overview drawer tab (e.g. a planet's Moons tab), and
 *  `featureType` to arrive with the Surface list already narrowed to one type. */
export function focusHref(
	appState: AppState | undefined,
	id: string,
	name: string,
	tab?: Exclude<DrawerTab, 'overview'>,
	featureType?: string
): string | undefined {
	if (!appState) return undefined;
	return serializeUrl(
		applyFocus(appState.view, { type: urlTypeFromId(id), id, name, tab, featureType })
	);
}

/** The URL for another drawer tab on the object already in view. */
export function tabHref(appState: AppState | undefined, tab: DrawerTab): string | undefined {
	return appState ? serializeUrl(applyTab(appState.view, tab)) : undefined;
}

/** The URL for a `/g/<slug>` collection page. */
export function groupHref(
	appState: AppState | undefined,
	slug: string,
	name: string
): string | undefined {
	return appState ? serializeUrl(applyGroup(appState.view, slug, name)) : undefined;
}

/** The URL for the `/nav` trip planner; either end may be null. `terms` sets
 *  the trip fields the link is about — the orbit an end is met in, say. */
export function navHref(
	appState: AppState | undefined,
	from: string | NavEnd | null,
	to: string | NavEnd | null = null,
	terms?: Partial<TripState>
): string | undefined {
	return appState ? serializeUrl(applyNav(appState.view, from, to, terms)) : undefined;
}

/** The current view with the trip reading one named trajectory — where a
 *  route row in the planner leads. */
export function tripRouteHref(
	appState: AppState | undefined,
	trip: TripState,
	profile: RouteOption
): string | undefined {
	return appState ? serializeUrl({ ...appState.view, trip: { ...trip, profile } }) : undefined;
}

/** The URL for the image viewer opened on one image. Pass the gallery key when
 *  the link also has to switch shelves — the index counts into that gallery. */
export function imageHref(
	appState: AppState | undefined,
	index: number,
	gallery?: string
): string | undefined {
	if (!appState) return undefined;
	const base = gallery === undefined ? appState.view : applyGallery(appState.view, gallery);
	return serializeUrl(applyImage(base, index));
}

/** The URL for one image gallery under the Images tab, or its shelf index. */
export function galleryHref(
	appState: AppState | undefined,
	key: string | null
): string | undefined {
	return appState ? serializeUrl(applyGallery(appState.view, key)) : undefined;
}

/** The URL for the Surface tab narrowed to one quadrangle, or all of them. */
export function quadHref(appState: AppState | undefined, code: string | null): string | undefined {
	return appState ? serializeUrl(applyQuad(appState.view, code)) : undefined;
}

/** A non-primary / modified click (new tab, etc.) — leave it to the browser. */
export function isModifiedClick(e: MouseEvent): boolean {
	return e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey;
}

/** Click handler that focuses a body in-app (suppressing the href nav), unless
 *  the click is modified. Flies the camera to it by default. */
export function focusClick(
	focusObject: FocusObject | undefined,
	id: string,
	name: string,
	opts?: {
		moveCamera?: boolean;
		tab?: Exclude<DrawerTab, 'overview'>;
		featureType?: string;
	}
): (e: MouseEvent) => void {
	return (e) => {
		if (isModifiedClick(e) || !focusObject) return;
		e.preventDefault();
		focusObject(id, name, {
			moveCamera: opts?.moveCamera ?? true,
			tab: opts?.tab,
			featureType: opts?.featureType
		});
	};
}

/** Click handler that opens a `/g/<slug>` collection page in-app, unless the
 *  click is modified. */
export function groupClick(
	appState: AppState | undefined,
	slug: string,
	name: string
): (e: MouseEvent) => void {
	return (e) => {
		if (isModifiedClick(e) || !appState) return;
		e.preventDefault();
		appState.setGroup(slug, name);
	};
}
