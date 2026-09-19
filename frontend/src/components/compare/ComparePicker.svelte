<!--
  What goes into a comparison: a ready-made set, or one object out of the whole
  catalogue. Nothing here says anything about pages — how the row is broken up
  is settled when it is drawn, not when something is picked.
-->
<script lang="ts">
	import CheckIcon from '@lucide/svelte/icons/check';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import SearchIcon from '@lucide/svelte/icons/search';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import { search, type ObjectHit } from '$lib/search/client';
	import { getLocale } from '$lib/host';
	import { objectTypeLabel } from '$lib/format/object-type';
	import { formatQuantity } from '$lib/format/quantities';
	import { COMPARE_PRESETS, presetOn, type ComparePreset } from '$lib/compare/presets';

	interface Props {
		/** Already in the comparison: those rows are marked and do nothing. */
		chosen: string[];
		onadd: (hit: ObjectHit) => void;
		/** Put the preset up, or take it down: several can be up at once. */
		onpreset: (preset: ComparePreset) => void;
	}

	let { chosen, onadd, onpreset }: Props = $props();

	/** The four families a reader thinks in. A type filter narrows the search to
	 *  one of them; the catalogue's own type strings are finer than that. */
	const FAMILIES: { key: string; label: () => string; match: (type: string) => boolean }[] = [
		{ key: 'all', label: m.compare_family_all, match: () => true },
		{
			key: 'planets',
			label: m.compare_family_planets,
			match: (t) => t === 'planet' || t === 'dwarf_planet'
		},
		{ key: 'moons', label: m.compare_family_moons, match: (t) => t === 'moon' },
		{
			key: 'small',
			label: m.compare_family_small,
			match: (t) => t.startsWith('asteroid') || t === 'comet'
		},
		{ key: 'craft', label: m.compare_family_craft, match: (t) => t === 'spacecraft' }
	];

	let query = $state('');
	let family = $state('all');
	let hits = $state<ObjectHit[]>([]);
	let searching = $state(false);

	/** One request per settled query: typing fires this on every keystroke, and
	 *  a stale answer must never overwrite a newer one. */
	let token = 0;
	$effect(() => {
		const q = query.trim();
		const mine = ++token;
		if (!q) {
			hits = [];
			searching = false;
			return;
		}
		searching = true;
		const timer = setTimeout(() => {
			search(q, getLocale(), 30)
				.then((found) => {
					if (mine !== token) return;
					hits = found.filter((h): h is ObjectHit => h.kind === 'object');
					searching = false;
				})
				.catch(() => {
					if (mine === token) searching = false;
				});
		}, 180);
		return () => clearTimeout(timer);
	});

	const matcher = $derived(FAMILIES.find((f) => f.key === family) ?? FAMILIES[0]);
	const results = $derived(hits.filter((h) => matcher.match(h.type)).slice(0, 12));

	function sizeText(hit: ObjectHit): string | null {
		if (!hit.diameter_km) return null;
		return formatQuantity({ value: hit.diameter_km, unit: 'kilometre' }, true);
	}
</script>

<div class="flex max-h-[70dvh] w-full flex-col">
	<div class="border-b border-border p-3">
		<div class="flex h-10 items-center gap-2 rounded-lg border border-input bg-background/60 px-3">
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
	</div>

	<div class="flex gap-1 border-b border-border px-3 py-2">
		{#each FAMILIES as f (f.key)}
			<button
				type="button"
				onclick={() => (family = f.key)}
				aria-pressed={family === f.key}
				class="h-7 rounded-lg px-2.5 text-xs transition-colors {family === f.key
					? 'bg-accent font-medium text-accent-foreground'
					: 'text-muted-foreground hover:text-foreground'}"
			>
				{f.label()}
			</button>
		{/each}
	</div>

	<ScrollArea class="min-h-0 flex-1">
		{#if !query.trim()}
			<div class="px-3.5 pt-3 pb-1.5">
				<span class="text-[11px] font-medium tracking-wider text-muted-foreground uppercase"
					>{m.compare_presets()}</span
				>
			</div>
			<ul class="px-1.5 pb-2">
				{#each COMPARE_PRESETS as preset (preset.slug)}
					{@const on = presetOn(preset, chosen)}
					<li>
						<button
							type="button"
							aria-pressed={on}
							onclick={() => onpreset(preset)}
							class="flex h-11 w-full items-center gap-3 rounded-lg px-2 text-start hover:bg-accent"
						>
							<span
								class="flex size-4 shrink-0 items-center justify-center rounded border {on
									? 'border-primary bg-primary text-primary-foreground'
									: 'border-border'}"
							>
								{#if on}<CheckIcon class="size-3" />{/if}
							</span>
							<span class="flex-1 text-sm font-medium">{preset.label()}</span>
							<span class="text-xs text-muted-foreground"
								>{m.compare_object_count({ count: preset.ids.length })}</span
							>
						</button>
					</li>
				{/each}
			</ul>
		{:else if results.length === 0}
			<p class="px-3.5 py-4 text-sm text-muted-foreground">
				{searching ? m.compare_searching() : m.compare_no_results()}
			</p>
		{:else}
			<ul class="px-1.5 py-2">
				{#each results as hit (hit.id)}
					{@const already = chosen.includes(hit.id)}
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
									{objectTypeLabel(hit.type)}{sizeText(hit) ? ` · ${sizeText(hit)}` : ''}
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
	</ScrollArea>
</div>
