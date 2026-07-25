/** What the drawer is currently focused on. Body/feature variants anchor on
 *  a host `PositionedBody`; the group variant has no body — it only filters
 *  what renders. */

import { classNameFromSlug, FLAG_SLUG_PREFIX, orbitClassLabel } from '$lib/charts/orbit-zones';
import { categoryLabel, FEATURE_TYPE_SLUG_PREFIX } from '$lib/fetch/groups/registry';
import type { NomenclatureFeature } from '$lib/fetch/nomenclature/fetch';
import type { PositionedBody } from '$lib/types/objects';
import type { DrawerTab } from './view';
import * as m from '$lib/paraglide/messages.js';

export type Focusable =
	| { kind: 'body'; body: PositionedBody }
	| { kind: 'feature'; body: PositionedBody; feature: NomenclatureFeature }
	| { kind: 'group'; slug: string };

/** Full in-session object navigation: coverage snap + URL focus + camera
 *  fly-to. Provided by MapPage via setContext('focusObject') — a bare
 *  `appState.setFocus` only rewrites the URL and never reaches the renderer,
 *  so the drawer (driven by the renderer's focus) would not follow.
 *
 *  `moveCamera: false` selects the body (drawer follows) without the zoom
 *  fly-in — used for comet fragments/parents, whose tiny meshes aren't worth
 *  flying to. */
export type FocusObject = (
	id: string,
	name: string,
	opts?: { moveCamera?: boolean; tab?: Exclude<DrawerTab, 'overview'> }
) => void;

/** Open a surface feature on its host body, streaming the body in if the
 *  camera isn't already in that system (a feature-type page lists features
 *  across every body). Provided by MapPage on the `focusFeature` context. */
export type FocusFeature = (bodyId: string, featureId: number, name: string) => void;

/** Stable identity for cache/dedupe keys (detail-fetch effects, log dedupe). */
export function focusableKey(f: Focusable): string {
	if (f.kind === 'feature') return `feature-${f.feature.featureId}`;
	if (f.kind === 'group') return `group-${f.slug}`;
	return f.body.data.id;
}

/** Header fallback while the detail bundle is loading. Nameless bodies show
 *  the bare catalog number, not the prefixed Object.id. Orbit-class and flag
 *  group labels are bundled, so those resolve without the detail fetch. */
export function focusableFallbackName(f: Focusable): string {
	if (f.kind === 'feature') return f.feature.name;
	if (f.kind === 'group') return groupSlugLabel(f.slug);
	return f.body.data.name ?? bodyIdNumber(f.body.data.id);
}

/** Bundled label for a group slug: orbit classes and NEO/PHA flags resolve
 *  locally; other group types fall back to the slug itself. */
export function groupSlugLabel(slug: string): string {
	const className = classNameFromSlug(slug);
	if (className != null) return orbitClassLabel(className);
	if (slug === `${FLAG_SLUG_PREFIX}neo`) return m.neo();
	if (slug === `${FLAG_SLUG_PREFIX}pha`) return m.pha();
	// Feature types carry their English name in the slug — a readable stand-in
	// until the localized bundle lands.
	if (slug.startsWith(FEATURE_TYPE_SLUG_PREFIX)) {
		const name = slug.slice(FEATURE_TYPE_SLUG_PREFIX.length).replace(/-/g, ' ');
		return name.charAt(0).toUpperCase() + name.slice(1);
	}
	return categoryLabel(slug);
}

function bodyIdNumber(id: string): string {
	const dash = id.indexOf('-');
	return dash === -1 ? id : id.slice(dash + 1);
}
