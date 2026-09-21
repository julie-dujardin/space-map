<!--
  The comparison's one control, floating over the row: what the row is
  measured against, a search that adds to it, and behind one pill each the
  ready-made sets and the list of what is in it. Nothing here says anything
  about pages — how the row is broken up is settled when it is drawn, not when
  something is picked. One card at every width: a phone gets it over the row
  as well.
-->
<script lang="ts">
	import CheckIcon from '@lucide/svelte/icons/check';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import ChevronUpIcon from '@lucide/svelte/icons/chevron-up';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import SearchIcon from '@lucide/svelte/icons/search';
	import XIcon from '@lucide/svelte/icons/x';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { Switch } from '$lib/components/ui/switch/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import { isSearchEnabled, search, type ObjectHit } from '$lib/search/client';
	import { getLocale } from '$lib/host';
	import { objectTypeLabel } from '$lib/format/object-type';
	import { formatQuantity } from '$lib/format/quantities';
	import {
		COMPARE_PRESETS,
		COMPARE_PRESET_GROUPS,
		presetOn,
		type ComparePreset
	} from '$lib/compare/presets';
	import { isModifiedClick } from '$lib/modified-click';
	import SearchStatus from '../search/SearchStatus.svelte';

	export interface ListedObject {
		id: string;
		name: string;
		color: string;
		size: string;
		/** Its place in the comparison as an address, or null for one with no
		 *  page of its own to maximize. */
		href: string | null;
	}

	interface Props {
		/** Ids in the comparison: a hit already there is marked and does nothing. */
		selected: readonly string[];
		/** The ones resolved so far, largest first. */
		listed: ListedObject[];
		comparablesOn: boolean;
		ontogglecomparables: () => void;
		onadd: (hit: ObjectHit) => void;
		/** Put the preset up, or take it down: several can be up at once. */
		onpreset: (preset: ComparePreset) => void;
		onclear: () => void;
		onremove: (id: string) => void;
		/** Maximize one object in the row. */
		onopen: (id: string) => void;
		onclose: () => void;
	}

	let {
		selected,
		listed,
		comparablesOn,
		ontogglecomparables,
		onadd,
		onpreset,
		onclear,
		onremove,
		onopen,
		onclose
	}: Props = $props();

	type Section = 'presets' | 'list';

	const enabled = isSearchEnabled();

	let query = $state('');
	let hits = $state<ObjectHit[]>([]);
	let searching = $state(false);
	let failed = $state(false);
	/** The body holds one thing at a time: the sets, or what is in the row. */
	let open = $state<Section | null>(null);

	/** The slugs of the sets that are up. */
	const up = $derived(
		new Set(COMPARE_PRESETS.filter((p) => presetOn(p, selected)).map((p) => p.slug))
	);
	/** A query takes the body over; whatever was open comes back once it is cleared. */
	const showHits = $derived(query.trim() !== '');

	/** One request per settled query: typing fires this on every keystroke, and
	 *  a stale answer must never overwrite a newer one. */
	let token = 0;
	$effect(() => {
		const q = query.trim();
		const mine = ++token;
		hits = [];
		failed = false;
		if (!q) {
			searching = false;
			return;
		}
		searching = true;
		const timer = setTimeout(() => {
			search(q, getLocale(), 12)
				.then((found) => {
					if (mine !== token) return;
					hits = found.filter((h): h is ObjectHit => h.kind === 'object');
					searching = false;
				})
				.catch((err) => {
					if (mine !== token) return;
					console.warn('[search] compare query failed:', err);
					failed = true;
					searching = false;
				});
		}, 180);
		return () => clearTimeout(timer);
	});

	function sizeText(hit: ObjectHit): string | null {
		if (!hit.diameter_km) return null;
		return formatQuantity({ value: hit.diameter_km, unit: 'kilometre' }, true);
	}
</script>

{#snippet toggle(section: Section, label: string, count?: number)}
	<Button
		variant="outline"
		aria-expanded={open === section}
		onclick={() => (open = open === section ? null : section)}
	>
		{label}
		{#if count}
			<Badge class="h-[18px] min-w-[18px] px-1.5 text-[11px] tabular-nums">{count}</Badge>
		{/if}
		{#if open === section}
			<ChevronUpIcon class="size-3.5 text-muted-foreground" />
		{:else}
			<ChevronDownIcon class="size-3.5 text-muted-foreground" />
		{/if}
	</Button>
{/snippet}

<div
	class="flex max-h-full w-full flex-col rounded-2xl border border-border bg-card text-card-foreground shadow-lg"
>
	<div class="flex shrink-0 flex-col gap-3 p-4">
		<div class="flex items-center gap-2">
			<label class="flex flex-1 items-center gap-2.5 text-[13px] font-medium">
				<Switch checked={comparablesOn} onCheckedChange={ontogglecomparables} />
				{m.compare_comparables()}
			</label>
			<Button variant="ghost" size="icon-sm" aria-label={m.compare_hide_menu()} onclick={onclose}>
				<XIcon />
			</Button>
		</div>

		{#if enabled}
			<div
				class="flex h-10 items-center gap-2 rounded-lg border border-input bg-background/60 px-3"
			>
				<SearchIcon class="size-4 shrink-0 text-muted-foreground" />
				<label class="sr-only" for="compare-search">{m.compare_search_label()}</label>
				<input
					id="compare-search"
					type="search"
					bind:value={query}
					placeholder={m.compare_search_placeholder()}
					class="min-w-0 flex-1 bg-transparent text-sm outline-none"
				/>
			</div>
		{:else}
			<p class="text-xs text-muted-foreground">{m.search_catalog_unavailable()}</p>
		{/if}

		<div class="flex items-center gap-2">
			{@render toggle('presets', m.compare_presets(), up.size)}
			{#if selected.length}
				<Button variant="ghost" class="text-muted-foreground" onclick={onclear}>
					{m.compare_clear()}
				</Button>
			{/if}
			<span class="flex-1"></span>
			{@render toggle('list', m.compare_object_count({ count: selected.length }))}
		</div>
	</div>

	{#if showHits || open}
		<ScrollArea class="min-h-0 flex-1 border-t border-border">
			{#if showHits}
				{#if hits.length === 0}
					<SearchStatus status={failed ? 'error' : searching ? 'loading' : 'empty'} {query} />
				{:else}
					<ul class="px-2 py-2">
						{#each hits as hit (hit.id)}
							{@const already = selected.includes(hit.id)}
							{@const size = sizeText(hit)}
							<li>
								<button
									type="button"
									disabled={already}
									onclick={() => onadd(hit)}
									class="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-start hover:bg-accent disabled:opacity-45 disabled:hover:bg-transparent"
								>
									<span class="min-w-0 flex-1">
										<span class="block truncate text-sm font-medium">{hit.name}</span>
										<span class="block truncate text-[11.5px] text-muted-foreground">
											{objectTypeLabel(hit.type)}{size ? ` · ${size}` : ''}
										</span>
									</span>
									{#if already}
										<span class="shrink-0 text-[11.5px] text-muted-foreground"
											>{m.compare_already()}</span
										>
									{:else}
										<PlusIcon class="size-4 shrink-0 text-muted-foreground" />
									{/if}
								</button>
							</li>
						{/each}
					</ul>
				{/if}
			{:else if open === 'presets'}
				<div class="flex flex-col gap-2 px-4 py-3">
					{#each COMPARE_PRESET_GROUPS as group (group.id)}
						<div class="flex flex-col">
							<span class="flex h-6 items-center text-xs font-medium text-muted-foreground"
								>{group.label()}</span
							>
							{#each group.presets as preset (preset.slug)}
								{@const on = up.has(preset.slug)}
								<button
									type="button"
									aria-pressed={on}
									onclick={() => onpreset(preset)}
									class="-mx-2 flex h-9 items-center gap-2.5 rounded-lg px-2 text-start hover:bg-accent"
								>
									<span
										class="flex size-4 shrink-0 items-center justify-center rounded border {on
											? 'border-primary bg-primary text-primary-foreground'
											: 'border-border'}"
									>
										{#if on}<CheckIcon class="size-3" />{/if}
									</span>
									<span class="flex-1 text-[13px] {on ? 'font-medium' : ''}">{preset.label()}</span>
									<span class="text-xs text-muted-foreground tabular-nums">{preset.ids.length}</span
									>
								</button>
							{/each}
						</div>
					{/each}
				</div>
			{:else}
				<ul class="flex flex-col px-4 py-1">
					{#each listed as object (object.id)}
						<li class="flex h-10 items-center gap-2.5 border-b border-border/60 last:border-b-0">
							<span class="size-2.5 shrink-0 rounded-full" style="background: {object.color}"
							></span>
							{#if object.href}
								<!-- Maximizes it here; its own page is on the context menu. -->
								<a
									href={object.href}
									onclick={(e) => {
										if (isModifiedClick(e)) return;
										e.preventDefault();
										onopen(object.id);
									}}
									class="flex-1 truncate text-[13px] font-medium hover:underline">{object.name}</a
								>
							{:else}
								<span class="flex-1 truncate text-[13px] font-medium">{object.name}</span>
							{/if}
							<span class="shrink-0 text-xs text-muted-foreground tabular-nums">{object.size}</span>
							<Button
								variant="ghost"
								size="icon-xs"
								class="text-muted-foreground"
								aria-label={m.compare_remove({ name: object.name })}
								onclick={() => onremove(object.id)}
							>
								<XIcon class="size-3.5" />
							</Button>
						</li>
					{/each}
				</ul>
			{/if}
		</ScrollArea>
	{/if}
</div>
