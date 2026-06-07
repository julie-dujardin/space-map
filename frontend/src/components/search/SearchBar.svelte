<script lang="ts">
	import { getContext } from 'svelte';
	import SearchIcon from '@lucide/svelte/icons/search';
	import XIcon from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { search, localizedName, isSearchEnabled, type SearchHit } from '$lib/search/client';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

	type Props = {
		onSelect: (hit: SearchHit) => void;
	};

	let { onSelect }: Props = $props();

	const ctx = getContext<ContextManager>('ctx');

	let query = $state('');
	let hits = $state<SearchHit[]>([]);
	let open = $state(false);
	let highlighted = $state(0);
	let inputEl: HTMLInputElement | undefined = $state();

	const enabled = isSearchEnabled();

	// Newer queries win when fetches resolve out of order.
	let activeQueryToken = 0;

	async function runSearch(q: string) {
		const token = ++activeQueryToken;
		const trimmed = q.trim();
		if (!trimmed) {
			hits = [];
			return;
		}
		try {
			const result = await search(trimmed, getLocale(), 8);
			if (token !== activeQueryToken) return;
			hits = result;
			highlighted = 0;
		} catch (err) {
			if (token !== activeQueryToken) return;
			console.warn('[search] query failed:', err);
			hits = [];
		}
	}

	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		const q = query;
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => runSearch(q), 150);
		return () => clearTimeout(debounceTimer);
	});

	function bodyName(bodyId: string): string {
		return ctx.getBody(bodyId)?.data.name ?? bodyId;
	}

	// Dynamic `type_*` / `feature_type_label_*` lookup so we don't need a static
	// switch per object/feature kind.
	const messages = m as unknown as Record<
		string,
		((args?: Record<string, unknown>) => string) | undefined
	>;

	// Types that orbit the Sun/SSB directly — no need to spell out the parent.
	const HELIOCENTRIC_TYPES = new Set([
		'planet',
		'dwarf_planet',
		'comet',
		'asteroid',
		'asteroid_inner',
		'asteroid_main_belt',
		'asteroid_trojan',
		'asteroid_centaur',
		'asteroid_tno'
	]);
	// Types where mentioning a parent adds nothing useful.
	const SELF_EXPLANATORY_TYPES = new Set(['star', 'spacecraft', 'undocumented']);

	function typeLabel(type: string): string {
		const key = type.startsWith('asteroid') ? 'type_asteroid' : `type_${type}`;
		return messages[key]?.() ?? type.replace(/_/g, ' ');
	}

	function featureTypeLabel(code: string): string {
		return messages[`feature_type_label_${code}`]?.() ?? code;
	}

	function secondaryText(hit: SearchHit): string {
		if (hit.kind === 'feature') {
			return m.search_secondary_feature_on({
				type: featureTypeLabel(hit.feature_type),
				parent: bodyName(hit.body_id)
			});
		}
		if (hit.id.startsWith('norad_satcat-')) {
			return hit.type === 'debris' ? m.type_earth_debris() : m.type_earth_satellite();
		}
		const label = typeLabel(hit.type);
		if (HELIOCENTRIC_TYPES.has(hit.type) || SELF_EXPLANATORY_TYPES.has(hit.type)) {
			return label;
		}
		if (hit.parent_id) {
			return m.search_secondary_orbiting({ type: label, parent: bodyName(hit.parent_id) });
		}
		return label;
	}

	function pick(hit: SearchHit) {
		onSelect(hit);
		query = '';
		hits = [];
		open = false;
		inputEl?.blur();
	}

	function onKeyDown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			query = '';
			hits = [];
			open = false;
			inputEl?.blur();
			return;
		}
		if (!hits.length) return;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			highlighted = (highlighted + 1) % hits.length;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			highlighted = (highlighted - 1 + hits.length) % hits.length;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			const h = hits[highlighted];
			if (h) pick(h);
		}
	}

	function onContainerFocusOut(e: FocusEvent) {
		const next = e.relatedTarget as Node | null;
		if (next && (e.currentTarget as HTMLElement).contains(next)) return;
		open = false;
	}

	const showDropdown = $derived(open && query.trim().length > 0);
</script>

{#if enabled}
	<div
		class="relative w-full"
		role="search"
		onfocusin={() => (open = true)}
		onfocusout={onContainerFocusOut}
	>
		<div
			class="flex items-center gap-2 rounded-full bg-popover/90 backdrop-blur-md shadow-lg border border-border ps-3 pe-2 py-2 focus-within:ring-2 focus-within:ring-ring/40"
		>
			<SearchIcon class="size-4 text-muted-foreground shrink-0" />
			<input
				bind:this={inputEl}
				bind:value={query}
				type="text"
				class="flex-1 bg-transparent outline-none text-sm text-foreground placeholder:text-muted-foreground min-w-0"
				placeholder={m.search_placeholder()}
				autocomplete="off"
				spellcheck="false"
				onkeydown={onKeyDown}
			/>
			{#if query}
				<button
					type="button"
					class="rounded-full p-1 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
					onclick={() => {
						query = '';
						hits = [];
						inputEl?.focus();
					}}
					aria-label="Clear"
				>
					<XIcon class="size-4" />
				</button>
			{/if}
		</div>

		{#if showDropdown}
			<div
				class="absolute start-0 end-0 mt-2 rounded-2xl bg-popover/95 backdrop-blur-md shadow-xl border border-border overflow-hidden"
			>
				{#if hits.length === 0}
					<div class="px-4 py-3 text-sm text-muted-foreground">{m.search_no_results()}</div>
				{:else}
					<ul class="max-h-[60vh] overflow-y-auto py-1">
						{#each hits as hit, i (hit.id)}
							<li>
								<button
									type="button"
									class="w-full text-start px-4 py-2 flex flex-col gap-0.5 transition-colors {i ===
									highlighted
										? 'bg-accent'
										: 'hover:bg-accent'}"
									onmouseenter={() => (highlighted = i)}
									onclick={() => pick(hit)}
								>
									<span class="text-sm text-foreground truncate"
										>{localizedName(hit, getLocale())}</span
									>
									<span class="text-xs text-muted-foreground truncate">{secondaryText(hit)}</span>
								</button>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		{/if}
	</div>
{/if}
