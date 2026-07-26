/**
 * Shared "focus this body" link behaviour for the in-drawer lineups and charts.
 *
 * Each spot renders an `<a href>` (so middle-click / ⌘-click open a real URL)
 * whose left-click is intercepted to focus the body in-app instead. This bundles
 * the three repeated pieces: the href, the modified-click test, and the click
 * handler that focuses + flies the camera.
 */
import type { AppState } from './app-state.svelte';
import type { FocusObject } from './focusable';
import type { DrawerTab } from './view';
import { applyFocus, serializeUrl, urlTypeFromId } from './url';

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
