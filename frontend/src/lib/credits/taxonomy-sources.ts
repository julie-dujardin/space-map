/**
 * Who to credit for an asteroid's spectral class, resolved from the ids in
 * `interior.taxonomy_sources`. Mirror of `_class_credits` in
 * `data/src/space_map_data/export/objects/interior.py`.
 *
 * Ids rather than citations because 171,000 asteroids take the estimate route
 * and these two names never vary; the /credits page lists them in full under
 * object metadata.
 */
import * as m from '$lib/paraglide/messages.js';

interface TaxonomySource {
	label: () => string;
	url: string;
	role: () => string;
}

export const TAXONOMY_SOURCES: Record<string, TaxonomySource> = {
	ssodnet: {
		label: m.source_ssodnet_name,
		url: 'https://ssp.imcce.fr/webservices/ssodnet/',
		role: m.source_ssodnet_role
	},
	mahlke: {
		label: m.source_mahlke_name,
		url: 'https://doi.org/10.1051/0004-6361/202243587',
		role: m.source_mahlke_role
	}
};
