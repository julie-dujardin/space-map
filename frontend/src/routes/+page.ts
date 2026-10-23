import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

// The query goes along: `/?q=` is the short link to the map's full search.
export const load: PageLoad = ({ url }) => {
	redirect(302, `/b/399/Earth${url.search}`);
};
