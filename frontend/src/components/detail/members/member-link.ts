/**
 * Where a member row goes. Three lists carry the same three kinds of entry —
 * a group slug, a surface feature on a host body, or a body of its own — and
 * the paginated list works over its own flattened row type, so routing takes
 * the smallest shape that distinguishes them rather than the exported entry.
 */
import { memberEntryKey, type NotableMemberEntry } from '$lib/fetch/objects/object-data';
import { isModifiedClick } from '$lib/modified-click';
import type { AppState } from '$lib/state/app-state.svelte';
import type { FocusFeature, FocusObject } from '$lib/state/focusable';
import { focusClick, focusHref, groupClick, groupHref } from '$lib/state/focus-link';
import { applyFeature, serializeUrl } from '$lib/state/url';

/** All routing needs of a member row. */
export interface MemberTarget {
	/** Object id, or the host body of a feature row. */
	id?: string;
	/** Group slug; set → the row opens `/g/<slug>` instead of focusing. */
	group?: string;
	/** IAU feature id; set → the row opens that feature on `id`. */
	feature_id?: number;
}

/** What the lists need from context to open a row in-session. */
export interface MemberNav {
	appState: AppState | undefined;
	focusObject: FocusObject | undefined;
	focusFeature: FocusFeature | undefined;
	/** Fragment lists pass false: select the piece without flying to its mesh. */
	moveCamera?: boolean;
}

/** The row's label: the locale's override, else the exported English name.
 *  Keyed the way the export writes the map — group slug, then feature, then id,
 *  with the name backstopping an entry that has no page of its own. */
export function memberDisplayName(
	entry: NotableMemberEntry,
	localizedNames?: Record<string, string>
): string {
	return localizedNames?.[memberEntryKey(entry)] ?? entry.name;
}

export function memberHref(
	appState: AppState | undefined,
	entry: MemberTarget,
	name: string
): string | undefined {
	if (entry.group) return groupHref(appState, entry.group, name);
	if (!entry.id) return undefined;
	if (entry.feature_id != null && appState) {
		return serializeUrl(
			applyFeature(appState.view, {
				bodyId: entry.id,
				featureId: entry.feature_id,
				featureName: name
			})
		);
	}
	return focusHref(appState, entry.id, name);
}

/** Plain left-click opens the row in-session; anything else is the browser's,
 *  and so is a click with nothing in context to open it with. */
export function memberClick(
	nav: MemberNav,
	entry: MemberTarget,
	name: string
): (e: MouseEvent) => void {
	if (entry.group) return groupClick(nav.appState, entry.group, name);
	const id = entry.id;
	if (!id) return () => {};
	const featureId = entry.feature_id;
	// A feature is streamed in and framed on its host body.
	if (featureId != null) {
		return (e) => {
			if (isModifiedClick(e) || !nav.focusFeature) return;
			e.preventDefault();
			nav.focusFeature(id, featureId, name);
		};
	}
	return focusClick(nav.focusObject, id, name, { moveCamera: nav.moveCamera });
}
