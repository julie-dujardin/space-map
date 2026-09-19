/** What the site row and its phone menu share, so both list the same pages on
 *  the same column. */
import * as m from '$lib/paraglide/messages.js';

/** The column every page in the site shares — the row and the page body sit
 *  on it, so a heading keeps its place from page to page. */
export const SITE_COLUMN = 'mx-auto w-full max-w-4xl';
/** The column's side gutter, apart from the column itself so a page can put
 *  something across the full width and gutter the rest of its content. */
export const SITE_GUTTER = 'px-6';

/** A page the site links to; `current` names the one being rendered. */
export type NavPage = 'map' | 'nav' | 'panoramas' | 'credits';

export const SITE_PAGES: { id: NavPage; href: string; label: () => string }[] = [
	{ id: 'map', href: '/', label: m.nav_map },
	{ id: 'nav', href: '/nav', label: m.nav_delta_v },
	{ id: 'panoramas', href: '/view', label: m.nav_panoramas },
	{ id: 'credits', href: '/credits', label: m.credits_page_title }
];
