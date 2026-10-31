<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { byRegion, cultureName } from '../../../layers/sky-culture-list';
	import { datasetSources } from '../culture-credits';
	import type { Source } from '../SourcesFooter.svelte';
	import {
		fetchStarFigures,
		labelOf,
		type SkyCultureEntry,
		type StarFigure
	} from '$lib/fetch/extrasolar/skycultures';
	import { CAT_CONSTELLATIONS, SKY_CULTURE_SLUG_PREFIX } from '$lib/fetch/groups/registry';
	import { categoryLabel } from '$lib/format/group';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { groupClick, groupHref } from '$lib/state/focus-link';

	interface Props {
		/** The extrasolar ID of the star. */
		id: number;
		/** The datasets behind the list, for the sources footer. */
		onCredits?: (credits: Source[]) => void;
	}
	let { id, onCredits }: Props = $props();

	/** Cultures shown before the toggle: a bright star is in most of them. */
	const COLLAPSED = 6;

	const appState = getContext<AppState | undefined>('appState');

	let cultures = $state.raw<{ culture: SkyCultureEntry; figures: StarFigure[] }[]>([]);
	let expanded = $state(false);

	$effect(() => {
		const star = id;
		const locale = getLocale();
		cultures = [];
		expanded = false;
		let current = true;
		fetchStarFigures(star).then(
			({ cultures: holding, figures }) => {
				if (!current) return;
				// In the picker's order.
				cultures = byRegion(holding, locale).flatMap((region) =>
					region.cultures.map((culture) => ({ culture, figures: figures[culture.key] }))
				);
				onCredits?.(datasetSources(holding.map(({ credit }) => credit)));
			},
			(e: unknown) => console.warn(`[constellations] no figures for ${star}:`, e)
		);
		return () => {
			current = false;
			onCredits?.([]);
		};
	});

	let hidden = $derived(cultures.length - COLLAPSED);
	let rows = $derived.by(() => {
		const locale = getLocale();
		return (expanded ? cultures : cultures.slice(0, COLLAPSED)).map(({ culture, figures }) => ({
			key: culture.key,
			name: cultureName(culture, locale),
			slug: `${SKY_CULTURE_SLUG_PREFIX}${culture.key}`,
			figures: figures.flatMap((figure) => {
				const name = labelOf(figure, locale);
				return name ? [{ name, slug: figure.page }] : [];
			})
		}));
	});
</script>

{#snippet link(slug: string, name: string, muted: boolean)}
	<a
		href={groupHref(appState, slug, name)}
		onclick={groupClick(appState, slug, name)}
		dir="auto"
		class="hover:text-foreground underline-offset-2 {muted
			? 'text-muted-foreground hover:underline'
			: 'decoration-muted-foreground/50 underline'}"
	>
		{name}
	</a>
{/snippet}

{#if cultures.length > 0}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{categoryLabel(CAT_CONSTELLATIONS)}</h3>
		<div class="border-border/60 border-t"></div>
		<dl class="flex flex-col gap-1.5 pt-1 text-sm">
			{#each rows as row (row.key)}
				<div class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-3">
					<dt class="min-w-0">{@render link(row.slug, row.name, true)}</dt>
					<dd class="flex min-w-0 flex-wrap gap-x-2">
						{#each row.figures as figure, i (i)}
							{#if figure.slug}
								{@render link(figure.slug, figure.name, false)}
							{:else}
								<span dir="auto">{figure.name}</span>
							{/if}
						{/each}
					</dd>
				</div>
			{/each}
		</dl>
		{#if hidden > 0}
			<button
				type="button"
				onclick={() => (expanded = !expanded)}
				aria-expanded={expanded}
				class="border-border/60 hover:bg-muted/60 text-muted-foreground mt-1 self-start rounded-md border px-2 py-1 text-xs transition-colors"
			>
				{expanded ? m.group_family_collapse() : `+${hidden}`}
			</button>
		{/if}
	</div>
{/if}
