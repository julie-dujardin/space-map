<!--
  Picking one end of a trip out of the whole catalogue.

  The fixed planet list this replaced could only ever offer the dozen bodies the
  scene had already loaded. Meili ranks the whole index, so a moon, a comet or a
  named crater is one query away — and a crater is a real endpoint, not a
  curiosity: it is where a landing actually goes.
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
		type FeatureHit,
		type ObjectHit
	} from '$lib/search/client';
	import { secondaryText } from '$lib/search/format';
	import { fetchGroupIndex } from '$lib/fetch/groups/registry';
	import { featureTypeLabel as featureTypeName } from '$lib/format/feature-type';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { TravelEndpointPick } from '$lib/travel/endpoint';

	interface Props {
		/** Bodies this end may not be — the other end, and anything the kernel
		 *  cannot solve against it. Ids, checked after the query returns. */
		excludeIds: ReadonlySet<string>;
		onPick: (pick: TravelEndpointPick) => void;
	}
	let { excludeIds, onPick }: Props = $props();

	/** Long enough that a one-letter keystroke doesn't fan out to the index. */
	const MIN_QUERY = 2;
	const DEBOUNCE_MS = 180;
	/** Over-fetch so the exclusions below can't empty a full page of results. */
	const FETCH_LIMIT = 12;
	const SHOW_LIMIT = 7;

	let query = $state('');
	let hits = $state<(ObjectHit | FeatureHit)[]>([]);
	let searching = $state(false);
	let input = $state<HTMLInputElement | null>(null);

	// Newest query wins: results that land after a later keystroke are dropped
	// rather than flashing over the newer ones.
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

	// A feature is excluded by its host: you cannot fly to a crater on the body
	// you are leaving from.
	let visible = $derived(
		hits
			.filter((h) => !excludeIds.has(h.kind === 'feature' ? h.body_id : h.id))
			.slice(0, SHOW_LIMIT)
	);

	function pick(hit: ObjectHit | FeatureHit) {
		const name = localizedName(hit, getLocale());
		onPick(
			hit.kind === 'feature'
				? { bodyId: hit.body_id, featureId: hit.feature_id, name }
				: { bodyId: hit.id, featureId: null, name }
		);
	}

	// Same second line as the main search: a description when the hit has one,
	// else what it is and where. Both names it needs arrive as ids, so they are
	// resolved from the scene first and the catalogue after.
	const ctx = getContext<ContextManager | undefined>('ctx');
	let catalogNames = $state(new Map<string, string>());
	function bodyName(bodyId: string): string {
		return ctx?.getBody(bodyId)?.data.name ?? catalogNames.get(bodyId) ?? bodyId;
	}
	let unnamedBodyIds = $derived(
		visible
			.map((h) => (h.kind === 'feature' ? h.body_id : h.parent_id))
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

	function sublabel(hit: ObjectHit | FeatureHit): string {
		return secondaryText(hit, { bodyName, featureTypeLabel });
	}

	$effect(() => {
		input?.focus();
	});
</script>

{#if isSearchEnabled()}
	<div class="flex flex-col gap-2">
		<div
			class="border-border/60 bg-background flex items-center gap-2 rounded-md border px-2 py-1.5"
		>
			<SearchIcon class="text-muted-foreground size-3.5 shrink-0" />
			<!-- Deliberately not type="search": its native cancel button is drawn far
			     heavier than the rest of the panel. -->
			<input
				bind:this={input}
				bind:value={query}
				type="text"
				placeholder={m.travel_search_placeholder()}
				aria-label={m.travel_search_placeholder()}
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
				<ScrollArea class="[&_[data-slot=scroll-area-viewport]]:max-h-56">
					<ul class="flex flex-col">
						{#each visible as hit (hit.kind === 'feature' ? `f${hit.feature_id}` : hit.id)}
							<li>
								<button
									type="button"
									onclick={() => pick(hit)}
									class="hover:bg-muted flex w-full items-center gap-2 rounded-[5px] px-2 py-1.5 text-start"
								>
									{#if hit.kind === 'feature'}
										<MapPinIcon class="text-muted-foreground size-3.5 shrink-0" />
									{/if}
									<span class="min-w-0 flex-1">
										<span class="block truncate text-xs">{localizedName(hit, getLocale())}</span>
										<span class="text-muted-foreground block truncate text-[10px]">
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
		{/if}
	</div>
{:else}
	<p class="text-muted-foreground px-2 text-xs">{m.travel_search_unavailable()}</p>
{/if}
