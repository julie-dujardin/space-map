/**
 * `/compare` — anything the row can draw, side by side on one scale.
 * `?m=<id,…>` is the comparison itself, so a reader can link to the one they
 * assembled; without it the page opens on a preset.
 *
 * Client-rendered: everything it draws is fetched from `/data`, which collides
 * with the `[type]/[id]` route under SSR (same reason as the credits page).
 */

import { DEFAULT_PRESET, presetBySlug } from '$lib/compare/presets';
import type { PageLoad } from './$types';

export const ssr = false;

export interface ComparePageData {
	/** Object ids, in the order they were added. */
	selected: string[];
}

export const load: PageLoad = ({ url }): ComparePageData => {
	const raw = url.searchParams.get('m');
	// An empty `m` is an emptied comparison, not a missing one.
	const asked = raw === null ? (presetBySlug(DEFAULT_PRESET)?.ids ?? []) : raw.split(',');
	return { selected: [...new Set(asked.filter(Boolean))] };
};
