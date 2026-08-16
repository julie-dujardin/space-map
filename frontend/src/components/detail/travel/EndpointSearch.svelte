<!--
  Picking one end of a trip from the whole catalogue via Meili, not the dozen
  bodies the scene has loaded — a moon, comet, or named crater is one query
  away, and a crater is a real landing endpoint, not a curiosity.
-->
<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import SearchIcon from '@lucide/svelte/icons/search';
	import MapPinIcon from '@lucide/svelte/icons/map-pin';
	import XIcon from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import {
		fetchObjectNames,
		isSearchEnabled,
		localizedName,
		searchEndpoints,
		type EndpointHit
	} from '$lib/search/client';
	import { secondaryText } from '$lib/search/format';
	import { fetchGroupIndex } from '$lib/fetch/groups/registry';
	import { featureTypeLabel as featureTypeName } from '$lib/format/feature-type';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { EARTH_ID } from '$lib/constants';
	import { isCoarsePointer } from '$lib/device';
	import type { TravelEndpointPick } from '$lib/travel/endpoint';

	interface Props {
		/** What this search chooses — accessible name, so the two otherwise-identical boxes announce apart. */
		label: string;
		/** Bodies this end may not be: the other end, plus anything the kernel can't solve against it. */
		excludeIds: ReadonlySet<string>;
		onPick: (pick: TravelEndpointPick) => void;
	}
	let { label, excludeIds, onPick }: Props = $props();

	const uid = $props.id();
	const listboxId = `travel-endpoint-list-${uid}`;
	function optionId(index: number): string {
		return `${listboxId}-${index}`;
	}

	/** Long enough that a one-letter keystroke doesn't fan out to the index. */
	const MIN_QUERY = 2;
	const DEBOUNCE_MS = 180;
	/** Over-fetch so the exclusions below can't empty a full page of results. */
	const FETCH_LIMIT = 12;
	const SHOW_LIMIT = 7;

	let query = $state('');
	let hits = $state<EndpointHit[]>([]);
	let searching = $state(false);
	let input = $state<HTMLInputElement | null>(null);

	// Newest query wins — stale results are dropped, never flashed over newer ones.
	let token = 0;

	$effect(() => {
		const q = query.trim();
		if (q.length < MIN_QUERY) {
			hits = [];
			searching = false;
			return;
		}
		const mine = ++token;
		searching = true;
		const timer = setTimeout(() => {
			searchEndpoints(q, getLocale(), FETCH_LIMIT)
				.then((found) => {
					if (mine !== token) return;
					hits = found;
					searching = false;
				})
				.catch((e) => {
					if (mine !== token) return;
					console.warn('[travel] endpoint search failed:', e);
					hits = [];
					searching = false;
				});
		}, DEBOUNCE_MS);
		return () => clearTimeout(timer);
	});

	// A feature is excluded by its host: you can't fly to a crater on the body you're leaving from.
	let visible = $derived(hits.filter((h) => !excludeIds.has(hostOf(h))).slice(0, SHOW_LIMIT));

	/** The body a hit prices against: a feature's host, a pad's planet, or itself. */
	function hostOf(hit: EndpointHit): string {
		if (hit.kind === 'feature') return hit.body_id;
		if (hit.kind === 'pad') return EARTH_ID;
		return hit.id;
	}

	function pick(hit: EndpointHit) {
		const name = localizedName(hit, getLocale());
		if (hit.kind === 'pad') {
			onPick({
				bodyId: EARTH_ID,
				featureId: null,
				place: {
					latDeg: hit.lat,
					lonDeg: hit.lon,
					siteSlug: hit.site_slug,
					padCode: hit.code
				},
				name
			});
			return;
		}
		onPick(
			hit.kind === 'feature'
				? { bodyId: hit.body_id, featureId: hit.feature_id, name }
				: { bodyId: hit.id, featureId: null, name }
		);
	}

	// Same second line as the main search. Names arrive as ids, resolved from the scene first, catalogue after.
	const ctx = getContext<ContextManager | undefined>('ctx');
	let catalogNames = $state(new Map<string, string>());
	function bodyName(bodyId: string): string {
		return ctx?.getBody(bodyId)?.data.name ?? catalogNames.get(bodyId) ?? bodyId;
	}
	let unnamedBodyIds = $derived(
		visible
			.map((h) => (h.kind === 'feature' ? h.body_id : h.kind === 'pad' ? null : h.parent_id))
			.filter((id): id is string => !!id && !ctx?.getBody(id) && !catalogNames.has(id))
	);
	$effect(() => {
		const ids = unnamedBodyIds;
		const locale = getLocale();
		if (!ids.length) return;
		untrack(() => fetchObjectNames(ids, locale)).then((named) => {
			if (!named.size) return;
			catalogNames = new Map([...catalogNames, ...named]);
		});
	});

	// Feature types are indexed by IAU code but named on their `ft-` slug.
	let featureTypeSlugByCode = $state<Record<string, string>>({});
	$effect(() => {
		fetchGroupIndex().then((index) => {
			const out: Record<string, string> = {};
			for (const [slug, entry] of Object.entries(index)) {
				if (entry.code) out[entry.code] = slug;
			}
			featureTypeSlugByCode = out;
		});
	});
	function featureTypeLabel(code: string): string {
		return featureTypeName(featureTypeSlugByCode[code]) ?? code;
	}

	function sublabel(hit: EndpointHit): string {
		return secondaryText(hit, { bodyName, featureTypeLabel });
	}

	// Autofocus is a desktop gesture — on touch it throws the keyboard over the popover that just opened.
	$effect(() => {
		if (!isCoarsePointer()) input?.focus();
	});

	// Combobox-style: walked from the input, not seven extra tab stops before the rest of the panel.
	let activeIndex = $state(-1);
	$effect(() => {
		void visible;
		activeIndex = -1;
	});
	$effect(() => {
		if (activeIndex >= 0) {
			document.getElementById(optionId(activeIndex))?.scrollIntoView({ block: 'nearest' });
		}
	});

	function onKey(e: KeyboardEvent) {
		if (!visible.length) return;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			activeIndex = (activeIndex + 1) % visible.length;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			activeIndex = activeIndex <= 0 ? visible.length - 1 : activeIndex - 1;
		} else if (e.key === 'Enter' && activeIndex >= 0) {
			e.preventDefault();
			pick(visible[activeIndex]);
		}
	}
</script>

{#if isSearchEnabled()}
	<div class="flex flex-col gap-2">
		<div
			class="border-border/60 bg-background flex items-center gap-2 rounded-md border px-2 py-1.5"
		>
			<SearchIcon class="text-muted-foreground size-3.5 shrink-0" />
			<!-- Deliberately not type="search": its native cancel button is drawn far heavier than the rest. -->
			<input
				bind:this={input}
				bind:value={query}
				type="text"
				placeholder={m.travel_search_placeholder()}
				aria-label={label}
				role="combobox"
				aria-expanded={visible.length > 0}
				aria-controls={listboxId}
				aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
				aria-autocomplete="list"
				onkeydown={onKey}
				autocomplete="off"
				spellcheck="false"
				class="placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-sm outline-none"
			/>
			{#if query}
				<button
					type="button"
					onclick={() => {
						query = '';
						input?.focus();
					}}
					aria-label={m.search_clear_search()}
					class="text-muted-foreground hover:bg-accent hover:text-foreground shrink-0 rounded-full p-0.5 transition-colors"
				>
					<XIcon class="size-3.5" />
				</button>
			{/if}
		</div>

		{#if query.trim().length >= MIN_QUERY}
			{#if visible.length > 0}
				<!-- Tall enough for all SHOW_LIMIT rows — a scrollbar for nothing shorter. -->
				<ScrollArea viewportClasses="max-h-72">
					<ul id={listboxId} role="listbox" class="flex flex-col">
						{#each visible as hit, index (hit.kind === 'feature' ? `f${hit.feature_id}` : hit.id)}
							<li role="presentation">
								<button
									type="button"
									role="option"
									id={optionId(index)}
									aria-selected={index === activeIndex}
									tabindex="-1"
									onclick={() => pick(hit)}
									class="hover:bg-muted flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start {index ===
									activeIndex
										? 'bg-muted'
										: ''}"
								>
									{#if hit.kind === 'feature'}
										<MapPinIcon
											class="text-muted-foreground size-3.5 shrink-0"
											aria-hidden="true"
										/>
									{/if}
									<span class="min-w-0 flex-1">
										<span class="block truncate text-xs">{localizedName(hit, getLocale())}</span>
										<span class="text-muted-foreground block truncate text-[11px]">
											{sublabel(hit)}
										</span>
									</span>
								</button>
							</li>
						{/each}
					</ul>
				</ScrollArea>
			{:else if searching}
				<p class="text-muted-foreground px-2 text-xs">{m.travel_searching()}</p>
			{:else}
				<p class="text-muted-foreground px-2 text-xs">{m.travel_search_empty()}</p>
			{/if}
		{:else if query.trim().length > 0}
			<!-- One letter in: silence here reads as a search that found nothing. -->
			<p class="text-muted-foreground px-2 text-xs">{m.travel_search_more()}</p>
		{/if}
	</div>
{:else}
	<p class="text-muted-foreground px-2 text-xs">{m.travel_search_unavailable()}</p>
{/if}
