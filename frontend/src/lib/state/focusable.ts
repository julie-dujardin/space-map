/** What the drawer is currently focused on. Body/feature variants anchor on
 *  a host `PositionedBody`; the group variant has no body — it only filters
 *  what renders. */

import type { NomenclatureFeature } from '$lib/fetch/nomenclature/fetch';
import type { PositionedBody } from '$lib/types/objects';

export type Focusable =
	| { kind: 'body'; body: PositionedBody }
	| { kind: 'feature'; body: PositionedBody; feature: NomenclatureFeature }
	| { kind: 'group'; slug: string };

/** Stable identity for cache/dedupe keys (detail-fetch effects, log dedupe). */
export function focusableKey(f: Focusable): string {
	if (f.kind === 'feature') return `feature-${f.feature.featureId}`;
	if (f.kind === 'group') return `group-${f.slug}`;
	return f.body.data.id;
}

/** Header fallback while the detail bundle is loading. Nameless bodies show
 *  the bare catalog number, not the prefixed Object.id. */
export function focusableFallbackName(f: Focusable): string {
	if (f.kind === 'feature') return f.feature.name;
	if (f.kind === 'group') return f.slug;
	return f.body.data.name ?? bodyIdNumber(f.body.data.id);
}

function bodyIdNumber(id: string): string {
	const dash = id.indexOf('-');
	return dash === -1 ? id : id.slice(dash + 1);
}
