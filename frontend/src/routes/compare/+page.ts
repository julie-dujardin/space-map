/**
 * `/compare` — anything the row can draw, side by side on one scale.
 * `?m=<id,…>` is the comparison itself, so a reader can link to the one they
 * assembled; without it the page opens on a preset. `?o=<id>` maximizes one of
 * them: the row keeps only that object, and the panel beside it is the object's
 * own page. `?on=<id>` opens the row on the page that holds one object, for a
 * link arriving from that object — a set it joins from below starts pages away
 * from it otherwise.
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
	/** The one object the page is opened on, or null for the whole row. */
	opened: string | null;
	/** The object whose page the row starts on, once its size is known. */
	startOn: string | null;
}

export const load: PageLoad = ({ url }): ComparePageData => {
	const raw = url.searchParams.get('m');
	// An empty `m` is an emptied comparison, not a missing one.
	const asked = raw === null ? (presetBySlug(DEFAULT_PRESET)?.ids ?? []) : raw.split(',');
	const selected = [...new Set(asked.filter(Boolean))];
	const opened = url.searchParams.get('o');
	const startOn = url.searchParams.get('on');
	// Only the comparison's own members have a page here.
	return {
		selected,
		opened: opened && selected.includes(opened) ? opened : null,
		startOn: startOn && selected.includes(startOn) ? startOn : null
	};
};
