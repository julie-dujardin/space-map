<script lang="ts">
	import { untrack } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { thumbnailUrl, type SearchHit } from '$lib/search/client';
	import { inceptionYear } from '$lib/search/format';
	import { CHUNK, type SearchModel } from '$lib/search/model.svelte';
	import ResultRow from './ResultRow.svelte';

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

	// Estimated row height. Fixed spacers stand in for unloaded hits, so the
	// scrollbar spans the full set and the window slides without scroll jumps.
	const ROW_H = 52;

	let highlighted = $state(-1);
	let scrollEl = $state<HTMLDivElement>();
	let didRestore = false;
	const initialPage = untrack(() => model.page);

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

	// Load the pages near the scroll edges and publish the anchor page.
	function check(): void {
		const el = scrollEl;
		if (!el) return;
		const { scrollTop, clientHeight } = el;
		const pad = Math.max(300, clientHeight * 0.5);
		const loadedTop = model.firstIndex * ROW_H;
		const loadedBottom = (model.firstIndex + model.hits.length) * ROW_H;
		if (scrollTop + clientHeight > loadedBottom - pad) model.ensureNext();
		if (scrollTop < loadedTop + pad) model.ensurePrev();
		const topItem = Math.floor((scrollTop + 1) / ROW_H);
		model.setAnchor(Math.floor(topItem / CHUNK) + 1);
	}

	let ticking = false;
	function onScroll(): void {
		if (ticking) return;
		ticking = true;
		requestAnimationFrame(() => {
			ticking = false;
			check();
		});
	}

	// Re-check after each load to fill a tall panel (check() reads hits/total, so
	// it re-runs as the window grows; async, so it settles rather than recurses).
	$effect(() => {
		check();
	});

	// One-time scroll restore for a hydrated `page=N` link.
	$effect(() => {
		if (didRestore || model.hits.length === 0) return;
		didRestore = true;
		if (initialPage > 1 && scrollEl) scrollEl.scrollTop = (initialPage - 1) * CHUNK * ROW_H;
	});

	const bottomPad = $derived(
		Math.max(0, (model.total - model.firstIndex - model.hits.length) * ROW_H)
	);
</script>

<div bind:this={scrollEl} onscroll={onScroll} class="min-h-0 flex-1 overflow-y-auto">
	{#if model.error}
		<div class="px-3 py-10 text-center">
			<div class="mb-1 text-sm text-foreground">{m.search_error()}</div>
			<div class="text-xs text-muted-foreground">{m.search_error_hint()}</div>
		</div>
	{:else if !model.loading && model.hits.length === 0}
		<div class="px-3 py-10 text-center">
			<div class="mb-1 text-sm text-foreground">{m.search_no_results()}</div>
			{#if model.query.trim()}
				<div class="text-xs text-muted-foreground">
					{m.search_no_results_for({ query: model.query.trim() })}
				</div>
			{/if}
		</div>
	{:else}
		<!-- spacer: hits above the window -->
		<div style="height: {model.firstIndex * ROW_H}px"></div>
		<ul class="px-2">
			{#each model.hits as hit, i (hit.id)}
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
		<!-- spacer: hits below the window -->
		<div style="height: {bottomPad}px"></div>
	{/if}
</div>
