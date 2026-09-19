<script lang="ts">
	import { untrack } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { thumbnailUrl, type SearchHit } from '$lib/search/client';
	import { inceptionYear, optionDomId } from '$lib/search/format';
	import { formatNumber } from '$lib/format/quantities';
	import { CHUNK, type SearchModel } from '$lib/search/model.svelte';
	import ResultRow from './ResultRow.svelte';
	import SearchStatus from './SearchStatus.svelte';

	let {
		model,
		name,
		secondary,
		onselect,
		highlightedId,
		onhighlight
	}: {
		model: SearchModel;
		name: (hit: SearchHit) => string;
		secondary: (hit: SearchHit) => string;
		onselect: (hit: SearchHit) => void;
		// Highlight lives in SearchBar so the combobox input's arrow keys and
		// aria-activedescendant drive the same state as hover.
		highlightedId: string | null;
		onhighlight: (id: string) => void;
	} = $props();

	// Estimated row height. Fixed spacers stand in for unloaded hits, so the
	// scrollbar spans the full set and the window slides without scroll jumps.
	const ROW_H = 52;
	// The ScrollArea viewport is the scrolling element the windowing reads/writes.
	let scrollEl = $state<HTMLElement | null>(null);
	let didRestore = false;
	const initialPage = untrack(() => model.page);

	// Right-aligned value tied to the active sort. Objects/features only — group
	// rows show their member count instead (handled inside ResultRow).
	function metricFor(hit: SearchHit): { value: string; unit?: string } | undefined {
		// Neither has a figure of its own: a group shows its member count inside
		// ResultRow, and a pad is a slab with a name.
		if (hit.kind === 'group' || hit.kind === 'pad') return undefined;
		switch (model.sort) {
			case 'size':
				return hit.diameter_km != null
					? { value: formatNumber(Math.round(hit.diameter_km)), unit: m.unit_symbol_kilometre() }
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

	// ScrollArea's viewport doesn't take an onscroll prop, so wire it up directly.
	$effect(() => {
		const el = scrollEl;
		if (!el) return;
		el.addEventListener('scroll', onScroll, { passive: true });
		return () => el.removeEventListener('scroll', onScroll);
	});

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

<ScrollArea class="min-h-0 flex-1" bind:viewportRef={scrollEl}>
	{#if model.error || model.hits.length === 0}
		<SearchStatus
			status={model.error ? 'error' : model.loading ? 'loading' : 'empty'}
			query={model.query}
		/>
	{:else}
		<!-- spacer: hits above the window -->
		<div style="height: {model.firstIndex * ROW_H}px"></div>
		<ul
			class="px-2"
			id="search-results-listbox"
			role="listbox"
			aria-label={m.search_results_aria()}
		>
			{#each model.hits as hit (hit.id)}
				<li role="presentation">
					<ResultRow
						{hit}
						id={optionDomId(hit.id)}
						name={name(hit)}
						secondary={secondary(hit)}
						thumbnail={thumbnailUrl(hit)}
						metric={metricFor(hit)}
						active={hit.id === highlightedId}
						onselect={() => onselect(hit)}
						onhover={() => onhighlight(hit.id)}
					/>
				</li>
			{/each}
		</ul>
		<!-- spacer: hits below the window -->
		<div style="height: {bottomPad}px"></div>
	{/if}
</ScrollArea>
