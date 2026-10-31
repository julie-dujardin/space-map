import type { ExtrasolarCredit } from '$lib/fetch/extrasolar/files';
import * as m from '$lib/paraglide/messages.js';
import { STELLARIUM_TEAM } from '$lib/scene/state/attribution';
import type { Source } from './SourcesFooter.svelte';

/** A culture's credit as a row of the sources footer. */
export function cultureSource(credit: ExtrasolarCredit, note: string): Source {
	return {
		key: credit.source,
		label: [
			credit.organisation,
			credit.name,
			...(credit.authors ?? []).filter((author) => author !== STELLARIUM_TEAM)
		].join(', '),
		url: credit.source,
		note
	};
}

/** One row per dataset: a bright star is in most cultures, and a row for each
 *  would bury the footer. */
export function datasetSources(credits: readonly ExtrasolarCredit[]): Source[] {
	const licences = new Map<string, Set<string>>();
	const urls = new Map<string, string>();
	for (const { organisation, source, license } of credits) {
		urls.set(organisation, source.replace(/\/(tree|blob)\/.*$/, ''));
		licences.set(organisation, (licences.get(organisation) ?? new Set()).add(license ?? ''));
	}
	return [...licences].map(([dataset, held]) => ({
		key: urls.get(dataset)!,
		label: dataset,
		url: urls.get(dataset),
		note:
			held.size === 1
				? m.source_culture_figures_note({ license: [...held][0] })
				: m.source_culture_figures_note_various()
	}));
}
