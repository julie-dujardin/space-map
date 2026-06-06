/**
 * What the drawer is currently focused on.
 *
 * A `Focusable` is always anchored to a host `PositionedBody` (camera framing,
 * share URL, minimize zoom all need it), but its variant decides what panels
 * the drawer renders and which fallback name shows in the header.
 *
 * Add a new variant when a future selection type ships (mission event, probe
 * landing site, IAU instrument footprint, …). The drawer narrows on `kind`
 * and the helpers below cover the "tell me X about whatever this is" lookups.
 */

import type { NomenclatureFeature } from '$lib/fetch/nomenclature/fetch';
import type { PositionedBody } from '$lib/types/objects';

export type Focusable =
	| { kind: 'body'; body: PositionedBody }
	| { kind: 'feature'; body: PositionedBody; feature: NomenclatureFeature };

/** Stable identity for cache/dedupe keys (detail-fetch effects, log dedupe). */
export function focusableKey(f: Focusable): string {
	return f.kind === 'feature' ? `feature-${f.feature.featureId}` : f.body.data.id;
}

/** Header fallback while the detail bundle is loading. Nameless bodies show
 *  the bare catalog number, not the prefixed Object.id. */
export function focusableFallbackName(f: Focusable): string {
	if (f.kind === 'feature') return f.feature.name;
	return f.body.data.name ?? bodyIdNumber(f.body.data.id);
}

function bodyIdNumber(id: string): string {
	const dash = id.indexOf('-');
	return dash === -1 ? id : id.slice(dash + 1);
}
