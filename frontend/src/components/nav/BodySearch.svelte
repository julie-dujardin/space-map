<!--
  Finding a body for the Δv map in the whole catalogue rather than in the two
  dozen the page offers by default. Bodies only: the map's stops are wells,
  so a crater or a launch pad — a real end of a trip — is not one of them.
-->
<script lang="ts">
	import { untrack, type Snippet } from 'svelte';
	import SearchIcon from '@lucide/svelte/icons/search';
	import XIcon from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import {
		fetchObjectNames,
		localizedName,
		searchBodies,
		type ObjectHit
	} from '$lib/search/client';
	import { secondaryText } from '$lib/search/format';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { isCoarsePointer } from '$lib/device';

	interface Props {
		/** Accessible name: two of these on one page announce apart. */
		label: string;
		/** Bodies already on the map, or the one being replaced. */
		excludeIds: ReadonlySet<string>;
		/** Names the page already holds, so a parent is usually named without a
		 *  second round trip. */
		names: Record<string, string>;
		/** The page a result leads to. A result navigates, so it is a link. */
		hrefFor: (id: string) => string;
		/** Called as one is followed, to close whatever opened this. */
		onNavigate?: () => void;
		/** What stands in the results' place before anything is typed — the
		 *  bodies already to hand, so the usual choice needs no query. */
		browse?: Snippet;
	}
	let { label, excludeIds, names, hrefFor, onNavigate, browse }: Props = $props();

	const uid = $props.id();
	const listboxId = `nav-body-list-${uid}`;
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
	let hits = $state<ObjectHit[]>([]);
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
			searchBodies(q, getLocale(), FETCH_LIMIT)
				.then((found) => {
					if (mine !== token) return;
					hits = found;
					searching = false;
				})
				.catch((e) => {
					if (mine !== token) return;
					console.warn('[nav] body search failed:', e);
					hits = [];
					searching = false;
				});
		}, DEBOUNCE_MS);
		return () => clearTimeout(timer);
	});

	let visible = $derived(hits.filter((h) => !excludeIds.has(h.id)).slice(0, SHOW_LIMIT));

	// Same second line as the main search. Parents arrive as ids; the page's own
	// names cover the ones already drawn, the index the rest.
	let fetched = $state(new Map<string, string>());
	function bodyName(bodyId: string): string {
		return names[bodyId] ?? fetched.get(bodyId) ?? bodyId;
	}
	let unnamedParentIds = $derived(
		visible
			.map((h) => h.parent_id)
			.filter((id): id is string => !!id && !names[id] && !fetched.has(id))
	);
	$effect(() => {
		const ids = unnamedParentIds;
		const locale = getLocale();
		if (!ids.length) return;
		untrack(() => fetchObjectNames(ids, locale)).then((named) => {
			if (!named.size) return;
			fetched = new Map([...fetched, ...named]);
		});
	});

	// Autofocus is a desktop gesture — on touch it throws the keyboard over the
	// popover that just opened.
	$effect(() => {
		if (!isCoarsePointer()) input?.focus();
	});

	// Combobox-style: walked from the input, not seven extra tab stops.
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
			document.getElementById(optionId(activeIndex))?.click();
		}
	}
</script>

<div class="flex min-h-0 flex-col gap-2">
	<div
		class="border-border/60 bg-background flex shrink-0 items-center gap-2 rounded-md border px-2 py-1.5"
	>
		<SearchIcon class="text-muted-foreground size-3.5 shrink-0" />
		<!-- Deliberately not type="search": its native cancel button is drawn far
		     heavier than the rest. -->
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
					{#each visible as hit, index (hit.id)}
						<li role="presentation">
							<a
								role="option"
								id={optionId(index)}
								href={hrefFor(hit.id)}
								aria-selected={index === activeIndex}
								tabindex="-1"
								onclick={() => onNavigate?.()}
								class="hover:bg-muted flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start {index ===
								activeIndex
									? 'bg-muted'
									: ''}"
							>
								<span class="min-w-0 flex-1">
									<span class="block truncate text-xs">{localizedName(hit, getLocale())}</span>
									<span class="text-muted-foreground block truncate text-[11px]">
										{secondaryText(hit, { bodyName, featureTypeLabel: (code) => code })}
									</span>
								</span>
							</a>
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
	{:else if browse}
		{@render browse()}
	{/if}
</div>
