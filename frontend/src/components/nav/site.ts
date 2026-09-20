/** What the site row and its phone menu share, so both list the same pages on
 *  the same column. */
import * as m from '$lib/paraglide/messages.js';
import { GITHUB_REPO_URL } from '$lib/constants';

/** The column every page in the site shares — the row and the page body sit
 *  on it, so a heading keeps its place from page to page. */
export const SITE_COLUMN = 'mx-auto w-full max-w-4xl';
/** The column's side gutter, apart from the column itself so a page can put
 *  something across the full width and gutter the rest of its content. */
export const SITE_GUTTER = 'px-6';

/** A page the site links to; `current` names the one being rendered, and is
 *  absent on a page the row does not list. */
export type NavPage = 'map' | 'nav' | 'compare' | 'panoramas' | 'credits' | 'status';

export interface SiteLink {
	id: NavPage | 'github';
	href: string;
	label: () => string;
	/** Leaves the site, so it opens in a new tab and is never `current`. */
	external?: boolean;
}

/** The pages the row lists on their own. */
export const SITE_PAGES: SiteLink[] = [
	{ id: 'map', href: '/', label: m.nav_map },
	{ id: 'nav', href: '/nav', label: m.nav_delta_v },
	{ id: 'compare', href: '/compare', label: m.compare_page_title },
	{ id: 'panoramas', href: '/view', label: m.nav_panoramas }
];

/** The pages about the site itself, grouped behind one entry so the row keeps
 *  its width as they multiply. */
export const ABOUT_LINKS: SiteLink[] = [
	{ id: 'credits', href: '/credits', label: m.credits_page_title },
	{ id: 'status', href: '/status', label: m.status_page_title },
	{ id: 'github', href: GITHUB_REPO_URL, label: m.nav_github, external: true }
];
