/**
 * Names and links for the source keys of `/about/data`'s objects. Mirror of
 * `entry_sources` in `data/src/space_map_data/export/about_objects.py`, which
 * uses the keys of the object panel's source list.
 */
import * as m from '$lib/paraglide/messages.js';
import { archiveLabel, archiveUrl } from '$lib/credits/archive-labels';
import { orientationCredits } from '$lib/credits/orientation-sources';
import { PROVIDERS, type ProviderKey } from '$lib/credits/providers';
import { TAXONOMY_SOURCES } from '$lib/credits/taxonomy-sources';

export interface SourceLink {
	label: string;
	/** Absent for a source with no general page. */
	url?: string;
}

const TAXONOMY_PREFIX = 'taxonomy:';

// The panel credits these two outside its list.
const WIKIMEDIA_LINKS: Record<string, { label: () => string; url: string }> = {
	wikipedia: { label: m.source_wikipedia_name, url: 'https://www.wikipedia.org/' },
	commons: { label: m.source_wikimedia_commons_name, url: 'https://commons.wikimedia.org/' }
};

/** The links of a source key. A kernel pole credits two bodies. An unknown
 *  key shows as it is. */
export function sourceLinks(key: string): SourceLink[] {
	if (key === 'pck' || key === 'damit') {
		return orientationCredits(key === 'pck' ? 'pck' : 'lightcurve').map((credit) => ({
			label: credit.short,
			url: credit.url
		}));
	}
	if (key.startsWith(TAXONOMY_PREFIX)) {
		const source = TAXONOMY_SOURCES[key.slice(TAXONOMY_PREFIX.length)];
		if (source) return [{ label: source.label(), url: source.url }];
	}
	const archive = archiveLabel(key);
	if (archive) return [{ label: archive, url: archiveUrl(key) ?? undefined }];
	if (key in PROVIDERS) {
		const provider = PROVIDERS[key as ProviderKey];
		return [{ label: provider.name(), url: provider.url }];
	}
	const wikimedia = WIKIMEDIA_LINKS[key];
	if (wikimedia) return [{ label: wikimedia.label(), url: wikimedia.url }];
	return [{ label: key }];
}
