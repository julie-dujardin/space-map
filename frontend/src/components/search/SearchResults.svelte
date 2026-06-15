<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { thumbnailUrl, type SearchHit } from '$lib/search/client';
	import { inceptionYear } from '$lib/search/format';
	import type { SearchModel } from '$lib/search/model.svelte';
	import ResultRow from './ResultRow.svelte';
	import Pagination from './Pagination.svelte';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';

	let {
		model,
		name,
		secondary,
		onselect
	}: {
		model: SearchModel;
		name: (hit: SearchHit) => string;
		secondary: (hit: SearchHit) => string;
		onselect: (hit: SearchHit) => void;
	} = $props();

	let highlighted = $state(-1);

	// Right-aligned value tied to the active sort. Objects/features only — group
	// rows show their member count instead (handled inside ResultRow).
	function metricFor(hit: SearchHit): { value: string; unit?: string } | undefined {
		if (hit.kind === 'group') return undefined;
		switch (model.sort) {
			case 'size':
				return hit.diameter_km != null
					? { value: Math.round(hit.diameter_km).toLocaleString(), unit: 'km' }
					: undefined;
			case 'brightness':
				return hit.kind === 'object' && hit.magnitude != null
					? { value: hit.magnitude.toFixed(1), unit: 'H' }
					: undefined;
			case 'date':
				return hit.kind === 'object' && hit.inception != null
					? { value: String(inceptionYear(hit.inception)) }
					: undefined;
			default:
				return undefined;
		}
	}
</script>

<ScrollArea class="min-h-0 flex-1">
	<div class="px-2 py-1">
		{#if model.result.hits.length === 0}
			<div class="px-3 py-10 text-center">
				<div class="mb-1 text-sm text-foreground">{m.search_no_results()}</div>
				{#if model.query.trim()}
					<div class="text-xs text-muted-foreground">
						{m.search_no_results_for({ query: model.query.trim() })}
					</div>
				{/if}
			</div>
		{:else}
			<ul>
				{#each model.result.hits as hit, i (hit.id)}
					<li>
						<ResultRow
							{hit}
							name={name(hit)}
							secondary={secondary(hit)}
							thumbnail={thumbnailUrl(hit)}
							metric={metricFor(hit)}
							active={i === highlighted}
							onselect={() => onselect(hit)}
							onhover={() => (highlighted = i)}
						/>
					</li>
				{/each}
			</ul>
		{/if}
	</div>
</ScrollArea>

{#if model.result.hits.length > 0}
	<div class="border-t border-border px-3 py-1.5">
		<Pagination {model} />
	</div>
{/if}
