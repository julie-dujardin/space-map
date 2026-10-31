<script lang="ts">
	import PaginatedMemberList from '../members/PaginatedMemberList.svelte';
	import { cultureSource } from './culture-credits';
	import type { Source } from './SourcesFooter.svelte';
	import { fetchSkyCulture, labelOf } from '$lib/fetch/extrasolar/skycultures';
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { CAT_CONSTELLATIONS } from '$lib/fetch/groups/registry';
	import { categoryLabel } from '$lib/format/group';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';

	interface Props {
		/** The key of the culture of this page. */
		culture: string;
		/** The culture behind the list, for the sources footer. */
		onCredits?: (credits: Source[]) => void;
	}
	let { culture, onCredits }: Props = $props();

	let entries = $state.raw<NotableMemberEntry[]>([]);

	// A figure with a page is a link and any other one a name, from the file
	// that the map draws: no index holds them.
	$effect(() => {
		const key = culture;
		const locale = getLocale();
		entries = [];
		let current = true;
		fetchSkyCulture(key).then(
			(loaded) => {
				if (!current || loaded?.file.key !== key) return;
				const collator = new Intl.Collator(locale);
				entries = loaded.file.figures
					.filter((figure) => !figure.ray_helper)
					.flatMap((figure) => {
						const name = labelOf(figure, locale);
						return name ? [{ name, group: figure.page }] : [];
					})
					.sort((a, b) => collator.compare(a.name, b.name));
				const [credit] = loaded.credits;
				const note = m.source_culture_figures_note({ license: credit.license ?? '' });
				onCredits?.([cultureSource(credit, note)]);
			},
			(e: unknown) => console.warn(`[constellations] no figures of ${key}:`, e)
		);
		return () => {
			current = false;
			onCredits?.([]);
		};
	});
</script>

{#if entries.length > 0}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{categoryLabel(CAT_CONSTELLATIONS)}</h3>
		<div class="border-border/60 border-t"></div>
		<PaginatedMemberList
			source={{ kind: 'list', key: culture }}
			totalCount={entries.length}
			fallback={entries}
		/>
	</div>
{/if}
